# -*- coding: utf-8 -*-
"""定期更新エントリポイント: python -m src.update(F-07)

data/sources.json の宣言フィードを収集し、成功した種別だけ own を差し替えて
data/people.json を更新、meta.json の時刻を進め、out/index.html を再生成する。

共著ブログ(Marginal Revolution・Balkinization など)は `author` 条件を持つ。
**条件が宣言されているのに著者が読めない項目は捨てる** —— 誤って他人の記事を
本人の発信として載せるより、載せないほうがよい。

exit code: 全フィード失敗のみ 1(それ以外は劣化継続で 0)。
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .feedparse import parse_feed
from .merge import merge_section

ROOT = Path(__file__).resolve().parents[1]
UA = "hyakugaku-lens/1.0 (+https://github.com/twill3c/hyakugaku-lens)"
UNKNOWN = "不明"


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, */*"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def read_json(name: str):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def write_json(name: str, obj) -> None:
    (ROOT / "data" / name).write_text(
        json.dumps(obj, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")


def absolutize(u: str, base: str) -> str:
    """フィード内 URL の絶対化。スキームなし・ホスト先頭(ofir.io/…)にも対応。"""
    if u.startswith(("http://", "https://")):
        return u
    if u.startswith("//"):
        return "https:" + u
    host = urllib.parse.urlparse(base).netloc
    if u.startswith(host + "/"):
        return "https://" + u
    return urllib.parse.urljoin(base, u)


# CMS の初期投稿。本人の発信ではないが、休止中のブログではこれだけが残る。
# 見出し全体がこれと一致するときだけ落とす(語句を含む正当な題を撃たないため)
BOILERPLATE = {"hello world", "hello world!", "sample page", "uncategorized",
               "サンプルページ", "はじめての投稿"}


def is_boilerplate(title: str) -> bool:
    return title.strip().lower().rstrip("!！") in {t.rstrip("!！") for t in BOILERPLATE}


def feed_items(raw: bytes, s: str, base: str = "", authors: list[str] | None = None) -> list[dict]:
    """フィードを本文項目に整形する。authors が指定されたら著者一致のものだけを残す。"""
    keys = [a.lower() for a in (authors or [])]
    items = []
    for e in parse_feed(raw):
        if not (e["title"] and e["url"]):
            continue
        if is_boilerplate(e["title"]):
            continue
        if keys:
            who = (e.get("author") or "").lower()
            if not who or not any(k in who for k in keys):
                continue
        u = absolutize(e["url"], base)
        if u.startswith(("http://", "https://")):
            items.append({"d": e["date"] or UNKNOWN, "t": e["title"].strip(), "u": u, "s": s})
    return items


def run(people, sources, fetch=http_get, now=""):
    """(people, report) を返す純関数コア。people は書き換えず新リストを返す。"""
    by_name: dict[str, list[dict]] = {}
    status, ok_count = [], 0
    sources = [s for s in sources if not s.get("skip")]
    for src in sources:
        rec = {"n": src["n"], "s": src["s"], "feed": src["feed"], "ok": False, "count": 0}
        try:
            items = feed_items(fetch(src["feed"]), src["s"], src["feed"], src.get("author"))
        except Exception as e:                              # noqa: BLE001 — 失敗は劣化継続
            rec["error"] = f"{type(e).__name__}: {e}"[:200]
            items = []
        if items:
            rec.update(ok=True, count=len(items))
            ok_count += 1
            by_name.setdefault(src["n"], []).append({"s": src["s"], "items": items})
        status.append(rec)

    out_people = []
    for p in people:
        # 既存側にも同じ関門を掛ける。フィードが空になった休止中のブログでは、
        # 初期投稿だけが「劣化継続」で残り続ける —— 収集の成否によらず落とす
        kept = [i for i in p["own"] if not is_boilerplate(i["t"])]
        got = by_name.get(p["n"])
        if not got:
            if len(kept) != len(p["own"]):
                p = dict(p, own=kept)
            out_people.append(p)
            continue
        q = dict(p)
        q["own"] = merge_section(kept,
                                 [i for g in got for i in g["items"]],
                                 {g["s"] for g in got})
        out_people.append(q)

    return out_people, {"generated_at": now, "ok": ok_count,
                        "fail": len(sources) - ok_count, "sources": status}


def main() -> int:
    people, meta, sources = read_json("people.json"), read_json("meta.json"), read_json("sources.json")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    new_people, report = run(people, sources, now=now)

    write_json("people.json", new_people)
    meta["updated_at"] = meta["feed_updated_at"] = now
    write_json("meta.json", meta)
    write_json("update_status.json", report)

    from .build import build
    build()

    print(f"update: {report['ok']}/{report['ok'] + report['fail']} フィード成功")
    for s in report["sources"]:
        print(f"  {'ok ' if s['ok'] else 'NG '}{s['n']} [{s['s']}] {s['count']} 件 {s.get('error', '')}")
    return 0 if (report["ok"] > 0 or not sources) else 1


if __name__ == "__main__":
    sys.exit(main())
