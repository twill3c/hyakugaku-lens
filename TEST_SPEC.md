# TEST_SPEC.md — hyakugaku-lens

<!-- scaffold template v1.24.0 から展開(2026-08-31)。以後このファイルはプロジェクトが育てる -->

## テスト一覧

| ID | 内容 | 対応要求 | ファイル |
|---|---|---|---|
| T-01 | データスキーマ検証: 必須キー、分類/ソース語彙、日付形式、URL 形式、各セクション最大 3 件、氏名(n)と原綴(en)の重複なし | F-01 | tests/test_data.py |
| T-02 | 名簿の構成: 100 名、日本の学者 20 名、分類 12 区分がすべて出現し `meta.cats` と集合一致、分類ごとの人数が `meta.cat_size` と一致 | F-01 | tests/test_data.py |
| T-03 | 往復一致オラクル: `out/index.html` から P / CAT_LABEL / SRC / CATS を再抽出し `data/*.json` と完全一致 | F-02 | tests/test_build.py |
| T-04 | 出力健全性: プレースホルダ残存なし、件数行(データから算出)・分類チップ 12 個の埋め込み、esc 関数と各 UI 部品の存在、外部リソース参照が無いこと | F-02, F-03, N-02 | tests/test_build.py |
| T-05 | 決定性: 2 回ビルドしてバイト一致 | N-01 | tests/test_build.py |
| T-06 | 件数行の算出: `counts_line` が人数・各セクション件数・合計をデータから導く(定数ではない)。項目を足すと行が変わることを対照で示す | F-04 | tests/test_build.py |
| T-07 | 期間絞り込みの下地: 日付「不明」を含むレコードが `sort_items` で末尾に来る。`YYYY-MM` は月初として比較される | F-05, F-07 | tests/test_merge.py |
| T-08 | マージ規則: 成功種別のみ差し替え・失敗時は既存維持(劣化継続)・日付降順(不明末尾)・URL 重複排除・最大 3 件・入力非破壊 | F-07 | tests/test_merge.py |
| T-09 | フッタ構成(フリート共通規約・画面最下部固定)と最終更新行の埋め込み | F-10 | tests/test_build.py |
| T-10 | HTML エスケープ: 引用符・山括弧を含む文字列が生の形で出力に現れない(陽性対照つき) | N-02 | tests/test_build.py |
| T-11 | 字種検査: `data/*.json` の日本語本文にキリル文字・ハングル・制御文字が混入していない。検査器の陽性対照つき | N-04 | tests/test_hygiene.py |
| T-12 | 公式サイト URL の検証記録: `h` が非空なら `data/link_status.json` に検証済みとして記録されている(未検証の URL を出荷しない) | F-01 | tests/test_data.py |

## 実行

```bash
python -m pytest -q
```
