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


# 0 件の欄に出す理由の語彙(F-13)。文は表示用だが、それぞれ収集の記録に対する述語に
# 対応している(HC-079)。{n} は件数・本数で、build 時にデータから埋める
REASONS = {
    "own_no_site":     "公式サイトが未確認で、取得元も無い",
    "own_no_source":   "取得元なし(公式サイトにフィードが見つからない)",
    "own_zero":        "取得元 {n} 本・現在は本人の記事なし",
    "own_error":       "取得元 {n} 本が取得できず",
    "pub_excluded":    "OpenAlex の対象外(所属を持たない)",
    "pub_no_match":    "OpenAlex に同定できず(所属と分野の二要素を満たす候補なし)",
    "pub_unreachable": "OpenAlex に照会できず(利用枠の回復待ち)",
    "pub_zero":        "同定済み・直近の業績が取れていない",
    "pub_error":       "同定済み・業績の取得に失敗",
    "yt_pending":      "審査待ちの候補 {n} 件(許可した場がまだ無い)",
    "yt_none":         "直近半年の検索に候補なし(題名に氏名を含む長尺動画が無い)",
    "yt_unsearched":   "未検索",
    "yt_error":        "検索できず",
}


def _read_optional(name: str) -> dict:
    path = ROOT / "data" / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_context() -> dict:
    """理由を導くための収集の記録。無いファイルは空として扱う。"""
    return {
        "sources": json.loads((ROOT / "data" / "sources.json").read_text(encoding="utf-8"))
        if (ROOT / "data" / "sources.json").exists() else [],
        "update_status": _read_optional("update_status.json"),
        "scholar_ids": _read_optional("scholar_ids.json"),
        "scholar_status": _read_optional("scholar_status.json"),
        "yt_review": _read_optional("yt_review.json"),
    }


def _own_reason(p: dict, ctx: dict) -> str:
    srcs = [s for s in ctx.get("sources", [])
            if s["n"] == p["n"] and s.get("sec", "own") == "own" and not s.get("skip")]
    if not srcs:
        return REASONS["own_no_site"] if not p.get("h") else REASONS["own_no_source"]
    feeds = {s["feed"] for s in srcs}
    recs = [r for r in ctx.get("update_status", {}).get("sources", [])
            if r["n"] == p["n"] and r["feed"] in feeds]
    if recs and all(r.get("error") for r in recs):
        return REASONS["own_error"].format(n=len(srcs))
    return REASONS["own_zero"].format(n=len(srcs))


def _pub_reason(p: dict, ctx: dict) -> str:
    ids = [r for r in ctx.get("scholar_ids", {}).get("results", []) if r["n"] == p["n"]]
    if not ids:
        return REASONS["pub_excluded"]
    r = ids[0]
    if not r.get("verified"):
        unreachable = r.get("error") or any("fetch_failed" in str(t) for t in r.get("tried", []))
        return REASONS["pub_unreachable"] if unreachable else REASONS["pub_no_match"]
    st = [a for a in ctx.get("scholar_status", {}).get("authors", []) if a["n"] == p["n"]]
    if st and st[0].get("error"):
        return REASONS["pub_error"]
    return REASONS["pub_zero"]


def _yt_reason(p: dict, ctx: dict) -> str:
    recs = [r for r in ctx.get("yt_review", {}).get("people", []) if r["n"] == p["n"]]
    if not recs:
        return REASONS["yt_unsearched"]
    r = recs[0]
    if r.get("error"):
        return REASONS["yt_error"]
    if r.get("pending"):
        return REASONS["yt_pending"].format(n=len(r["pending"]))
    return REASONS["yt_none"]


def reasons(people: list[dict], ctx: dict) -> dict[str, dict[str, str]]:
    """人ごと・欄ごとに、0 件である理由を収集の記録から導く。項目のある欄には付けない。"""
    fn = {"own": _own_reason, "pub": _pub_reason, "yt": _yt_reason}
    out: dict[str, dict[str, str]] = {}
    for p in people:
        why = {sec: fn[sec](p, ctx) for sec in SECTIONS if not p.get(sec)}
        if why:
            out[p["n"]] = why
    return out


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
            .replace("__WHY__", j(reasons(people, load_context())))
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
