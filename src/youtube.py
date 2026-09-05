# -*- coding: utf-8 -*-
"""講演・対談の候補を YouTube から集める(F-11): python -m src.youtube

YouTube Data API v3 の `search.list` で各人の出演動画を探し、**誤帰属ゲート**を
通ったものだけを候補にする。ゲートは hyakunin-lens loop_005 で較正されたものを移植した。

  videoDuration=long   20 分超のみ。切り抜き・ショート・クリックベイトを外す
  order=relevance      「本人が長く話す」動画を上位に寄せる
  publishedAfter       期間窓(既定 180 日)
  題名に氏名の語形      中間イニシャル・漢字名に対応。`#shorts` の印は落とす
  他の欄との重複除外    own / pub に出ている URL は採らない

**それでも足りない。** この 100 名は学者なので、「本人が話す動画」より
「第三者が本人について語る動画」のほうが多い。姉妹プロジェクトは氏名一致だけで
切り抜きに汚染され revert している。だから既定は**審査**であって適用ではない ——
`--apply` を付けない限り `data/people.json` には触らず、候補を
`data/yt_review.json` に出すだけにする。人が抜き取り検査を通してから有効にする。

クォータ: `search.list` は 100 units/回、無料枠は 10,000/日(Google Cloud
プロジェクト単位。鍵を増やしても増えない)。1 回の実行で半数(50 名)だけを回し、
2 日で一巡する = 5,000 units/日で枠の 50%。

環境変数 `YOUTUBE_API_KEY` が未設定なら何もせず exit 0(手元・CI で安全)。
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .merge import merge_section
from .robots import RobotsGate

ROOT = Path(__file__).resolve().parents[1]
API = "https://www.googleapis.com/youtube/v3/search"
WINDOW_DAYS = 180
BUCKETS = 2                      # 1 日あたり半数 = 50 名 = 5,000 units
_CJK = re.compile(r"[぀-ヿ一-鿿]+")
_LATIN = re.compile(r"[A-Za-z][A-Za-z .'À-ɏ-]*[A-Za-z.]")


_KANJI = re.compile(r"[一-鿿]")


def query_term(person: dict) -> str:
    """検索に使う語。

    **表示名(カタカナ)で引いてはならない。** 実測(2026-09-01)で
    「ペーター=ポール・フェルベーク」の表示名から取った「ペーター」が
    『あつ森の住民ペーター』『連続殺人犯ペーター・キュルテン』『聖ペーター教会』に当たり、
    22 件すべてが別物だった。原綴を持っているのだから、そちらで引く。

    日本の学者(漢字の氏名)は原綴のローマ字より漢字のほうが当たるので、表示名を使う。
    """
    return person["n"] if _KANJI.search(person["n"]) else person["en"]


def accepted_forms(person: dict) -> list[str]:
    """題名に現れてよい語形。検索語だけでなく、もう一方の表記も許す。"""
    forms = name_variants(person["en"]) + name_variants(person["n"])
    seen, out = set(), []
    for f in forms:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def name_variants(name: str) -> list[str]:
    """氏名の照合語形。'Philip N. Howard' → ['Philip N. Howard', 'Philip Howard']。"""
    variants = []
    latin = _LATIN.search(name)
    if latin:
        v = latin.group().strip()
        variants.append(v)
        no_middle = re.sub(r"\s+[A-Z]\.\s+", " ", v)
        if no_middle != v:
            variants.append(no_middle)
    variants += _CJK.findall(name)
    return variants or [name]


def title_matches(title: str, name_or_forms) -> bool:
    t = title.lower()
    if "#shorts" in t or "#short" in t:
        return False
    forms = name_or_forms if isinstance(name_or_forms, list) else name_variants(name_or_forms)
    return any(v.lower() in t for v in forms)


def search_url(term: str, key: str, published_after: str = "") -> str:
    params = {
        "part": "snippet", "type": "video", "maxResults": 25,
        "order": "relevance", "videoDuration": "long",
        "q": f'"{term}"', "key": key,
    }
    if published_after:
        params["publishedAfter"] = published_after
    return f"{API}?{urllib.parse.urlencode(params)}"


def search_person(person: dict, key: str, fetch, published_after: str = "",
                  dropped: dict[str, int] | None = None) -> list[dict]:
    """検索し、氏名ゲートを通った候補を返す。落としたものは理由ごとに数える。"""
    def drop(why: str) -> None:
        if dropped is not None:
            dropped[why] = dropped.get(why, 0) + 1

    forms = accepted_forms(person)
    body = json.loads(fetch(search_url(query_term(person), key, published_after)))
    items = []
    for it in body.get("items", []):
        vid = (it.get("id") or {}).get("videoId")
        sn = it.get("snippet") or {}
        title = html.unescape(sn.get("title", ""))
        if not vid or not title:
            drop("動画 ID か題名が無い")
            continue
        low = title.lower()
        if "#shorts" in low or "#short" in low:
            drop("切り抜きの印")
            continue
        if not title_matches(title, forms):
            drop("題名に氏名が無い")
            continue
        items.append({
            "d": (sn.get("publishedAt") or "")[:10] or "不明",
            "t": title,
            "u": f"https://www.youtube.com/watch?v={vid}",
            "s": "yt",
            "o": html.unescape(sn.get("channelTitle", "")),
        })
    return items


def todays_bucket(now: datetime) -> int:
    """UTC 通日で組を交替する。2 日で全員を一巡する。"""
    return now.toordinal() % BUCKETS


def window_start(now: datetime, days: int = WINDOW_DAYS) -> str:
    return (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_channel(name: str) -> str:
    """チャンネル名の照合形。大文字小文字と空白の揺れを吸収する。"""
    return " ".join(name.split()).lower()


def run_yt(people, key, fetch, bucket: int, published_after: str = "", gate=None,
           limit: int = 0, channels: set[str] | None = None):
    """(people, report) を返す純関数コア。people は書き換えない。

    bucket に該当する人(index % BUCKETS == bucket)だけを検索する。
    gate は robots.txt の関門(None なら確認しない — 単体テスト用)。

    channels は **(チャンネル, 人物)の組**の集合。題名の字面では「本人による」と
    「本人についての」を分けられないことが実測で分かったので、分けられるもの——**場**——で
    絞る(loop_011 の四つの規則がいずれも届かなかった)。

    組で持つのは、**ある人を招く場が別の人も招くとは限らない**からである。実測(loop_012):
    マッカスキルの回で許可した Zenvora Productions が、同名の別人(柔術コーチの
    ジョン・ダナハー)の回を 3 件通した。その局は有名ポッドキャストの非公式再アップを
    集約するチャンネルだった。

    許可外の候補は捨てずに `pending` へ入れる。許可リストはそこから育てる。
    None を渡すと絞らない(審査モード)。
    """
    allow = None if channels is None else {(norm_channel(c), n) for c, n in channels}
    out, status, ok = [], [], 0
    for idx, p in enumerate(people):
        if idx % BUCKETS != bucket or (limit and len(status) >= limit):
            out.append(p)
            continue
        rec: dict = {"n": p["n"], "ok": False, "count": 0}
        dropped: dict[str, int] = {}
        try:
            if gate is not None:
                gate.check(search_url(query_term(p), key, published_after))
            found = search_person(p, key, fetch, published_after, dropped=dropped)
        except Exception as e:                              # noqa: BLE001 — 失敗は劣化継続
            rec["error"] = f"{type(e).__name__}: {e}"[:200]
            found = []
        # 他の欄に出ている動画は採らない(同じものを二度見せない)
        exclude = {i["u"] for i in p["own"] + p["pub"]}
        accepted, pending, seen = [], [], set()
        for i in found:
            if i["u"] in exclude:
                dropped["他の欄に既出"] = dropped.get("他の欄に既出", 0) + 1
                continue
            if i["u"] in seen:
                continue
            seen.add(i["u"])
            if allow is not None and (norm_channel(i["o"]), p["n"]) not in allow:
                dropped["許可していないチャンネル"] = dropped.get("許可していないチャンネル", 0) + 1
                pending.append(i)
                continue
            accepted.append(i)
        if dropped:
            rec["dropped"] = dropped
        rec["candidates"] = accepted
        if pending:
            rec["pending"] = pending
        if accepted:
            rec.update(ok=True, count=len(accepted))
            ok += 1
            q = dict(p)
            # s="yt" の既存項目だけを差し替える。ポッドキャストは別種別なので残る
            q["yt"] = merge_section(p["yt"], accepted, {"yt"})
            out.append(q)
        else:
            out.append(p)                                    # 劣化継続
        status.append(rec)
    return out, {"bucket": bucket, "ok": ok, "attempted": len(status), "people": status}


def carry_over(prev: dict | None, new: dict) -> dict:
    """前回の審査ファイルのうち、**今日検索しなかった人**の記録を新しい報告へ持ち越す。

    実測(2026-09-06): 審査ファイルは毎日の実行で上書きされ、その日の組(50 名)の候補しか
    残らなかった。前日の組の pending は git の履歴にしか無く、審査の材料が半分見えなかった。
    持ち越した記録には最初に得た日付(carried_from)を付け、持ち越しのたびに更新しない。
    """
    if not prev:
        return new
    today = {p["n"] for p in new["people"]}
    kept = [dict(p, carried_from=p.get("carried_from") or prev.get("generated_at", ""))
            for p in prev.get("people", []) if p["n"] not in today]
    out = dict(new)
    out["people"] = list(new["people"]) + kept
    out["carried"] = len(kept)
    return out


def apply_review(people, report: dict, channels: set[tuple[str, str]]):
    """審査ファイルの候補に許可リストを**当て直す**(検索しない・クォータを使わない)。

    許可リストを育てたあと、翌日の検索を待たずに取得済みの候補へ同じ関門を通すための経路。
    関門は run_yt と同じ(チャンネル × 人物)の組。通った候補は candidates へ移し、
    既に通っていた候補と合わせて yt 種別を差し替える(ポッドキャストは別種別なので残る)。
    (people, report) を返し、入力は書き換えない。
    """
    allow = {(norm_channel(c), n) for c, n in channels}
    by_name = {p["n"]: p for p in people}
    recs, promoted = [], {}
    for rec in report.get("people", []):
        r = dict(rec)
        newly = [i for i in rec.get("pending", []) if (norm_channel(i["o"]), rec["n"]) in allow]
        if newly:
            r["candidates"] = list(rec.get("candidates", [])) + newly
            r["pending"] = [i for i in rec.get("pending", []) if i not in newly]
            if not r["pending"]:
                r.pop("pending", None)
            r["ok"], r["count"] = True, len(r["candidates"])
            promoted[rec["n"]] = r["candidates"]
        recs.append(r)
    out = []
    for p in people:
        if p["n"] in promoted and p["n"] in by_name:
            q = dict(p)
            q["yt"] = merge_section(p["yt"], promoted[p["n"]], {"yt"})
            out.append(q)
        else:
            out.append(p)
    new_report = dict(report)
    new_report["people"] = recs
    new_report["promoted"] = len(promoted)
    return out, new_report


def http_get(url: str) -> bytes:
    time.sleep(1.2)                                          # 連続 50 検索の 429 予防
    req = urllib.request.Request(url, headers={"User-Agent": "hyakugaku-lens/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def load_channels() -> set[tuple[str, str]]:
    """`data/yt_channels.jsonl` の許可(チャンネル, 人物)。無ければ空(=何も通さない)。"""
    path = ROOT / "data" / "yt_channels.jsonl"
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            out.add((d["ch"], d["for"]))
    return out


def read_json(name: str):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def write_json(name: str, obj) -> None:
    (ROOT / "data" / name).write_text(
        json.dumps(obj, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")


def main_from_review() -> int:
    """`--from-review`: 検索せず、data/yt_review.json の候補へ許可リストを当て直す。"""
    people, meta = read_json("people.json"), read_json("meta.json")
    report = read_json("yt_review.json")
    new_people, new_report = apply_review(people, report, load_channels())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_report["reapplied_at"] = now
    new_report["channels_allowed"] = len(load_channels())
    write_json("yt_review.json", new_report)
    print(f"youtube --from-review: 許可リストを当て直して {new_report['promoted']} 名の候補が通った")
    if new_report["promoted"]:
        write_json("people.json", new_people)
        meta["updated_at"] = meta["yt_updated_at"] = now
        write_json("meta.json", meta)
        from .build import build
        build()
        print("  data/people.json と out/index.html を更新した")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv or []
    if "--from-review" in argv:
        return main_from_review()
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        print("youtube: YOUTUBE_API_KEY 未設定 — 何もせず終了")
        return 0
    apply = "--apply" in argv
    people, meta = read_json("people.json"), read_json("meta.json")
    now = datetime.now(timezone.utc)
    bucket = todays_bucket(now)

    limit = 0
    for a in argv:
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])
    # 審査モードでは絞らない(許可リストを育てるため候補を全部見る)。
    # 適用モードでは許可チャンネルだけを採る
    channels = load_channels() if apply else None
    new_people, report = run_yt(people, key, http_get, bucket,
                                published_after=window_start(now), gate=RobotsGate(),
                                limit=limit, channels=channels)
    report["channels_allowed"] = len(channels) if channels is not None else None
    report["generated_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    report["applied"] = apply
    report["window_start"] = window_start(now)
    # 今日検索しなかった組の記録を前回の審査ファイルから持ち越す(審査の材料を消さない)
    prev_path = ROOT / "data" / "yt_review.json"
    prev = json.loads(prev_path.read_text(encoding="utf-8")) if prev_path.exists() else None
    report = carry_over(prev, report)
    write_json("yt_review.json", report)

    total = sum(r["count"] for r in report["people"])
    print(f"youtube: 組 {bucket} / 検索 {report['attempted']} 名 / "
          f"ゲート通過 {total} 件({report['ok']} 名)")
    for r in report["people"]:
        if r.get("error"):
            print(f"  NG {r['n']}: {r['error']}")
    if not apply:
        print("  審査のみ — data/people.json には書いていない(data/yt_review.json を見ること)")
        print("  抜き取り検査を通したら --apply を付けて実行する")
        return 0

    write_json("people.json", new_people)
    meta["updated_at"] = meta["yt_updated_at"] = report["generated_at"]
    write_json("meta.json", meta)
    from .build import build
    build()
    print("  data/people.json と out/index.html を更新した")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
