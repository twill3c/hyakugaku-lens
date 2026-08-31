# -*- coding: utf-8 -*-
"""【使用停止】researchmap の氏名検索から本人のプロフィールを同定していた道具。

**この道具は使ってはならない。** researchmap の robots.txt は `/researchers`(氏名検索)を
Disallow している。loop_001 で 19 回叩いたあと、loop_004 でそれに気づいた ——
**取得の前に robots.txt を読む**という手順が抜けていた。

得られた 19 件のプロフィール URL は、公開プロフィール直下(`/<id>`。robots で許可されている)
への到達と氏名一致を `tools/verify_links.py` が改めて確かめており、出荷データはそのまま使える。
業績の収集は `/*/published_papers/` を含む下位ページがすべて Disallow のため行わない。

再現の必要が出た場合は、researchmap の公式 API か sitemap.xml から辿る経路を先に探すこと。
ソースは経緯の記録として残す(実行はしない)。
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.verify_links import fetch, visible_text  # noqa: E402

SEARCH = "https://researchmap.jp/researchers?q="
ID_RE = re.compile(r'href="/([a-zA-Z0-9_.\-]{5,40})"')
SKIP_IDS = {"researchers"}


def candidates(q: str) -> list[str]:
    _, html, _ = fetch(SEARCH + urllib.parse.quote(q))
    seen, out = set(), []
    for m in ID_RE.finditer(html):
        i = m.group(1)
        if i in SKIP_IDS or i in seen:
            continue
        seen.add(i)
        out.append(i)
    return out[:8]


def resolve(row: dict) -> dict:
    rec = {"n": row["n"], "url": "", "verified": False, "tried": []}
    try:
        ids = candidates(row["q"])
    except Exception as e:                                  # noqa: BLE001
        rec["error"] = f"検索失敗 {type(e).__name__}"
        return rec
    for i in ids:
        url = f"https://researchmap.jp/{i}"
        try:
            code, html, _ = fetch(url)
        except Exception:                                   # noqa: BLE001
            rec["tried"].append({"id": i, "why": "取得失敗"})
            continue
        text = visible_text(html).replace("　", " ")
        flat = re.sub(r"\s+", "", text)
        name_ok = re.sub(r"\s+", "", row["q"]) in flat
        inst_hit = [k for k in row["inst"] if k in flat]
        rec["tried"].append({"id": i, "name": name_ok, "inst": inst_hit})
        if code == 200 and name_ok and inst_hit:
            rec.update(url=url, verified=True, matched_inst=inst_hit)
            return rec
    return rec


def main(path: str, out: str) -> int:
    rows = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    res = [resolve(r) for r in rows]
    for r in res:
        mark = "ok " if r["verified"] else "NG "
        print(f"  {mark}{r['n']:8s} {r['url'] or r.get('error','所属一致せず')}"
              f"  {r.get('matched_inst','')}")
    Path(out).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in res),
                         encoding="utf-8", newline="\n")
    print(f"同定 {sum(1 for r in res if r['verified'])}/{len(res)} 名")
    return 0


if __name__ == "__main__":
    raise SystemExit("この道具は使用停止(researchmap の robots.txt が /researchers を Disallow)")
