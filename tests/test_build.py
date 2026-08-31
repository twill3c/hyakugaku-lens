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
    "__WALKTHROUGH_URL__", "__BLUEPRINT_URL__",
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
