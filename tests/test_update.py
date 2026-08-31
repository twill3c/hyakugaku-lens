# -*- coding: utf-8 -*-
"""T-06 / T-13 / T-14 — フィードパーサ・sources.json スキーマ・著者絞り込みの検証。

期待値の出所:
- T-06 の入力はテスト内で組み立てた最小のフィード。仕様(RSS2.0 / Atom / RSS1.0)から直接書いた
- T-14 の陽性対照は「他人の記事を含むフィード」を作り、絞り込みが実際にそれを落とすことを見る。
  対照が対照であること(混ぜた他人の記事が本当に入っていること)も assert で固定する
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.feedparse import parse_feed  # noqa: E402
from src.update import feed_items, run  # noqa: E402

RSS2 = """<?xml version="1.0"?><rss version="2.0"
 xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>Shared Blog</title>
<item><title>Mine</title><link>https://ex.org/a</link>
 <pubDate>Mon, 03 Aug 2026 09:00:00 +0000</pubDate><dc:creator>Tyler Cowen</dc:creator></item>
<item><title>Theirs</title><link>https://ex.org/b</link>
 <pubDate>Tue, 04 Aug 2026 09:00:00 +0000</pubDate><dc:creator>Alex Tabarrok</dc:creator></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<title>Personal</title>
