# -*- coding: utf-8 -*-
"""T-11 — data/*.json の日本語本文に別字種・制御文字が混入していないこと(N-04)。

harness/text_hygiene.py は既定で data/ を外す(外部コーパスを入れる場所だから)。
本プロジェクトの data/ は**人が書いた日本語**なので、明示的に当てる。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "harness" / "text_hygiene.py"
TARGETS = sorted(str(p) for p in (ROOT / "data").glob("*.json"))


def test_checker_self_test_passes():
    """陽性対照: 検査器自身の対照が通ること(通らない検査器の緑は無意味)。"""
    r = subprocess.run([sys.executable, str(TOOL), "--self-test"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_targets_not_empty():
    assert TARGETS, "走査対象が空 — 検査が何も見ていない"


def test_data_json_is_clean():
    r = subprocess.run([sys.executable, str(TOOL), *TARGETS],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr


def test_checker_catches_injected_cyrillic(tmp_path):
    """陽性対照: 混入させた例を実際に捕まえること。"""
    bad = tmp_path / "bad.json"
    bad.write_text('{"bio": "Сontrol еxample"}', encoding="utf-8")
    r = subprocess.run([sys.executable, str(TOOL), str(bad)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 1, "混入を見逃した"
