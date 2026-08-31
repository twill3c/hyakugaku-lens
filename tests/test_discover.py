# -*- coding: utf-8 -*-
"""T-16 — フィード採用の関門(tools/discover_feeds.judge)の検証。

このテストは loop_002 で実際に起きた二つの誤帰属を回帰として固定する。

  (a) The Conversation の著者フィード —— HTTP 200・Atom として妥当・しかし別人
  (b) ホスト一致だけを証拠にした結果、MIT 経済学部・コーネル法科大学院・OII・CEPR・
      note.com の**サイト全体のフィード**が本人の発信として 8 件混入した

期待値の出所: SPEC.md F-06 と上記の実測(2026-08-31)。フィード本文はテスト内で
組み立てた最小例で、主張したい性質(共著であること・表題に名前が無いこと)は
それぞれ対照ケースで assert している。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.feedparse import parse_feed          # noqa: E402
from tools.discover_feeds import judge        # noqa: E402

PERSON = {"n": "ダロン・アセモグル", "en": "Daron Acemoglu"}
LAZAR = {"n": "セス・ラザー", "en": "Seth Lazar"}
BALKIN = {"n": "ジャック・バルキン", "en": "Jack Balkin"}


def feed(title, entries):
    items = "".join(
        f"<item><title>{t}</title><link>{u}</link>"
        f"<pubDate>Mon, 03 Aug 2026 09:00:00 +0000</pubDate>"
        + (f"<dc:creator>{a}</dc:creator>" if a else "")
        + "</item>"
        for t, u, a in entries)
    return (f'<?xml version="1.0"?><rss version="2.0" '
            f'xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>'
            f"<title>{title}</title>{items}</channel></rss>").encode()


# 学部全体のフィード。表題に本人名は無く、著者も付かない
DEPARTMENT = feed("MIT Economics", [("Seminar notice", "https://economics.mit.edu/n1", "")])
# 本人の個人サイトのフィード
PERSONAL = feed("Seth Lazar", [("On AI power", "https://sethlazar.org/p1", "")])
# 共著ブログ。表題には本人の名前が入るが、記事は別人のもの
SHARED = feed("Balkinization", [("Guest post", "https://balkin.blogspot.com/g", "Guest Blogger"),
                                ("Another guest", "https://balkin.blogspot.com/h", "Sandy Levinson")])


def get(raw):
    return lambda _url: raw


# --- 対照の前提を固定する ------------------------------------------

def test_control_department_feed_has_no_name_and_no_author():
    items = parse_feed(DEPARTMENT)
    assert "acemoglu" not in "MIT Economics".lower()
    assert all(not i["author"] for i in items), "対照が『著者なし』でなければ検査は別物を見る"


def test_control_shared_feed_really_has_multiple_authors():
    authors = {i["author"] for i in parse_feed(SHARED)}
    assert len(authors) > 1, "対照が共著でなければ共著の規則を試せない"
    assert "balkin" in "Balkinization".lower(), "表題一致の誘惑が実在すること"


# --- (b) ホスト一致だけでは採らない --------------------------------

def test_site_wide_feed_rejected_when_homepage_is_a_subpage():
    """公式サイトが大きなサイトの 1 ページなら、ホスト一致は証拠にならない。"""
    rec = judge(PERSON, "https://economics.mit.edu/people/faculty/daron-acemoglu",
                "https://economics.mit.edu/rss.xml", get=get(DEPARTMENT))
    assert not rec["ok"], rec


def test_own_domain_accepted_when_homepage_is_root():
    rec = judge(LAZAR, "https://sethlazar.org/", "https://sethlazar.org/feed",
                get=get(PERSONAL))
    assert rec["ok"] and rec["evidence"] == "own-domain"


def test_own_domain_accepted_when_feed_is_under_homepage_path():
    rec = judge(LAZAR, "https://example.org/~lazar", "https://example.org/~lazar/feed",
                get=get(PERSONAL))
    assert rec["ok"] and rec["evidence"] == "own-domain"


# --- 共著フィードは著者一致でしか採らない --------------------------

def test_shared_feed_rejected_even_though_title_matches():
    rec = judge(BALKIN, "https://balkin.blogspot.com/",
                "https://balkin.blogspot.com/feeds/posts/default", get=get(SHARED))
    assert not rec["ok"], "表題一致で共著フィードを通してはならない"
    assert "共著" in rec["error"]


def test_shared_feed_accepted_with_author_condition():
    mixed = feed("Marginal Revolution",
                 [("Mine", "https://mr.com/a", "Tyler Cowen"),
                  ("Theirs", "https://mr.com/b", "Alex Tabarrok")])
    rec = judge({"n": "タイラー・コーエン", "en": "Tyler Cowen"},
                "https://marginalrevolution.com/", "https://marginalrevolution.com/feed",
                get=get(mixed))
    assert rec["ok"] and rec["evidence"] == "item-author"
    assert rec["author"] == ["Tyler Cowen"]


# --- (a) 別人のフィードは採らない ----------------------------------

def test_other_persons_feed_rejected():
    """取得できて妥当な Atom でも、表題が別人なら採らない(The Conversation の実例)。"""
    other = feed("Leping Mou – The Conversation",
                 [("Some article", "https://theconversation.com/x", "")])
    rec = judge({"n": "マーク・クーケルバーク", "en": "Mark Coeckelbergh"},
                "https://markcoeckelbergh.wordpress.com/",
                "https://theconversation.com/profiles/mark-coeckelbergh-1149861/articles.atom",
                get=get(other))
    assert not rec["ok"], rec


def test_empty_feed_rejected():
    rec = judge(LAZAR, "https://sethlazar.org/", "https://sethlazar.org/feed",
                get=get(b'<?xml version="1.0"?><rss version="2.0"><channel/></rss>'))
    assert not rec["ok"]
