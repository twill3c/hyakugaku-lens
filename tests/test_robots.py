# -*- coding: utf-8 -*-
"""T-19 — 取得の前に robots.txt を確かめる関門(N-05)。

なぜ要るか: loop_001 で researchmap の氏名検索 `/researchers?q=` を 19 回叩いた。
その経路は robots.txt が Disallow していた。**気づいたのは 3 ループ後**である。
記録だけでは再発するので、収集器の側に関門を置く。

期待値の出所:
- 判定規則は robots.txt の意味論(標準)そのもの
- 実データの検査は「出荷している取得経路が全て許可されていること」という不変量。
  件数は書かない(経路が増減しても壊れない)
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.robots import Disallowed, RobotsGate  # noqa: E402

RESEARCHMAP = b"""User-agent: *
Disallow: /researchers
Disallow: /*/misc/
"""

OPEN = b"User-agent: *\nDisallow:\n"


def gate(body=RESEARCHMAP, fail=False):
    def get(_url):
        if fail:
            raise OSError("robots.txt が取れない")
        return body
    return RobotsGate(get)


# --- 判定規則 ---------------------------------------------------------

def test_disallowed_path_is_refused():
    """実際に踏んだ経路がここで止まること(陽性対照)。"""
    g = gate()
    assert not g.allowed("https://researchmap.jp/researchers?q=%E6%9D%B1")


def test_allowed_path_passes():
    """陰性対照: 許可されている公開プロフィール直下は通ること。"""
    g = gate()
    assert g.allowed("https://researchmap.jp/read0211749")


def test_wildcard_rule_is_honoured():
    g = gate()
    assert not g.allowed("https://researchmap.jp/read0211749/misc/")


def test_site_without_restrictions_passes():
    g = gate(OPEN)
    assert g.allowed("https://example.org/anything/at/all")


def test_check_raises_with_the_offending_url():
    g = gate()
    with pytest.raises(Disallowed) as e:
        g.check("https://researchmap.jp/researchers?q=x")
    assert "researchmap.jp" in str(e.value)


def test_unreachable_robots_does_not_block():
    """robots.txt が取れないことを『禁止』と読み替えない。

    取れない理由は多くの場合ネットワーク側にあり、そこで全経路を止めると
    収集が静かに全滅する。**取れなかったことは記録に残す**。
    """
    g = gate(fail=True)
    assert g.allowed("https://example.org/x")
    assert g.unreachable == {"example.org"}


def test_robots_is_fetched_once_per_host():
    calls = []

    def get(url):
        calls.append(url)
        return OPEN

    g = RobotsGate(get)
    for path in ("/a", "/b", "/c"):
        g.allowed("https://example.org" + path)
    assert calls == ["https://example.org/robots.txt"]


# --- 出荷している取得経路 --------------------------------------------

def urls_we_fetch() -> list[str]:
    """定期実行が実際に叩く URL。人手の探索ではなく**繰り返し叩く経路**を対象にする。"""
    out = [s["feed"] for s in
           json.loads((ROOT / "data" / "sources.json").read_text(encoding="utf-8"))
           if not s.get("skip")]
    return out


def test_target_list_is_not_empty():
    assert urls_we_fetch(), "検査対象が空 — この検査は何も見ていない"


def _live_gate():
    from src.robots import RobotsGate as G
    return G()


@pytest.mark.network
def test_shipped_feeds_are_allowed():
    """実測。ネットワークが要るので既定では走らせない(`-m network` で実行)。

    この検査は 2026-08-31 に実際に 1 件見つけた —— NYT の署名コラム RSS は
    `/svc` 配下で、robots が禁じていた。見つけた経路は取り下げ、項目も消した。
    """
    g = _live_gate()
    bad = [u for u in urls_we_fetch() if not g.allowed(u)]
    assert not bad, f"robots が禁じている取得経路が出荷されている: {bad}"


@pytest.mark.network
def test_shipped_homepages_are_allowed():
    """公式サイト欄の URL も、こちらが取得して確かめている以上は同じ関門にかける。"""
    people = json.loads((ROOT / "data" / "people.json").read_text(encoding="utf-8"))
    g = _live_gate()
    bad = [p["h"] for p in people if p["h"] and not g.allowed(p["h"])]
    assert not bad, f"robots が禁じている公式サイト URL が出荷されている: {bad}"


# --- 規則の解釈(RFC 9309)-------------------------------------------

ALLOW_OVERRIDE = b"""User-agent: *
Disallow: /docs/
Allow: /docs/public/
"""

AGENT_SPECIFIC = b"""User-agent: *
Disallow: /

User-agent: hyakugaku-lens
Disallow: /private/
"""


def test_longest_match_wins_and_allow_breaks_ties():
    g = gate(ALLOW_OVERRIDE)
    assert not g.allowed("https://ex.org/docs/secret.html")
    assert g.allowed("https://ex.org/docs/public/a.html")


def test_agent_specific_group_replaces_the_star_group():
    g = gate(AGENT_SPECIFIC)
    assert g.allowed("https://ex.org/anything")
    assert not g.allowed("https://ex.org/private/x")


def test_empty_disallow_means_everything_is_allowed():
    g = gate(b"User-agent: *\nDisallow:\n")
    assert g.allowed("https://ex.org/a/b/c")


def test_dollar_anchors_the_end():
    g = gate(b"User-agent: *\nDisallow: /*.pdf$\n")
    assert not g.allowed("https://ex.org/a/b.pdf")
    assert g.allowed("https://ex.org/a/b.pdf.html")


def test_query_string_is_part_of_the_path():
    """踏んだ経路は `/researchers?q=...` だった。問い合わせ文字列も照合対象に入れる。"""
    g = gate(b"User-agent: *\nDisallow: /search?q=\n")
    assert not g.allowed("https://ex.org/search?q=x")
    assert g.allowed("https://ex.org/search")


def test_comments_are_ignored():
    g = gate(b"# comment\nUser-agent: *  # who\nDisallow: /x/  # why\n")
    assert not g.allowed("https://ex.org/x/y")
    assert g.allowed("https://ex.org/y")
