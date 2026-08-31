# -*- coding: utf-8 -*-
"""T-17 / T-18 — OpenAlex の同定関門と学術発表の取り込みの検証。

期待値の出所:
- 二要素の関門(所属 × 分野)は SPEC.md F-08。判定の入力はテスト内で組み立てた候補で、
  **実測で見つかった誤同定**(慶應の T. Ohya は法哲学者ではなく映像符号化の工学者)を
  そのまま対照にしている(2026-08-31)
- 取り込みの条件(題名・到達できる URL・完全な日付)は src/scholar.py の docstring
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.scholar import run, verified_ids, work_items, works_url  # noqa: E402
from tools.resolve_openalex import judge  # noqa: E402

DECL = {"n": "大屋雄裕", "q": "Takehiro Ohya", "inst": ["Keio", "Nagoya"]}


def author(name, insts, doms, works=10, aid="A1"):
    return {
        "id": f"https://openalex.org/{aid}",
        "display_name": name,
        "works_count": works,
        "last_known_institutions": [{"display_name": i} for i in insts],
        "affiliations": [],
        "topics": [{"domain": {"display_name": d}} for d in doms],
    }


# --- T-17 二要素の関門 ------------------------------------------------

def test_control_wrong_person_really_shares_the_institution():
    """対照の前提: 誤同定の候補は所属が一致していること(一致しないなら関門を試せない)。"""
    engineer = author("T. Ohya", ["Keio University"], ["Physical Sciences", "Health Sciences"])
    v = judge(DECL, engineer)
    assert v["inst_hit"] == ["Keio"], "所属で当たらない候補では対照にならない"


def test_institution_alone_does_not_pass():
    """所属が合っていても分野が違えば採らない(実測の誤同定を落とす)。"""
    engineer = author("T. Ohya", ["Keio University"], ["Physical Sciences", "Health Sciences"])
    assert not judge(DECL, engineer)["ok"]


def test_domain_alone_does_not_pass():
    """分野が合っていても所属が違えば採らない。"""
    other = author("Takehiro Ohya", ["Some Other University"], ["Social Sciences"])
    v = judge(DECL, other)
    assert v["domain_ok"] and not v["inst_hit"]
    assert not v["ok"]


def test_both_factors_pass():
    real = author("Takehiro Ohya", ["Nagoya University"], ["Social Sciences", "Physical Sciences"])
    assert judge(DECL, real)["ok"]


def test_humanities_domain_also_passes():
    hum = author("Donna Haraway", ["University of California, Santa Cruz"],
                 ["Arts and Humanities", "Life Sciences"])
    assert judge({"n": "x", "q": "Donna Haraway", "inst": ["Santa Cruz"]}, hum)["ok"]


def test_affiliation_history_counts():
    """異動した人は last_known では当たらない。過去の所属も手がかりにする。"""
    a = author("Takehiro Ohya", [], ["Social Sciences"])
    a["affiliations"] = [{"institution": {"display_name": "Nagoya University"}}]
    assert judge(DECL, a)["ok"]


# --- T-18 業績の取り込み ---------------------------------------------

def payload(*works):
    return {"results": list(works)}


def test_work_items_shape():
    got = work_items(payload({"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/x",
                              "title": "Law and computation", "publication_date": "2026-04-02",
                              "type": "article"}))
    assert got == [{"d": "2026-04-02", "t": "Law and computation",
                    "u": "https://doi.org/10.1/x", "s": "paper"}]


def test_books_are_labelled_as_books():
    got = work_items(payload({"id": "https://openalex.org/W2", "doi": None, "title": "A Book",
                              "publication_date": "2025-01-01", "type": "book"}))
    assert got[0]["s"] == "book" and got[0]["u"] == "https://openalex.org/W2"


def test_bare_doi_is_made_absolute():
    got = work_items(payload({"id": "https://openalex.org/W3", "doi": "10.5/y", "title": "T",
                              "publication_date": "2025-01-01", "type": "article"}))
    assert got[0]["u"] == "https://doi.org/10.5/y"


def test_incomplete_records_are_dropped():
    """題名なし・日付が年だけ・到達先なしは採らない。"""
    bad = payload(
        {"id": "https://openalex.org/W4", "title": "", "publication_date": "2026-01-01"},
        {"id": "https://openalex.org/W5", "title": "Year only", "publication_date": "2026"},
        {"id": "", "doi": None, "title": "No landing", "publication_date": "2026-01-01"},
    )
    assert work_items(bad) == []


def test_query_excludes_paratext_and_retractions():
    """関門は URL の側にもある。取り下げ論文や目次を数に入れない。"""
    u = works_url("A5017802782")
    assert "is_paratext%3Afalse" in u or "is_paratext:false" in u
    assert "is_retracted%3Afalse" in u or "is_retracted:false" in u
    assert "publication_date%3Adesc" in u or "publication_date:desc" in u


# --- 劣化継続と入力非破壊 --------------------------------------------

def _person(pub):
    return {"n": "P", "own": [], "pub": pub, "yt": []}


def test_failure_keeps_existing_pub():
    people = [_person([{"d": "2020-01-01", "t": "old", "u": "https://o", "s": "paper"}])]

    def boom(_u):
        raise OSError("down")

    out, rep = run(people, {"P": "A1"}, fetch=boom)
    assert [i["u"] for i in out[0]["pub"]] == ["https://o"]
    assert rep["ok"] == 0 and rep["fail"] == 1


def test_success_replaces_pub():
    people = [_person([{"d": "2020-01-01", "t": "old", "u": "https://o", "s": "paper"}])]
    ok = payload({"id": "https://openalex.org/W9", "doi": None, "title": "New",
                  "publication_date": "2026-02-02", "type": "article"})
    out, _ = run(people, {"P": "A1"}, fetch=lambda _u: ok)
    assert [i["t"] for i in out[0]["pub"]] == ["New"]


def test_run_does_not_mutate_input():
    people = [_person([{"d": "2020-01-01", "t": "old", "u": "https://o", "s": "paper"}])]
    snapshot = json.loads(json.dumps(people))
    run(people, {"P": "A1"}, fetch=lambda _u: payload())
    assert people == snapshot


def test_verified_ids_ignores_unverified():
    doc = {"results": [{"n": "A", "verified": True, "openalex_id": "A1"},
                       {"n": "B", "verified": False}]}
    assert verified_ids(doc) == {"A": "A1"}


# --- 実データの記録 ---------------------------------------------------

def test_scholar_ids_record_exists_and_has_negatives():
    """同定に落ちた人が居ること。全員通るなら関門が働いているか疑う。"""
    doc = json.loads((ROOT / "data" / "scholar_ids.json").read_text(encoding="utf-8"))
    assert doc["verified"] >= 1
    assert doc["verified"] < doc["declared"], "全員が通っている — 二要素の関門を疑うこと"


def test_shipped_pub_items_come_from_verified_authors():
    """出荷している業績が、同定済みの人のものだけであること。"""
    doc = json.loads((ROOT / "data" / "scholar_ids.json").read_text(encoding="utf-8"))
    ok = set(verified_ids(doc))
    people = json.loads((ROOT / "data" / "people.json").read_text(encoding="utf-8"))
    for p in people:
        if p["pub"]:
            assert p["n"] in ok, f"{p['n']}: 同定していないのに業績が載っている"


# --- 同一論文の別版をまとめる(実測: ボストロムで 8 件中 4 件が同一)---

def test_duplicate_versions_are_collapsed():
    from src.scholar import title_key
    dup = payload(
        {"id": "https://openalex.org/W1", "doi": None,
         "title": "How malicious AI swarms can threaten democracy",
         "publication_date": "2026-01-22", "type": "article"},
        {"id": "https://openalex.org/W2", "doi": None,
         "title": "How malicious AI swarms can threaten democracy.",
         "publication_date": "2026-01-22", "type": "preprint"},
        {"id": "https://openalex.org/W3", "doi": None,
         "title": "How Malicious AI Swarms Can Threaten Democracy",
         "publication_date": "2025-09-26", "type": "preprint"},
    )
    assert title_key("How malicious AI swarms can threaten democracy.") == \
           title_key("How Malicious AI Swarms Can Threaten Democracy")
    got = work_items(dup)
    assert len(got) == 1
    assert got[0]["d"] == "2026-01-22", "残すのは最新版"


def test_different_titles_are_not_collapsed():
    """陰性対照: 別の論文をまとめてしまわない。"""
    from src.scholar import title_key
    assert title_key("The ethics of digital duplicates") != title_key("The ethics of digital twins")
    two = payload(
        {"id": "https://openalex.org/W1", "doi": None, "title": "Paper A",
         "publication_date": "2026-01-01", "type": "article"},
        {"id": "https://openalex.org/W2", "doi": None, "title": "Paper B",
         "publication_date": "2025-01-01", "type": "article"},
    )
    assert len(work_items(two)) == 2


def test_record_separates_unreachable_from_no_match():
    """『取れなかった』と『該当しなかった』を混ぜない(loop_003 の実測 S2)。

    混ぜると、レート制限で全滅した日に「日本の学者は OpenAlex に載っていない」という
    誤った結論が出荷される。三分割の合計が宣言数に一致することを固定する。
    """
    doc = json.loads((ROOT / "data" / "scholar_ids.json").read_text(encoding="utf-8"))
    for k in ("verified", "no_match", "unreachable"):
        assert k in doc, f"{k} が記録されていない"
    assert doc["verified"] + doc["no_match"] + doc["unreachable"] == doc["declared"]


def test_scholar_run_refuses_when_robots_disallows():
    """陽性対照: 関門が落とせば取りに行かず、既存を維持すること。"""
    from src.robots import Disallowed

    class Deny:
        def check(self, url):
            raise Disallowed(url)

    people = [_person([{"d": "2020-01-01", "t": "old", "u": "https://o", "s": "paper"}])]
    calls = []
    out, rep = run(people, {"P": "A1"},
                   fetch=lambda u: calls.append(u) or payload(), gate=Deny())
    assert calls == []
    assert [i["u"] for i in out[0]["pub"]] == ["https://o"]
    assert rep["ok"] == 0
