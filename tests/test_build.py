# -*- coding: utf-8 -*-
"""T-03 / T-04 / T-05 / T-06 / T-09 / T-10 — ビルド器の検証。

期待値の出所:
- T-03(往復一致)は「出力に埋めた JSON が入力と同一である」という不変量。定数は持たない
- T-04 のプレースホルダ名は src/template.html を実際に読んで列挙した(2026-08-31)
- 分類チップ 12 個は SPEC.md F-03
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import build as B  # noqa: E402


@pytest.fixture(scope="module")
def html():
    B.build()
    return (ROOT / "out" / "index.html").read_text(encoding="utf-8")


def _grab(html: str, name: str):
    """`const P = {...}` 形式で埋め込んだ JSON を再抽出する。"""
    m = re.search(rf"\b{name} = (\[.*?\]|\{{.*?\}})[,;]?\n", html, re.S)
    assert m, f"{name} を出力から取り出せない"
    return json.loads(m.group(1))


# --- T-03 往復一致オラクル -------------------------------------------

def test_roundtrip_people(html):
    assert _grab(html, "P") == json.loads((ROOT / "data" / "people.json").read_text(encoding="utf-8"))


def test_roundtrip_meta(html):
    meta = json.loads((ROOT / "data" / "meta.json").read_text(encoding="utf-8"))
    assert _grab(html, "CAT_LABEL") == meta["cat_label"]
    assert _grab(html, "SRC") == meta["src_label"]
    assert _grab(html, "CATS") == meta["cats"]


# --- T-04 出力健全性 -------------------------------------------------

PLACEHOLDERS = [
    "__PEOPLE__", "__CAT_LABEL__", "__SRC__", "__CATS__", "__COUNTS__",
    "__CAT_CHIPS__", "__UPDATED__", "__FEED_UPDATED__", "__PUB_UPDATED__",
    "__WALKTHROUGH_URL__", "__BLUEPRINT_URL__", "__WHY__",
]


def test_no_placeholder_left(html):
    for ph in PLACEHOLDERS:
        assert ph not in html, f"未置換のプレースホルダ {ph}"


def test_placeholders_are_all_present_in_template():
    """陽性対照: 上の一覧が template の実際のプレースホルダを取りこぼしていないこと。"""
    tpl = (ROOT / "src" / "template.html").read_text(encoding="utf-8")
    found = set(re.findall(r"__[A-Z_]+__", tpl))
    assert found == set(PLACEHOLDERS), f"一覧と template の差 {found ^ set(PLACEHOLDERS)}"


def test_counts_line_embedded(html):
    people = json.loads((ROOT / "data" / "people.json").read_text(encoding="utf-8"))
    assert B.counts_line(people) in html


def test_cat_chips(html):
    meta = json.loads((ROOT / "data" / "meta.json").read_text(encoding="utf-8"))
    for c in meta["cats"]:
        assert f'data-cat="{c}"' in html
    assert html.count('class="chip" data-cat=') == len(meta["cats"])


def test_ui_parts(html):
    for frag in ("const esc =", 'id="q"', 'id="fOwn"', 'id="fPub"', 'id="fYt"',
                 'id="f1m"', 'id="f1w"', 'id="grid"'):
        assert frag in html, frag


def test_self_contained(html):
    """外部リソース参照が無いこと(N-02 / F-02)。本文リンクの href は対象外。"""
    bad = re.findall(r'<(?:script|img|iframe)[^>]+src=|<link[^>]+href="https?://', html)
    assert not bad, bad


# --- T-05 決定性 -----------------------------------------------------

def test_deterministic():
    a = B.build().read_bytes()
    b = B.build().read_bytes()
    assert a == b


# --- T-06 件数行の算出 -----------------------------------------------

def test_counts_line_is_computed():
    base = [{"n": "x", "own": [], "pub": [], "yt": []}]
    line0 = B.counts_line(base)
    plus = [{"n": "x", "own": [{"d": "不明"}], "pub": [], "yt": []}]
    line1 = B.counts_line(plus)
    assert line0 != line1, "項目を足しても件数行が変わらない — 定数を書いていないか"
    assert "1名" in line0
    assert "合計 0件" in line0 and "合計 1件" in line1


# --- T-09 フッタ -----------------------------------------------------

def test_footer(html):
    m = re.search(r"<footer>(.*?)</footer>", html, re.S)
    assert m, "footer が無い"
    foot = m.group(1)
    for frag in ("MIT License", "GitHub", "の歩き方", "設計図", "App Menu"):
        assert frag in foot, frag
    assert re.search(r"footer\{[^}]*position:fixed", html), "フッタが画面最下部に固定されていない"


def test_updated_line(html):
    meta = json.loads((ROOT / "data" / "meta.json").read_text(encoding="utf-8"))
    assert B.updated_jst(meta) in html


# --- T-10 エスケープ -------------------------------------------------

def test_escape_helper_covers_specials():
    """テンプレートの esc が & < > " を落とさないこと(陽性対照つき)。"""
    tpl = (ROOT / "src" / "template.html").read_text(encoding="utf-8")
    m = re.search(r"const esc = .*?;\n", tpl, re.S)
    assert m
    src = m.group(0)
    for ch, ent in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;")):
        assert ent in src, f"{ch} の変換が無い"