<entry><title>Post</title><link rel="alternate" href="https://ex.org/p"/>
 <published>2026-07-01T10:00:00Z</published>
 <author><name>Seth Lazar</name></author></entry></feed>"""

RDF = """<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<item><title>RDF Post</title><link>https://ex.org/r</link>
 <dc:date>2026-06-05T00:00:00+09:00</dc:date><dc:creator>Someone</dc:creator></item></rdf:RDF>"""


# --- T-06 パーサ煙テスト ---------------------------------------------

@pytest.mark.parametrize("raw,url,date,author", [
    (RSS2, "https://ex.org/a", "2026-08-03", "Tyler Cowen"),
    (ATOM, "https://ex.org/p", "2026-07-01", "Seth Lazar"),
    (RDF, "https://ex.org/r", "2026-06-05", "Someone"),
])
def test_parse_formats(raw, url, date, author):
    got = parse_feed(raw.encode())
    assert got[0]["url"] == url
    assert got[0]["date"] == date
    assert got[0]["author"] == author


def test_non_feed_raises():
    with pytest.raises(ValueError):
        parse_feed(b"<html><body>not a feed</body></html>")


def test_empty_feed_raises():
    with pytest.raises(ValueError):
        parse_feed(b'<?xml version="1.0"?><rss version="2.0"><channel/></rss>')


# --- T-14 著者絞り込み(陽性対照つき)--------------------------------

def test_control_feed_actually_mixes_authors():
    """対照の前提: この共著フィードに本当に別人の記事が入っていること。"""
    authors = {e["author"] for e in parse_feed(RSS2.encode())}
    assert authors == {"Tyler Cowen", "Alex Tabarrok"}


def test_author_filter_keeps_only_the_person():
    got = feed_items(RSS2.encode(), "blog", "https://ex.org/", ["Tyler Cowen"])
    assert [i["u"] for i in got] == ["https://ex.org/a"]


def test_without_filter_all_items_pass():
    """対照: 条件を外せば別人の記事も通る(絞り込みが効いていることの裏づけ)。"""
    got = feed_items(RSS2.encode(), "blog", "https://ex.org/")
    assert len(got) == 2


def test_author_filter_drops_items_with_no_author():
    """条件が宣言されているのに著者が読めない項目は捨てる(誤帰属より欠落を選ぶ)。"""
    raw = b'<?xml version="1.0"?><rss version="2.0"><channel><item>' \
          b"<title>Anon</title><link>https://ex.org/x</link></item></channel></rss>"
    assert feed_items(raw, "blog", "https://ex.org/", ["Tyler Cowen"]) == []


# --- run() の劣化継続 ------------------------------------------------

def _person(own):
    return {"n": "P", "own": own, "pub": [], "yt": []}


def test_run_replaces_on_success():
    people = [_person([{"d": "2020-01-01", "t": "old", "u": "https://o", "s": "blog"}])]
    src = [{"n": "P", "s": "blog", "feed": "https://f"}]
    out, rep = run(people, src, fetch=lambda u: ATOM.encode())
    assert [i["u"] for i in out[0]["own"]] == ["https://ex.org/p"]
    assert rep["ok"] == 1 and rep["fail"] == 0


def test_run_keeps_on_failure():
    people = [_person([{"d": "2020-01-01", "t": "old", "u": "https://o", "s": "blog"}])]
    src = [{"n": "P", "s": "blog", "feed": "https://f"}]

    def boom(u):
        raise OSError("down")

    out, rep = run(people, src, fetch=boom)
    assert [i["u"] for i in out[0]["own"]] == ["https://o"]
    assert rep["ok"] == 0 and rep["fail"] == 1


def test_run_does_not_mutate_input():
    people = [_person([{"d": "2020-01-01", "t": "old", "u": "https://o", "s": "blog"}])]
    snapshot = json.loads(json.dumps(people))
    run(people, [{"n": "P", "s": "blog", "feed": "https://f"}], fetch=lambda u: ATOM.encode())
    assert people == snapshot


def test_run_skips_declared_skip():
    people = [_person([])]
    src = [{"n": "P", "s": "blog", "feed": "https://f", "skip": True}]
    out, rep = run(people, src, fetch=lambda u: ATOM.encode())
    assert out[0]["own"] == [] and rep["ok"] == 0 and rep["fail"] == 0


# --- T-13 sources.json スキーマ --------------------------------------

@pytest.fixture(scope="module")
def sources():
    return json.loads((ROOT / "data" / "sources.json").read_text(encoding="utf-8"))


def test_sources_reference_real_people(sources):
    names = {p["n"] for p in json.loads((ROOT / "data" / "people.json").read_text(encoding="utf-8"))}
    for s in sources:
        assert s["n"] in names, f"名簿に無い人物 {s['n']}"


AUTO_EVIDENCE = {"own-domain", "feed-title", "item-author"}
# 人が中身を見て採ると決めたもの(関門を外した分)
DECLARED_EVIDENCE = {"declared-site", "declared-author"}
# 多著者の論説媒体。採用条件は「その媒体が項目ごとに著者名を持つこと」で、
# 本人の記事が今あるかどうかとは独立に成り立つ(載っていない日は 0 件)
STANDING_EVIDENCE = {"standing-author"}


def test_sources_schema(sources):
    meta = json.loads((ROOT / "data" / "meta.json").read_text(encoding="utf-8"))
    for s in sources:
        assert s["s"] in meta["src_label"], s
        assert s["feed"].startswith(("http://", "https://")), s
        assert s["evidence"] in AUTO_EVIDENCE | DECLARED_EVIDENCE | STANDING_EVIDENCE, s
        if s["evidence"] in {"item-author", "declared-author", "standing-author"}:
            assert s.get("author"), f"{s['n']}: 著者条件が要る evidence なのに空"


def test_declared_sources_carry_a_reason(sources):
    """自動の関門を外した分は、外した理由を必ず書く(緩めた側だけを用意しない)。"""
    for s in sources:
        if s["evidence"] in DECLARED_EVIDENCE | STANDING_EVIDENCE:
            assert len(s.get("note", "")) >= 30, f"{s['n']}: 宣言の理由が書かれていない"


def test_declared_sources_stay_the_exception(sources):
    """人の判断で通した分は例外に留めること。関門の骨抜きを止める。

    standing-author は数に入れない —— あれは関門を外したのではなく、
    「著者名を持つ媒体だから著者で絞れる」という別の性質を機械で確かめている。
    """
    declared = [s for s in sources if s["evidence"] in DECLARED_EVIDENCE]
    auto = [s for s in sources if s["evidence"] in AUTO_EVIDENCE]
    assert len(declared) < len(auto), f"宣言 {len(declared)} 本 / 自動 {len(auto)} 本"


def test_standing_author_rows_name_the_person(sources):
    """常設の取得元は、誰の記事を採るのかを必ず名指しする(絞りの根拠)。"""
    for s in sources:
        if s["evidence"] in STANDING_EVIDENCE:
            assert s.get("author"), f"{s['n']}: 著者条件が無い"
            assert all(a.strip() for a in s["author"])


def test_sources_not_empty(sources):
    assert sources, "宣言フィードが 0 本 — 収集が何も動いていない"


def test_sources_unique_per_person_and_feed(sources):
    """同じフィードを複数人が指すのは正しい(多著者の媒体)。禁じるのは同じ組の重複。"""
    pairs = [(s["n"], s["feed"]) for s in sources]
    assert len(set(pairs)) == len(pairs), "同じ人・同じフィードの行が二重にある"


# --- CMS の初期投稿を落とす(陽性対照・陰性対照つき)-----------------

def test_boilerplate_titles_are_dropped():
    """WordPress 既定の "Hello world!" は本人の発信ではない(実測: 3 名で混入)。"""
    from src.update import is_boilerplate
    for t in ("Hello world!", "hello world", " Sample Page ", "Uncategorized"):
        assert is_boilerplate(t), t


def test_legitimate_titles_containing_the_phrase_are_kept():
    """陰性対照: 語句を含むだけの正当な見出しを撃たない。"""
    from src.update import is_boilerplate
    for t in ("Hello world, a history of programming",
              "Sample Page Layouts in Early Print",
              "世界に「はじめての投稿」をした人たち"):
        assert not is_boilerplate(t), t


def test_boilerplate_filter_applies_in_feed_items():
    raw = ('<?xml version="1.0"?><rss version="2.0"><channel>'
           "<item><title>Hello world!</title><link>https://ex.org/1</link></item>"
           "<item><title>Real post</title><link>https://ex.org/2</link></item>"
           "</channel></rss>").encode()
    got = feed_items(raw, "blog", "https://ex.org/")
    assert [i["t"] for i in got] == ["Real post"]


def test_skipped_sources_state_the_reason(sources):
    """止めたフィードには止めた理由を書く(黙って消さない)。"""
    for s in sources:
        if s.get("skip"):
            assert len(s.get("skip_reason", "")) >= 15, f"{s['n']}: skip の理由が無い"


def test_boilerplate_is_purged_even_when_fetch_fails():
    """収集に失敗しても、既存側の初期投稿は残さない(劣化継続の抜け道を塞ぐ)。"""
    people = [_person([{"d": "2016-02-08", "t": "Hello world!", "u": "https://x", "s": "blog"}])]
    out, _ = run(people, [{"n": "P", "s": "blog", "feed": "https://f"}],
                 fetch=lambda u: (_ for _ in ()).throw(OSError("down")))
    assert out[0]["own"] == []


# --- robots の関門が実際に効くこと(陽性対照)------------------------

class _DenyAll:
    def check(self, url):
        from src.robots import Disallowed
        raise Disallowed(f"robots.txt が禁じている経路: {url}")


class _AllowAll:
    def check(self, url):
        return None


def test_run_refuses_a_disallowed_feed():
    """関門を渡したとき、実際に取得が止まり劣化継続になること。"""
    people = [_person([{"d": "2020-01-01", "t": "old", "u": "https://o", "s": "blog"}])]
    src = [{"n": "P", "s": "blog", "feed": "https://f"}]
    calls = []
    out, rep = run(people, src, fetch=lambda u: calls.append(u) or ATOM.encode(),
                   gate=_DenyAll())
    assert calls == [], "禁じられているのに取りに行った"
    assert [i["u"] for i in out[0]["own"]] == ["https://o"], "既存が維持されていない"
    assert "Disallowed" in rep["sources"][0]["error"]


def test_run_proceeds_when_allowed():
    """陰性対照: 許可されていれば通ること(関門が常に落とすのではない)。"""
    people = [_person([])]
    out, rep = run(people, [{"n": "P", "s": "blog", "feed": "https://f"}],
                   fetch=lambda u: ATOM.encode(), gate=_AllowAll())
    assert rep["ok"] == 1 and out[0]["own"]
