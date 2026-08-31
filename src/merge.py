# -*- coding: utf-8 -*-
"""セクション項目の差し替えマージ(F-07 / T-07 / T-08)。

規則:
- 収集に成功したソース種別(s)の既存項目は捨て、収集項目で置き換える
- それ以外の種別(未収集・失敗種別)は既存のまま維持する(劣化継続)
- URL で重複排除し、日付降順(YYYY-MM は月初扱い、「不明」と空は末尾)で最大 3 件
"""

from __future__ import annotations

MAX_ITEMS = 3
UNKNOWN = "不明"


def _key(d: str) -> str:
    return d + "-01" if len(d) == 7 else d


def sort_items(items: list[dict]) -> list[dict]:
    """日付降順。日付が無い項目(不明・空)は元の順序を保ったまま末尾へ回す。"""
    known = [i for i in items if i["d"] not in ("", UNKNOWN)]
    unknown = [i for i in items if i["d"] in ("", UNKNOWN)]
    known.sort(key=lambda i: _key(i["d"]), reverse=True)
    return known + unknown


def merge_section(existing: list[dict], fetched: list[dict],
                  fetched_ok_types: set[str]) -> list[dict]:
    """existing: 現在の項目。fetched: 今回収集した項目(d/t/u/s)。
    fetched_ok_types: 今回取得に成功したソース種別の集合。"""
    kept = [i for i in existing if i["s"] not in fetched_ok_types]
    seen: set[str] = set()
    merged: list[dict] = []
    for i in sort_items(list(fetched) + kept):
        if i["u"] in seen:
            continue
        seen.add(i["u"])
        merged.append(dict(i))
    return merged[:MAX_ITEMS]
