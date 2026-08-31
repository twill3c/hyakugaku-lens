# -*- coding: utf-8 -*-
"""公式サイト URL を実際に取得し、氏名が載っていることまで確かめる(SPEC §4 / T-12)。

推測で書いた URL を出荷しないための道具。`data/homepage_candidates.jsonl` の候補を
順に当て、**到達(HTTP 200)かつ本文に氏名が現れる**最初の候補を採る。試したものは
成否を問わずすべて `data/link_status.json` に残す —— 落ちた記録が無いログは、
検証器が働いていない状態と区別できない。

  python tools/verify_links.py            # 検証して data/link_status.json を書く
  python tools/verify_links.py --apply    # さらに data/people.json の h を書き換える
"""
from __future__ import annotations

import gzip
import io
import json
import re
import sys
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.robots import RobotsGate  # noqa: E402

# 取得の前に robots.txt を確かめる。ホストごとに 1 回だけ引いて覚える(N-05)
GATE = RobotsGate()
UA = "Mozilla/5.0 (compatible; hyakugaku-lens/1.0; +https://github.com/twill3c/hyakugaku-lens)"
TAG = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
ANY_TAG = re.compile(r"<[^>]+>")


def fetch(url: str, timeout: int = 30, check_robots: bool = True) -> tuple[int, str, str]:
    """robots.txt が禁じている経路は取りに行かない(check_robots=False は robots.txt 自身の取得用)。"""
    if check_robots:
        GATE.check(url)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "ja,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(600_000)
        enc = (r.headers.get("Content-Encoding") or "").lower()
        final, code = r.geturl(), r.status
    if enc == "gzip":
        raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    elif enc == "deflate":
        raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    return code, raw.decode("utf-8", "replace"), final


def visible_text(html: str) -> str:
    return ANY_TAG.sub(" ", TAG.sub(" ", html))


def tokens(person: dict) -> list[str]:
    """このページに載っているべき語。表示名(和名)と原綴の姓。"""
    out = [person["n"]]
    parts = [w for w in re.split(r"[\s・]+", person.get("en", "")) if len(w) > 2]
    if parts:
        out.append(parts[-1])
    return out


def verify(person: dict, url: str) -> dict:
    rec = {"n": person["n"], "url": url, "verified": False,
           "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        code, html, final = fetch(url)
    except urllib.error.HTTPError as e:
        rec["error"] = f"HTTP {e.code}"
        return rec
    except Exception as e:                      # noqa: BLE001 — 取得失敗はすべて未検証
        rec["error"] = f"{type(e).__name__}: {e}"[:160]
        return rec
    rec["status"] = code
    if final.rstrip("/") != url.rstrip("/"):
        rec["final_url"] = final
    text = visible_text(html).lower()
    # 和名は researchmap のように姓名のあいだに空白が入ることがある。空白を潰した版でも照合する
    flat = re.sub(r"\s+", "", text)
    hit = [t for t in tokens(person)
           if t.lower() in text or re.sub(r"\s+", "", t.lower()) in flat]
    rec["matched"] = hit
    rec["verified"] = bool(hit) and code == 200
    if not hit:
        rec["error"] = "ページ本文に氏名が見当たらない"
    return rec


def run(people: list[dict], cands: dict[str, list[str]]) -> tuple[dict[str, str], list[dict]]:
    winners: dict[str, str] = {}
    log: list[dict] = []
    for p in people:
        for url in cands.get(p["n"], []):
            rec = verify(p, url)
            log.append(rec)
            print(f"  {'ok ' if rec['verified'] else 'NG '}{p['n']:16s} {url}  {rec.get('error', '')}")
            if rec["verified"]:
                winners[p["n"]] = url
                break
        else:
            if p["n"] not in winners:
                print(f"  -- {p['n']}: 到達かつ氏名一致の候補なし")
    return winners, log


def main(argv: list[str]) -> int:
    people = json.loads((ROOT / "data" / "people.json").read_text(encoding="utf-8"))
    cands = {}
    for line in (ROOT / "data" / "homepage_candidates.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            cands[d["n"]] = d["cands"]
    missing = [p["n"] for p in people if p["n"] not in cands]
    if missing:
        raise SystemExit(f"候補一覧に無い人物: {missing}")

    winners, log = run(people, cands)
    out = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "attempted": len(log),
           "verified": sum(1 for r in log if r["verified"]),
           "people_with_url": len(winners),
           "results": log}
    (ROOT / "data" / "link_status.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"試行 {out['attempted']} 件 / 到達かつ氏名一致 {out['verified']} 件 / "
          f"URL の付いた人 {out['people_with_url']}/{len(people)} 名")

    if "--apply" in argv:
        for p in people:
            p["h"] = winners.get(p["n"], "")
        (ROOT / "data" / "people.json").write_text(
            json.dumps(people, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        print("data/people.json の h を更新した")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
