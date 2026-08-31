# hyakugaku-lens — 百学レンズ

AI を**作る側**ではなく**論じる側**を見るダッシュボード。哲学・思想・経済学・法学・
社会学・STS・政治学・認知科学の学者 100 名(海外 80 名・日本 20 名)について、
紹介文と発信の最新状況を単一 HTML で一覧する。

姉妹プロジェクト [hyakunin-lens(百人レンズ)](https://hyakunin-lens.vercel.app)が
AI 研究者・実装者 100 名を扱うのに対し、こちらは AI がもたらす未来を研究し発信している
各界の学者を扱う。

## 何が違うか

hyakunin-lens は人手で集めたスナップショットを起点にしたが、**本プロジェクトは
名簿しか人が書かない**。氏名・所属・専門・紹介文だけを人が書き、発信の項目は
公開フィードと公開 API から機械的に集める。集められなかった人は 0 件のまま出す。
網羅性を捨てて再現可能性を取った設計である。

公式サイト URL も同じ方針で、**実際に取得して本人の氏名が載っていることを確かめた
ものだけ**を載せる(2026-08-31 時点で 95/100 名)。確かめられなかった 5 名は空欄で出す。

## 使い方

```bash
python src/build.py                  # data/*.json → out/index.html
python -m src.update                 # 宣言フィードを収集 → own を差し替え → 再ビルド
python tools/discover_feeds.py --apply       # フィードを探索して sources.json を作り直す
python tools/discover_feeds.py --declared-only  # 宣言フィードの分だけ入れ直す
python -m pytest -q                  # スキーマ検証 + 往復一致オラクル + 決定性 + 字種検査
python tools/verify_links.py --apply # 公式サイト候補を実測して h を更新
python tools/seed_people.py          # 名簿 JSONL から people.json を再生成(立ち上げ用)
```

## 定期更新のしかけ

GitHub Actions が二つの層を回し、差分があるときだけ `data/` + `out/` をコミットする
(Vercel の Git 連携が自動デプロイする)。

| 層 | 頻度 | 中身 |
|---|---|---|
| `collect.yml` | 6 時間ごと | 宣言フィード 21 本から「本人の発信」を差し替える |
| `scholar.yml` | 毎日 UTC 21:35 | 未同定の著者を引き直し、OpenAlex から「学術発表」を差し替える |

`scholar.yml` が未同定分を毎日引き直すのは、**OpenAlex に日次の無料予算がある**ためである。
初回の同定で予算を使い切り、19 名(日本の学者)が未取得のまま残っている。
予算は UTC 深夜に戻るので、翌日以降の実行で順に埋まる。

## 構成

| 場所 | 役割 |
|---|---|
| `data/people.json` | 100 名の名簿と発信項目(唯一の正本) |
| `data/meta.json` | 分類語彙・ソース種別語彙・各層の最終実行時刻 |
| `data/homepage_candidates.jsonl` | 公式サイトの候補 URL(順に試す) |
| `data/sources.json` | 採用したフィードと、本人のものだと言える証拠 |
| `data/feed_extra.jsonl` | 自動発見できないが在ることを知っている候補(同じ関門を通す) |
| `data/feed_declared.jsonl` | 自動判定に落ちるが中身を実測して採ると決めたもの(理由必須) |
| `data/feed_discovery.json` | 590 本の探索記録(落ちた理由も残す) |
| `data/link_status.json` | 候補 URL の検証結果(落ちた記録も残す) |
| `src/build.py` + `src/template.html` | 自己完結の単一 HTML を生成 |
| `src/merge.py` | セクション項目の差し替えマージ(劣化継続) |
| `out/index.html` | 出荷物。Vercel がそのまま静的配信する |

詳細は [SPEC.md](SPEC.md) と [TEST_SPEC.md](TEST_SPEC.md) を参照。
