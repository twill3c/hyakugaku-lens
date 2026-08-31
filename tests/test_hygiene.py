# -*- coding: utf-8 -*-
"""T-11 — 日本語本文への別字種・制御文字の混入を検出する(N-04)。

**射程を間違えると、正しいデータが落ちる。** 当初はこの検査を `data/*.json` 全体に
掛けていたが、OpenAlex から入った韓国語の論文題名(正当な原文)を混入として落とした
(loop_009 の実測)。外部から来た題名は多言語でありうる —— 引用と使用を分ける(HC-074)。

そこで対象を二つに割る。

  人が書く欄(n / en / aff / field / bio と meta.json)  字種検査を掛ける。
      ここに紛れたキリル文字・ハングルは、字形が近く読んでも気づけない混入である
  収集した項目の題名・URL                              **字種は問わない**。
      ただし制御文字は言語によらず欠陥なので、そこだけ検査する
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "harness" / "text_hygiene.py"
AUTHORED_FIELDS = ("n", "en", "aff", "field", "bio")
SECTIONS = ("own", "pub", "yt")
# タブ・改行・復帰以外の C0/C1 制御文字
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def people():
    return json.loads((ROOT / "data" / "people.json").read_text(encoding="utf-8"))


def run_checker(*paths):
    return subprocess.run([sys.executable, str(TOOL), *map(str, paths)],
                          capture_output=True, text=True, encoding="utf-8")


# --- 検査器そのものの対照 --------------------------------------------

def test_checker_self_test_passes():
    """陽性対照: 検査器自身の対照が通ること(通らない検査器の緑は無意味)。"""
    r = subprocess.run([sys.executable, str(TOOL), "--self-test"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_checker_catches_injected_cyrillic(tmp_path):
    """陽性対照: 混入させた例を実際に捕まえること。"""
    bad = tmp_path / "bad.json"
    bad.write_text('{"bio": "Сontrol еxample"}', encoding="utf-8")
    assert run_checker(bad).returncode == 1, "混入を見逃した"


# --- 人が書く欄 -------------------------------------------------------

def test_authored_fields_are_not_empty():
    """走査対象が空でないこと。空の対象に対する緑は何も言っていない。"""
    rows = people()
    assert rows
    assert all(all(p[k] for k in AUTHORED_FIELDS) for p in rows)


def test_authored_text_is_clean(tmp_path):
    """紹介文・所属・専門と語彙表に、別字種・制御文字が混じっていないこと。"""
    authored = [{k: p[k] for k in AUTHORED_FIELDS} for p in people()]
    target = tmp_path / "authored.json"
    target.write_text(json.dumps(authored, ensure_ascii=False, indent=1), encoding="utf-8")
    r = run_checker(target, ROOT / "data" / "meta.json")
    assert r.returncode == 0, r.stdout + r.stderr


# --- 収集した題名 -----------------------------------------------------

def collected_titles():
    return [(p["n"], i["t"]) for p in people() for s in SECTIONS for i in p[s]]


def test_collected_titles_exist():
    assert collected_titles(), "収集項目が 0 件 — この検査は何も見ていない"


def test_collected_titles_have_no_control_characters():
    """原文の字種は問わない。制御文字だけは言語によらず欠陥として落とす。"""
    bad = [(n, t) for n, t in collected_titles() if CONTROL.search(t)]
    assert not bad, f"制御文字を含む題名: {bad[:3]}"


def test_non_japanese_titles_are_allowed():
    """陰性対照: 日本語以外の原文題名が実在し、それを落とさないこと。

    これが無いと、検査を広げすぎたことに気づけない。実測(2026-09-01)で
    韓国語・トルコ語などの題名が入っている。
    """
    titles = [t for _, t in collected_titles()]
    non_latin_non_jp = [t for t in titles
                        if re.search(r"[가-힣Ѐ-ӿ]", t)]  # text-hygiene:allow
    assert non_latin_non_jp, "多言語の題名が 1 件も無い — 対照が成立していない"
    assert not any(CONTROL.search(t) for t in non_latin_non_jp)
