# -*- coding: utf-8 -*-
"""実ブラウザで out/index.html を開いて検品する(HC-041 / HC-078 / HC-080)。

テストで代替できない性質 —— 実際に描かれるか、絞り込みが効くか、横に溢れないか ——
を見る。**検品器自身が壊れていないこと**も見る: 読み込みに失敗した画面を撮って
「異常なし」と言わないよう、まず陽性対照(存在しない要素は見つからない・
壊した絞り込みは落ちる)を通してから本番の主張に入る。

要素名ではなく**振る舞い**で書く(HC-080)。カードの数は要素名ではなく grid の子の総数で数え、
再描画のたびに要素を引き直す。異常は終了コードで知らせる。

  python tools/inspect_page.py             # 検品して結果を出す(異常があれば exit 1)
  python tools/inspect_page.py --shot 出力先.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "out" / "index.html").as_uri()
WIDTHS = [(1600, 1000), (1024, 800), (390, 844)]   # 広い / 中くらい / 携帯

problems: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        problems.append(msg)


def cards(page) -> int:
    """毎回引き直す。掴み置きした要素は再描画で古くなる。"""
    return page.eval_on_selector("#grid", "el => el.querySelectorAll('.card').length")


def main(argv: list[str]) -> int:
    from playwright.sync_api import sync_playwright

    people = json.loads((ROOT / "data" / "people.json").read_text(encoding="utf-8"))
    meta = json.loads((ROOT / "data" / "meta.json").read_text(encoding="utf-8"))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTHS[0][0], "height": WIDTHS[0][1]})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(PAGE, wait_until="load")

        # --- 検品器の陽性対照 ---------------------------------------
        check(page.locator("#this-id-does-not-exist").count() == 0,
              "検品器の対照が壊れている(在るはずのない要素が見つかった)")
        check(cards(page) > 0, "カードが 1 枚も描かれていない(検品器か出力が壊れている)")

        # --- 全体 ---------------------------------------------------
        check(not errors, f"JavaScript エラー: {errors[:3]}")
        check(cards(page) == len(people),
              f"カード数がデータと合わない: 画面 {cards(page)} / データ {len(people)}")

        # --- 分類の絞り込み -----------------------------------------
        for c in meta["cats"]:
            page.click(f'.chip[data-cat="{c}"]')
            got = cards(page)
            check(got == meta["cat_size"][c],
                  f"分類「{c}」: 画面 {got} 名 / 宣言 {meta['cat_size'][c]} 名")
        page.click('.chip[data-cat="ALL"]')
        check(cards(page) == len(people), "「すべて」に戻らない")

        # --- 検索 ---------------------------------------------------
        # 件数では書かない —— 「ボストロム」は本人の他にミュラーの紹介文にも出る。
        # 主張するのは「絞り込まれ、その人が残る」という性質のほう
        page.fill("#q", "ボストロム")
        names = page.eval_on_selector_all("#grid .name", "els => els.map(e => e.textContent)")
        check("ニック・ボストロム" in names, "氏名で検索しても本人が出ない")
        check(0 < len(names) < len(people), f"検索で絞り込まれていない({len(names)} 枚)")
        page.fill("#q", "この語はどこにも無いはずである")
        check(cards(page) == 0, "該当なしのときにカードが残る")
        page.fill("#q", "")
        check(cards(page) == len(people), "検索を消しても戻らない")

        # --- セクション切替 -----------------------------------------
        page.click("#fPub")
        sects = page.eval_on_selector("#grid", "el => el.querySelectorAll('.sect').length")
        check(sects == len(people), f"学術発表のみの表示で見出しが {sects} 個(期待 {len(people)})")
        page.click("#fPub")

        # --- 幅ごとに横の溢れと縦の伸びすぎを見る(HC-078)----------
        for w, h in WIDTHS:
            page.set_viewport_size({"width": w, "height": h})
            page.wait_for_timeout(150)
            over = page.evaluate("() => document.documentElement.scrollWidth - "
                                 "document.documentElement.clientWidth")
            tall = page.evaluate("() => document.body.scrollHeight")
            check(over <= 1, f"幅 {w}px で横に {over}px 溢れている")
            check(tall < 200_000, f"幅 {w}px で縦が {tall}px(表の潰れを疑う)")
            print(f"  幅 {w:5d}px: 横の溢れ {over}px / 縦 {tall}px / カード {cards(page)} 枚")

        if "--shot" in argv:
            dest = argv[argv.index("--shot") + 1]
            page.set_viewport_size({"width": 1600, "height": 1000})
            page.screenshot(path=dest, full_page=False)
            print(f"  画面を {dest} に保存した")
        browser.close()

    if problems:
        print("異常:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("検品 OK(対照・カード数・分類・検索・切替・3 つの幅)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
