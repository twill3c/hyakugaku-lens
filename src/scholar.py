# -*- coding: utf-8 -*-
"""学術発表の更新エントリポイント: python -m src.scholar(F-08)

`data/scholar_ids.json` の**同定済み**著者 ID から OpenAlex の最近の業績を取り、
各人の pub セクションを差し替える。ID は固定で持つ —— 実行時に氏名で検索し直すと、
同姓同名の別人に静かに入れ替わる(loop_003 で工学者と法哲学者の実例)。

採る条件:
- 発表年があること(年しか無い業績は `YYYY` ではなく publication_date を使う)
- 題名があり、到達できる URL(DOI か OpenAlex のランディング)があること
- 撤回済み・paratext(表紙・目次など)でないこと

exit code: 同定済みが 1 人もいない場合のみ 1(個別の失敗は劣化継続で 0)。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .merge import merge_section
from .robots import RobotsGate

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.openalex.org"
UA = "hyakugaku-lens/1.0 (mailto:twill3c@gmail.com)"
PAUSE = 0.2
PER_PAGE = 8

# OpenAlex の type → 表示するソース種別
KIND = {"book": "book", "book-chapter": "book", "monograph": "book"}


def http_get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read())


def read_json(name: str):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def write_json(name: str, obj) -> None:
    (ROOT / "data" / name).write_text(
        json.dumps(obj, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")


def works_url(author_id: str) -> str:
    q = urllib.parse.urlencode({
        "filter": f"author.id:{author_id},is_paratext:false,is_retracted:false",
        "sort": "publication_date:desc",
        "per-page": PER_PAGE,
        "select": "id,doi,title,publication_date,type",
    })
    return f"{API}/works?{q}"


def landing(work: dict) -> str:
    if work.get("doi"):
        return work["doi"] if work["doi"].startswith("http") else "https://doi.org/" + work["doi"]
    wid = work.get("id", "")
    return wid if wid.startswith("http") else ""


def title_key(title: str) -> str:
    """同じ論文の別版をまとめるための鍵。

    OpenAlex はプレプリント・出版版・大文字小文字違いを別レコードで持つ。実測(2026-08-31)で
    ボストロムの 8 件中 4 件が同一論文の別版だった。英数字だけを残して畳む。
    """
    return "".join(c for c in title.lower() if c.isalnum())


def work_items(payload: dict) -> list[dict]:
    """結果は publication_date の降順で来る。同じ題名は最初に出たもの(=最新)だけ残す。"""
    out: list[dict] = []
    seen: set[str] = set()
    for w in payload.get("results", []):
        title = (w.get("title") or "").strip()
        url = landing(w)
        date = (w.get("publication_date") or "").strip()
        if not (title and url.startswith("http") and len(date) == 10):
            continue
        key = title_key(title)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"d": date, "t": title, "u": url,
                    "s": KIND.get(w.get("type", ""), "paper")})
    return out


def verified_ids(doc: dict) -> dict[str, str]:
    return {r["n"]: r["openalex_id"] for r in doc["results"] if r.get("verified")}


def run(people, ids: dict[str, str], fetch=http_get_json, now="", gate=None):
    """(people, report) を返す純関数コア。people は書き換えない。

    gate は robots.txt の関門(None なら確認しない — 単体テスト用)。
    """
    status, ok_count = [], 0
    got: dict[str, list[dict]] = {}
    for name, aid in ids.items():
        rec = {"n": name, "openalex_id": aid, "ok": False, "count": 0}
        try:
            if gate is not None:
                gate.check(works_url(aid))
            items = work_items(fetch(works_url(aid)))
        except Exception as e:                              # noqa: BLE001 — 失敗は劣化継続
            rec["error"] = f"{type(e).__name__}: {e}"[:200]
            items = []
        if items:
            rec.update(ok=True, count=len(items))
            ok_count += 1
            got[name] = items
        status.append(rec)
        time.sleep(PAUSE)

    out_people = []
    for p in people:
        items = got.get(p["n"])
        if not items:
            out_people.append(p)
            continue
        q = dict(p)
        q["pub"] = merge_section(p["pub"], items, {"paper", "book"})
        out_people.append(q)
    return out_people, {"generated_at": now, "ok": ok_count,
                        "fail": len(ids) - ok_count, "authors": status}


def main() -> int:
    people, meta = read_json("people.json"), read_json("meta.json")
    ids = verified_ids(read_json("scholar_ids.json"))
    if not ids:
        print("同定済みの著者が 1 人もいない — 先に tools/resolve_openalex.py を走らせること")
        return 1
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    new_people, report = run(people, ids, now=now, gate=RobotsGate())

    write_json("people.json", new_people)
    meta["updated_at"] = meta["pub_updated_at"] = now
    write_json("meta.json", meta)
    write_json("scholar_status.json", report)

    from .build import build
    build()

    print(f"scholar: {report['ok']}/{len(ids)} 名で業績を取得")
    for s in report["authors"]:
        if not s["ok"]:
            print(f"  NG {s['n']} {s.get('error', '業績が 0 件')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
