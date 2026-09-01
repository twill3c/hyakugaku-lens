# -*- coding: utf-8 -*-
"""T-23 — YouTube 候補の収集と誤帰属ゲート(F-11)。

**この 100 名に対して YouTube は姉妹プロジェクトより条件が悪い。** 学者は
「本人が話す動画」より「第三者が本人について語る動画」のほうが多いからである。
実測の裏づけが二つある:

  - hyakunin-lens は氏名一致 + 新着順だけで「本人について騒ぐ切り抜き」が通り、
    精選データを汚染して revert で復旧した(DATA-QUAL S2)
  - 本プロジェクトのポッドキャスト探索でも、「著者一致」8 件がすべて同姓同名の
    別人、題名一致の大半は本人を**語る**番組だった(loop_010)

そこでゲートは較正済みのものを移植し、**初回は people.json に書かない**。
候補を審査用ファイルへ出して抜き取り検査を通す。

期待値の出所: ゲートの各条件は hyakunin-lens loop_005 の較正結果。
API の応答はテスト内で組み立てた最小例で、実物の形(items[].id.videoId /
snippet.title / publishedAt / channelTitle)に合わせてある。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.youtube import (  # noqa: E402
    accepted_forms, name_variants, query_term, search_person, title_matches,
    todays_bucket, run_yt,
)


def person(n, en, **kw):
    base = {"n": n, "en": en, "own": [], "pub": [], "yt": []}
    base.update(kw)
    return base


def api(*items):
    return json.dumps({"items": [
        {"id": {"videoId": v}, "snippet": {"title": t, "publishedAt": d + "T00:00:00Z",
                                           "channelTitle": c}}
        for v, t, d, c in items]}).encode()


# --- 氏名の語形 -------------------------------------------------------

def test_latin_and_middle_initial():
    assert name_variants("Philip N. Howard") == ["Philip N. Howard", "Philip Howard"]


def test_japanese_name_is_kept_whole():
    assert name_variants("東浩紀") == ["東浩紀"]


def test_title_gate_accepts_the_person():
    assert title_matches("Yuval Noah Harari on AI and the future", "Yuval Noah Harari")


def test_title_gate_rejects_when_the_name_is_absent():
    """陰性対照: 名前の無い題名は通さない(検索語の残響で拾わない)。"""
    assert not title_matches("The future of artificial intelligence", "Yuval Noah Harari")


def test_shorts_are_rejected_even_with_the_name():
    """陽性対照: 切り抜きの印がある題名は、名前が入っていても落とす。"""
    assert not title_matches("Yuval Noah Harari on AI #shorts", "Yuval Noah Harari")


# --- 検索と絞り込み ---------------------------------------------------

def test_search_applies_the_query_gate():
    """関門は URL の側にもある。長尺・関連度順の条件が問い合わせに入ること。"""
    seen = {}

    def fetch(url):
        seen["url"] = url
        return api(("v1", "Seth Lazar: AI and Power", "2026-08-01", "ANU"))

    got = search_person(person("セス・ラザー", "Seth Lazar"), "KEY", fetch)
    assert "videoDuration=long" in seen["url"]
    assert "order=relevance" in seen["url"]
    assert got[0]["u"] == "https://www.youtube.com/watch?v=v1"
    assert got[0]["o"] == "ANU" and got[0]["d"] == "2026-08-01"


def test_search_counts_what_it_dropped():
    """黙って捨てない。落とした理由と件数が返ること(HC-116)。"""
    raw = api(("v1", "Seth Lazar on AI", "2026-08-01", "ANU"),
              ("v2", "Explaining AI ethics", "2026-08-02", "SomeChannel"),
              ("v3", "Seth Lazar clip #shorts", "2026-08-03", "Clips"))
    dropped: dict[str, int] = {}
    got = search_person(person("セス・ラザー", "Seth Lazar"), "KEY", lambda u: raw, dropped=dropped)
    assert [i["u"].endswith("v1") for i in got] == [True]
    assert dropped == {"題名に氏名が無い": 1, "切り抜きの印": 1}, dropped


# --- 日次ローテーション -----------------------------------------------

def test_bucket_alternates_by_day():
    from datetime import datetime, timezone
    a = todays_bucket(datetime(2026, 9, 1, tzinfo=timezone.utc))
    b = todays_bucket(datetime(2026, 9, 2, tzinfo=timezone.utc))
    assert {a, b} == {0, 1}, "日をまたいでも同じ組しか回らない"


def test_only_todays_half_is_searched():
    """1 日の検索は半数まで(search.list は 100 units・無料枠 10,000/日)。"""
    people = [person(f"P{i}", f"Person {i}") for i in range(100)]
    calls = []

    def fetch(u):
        calls.append(u)
        return api()

    run_yt(people, "KEY", fetch, bucket=0)
    assert len(calls) == 50, f"{len(calls)} 回検索した(上限 50)"


# --- 既存項目との関係 -------------------------------------------------

def _person(**kw):
    return person("セス・ラザー", "Seth Lazar", **kw)


def test_urls_already_shown_elsewhere_are_excluded():
    """他の欄に出ている動画を、講演・対談へ二重に載せない。"""
    dup = "https://www.youtube.com/watch?v=v1"
    people = [_person(own=[{"d": "2026-01-01", "t": "x", "u": dup, "s": "blog"}])]
    raw = api(("v1", "Seth Lazar on AI", "2026-08-01", "ANU"))
    _, rep = run_yt(people, "KEY", lambda u: raw, bucket=0)
    assert rep["people"][0]["count"] == 0


def test_failure_keeps_existing_items():
    people = [_person(yt=[{"d": "2020-01-01", "t": "old", "u": "https://o", "s": "podcast"}])]

    def boom(u):
        raise OSError("down")

    out, rep = run_yt(people, "KEY", boom, bucket=0)
    assert [i["u"] for i in out[0]["yt"]] == ["https://o"]
    assert rep["people"][0]["ok"] is False


def test_podcast_items_survive_a_youtube_update():
    """種別が違う項目は差し替えの対象外(劣化継続の規則)。"""
    people = [_person(yt=[{"d": "2026-08-30", "t": "第1回", "u": "https://show", "s": "podcast"}])]
    raw = api(("v1", "Seth Lazar on AI", "2026-08-01", "ANU"))
    out, _ = run_yt(people, "KEY", lambda u: raw, bucket=0)
    kinds = {i["s"] for i in out[0]["yt"]}
    assert "podcast" in kinds and "yt" in kinds


def test_run_does_not_mutate_input():
    people = [_person()]
    snapshot = json.loads(json.dumps(people))
    run_yt(people, "KEY", lambda u: api(("v1", "Seth Lazar talk", "2026-08-01", "ANU")), bucket=0)
    assert people == snapshot


# --- 検索語の選び方(実測 2026-09-01 の失敗)---------------------------

def test_foreign_scholars_are_searched_by_original_spelling():
    """表示名(カタカナ)で引いてはならない。

    「ペーター=ポール・フェルベーク」の表示名から取った「ペーター」で引いたところ、
    22 件すべてが別物だった(あつ森の住民・連続殺人犯・聖ペーター教会)。
    """
    p = person("ペーター=ポール・フェルベーク", "Peter-Paul Verbeek")
    assert query_term(p) == "Peter-Paul Verbeek"


def test_japanese_scholars_are_searched_by_their_kanji_name():
    """日本の学者はローマ字より漢字のほうが当たる。"""
    assert query_term(person("東浩紀", "Hiroki Azuma")) == "東浩紀"


def test_control_the_katakana_name_really_is_ambiguous():
    """対照の前提: 表示名の先頭語が短く、他に当たりうること。

    これが成り立たないなら、原綴で引く理由が無い。
    """
    p = person("ペーター=ポール・フェルベーク", "Peter-Paul Verbeek")
    first = name_variants(p["n"])[0]
    assert len(first) <= 4, f"{first!r} は十分に短く曖昧"


def test_both_spellings_are_accepted_in_titles():
    """日本語の媒体は原綴でなくカタカナで書くことがあるので、題名側は両方許す。"""
    p = person("ユヴァル・ノア・ハラリ", "Yuval Noah Harari")
    forms = accepted_forms(p)
    assert title_matches("Yuval Noah Harari on AI", forms)
    assert title_matches("ユヴァル・ノア・ハラリが語るAIの未来", forms)


def test_limit_caps_how_many_are_searched():
    """少量で測れること(クォータを使い切らずに較正するため)。"""
    people = [person(f"P{i}", f"Person {i}") for i in range(100)]
    calls = []
    run_yt(people, "KEY", lambda u: calls.append(u) or api(), bucket=0, limit=6)
    assert len(calls) == 6


# --- チャンネル許可リスト(loop_012)-----------------------------------

ALLOW = {("Closer To Truth", "スーザン・シュナイダー"),
         ("ORBITS - Luciano Floridi", "ルチアーノ・フロリディ")}


def test_only_allowlisted_channels_are_accepted():
    """題名に氏名があっても、許可していないチャンネルは採らない。

    実測(2026-09-01)で、題名の字面では「本人による」と「本人についての」を
    分けられなかった。分けられるのは**場**のほうである。
    """
    raw = api(("v1", "The Biggest AI Risks | Susan Schneider", "2026-08-16", "Closer To Truth"),
              ("v2", "Susan Schneider explained", "2026-08-17", "Some Explainer Channel"))
    people = [person("スーザン・シュナイダー", "Susan Schneider")]
    out, rep = run_yt(people, "KEY", lambda u: raw, bucket=0, channels=ALLOW)
    assert [i["u"].endswith("v1") for i in out[0]["yt"]] == [True]
    assert rep["people"][0]["dropped"] == {"許可していないチャンネル": 1}


def test_channel_match_ignores_case_and_spacing():
    raw = api(("v1", "Susan Schneider on AI", "2026-08-16", "  CLOSER  To Truth "))
    people = [person("スーザン・シュナイダー", "Susan Schneider")]
    out, _ = run_yt(people, "KEY", lambda u: raw, bucket=0, channels=ALLOW)
    assert out[0]["yt"]


def test_empty_allowlist_accepts_nothing():
    """陽性対照: 許可リストが空なら 1 件も通らない(関門が効いていることの裏づけ)。"""
    raw = api(("v1", "Susan Schneider on AI", "2026-08-16", "Closer To Truth"))
    people = [person("スーザン・シュナイダー", "Susan Schneider")]
    out, _ = run_yt(people, "KEY", lambda u: raw, bucket=0, channels=set())
    assert out[0]["yt"] == []


def test_no_allowlist_argument_keeps_the_old_behaviour():
    """陰性対照: 許可リストを渡さない審査モードでは、従来どおり全候補が残る。"""
    raw = api(("v1", "Susan Schneider on AI", "2026-08-16", "Anywhere"))
    people = [person("スーザン・シュナイダー", "Susan Schneider")]
    _, rep = run_yt(people, "KEY", lambda u: raw, bucket=0)
    assert rep["people"][0]["count"] == 1


def test_rejected_candidates_are_kept_for_review():
    """許可外のものも審査用に残す —— 許可リストはここから育てる。"""
    raw = api(("v1", "Susan Schneider on AI", "2026-08-16", "New Venue"))
    people = [person("スーザン・シュナイダー", "Susan Schneider")]
    _, rep = run_yt(people, "KEY", lambda u: raw, bucket=0, channels=ALLOW)
    assert [c["o"] for c in rep["people"][0]["pending"]] == ["New Venue"]


def test_allowlist_entries_carry_the_evidence_that_admitted_them():
    """許可したチャンネルには、**実際に読んだ題名**を証拠として残す。

    「その場が本人を招いている」という判断は機械にはできない。だから
    判断の材料を消さずに置く —— 後から見て、なぜ通したかが分かるように。
    """
    path = ROOT / "data" / "yt_channels.jsonl"
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert rows, "許可リストが空"
    kinds = {"own", "interview", "institution", "event", "press"}
    for r in rows:
        assert r["ch"].strip(), r
        assert r["kind"] in kinds, r
        assert len(r["seen"]) >= 10, f"{r['ch']}: 根拠の題名が無い"
        assert r["for"].strip(), r


def test_allowlist_has_no_duplicate_pairs():
    """鍵は(チャンネル, 人物)の組。同じチャンネルが複数の人物に出るのは正しい。"""
    from src.youtube import norm_channel
    path = ROOT / "data" / "yt_channels.jsonl"
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    pairs = [(norm_channel(r["ch"]), r["for"]) for r in rows]
    assert len(set(pairs)) == len(pairs)


def test_allowlist_names_only_people_on_the_roster():
    """陽性対照: 許可が実在の人物を指していること(名簿の改名で腐らせない)。"""
    names = {p["n"] for p in json.loads((ROOT / "data" / "people.json").read_text(encoding="utf-8"))}
    path = ROOT / "data" / "yt_channels.jsonl"
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    unknown = {r["for"] for r in rows} - names
    assert not unknown, f"名簿に無い人物を指している: {unknown}"


def test_allowlist_is_per_channel_and_person():
    """ある人を招く場が、別の人も招くとは限らない。

    実測(loop_012): マッカスキルの回で許可した Zenvora Productions が、
    **同名の別人**(柔術コーチのジョン・ダナハー)の回を 3 件通した。
    その局は有名ポッドキャストの非公式再アップを集約するチャンネルだった。
    """
    raw = api(("v1", "John Danaher: The Path to Mastery in Jiu Jitsu", "2026-08-05", "Closer To Truth"))
    people = [person("ジョン・ダナハー", "John Danaher")]
    out, rep = run_yt(people, "KEY", lambda u: raw, bucket=0, channels=ALLOW)
    assert out[0]["yt"] == [], "別人物に対して許可が波及している"
    assert rep["people"][0]["pending"], "審査用に残っていない"


def test_allowlist_admits_the_person_it_was_vouched_for():
    """陰性対照: 同じチャンネルでも、名指しした人物なら通る。"""
    raw = api(("v1", "The Biggest AI Risks | Susan Schneider", "2026-08-16", "Closer To Truth"))
    people = [person("スーザン・シュナイダー", "Susan Schneider")]
    out, _ = run_yt(people, "KEY", lambda u: raw, bucket=0, channels=ALLOW)
    assert out[0]["yt"]
