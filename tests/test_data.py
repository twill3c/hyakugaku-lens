# -*- coding: utf-8 -*-
"""T-01 / T-02 / T-12 — data/*.json のスキーマと名簿構成の検証。

期待値の出所:
- 人数 100 名・日本 20 名・分類 12 区分は SPEC.md §1 とユーザーの要件定義(2026-08-31)
- 分類ごとの人数は data/meta.json の cat_size に置き、テストは「データと meta が一致する」
  という不変量だけを主張する(件数の定数をテスト本体に書かない — HC-016)
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}|\d{4}-\d{2}|不明)$")
SECTIONS = ("own", "pub", "yt")
MAX_ITEMS = 3


@pytest.fixture(scope="module")
def people():
    return json.loads((ROOT / "data" / "people.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def meta():
    return json.loads((ROOT / "data" / "meta.json").read_text(encoding="utf-8"))


# --- T-01 -------------------------------------------------------------

def test_person_required_keys(people, meta):
    required = {"n", "en", "c", "aff", "field", "h", "bio", "own", "pub", "yt"}
    for p in people:
        assert required <= set(p), f"{p.get('n')}: 欠けたキー {required - set(p)}"
        assert p["c"] in meta["cats"], f"{p['n']}: 未知の分類 {p['c']}"
        for key in ("n", "en", "aff", "field", "bio"):
            assert p[key].strip(), f"{p['n']}: {key} が空"
        assert p["h"] == "" or p["h"].startswith(("http://", "https://"))


def test_items_shape(people, meta):
    for p in people:
        for sec in SECTIONS:
            assert isinstance(p[sec], list)
            assert len(p[sec]) <= MAX_ITEMS, f"{p['n']}/{sec}: {len(p[sec])} 件"
            for it in p[sec]:
                assert set(it) >= {"d", "t", "u", "s"}, f"{p['n']}: {it}"
                assert DATE_RE.match(it["d"]), f"{p['n']}: 日付 {it['d']!r}"
                assert it["u"].startswith(("http://", "https://")), it["u"]
                assert it["s"] in meta["src_label"], f"未知のソース種別 {it['s']}"
                assert it["t"].strip()


def test_names_unique(people):
    names = [p["n"] for p in people]
    ens = [p["en"] for p in people]
    assert len(set(names)) == len(names)
    assert len(set(ens)) == len(ens)


# --- T-02 -------------------------------------------------------------

def test_roster_size(people):
    assert len(people) == 100


def test_japan_share(people, meta):
    jp = [p for p in people if p["c"] in meta["jp_cats"]]
    assert len(jp) == 20


def test_categories_cover_meta(people, meta):
    used = {p["c"] for p in people}
    assert used == set(meta["cats"]), f"未使用の分類 {set(meta['cats']) - used}"
    assert len(meta["cats"]) == 12
    assert set(meta["cat_label"]) == set(meta["cats"])


def test_cat_size_matches_data(people, meta):
    from collections import Counter
    actual = Counter(p["c"] for p in people)
    assert dict(actual) == meta["cat_size"]


# --- T-12 -------------------------------------------------------------

def test_homepages_are_verified(people):
    """`h` が非空なら link_status.json に「到達し氏名を確認した」記録があること。

    推測した URL を出荷しないための歯止め(SPEC §4)。
    """
    status = json.loads((ROOT / "data" / "link_status.json").read_text(encoding="utf-8"))
    ok = {r["url"] for r in status["results"] if r["verified"]}
    for p in people:
        if p["h"]:
            assert p["h"] in ok, f"{p['n']}: 未検証の URL {p['h']}"


def test_link_status_has_negative_records(people):
    """陽性対照: 検証に落ちた URL が実在し、それが people.json に載っていないこと。

    全件 verified=True なら、この検査は「検証器が常に真を返す」場合と区別できない。
    """
    status = json.loads((ROOT / "data" / "link_status.json").read_text(encoding="utf-8"))
    failed = [r for r in status["results"] if not r["verified"]]
    assert failed, "検証に落ちた URL が 1 件も無い — 検証器が働いているか疑うこと"
    hs = {p["h"] for p in people}
    for r in failed:
        assert r["url"] not in hs, f"落ちた URL が出荷されている: {r['url']}"
