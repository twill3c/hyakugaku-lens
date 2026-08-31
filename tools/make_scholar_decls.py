# -*- coding: utf-8 -*-
"""名簿の所属(日本語)から OpenAlex 同定用の宣言 data/scholar_ids.jsonl を作る。

宣言は {"n": 表示名, "q": 検索語, "inst": [機関の英語名の一部, ...]}。
**対応の付かない所属は黙って飛ばさず、標準出力に列挙して止める** —— 落ちた分を
人が見て辞書に足すか、その人を対象外にするかを決める(HC-012)。

過去の所属も手がかりになる(異動した人は last_known だけでは当たらない)ため、
辞書は複数語を返してよい。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 日本語表記 → OpenAlex の機関名に現れる語。長いものから当てる
INST = {
    "オックスフォード": ["Oxford"],
    "イェール": ["Yale"],
    "ボローニャ": ["Bologna"],
    "ニューヨーク大": ["New York University"],
    "プリンストン": ["Princeton"],
    "エディンバラ": ["Edinburgh"],
    "ウィーン": ["Vienna"],
    "マインツ": ["Mainz"],
    "フロリダ・アトランティック": ["Florida Atlantic"],
    "ゴールウェイ": ["Galway"],
    "オーストラリア国立": ["Australian National"],
    "エアランゲン": ["Erlangen"],
    "アムステルダム": ["Amsterdam"],
    "サイモンフレーザー": ["Simon Fraser"],
    "エラスムス": ["Erasmus"],
    "ボン大": ["Bonn"],
    "ベルリン芸術大": ["Berlin"],
    "ユトレヒト": ["Utrecht"],
    "デューク": ["Duke"],
    "カリフォルニア大サンタクルーズ校": ["Santa Cruz"],
    "カリフォルニア大サンディエゴ校": ["San Diego"],
    "カリフォルニア大バークレー校": ["Berkeley"],
    "カリフォルニア大ロサンゼルス校": ["Los Angeles"],
    "UCLA": ["Los Angeles"],
    "カ・フォスカリ": ["Ca' Foscari", "Venice"],
    "マサチューセッツ工科大": ["Massachusetts Institute of Technology"],
    "MIT": ["Massachusetts Institute of Technology"],
    "スタンフォード": ["Stanford"],
    "コロンビア": ["Columbia"],
    "ジョージメイソン": ["George Mason"],
    "バージニア": ["Virginia"],
    "ケンブリッジ": ["Cambridge"],
    "IMD": ["IMD"],
    "トロント": ["Toronto"],
    "キングス・カレッジ・ロンドン": ["King's College London"],
    "ワシントン大": ["University of Washington"],
    "コーネル": ["Cornell"],
    "ブリュッセル自由大": ["Vrije Universiteit Brussel", "Brussel"],
    "ハーバード": ["Harvard"],
    "ジョージタウン": ["Georgetown"],
    "バーミンガム": ["Birmingham"],
    "トリノ": ["Turin", "Torino"],
    "ロンドン・スクール・オブ・エコノミクス": ["London School of Economics"],
    "ニューヨーク州立大オールバニ校": ["Albany"],
    "マイクロソフト・リサーチ": ["Microsoft"],
    "ランカスター": ["Lancaster"],
    "ETHチューリッヒ": ["ETH Zurich"],
    "南カリフォルニア大": ["Southern California"],
    "ヘブライ大": ["Hebrew University"],
    "ジョンズ・ホプキンス": ["Johns Hopkins"],
    "ミドルベリー": ["Middlebury"],
    "マックス・プランク": ["Max Planck"],
    "ペンシルベニア大": ["Pennsylvania"],
    "ユーラシア・グループ": ["Eurasia"],
    "王室天文官": ["Cambridge"],
    "ゲンロン": ["Genron"],
    "東京大": ["University of Tokyo"],
    "京都大": ["Kyoto University"],
    "慶應義塾大": ["Keio"],
    "名古屋大": ["Nagoya"],
    "九州大": ["Kyushu"],
    "明治学院大": ["Meiji Gakuin"],
    "玉川大": ["Tamagawa"],
    "南山大": ["Nanzan"],
    "立命館大": ["Ritsumeikan"],
    "駒澤大": ["Komazawa"],
}

# 異動歴。last_known だけでは当たらない人に、過去の所属を足す
EXTRA = {
    "大屋雄裕": ["Nagoya"],
    "戸谷洋志": ["Kansai Gaidai", "Osaka"],
    "鈴木貴之": ["Nanzan"],
    "神崎宣次": ["Shiga"],
    "成原慧": ["University of Tokyo"],
    "シャノン・ヴァラー": ["Santa Clara"],
    "ケイト・クロフォード": ["Microsoft", "New York University"],
    "ダナ・ボイド": ["Microsoft", "Data & Society"],
    "ペーター=ポール・フェルベーク": ["Twente"],
    "ユク・ホイ": ["Hong Kong", "Bauhaus"],
    "マッテオ・パスクィネッリ": ["Karlsruhe", "Venice"],
    "フランク・パスクァーレ": ["Maryland", "Brooklyn"],
    "ジュヌヴィエーヴ・ベル": ["Intel", "Australian National"],
    "リチャード・サスキンド": ["Oxford", "Strathclyde"],
    "エイミー・ウェブ": ["New York University"],
    "N・キャサリン・ヘイルズ": ["Duke", "Los Angeles"],
    "大澤真幸": ["Kyoto University", "Chiba"],
    "西垣通": ["University of Tokyo", "Tokyo Keizai"],
    "岡本裕一朗": ["Tamagawa"],
    "稲葉振一郎": ["Meiji Gakuin"],
}


def lookup(aff: str, name: str) -> list[str]:
    hits: list[str] = []
    for ja, en in INST.items():
        if ja in aff:
            hits += en
    hits += EXTRA.get(name, [])
    seen, out = set(), []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def main() -> int:
    people = json.loads((ROOT / "data" / "people.json").read_text(encoding="utf-8"))
    rows, missing = [], []
    for p in people:
        inst = lookup(p["aff"], p["n"])
        if not inst:
            missing.append((p["n"], p["aff"]))
            continue
        rows.append({"n": p["n"], "q": re.sub(r"\s+", " ", p["en"]).strip(), "inst": inst})
    (ROOT / "data" / "scholar_ids.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8", newline="\n")
    print(f"宣言 {len(rows)} 名 / 所属の対応が付かない {len(missing)} 名")
    for n, aff in missing:
        print(f"  未対応: {n}  ({aff})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