def test_no_raw_angle_brackets_in_embedded_json(html):
    """埋め込み JSON 内に生の </script> が現れないこと。"""
    body = html.split("const P = ", 1)[1]
    assert "</script>" not in body.split("</script>")[0] + ""
    assert html.count("</script>") == 1


# --- T-29 0 件の理由(loop_015)-------------------------------------------
#
# 「確認できず」は三つの違う状態を一語で潰していた —— 取得元が無い / 取得元はあるが
# 現在 0 件 / 取得に失敗。理由は表示用の文ではなく、収集の記録(sources.json・
# update_status.json・scholar_ids.json・scholar_status.json・yt_review.json)から
# 導いた述語に対応させる(HC-079: 判定を表に出す記号は、仕様のどの述語かを言えること)。
# 期待値の出所: 各記録ファイルの実際の形(2026-09-06 に data/ を読んで確認)。

from src.build import REASONS, load_context, reasons  # noqa: E402


def _p(n, h="", **kw):
    base = {"n": n, "en": n, "h": h, "own": [], "pub": [], "yt": []}
    base.update(kw)
    return base


def _ctx(sources=(), update=(), ids=(), status=(), review=()):
    return {"sources": list(sources),
            "update_status": {"sources": list(update)},
            "scholar_ids": {"results": list(ids)},
            "scholar_status": {"authors": list(status)},
            "yt_review": {"people": list(review)}}


def test_reasons_cover_every_empty_section_and_only_those():
    """実データ: 空の欄には必ず理由が付き、項目のある欄には付かない。"""
    people = json.loads((ROOT / "data" / "people.json").read_text(encoding="utf-8"))
    why = reasons(people, load_context())
    for p in people:
        for sec in ("own", "pub", "yt"):
            if p[sec]:
                assert sec not in why.get(p["n"], {}), f"{p['n']}/{sec}: 項目があるのに理由が付いた"
            else:
                assert why[p["n"]][sec].strip(), f"{p['n']}/{sec}: 空の欄に理由が無い"


def test_reason_texts_come_from_the_vocabulary():
    """理由は語彙表(REASONS)の型から作る。自由文を返さない。"""
    import re as _re
    people = json.loads((ROOT / "data" / "people.json").read_text(encoding="utf-8"))
    why = reasons(people, load_context())
    patterns = [_re.compile("^" + _re.escape(t).replace(r"\{n\}", r"\d+") + "$") for t in REASONS.values()]
    for n, secs in why.items():
        for sec, text in secs.items():
            assert any(pt.match(text) for pt in patterns), f"{n}/{sec}: 語彙表に無い理由 {text!r}"


