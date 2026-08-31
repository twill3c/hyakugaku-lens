# -*- coding: utf-8 -*-
"""data/people.json + data/meta.json + src/template.html → out/index.html を生成する。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECTIONS = ("own", "pub", "yt")


def load() -> tuple[list, dict]:
    people = json.loads((ROOT / "data" / "people.json").read_text(encoding="utf-8"))
    meta = json.loads((ROOT / "data" / "meta.json").read_text(encoding="utf-8"))
    return people, meta


def counts_line(people: list[dict]) -> str:
    """件数行。数字はすべてデータから算出する(F-04 — 手書きの数字を置かない)。"""
    n = {s: sum(len(p[s]) for p in people) for s in SECTIONS}
    total = sum(n.values())
    empty = sum(1 for p in people if not any(p[s] for s in SECTIONS))
    return (f"{len(people)}名 · 本人の発信 {n['own']}件 · 学術発表 {n['pub']}件 · "
            f"講演・対談 {n['yt']}件 · 合計 {total}件 · すべて0件の人 {empty}名")


def _jst(iso: str, fmt: str) -> str:
    dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=9))).strftime(fmt)


def updated_jst(meta: dict) -> str:
    iso = meta.get("updated_at")
    return _jst(iso, "%Y-%m-%d %H:%M JST") if iso else f"{meta['collected_on']}(名簿を作成)"


def layer_jst(meta: dict, key: str) -> str:
    iso = meta.get(key)
    return _jst(iso, "%Y-%m-%d") if iso else "未実行"


def cat_chips(meta: dict) -> str:
    return "\n  ".join(
        f'<span class="chip" data-cat="{c}">{meta["cat_label"].get(c, c)}'
        f'<i>{meta["cat_size"][c]}</i></span>'
        for c in meta["cats"]
    )


def build() -> Path:
    people, meta = load()
    tpl = (ROOT / "src" / "template.html").read_text(encoding="utf-8")
    j = lambda v: json.dumps(v, ensure_ascii=False)          # noqa: E731
    html = (tpl
            .replace("__PEOPLE__", j(people))
            .replace("__CAT_LABEL__", j(meta["cat_label"]))
            .replace("__SRC__", j(meta["src_label"]))
            .replace("__CATS__", j(meta["cats"]))
            .replace("__COUNTS__", counts_line(people))
            .replace("__UPDATED__", updated_jst(meta))
            .replace("__FEED_UPDATED__", layer_jst(meta, "feed_updated_at"))
            .replace("__PUB_UPDATED__", layer_jst(meta, "pub_updated_at"))
            .replace("__WALKTHROUGH_URL__", meta["links"]["walkthrough"] or "#")
            .replace("__BLUEPRINT_URL__", meta["links"]["blueprint"] or "#")
            .replace("__CAT_CHIPS__", cat_chips(meta)))
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    dest = out / "index.html"
    dest.write_text(html, encoding="utf-8", newline="\n")
    return dest


if __name__ == "__main__":
    d = build()
    print(f"{d} ({d.stat().st_size:,} bytes)")
