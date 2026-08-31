"""日付文字列の正規化(koho-lens → hyakunin-lens より移植・T-06)。

対応方言: RFC822(pubDate)/ ISO8601(±TZ, Z)/ 和文 YYYY年M月D日 /
YYYY.M.D / YYYY/M/D / YYYY-MM-DD。パース不能は空文字を返し、例外にしない。
返す日付はソース表記の暦日(タイムゾーン変換はしない — 発表日として扱う)。
"""

from __future__ import annotations

import re
from email.utils import parsedate_to_datetime

_NUMERIC = re.compile(r"(\d{4})[./\-年](\d{1,2})[./\-月](\d{1,2})")
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})T")


def normalize_date(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    s = raw.strip()
    if not s:
        return ""
    m = _ISO.match(s) or _NUMERIC.search(s)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
        return ""
    try:
        dt = parsedate_to_datetime(s)
        return dt.strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""
