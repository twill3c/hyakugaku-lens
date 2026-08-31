# -*- coding: utf-8 -*-
"""名簿 JSONL から data/people.json を初期化する(立ち上げ時に一度だけ使う)。

既存の people.json があるときは own/pub/yt を引き継ぎ、名簿側の記述(所属・紹介文)だけを更新する。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = ("own", "pub", "yt")


def main(src: str) -> int:
    rows = [json.loads(l) for l in Path(src).read_text(encoding="utf-8").splitlines() if l.strip()]
    dest = ROOT / "data" / "people.json"
    prev = {p["n"]: p for p in json.loads(dest.read_text(encoding="utf-8"))} if dest.exists() else {}
    out = []
    for r in rows:
        old = prev.get(r["n"], {})
        rec = {k: r[k] for k in ("n", "en", "c", "aff", "field", "h", "bio")}
        if r["n"] in prev:
            rec["h"] = old.get("h", r["h"])
        for s in SECTIONS:
            rec[s] = old.get(s, [])
        out.append(rec)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8", newline="\n")
    print(f"{dest} に {len(out)} 名を書いた")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "data/_roster.jsonl"))
