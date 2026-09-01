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

    channels を渡すと、**そのチャンネルの動画だけ**を採る。題名の字面では
    「本人による」と「本人についての」を分けられないことが実測で分かったので、
    分けられるもの——**場**——で絞る(loop_011 の四つの規則がいずれも届かなかった)。
    許可外の候補は捨てずに `pending` へ入れる。許可リストはそこから育てる。
    None を渡すと絞らない(審査モード)。
    """
    allow = None if channels is None else {norm_channel(c) for c in channels}
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
            if allow is not None and norm_channel(i["o"]) not in allow:
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


def http_get(url: str) -> bytes:
    time.sleep(1.2)                                          # 連続 50 検索の 429 予防
    req = urllib.request.Request(url, headers={"User-Agent": "hyakugaku-lens/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def load_channels() -> set[str]:
    """`data/yt_channels.jsonl` の許可チャンネル。無ければ空(=何も通さない)。"""
    path = ROOT / "data" / "yt_channels.jsonl"
    if not path.exists():
        return set()
    return {json.loads(l)["ch"] for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}


def read_json(name: str):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def write_json(name: str, obj) -> None:
    (ROOT / "data" / name).write_text(
        json.dumps(obj, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    argv = argv or []
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
