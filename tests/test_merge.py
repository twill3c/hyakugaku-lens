# -*- coding: utf-8 -*-
"""T-07 / T-08 — 並べ替えと差し替えマージの検証。

期待値の出所: SPEC.md F-07(成功種別のみ差し替え・日付降順・不明は末尾・最大 3 件)。
入力はすべてテスト内で組み立てた最小例で、フィクスチャの性質に依存しない。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.merge import MAX_ITEMS, merge_section, sort_items  # noqa: E402


def it(d, u, s="blog", t="t"):
    return {"d": d, "t": t, "u": u, "s": s}


# --- T-07 並べ替え ---------------------------------------------------

def test_unknown_goes_last():
    got = sort_items([it("不明", "a"), it("2026-01-01", "b"), it("", "c")])
    assert [x["u"] for x in got] == ["b", "a", "c"]


def test_year_month_compares_as_first_of_month():
    """2026-03 は 2026-03-01 として比較される(2026-02-28 より新しい)。"""
    got = sort_items([it("2026-02-28", "a"), it("2026-03", "b"), it("2026-03-02", "c")])
    assert [x["u"] for x in got] == ["c", "b", "a"]


def test_sort_is_stable_for_equal_dates():
    got = sort_items([it("2026-01-01", "a"), it("2026-01-01", "b")])
    assert [x["u"] for x in got] == ["a", "b"]


# --- T-08 マージ規則 -------------------------------------------------

def test_success_type_replaced():
    existing = [it("2020-01-01", "old", "blog")]
    fetched = [it("2026-01-01", "new", "blog")]
    got = merge_section(existing, fetched, {"blog"})
    assert [x["u"] for x in got] == ["new"]


def test_other_types_kept():
    existing = [it("2020-01-01", "x1", "x"), it("2020-01-01", "old", "blog")]
    fetched = [it("2026-01-01", "new", "blog")]
    got = merge_section(existing, fetched, {"blog"})
    assert {x["u"] for x in got} == {"new", "x1"}


def test_failure_keeps_existing():
    existing = [it("2020-01-01", "old", "blog")]
    got = merge_section(existing, [], set())
    assert [x["u"] for x in got] == ["old"]


def test_dedupe_by_url():
    fetched = [it("2026-01-01", "same"), it("2025-01-01", "same")]
    got = merge_section([], fetched, {"blog"})
    assert len(got) == 1


def test_cap_at_max():
    fetched = [it(f"2026-01-0{i}", f"u{i}") for i in range(1, 6)]
    got = merge_section([], fetched, {"blog"})
    assert len(got) == MAX_ITEMS
    assert [x["u"] for x in got] == ["u5", "u4", "u3"]


def test_input_not_mutated():
    existing = [it("2020-01-01", "old", "blog")]
    snapshot = [dict(x) for x in existing]
    merge_section(existing, [it("2026-01-01", "new", "blog")], {"blog"})
    assert existing == snapshot


# --- 同じ URL でも見出しが違えば別の項目(実測: ポッドキャスト)-------

def test_same_url_different_titles_are_kept():
    """回ごとのページを持たない番組では、複数の回が同じ番組ページを指す。

    実測(2026-09-01): megaphone のフィードは 336 件中 191 件に item/link が無い。
    URL だけで畳むと、その番組は 1 件しか出せなくなる。
    """
    show = "https://www.ppfideas.com/"
    got = merge_section([], [it("2026-08-30", show, "podcast", "第1回"),
                             it("2026-08-26", show, "podcast", "第2回")], {"podcast"})
    assert len(got) == 2
    assert [x["t"] for x in got] == ["第1回", "第2回"]


def test_same_url_same_title_still_collapses():
    """陰性対照: 本当に同じ項目は畳む(重複排除を無効にしたのではない)。"""
    got = merge_section([], [it("2026-08-30", "https://a", "blog", "同じ見出し"),
                             it("2026-08-26", "https://a", "blog", "同じ見出し")], {"blog"})
    assert len(got) == 1