def test_own_reasons_distinguish_no_source_zero_and_error():
    people = [_p("A"), _p("B", h="https://b.example/"),
              _p("C", h="https://c.example/"), _p("D", h="https://d.example/")]
    ctx = _ctx(
        sources=[{"n": "C", "s": "media", "feed": "https://ps/rss", "evidence": "standing-author"},
                 {"n": "C", "s": "media", "feed": "https://aeon/rss", "evidence": "standing-author"},
                 {"n": "D", "s": "blog", "feed": "https://d.example/feed", "evidence": "own-domain"}],
        update=[{"n": "C", "feed": "https://ps/rss", "ok": False, "count": 0},
                {"n": "C", "feed": "https://aeon/rss", "ok": False, "count": 0},
                {"n": "D", "feed": "https://d.example/feed", "ok": False, "count": 0,
                 "error": "HTTPError: HTTP Error 404"}])
    why = reasons(people, ctx)
    assert why["A"]["own"] == REASONS["own_no_site"]
    assert why["B"]["own"] == REASONS["own_no_source"]
    assert why["C"]["own"] == REASONS["own_zero"].format(n=2)
    assert why["D"]["own"] == REASONS["own_error"].format(n=1)


def test_own_reason_ignores_skipped_sources_and_talk_sources():
    """skip した取得元と、講演・対談(sec=yt)へ入れる取得元は、本人の発信の取得元に数えない。"""
    people = [_p("E", h="https://e.example/")]
    ctx = _ctx(sources=[{"n": "E", "s": "blog", "feed": "https://e/feed", "evidence": "own-domain", "skip": True},
                        {"n": "E", "s": "podcast", "feed": "https://e/pod", "evidence": "declared-host", "sec": "yt"}])
    assert reasons(people, ctx)["E"]["own"] == REASONS["own_no_source"]


def test_pub_reasons_distinguish_excluded_no_match_zero_and_error():
    people = [_p("E"), _p("F"), _p("G"), _p("H"), _p("I")]
    ctx = _ctx(
        ids=[{"n": "F", "verified": False},
             {"n": "G", "verified": False, "error": "HTTPError: 429"},
             {"n": "H", "verified": True, "openalex_id": "A1"},
             {"n": "I", "verified": True, "openalex_id": "A2"}],
        status=[{"n": "H", "openalex_id": "A1", "ok": False, "count": 0},
                {"n": "I", "openalex_id": "A2", "ok": False, "count": 0, "error": "URLError"}])
    why = reasons(people, ctx)
    assert why["E"]["pub"] == REASONS["pub_excluded"]
    assert why["F"]["pub"] == REASONS["pub_no_match"]
    assert why["G"]["pub"] == REASONS["pub_unreachable"]
    assert why["H"]["pub"] == REASONS["pub_zero"]
    assert why["I"]["pub"] == REASONS["pub_error"]


def test_yt_reasons_distinguish_pending_none_unsearched_and_error():
    people = [_p("J"), _p("K"), _p("L"), _p("M")]
    ctx = _ctx(review=[{"n": "J", "ok": False, "count": 0, "candidates": [],
                        "pending": [{"u": "https://1"}, {"u": "https://2"}, {"u": "https://3"}]},
                       {"n": "K", "ok": False, "count": 0, "candidates": []},
                       {"n": "M", "ok": False, "count": 0, "error": "HTTPError: 403"}])
    why = reasons(people, ctx)
    assert why["J"]["yt"] == REASONS["yt_pending"].format(n=3)
    assert why["K"]["yt"] == REASONS["yt_none"]
    assert why["L"]["yt"] == REASONS["yt_unsearched"]
    assert why["M"]["yt"] == REASONS["yt_error"]


def test_reasons_do_not_mutate_input():
    people = [_p("A")]
    snapshot = json.loads(json.dumps(people))
    reasons(people, _ctx())
    assert people == snapshot


def test_why_roundtrip(html):
    """往復一致: 出力に埋めた WHY は、データから導いた理由と完全一致する。"""
    people = json.loads((ROOT / "data" / "people.json").read_text(encoding="utf-8"))
    assert _grab(html, "WHY") == reasons(people, load_context())


def test_template_renders_the_reason_instead_of_a_fixed_phrase():
    tpl = (ROOT / "src" / "template.html").read_text(encoding="utf-8")
    assert "WHY[p.n]" in tpl, "カードが理由表を参照していない"
    assert '<div class="none">確認できず</div>' not in tpl, "固定文のままになっている"
