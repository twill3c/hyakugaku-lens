"""RSS1.0(RDF)/ RSS2.0 / Atom 共通フィードパーサ(koho-lens → hyakunin-lens より移植・T-06)。

xml.etree のみ使用。返り値は文書内出現順の
[{"title": str, "url": str, "date": "YYYY-MM-DD" | "", "author": str}]。

author は共著ブログ(Marginal Revolution・Balkinization など)で本人の記事だけを
選り分けるために使う。取れないフィードでは空文字になる。
フィードとして解釈できない XML/非 XML は ValueError。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .dates import normalize_date

_NS_RSS10 = "http://purl.org/rss/1.0/"
_NS_DC = "http://purl.org/dc/elements/1.1/"
_NS_ATOM = "http://www.w3.org/2005/Atom"


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def channel_link(raw: bytes) -> str:
    """フィード全体の代表 URL(RSS の channel/link、Atom の alternate)。

    ポッドキャストのフィードは**回ごとの link を持たないことがある**(megaphone で実測:
    336 件中 191 件)。そのとき回そのもののページは存在しないので、番組のページへ退避する。
    """
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return ""
    ch = root.find("channel")
    if ch is not None:
        return _text(ch.find("link"))
    if root.tag == f"{{{_NS_ATOM}}}feed":
        for ln in root.findall(f"{{{_NS_ATOM}}}link"):
            if ln.get("rel", "alternate") == "alternate":
                return ln.get("href", "")
    return ""


def parse_feed(raw: bytes) -> list[dict]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise ValueError(f"XML として解釈できない: {e}") from e
    tag = root.tag
    if tag.endswith("RDF"):
        items = root.findall(f"{{{_NS_RSS10}}}item")
        parsed = [
            {
                "title": _text(it.find(f"{{{_NS_RSS10}}}title")),
                "url": _text(it.find(f"{{{_NS_RSS10}}}link")),
                "date": normalize_date(_text(it.find(f"{{{_NS_DC}}}date"))),
                "author": _text(it.find(f"{{{_NS_DC}}}creator")),
            }
            for it in items
        ]
    elif tag == "rss":
        parsed = [
            {
                "title": _text(it.find("title")),
                "url": _text(it.find("link")),
                "date": normalize_date(
                    _text(it.find("pubDate")) or _text(it.find(f"{{{_NS_DC}}}date"))
                ),
                "author": _text(it.find(f"{{{_NS_DC}}}creator")) or _text(it.find("author")),
            }
            for it in root.iter("item")
        ]
    elif tag == f"{{{_NS_ATOM}}}feed":
        parsed = []
        for e in root.findall(f"{{{_NS_ATOM}}}entry"):
            link = ""
            for ln in e.findall(f"{{{_NS_ATOM}}}link"):
                rel = ln.get("rel", "alternate")
                if rel == "alternate":
                    link = ln.get("href", "")
                    break
            au = e.find(f"{{{_NS_ATOM}}}author")
            parsed.append(
                {
                    "author": _text(au.find(f"{{{_NS_ATOM}}}name")) if au is not None else "",
                    "title": _text(e.find(f"{{{_NS_ATOM}}}title")),
                    "url": link,
                    "date": normalize_date(
                        _text(e.find(f"{{{_NS_ATOM}}}published"))
                        or _text(e.find(f"{{{_NS_ATOM}}}updated"))
                    ),
                }
            )
    else:
        raise ValueError(f"未知のフィード形式: root={tag}")
    if not parsed:
        raise ValueError("フィードに item/entry が 1 件もない")
    return parsed
