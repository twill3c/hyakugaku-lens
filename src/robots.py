# -*- coding: utf-8 -*-
"""取得の前に robots.txt を確かめる関門(N-05)。

**なぜ要るか。** loop_001 で researchmap の氏名検索 `/researchers?q=` を 19 回叩いた。
その経路は robots.txt が Disallow していた。気づいたのは 3 ループ後である。
「気をつける」では再発するので、繰り返し叩く経路には機械の関門を置く。

判定は自前で行う。標準ライブラリの `urllib.robotparser` は経路の**途中**のワイルドカードを
解釈せず、`Disallow: /*/misc/` を素通しにする —— まさにこの関門が止めたい形である
(researchmap の robots.txt はこの形を 18 行使っている)。RFC 9309 の規則に従い、
`*` と `$` を扱い、**最も長く一致した規則が勝ち、同じ長さなら Allow が勝つ**。

ホストごとに 1 回だけ取得して覚える。

**取れなかったことを『禁止』と読み替えない。** robots.txt が落ちる理由はたいてい
ネットワーク側にあり、そこで全経路を止めると収集が静かに全滅する。取れなかったホストは
`unreachable` に記録して通す —— 判断の材料は残し、収集は止めない。
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request

UA = "hyakugaku-lens"


class Disallowed(RuntimeError):
    """robots.txt が禁じている URL を取りに行こうとした。"""


def _to_regex(pattern: str) -> re.Pattern[str]:
    """robots の経路パターンを正規表現にする。`*` は任意列、末尾の `$` は行末。"""
    end = pattern.endswith("$")
    body = pattern[:-1] if end else pattern
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile("^" + rx + ("$" if end else ""))


def parse_rules(text: str, agent: str) -> list[tuple[bool, str, re.Pattern[str]]]:
    """`*` と自分向けの群から (許可か, パターン文字列, 正規表現) を集める。

    自分向けの群があればそれだけを使う(RFC 9309: 最も限定的な群が 1 つだけ効く)。
    """
    groups: dict[str, list[tuple[bool, str]]] = {}
    current: list[str] = []
    starting = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            if not starting:
                current, starting = [], True
            current.append(value.lower())
            groups.setdefault(value.lower(), [])
        elif field in ("allow", "disallow"):
            starting = False
            for ua in current:
                groups.setdefault(ua, []).append((field == "allow", value))
    me = agent.lower()
    chosen = next((groups[k] for k in groups if k != "*" and k in me), groups.get("*", []))
    # 空の Disallow は「すべて許可」の意味なので規則にしない
    return [(ok, pat, _to_regex(pat)) for ok, pat in chosen if pat]


def is_allowed(rules: list[tuple[bool, str, re.Pattern[str]]], path: str) -> bool:
    """最長一致が勝ち、同じ長さなら Allow が勝つ(RFC 9309)。"""
    best: tuple[int, bool] | None = None
    for ok, pat, rx in rules:
        if rx.match(path):
            key = (len(pat), ok)
            if best is None or key > best:
                best = key
    return True if best is None else best[1]


def _default_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


class RobotsGate:
    """ホストごとの robots.txt を覚えて可否を答える。

    get は (url) -> bytes。既定は実際の HTTP 取得で、テストが差し替える。
    """

    def __init__(self, get=_default_get, agent: str = UA):
        self._get = get
        self._agent = agent
        self._rules: dict[str, list | None] = {}
        self.unreachable: set[str] = set()

    def _rules_for(self, host: str, scheme: str):
        if host in self._rules:
            return self._rules[host]
        try:
            body = self._get(f"{scheme}://{host}/robots.txt")
            rules = parse_rules(body.decode("utf-8", "replace"), self._agent)
        except Exception:                                   # noqa: BLE001 — 取れないなら止めない
            self.unreachable.add(host)
            rules = None
        self._rules[host] = rules
        return rules

    def allowed(self, url: str) -> bool:
        parts = urllib.parse.urlparse(url)
        if not parts.netloc:
            return True
        rules = self._rules_for(parts.netloc, parts.scheme or "https")
        if rules is None:
            return True
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        return is_allowed(rules, path)

    def check(self, url: str) -> None:
        """禁じられていれば例外にする。呼ぶ側は失敗として記録すればよい。"""
        if not self.allowed(url):
            raise Disallowed(f"robots.txt が禁じている経路: {url}")
