# -*- coding: utf-8 -*-
"""OpenAlex の著者を**二要素で同定**して ID を固定する(F-08)。

氏名検索だけでは決めない。同姓同名は珍しくないうえ、**所属が一致しても別人**という
実例がある —— 「Takehiro Ohya @ Keio University」は慶應の法哲学者ではなく、
映像符号化を研究する工学者だった(実測 2026-08-31)。

そこで採用条件を二つ課す。両方を満たす候補だけを採り、複数残ったら業績数の多い方を採る。

  所属  宣言した機関名の一部が last_known_institutions か affiliations に現れる
  分野  著者のトピックが Social Sciences か Arts and Humanities のドメインを含む

工学者の T. Ohya は分野で落ち、法哲学者の Takehiro Ohya(名古屋大時代の所属)が残る。
どちらの条件も満たす候補が無ければ**その人は対象外にする**(推測で当てない)。

  python tools/resolve_openalex.py                  # 全員を同定して data/scholar_ids.json を書く
  python tools/resolve_openalex.py --only-missing   # 済んだ人は引き継ぎ、残りだけ引き直す
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.openalex.org"
# OpenAlex は連絡先を入れると「行儀のよい」プールへ回してくれる
UA = "hyakugaku-lens/1.0 (mailto:twill3c@gmail.com)"
WANTED_DOMAINS = {"Social Sciences", "Arts and Humanities"}
PAUSE = 0.25


def get(url: str, tries: int = 5):
    """指数待避つきの取得。

    **取れなかったことを「該当なし」と混同してはならない。** 一覧の末尾でレート制限に
    当たった結果、日本の学者 19 名がまとめて『候補なし』に見えた実例がある(loop_003)。
    ここで諦めると、失敗が「そういう結果」として静かに出荷される。
    """
    last: Exception | None = None
    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504):
                raise
            wait = float(e.headers.get("Retry-After") or 0) or 2 ** i
            time.sleep(min(wait, 30))
        except Exception as e:                              # noqa: BLE001 — 接続断も待って再試行
            last = e
            time.sleep(2 ** i)
    raise RuntimeError(f"{tries} 回試して取れなかった: {last}")


def institutions(author: dict) -> list[str]:
    names = [i.get("display_name", "") for i in (author.get("last_known_institutions") or [])]
    names += [a["institution"]["display_name"] for a in (author.get("affiliations") or [])]
    return [n for n in names if n]


def domains(author: dict) -> set[str]:
    return {t["domain"]["display_name"] for t in (author.get("topics") or [])}


def judge(row: dict, author: dict) -> dict:
    """1 人の候補について、二つの条件がそれぞれ立つかを返す。"""
    insts = institutions(author)
    inst_hit = [k for k in row["inst"] if any(k.lower() in i.lower() for i in insts)]
    doms = domains(author)
    return {
        "id": author["id"].rsplit("/", 1)[-1],
        "display_name": author.get("display_name", ""),
        "works_count": author.get("works_count", 0),
        "institutions": insts[:5],
        "domains": sorted(doms),
        "inst_hit": inst_hit,
        "domain_ok": bool(doms & WANTED_DOMAINS),
        "ok": bool(inst_hit) and bool(doms & WANTED_DOMAINS),
    }


# 検索 1 回で判定に要る欄をまとめて取る。OpenAlex は 1 リクエストあたり $0.001 の
# 日次予算制で、候補ごとに引き直すと 1 人あたり 9 リクエストかかる。select を効かせれば
# 1 人 1 リクエストで済む(2026-08-31 に日次予算を使い切って足止めされた)
SELECT = "id,display_name,works_count,last_known_institutions,affiliations,topics"


def has_judgeable_fields(a: dict) -> bool:
    """判定に要る欄が検索結果に入っているか。入っていなければ個別に引き直す。"""
    return "topics" in a and ("last_known_institutions" in a or "affiliations" in a)


def resolve(row: dict) -> dict:
    rec = {"n": row["n"], "q": row["q"], "verified": False, "tried": []}
    try:
        found = get(f"{API}/authors?search={urllib.parse.quote(row['q'])}"
                    f"&per-page=8&select={SELECT}")["results"]
    except Exception as e:                                  # noqa: BLE001
        rec["error"] = f"検索失敗 {type(e).__name__}"
        return rec
    passed = []
    for a in found:
        full = a
        if not has_judgeable_fields(a):
            try:
                full = get(f"{API}/authors/{a['id'].rsplit('/', 1)[-1]}")
                time.sleep(PAUSE)
            except Exception as e:                          # noqa: BLE001
                # 飛ばした候補も記録する。黙って落とすと「検討した末の非該当」に見える
                rec["tried"].append({"id": a["id"].rsplit("/", 1)[-1], "fetch_failed": str(e)[:80]})
                continue
        v = judge(row, full)
        rec["tried"].append({k: v[k] for k in ("id", "display_name", "works_count",
                                               "inst_hit", "domain_ok", "ok")})
        if v["ok"]:
            passed.append(v)
    if passed:
        best = max(passed, key=lambda v: v["works_count"])
        rec.update(verified=True, openalex_id=best["id"], matched=best,
                   ambiguous=len(passed) > 1)
    return rec


def main(argv: list[str] | None = None) -> int:
    argv = argv or []
    rows = [json.loads(l) for l in
            (ROOT / "data" / "scholar_ids.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    prev: dict[str, dict] = {}
    dest = ROOT / "data" / "scholar_ids.json"
    if "--only-missing" in argv and dest.exists():
        # 済んだ人を引き継ぎ、同定できていない人だけを引き直す。
        # レート制限で落ちた分をやり直すための経路(全件やり直すと 40 分かかる)
        prev = {r["n"]: r for r in json.loads(dest.read_text(encoding="utf-8"))["results"]
                if r.get("verified")}
        print(f"  引き継ぎ {len(prev)} 名 / 引き直し {len(rows) - len(prev)} 名")
    out = []
    for row in rows:
        if row["n"] in prev:
            out.append(prev[row["n"]])
            continue
        rec = resolve(row)
        out.append(rec)
        if rec["verified"] and row["n"] not in prev:
            m = rec["matched"]
            flag = " (候補が複数)" if rec["ambiguous"] else ""
            print(f"  ok {row['n']:16s} {rec['openalex_id']:12s} "
                  f"{m['display_name'][:24]:24s} w={m['works_count']:<5d} {m['inst_hit']}{flag}")
        elif rec.get("error") or any("fetch_failed" in t for t in rec["tried"]):
            print(f"  NG {row['n']:16s} 取得できなかった(同定の可否は不明): "
                  f"{rec.get('error', '候補の取得に失敗')}")
        else:
            print(f"  -- {row['n']:16s} 二要素を満たす候補なし ({len(rec['tried'])} 件検討)")
        time.sleep(PAUSE)
    unreachable = sum(1 for r in out if not r["verified"]
                      and (r.get("error") or any("fetch_failed" in t for t in r["tried"])))
    doc = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "declared": len(rows),
           "verified": sum(1 for r in out if r["verified"]),
           "unreachable": unreachable,
           "no_match": len(rows) - sum(1 for r in out if r["verified"]) - unreachable,
           "results": out}
    (ROOT / "data" / "scholar_ids.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"同定 {doc['verified']}/{doc['declared']} 名 "
          f"(非該当 {doc['no_match']} 名 / 取得できず {doc['unreachable']} 名)")
    if doc["unreachable"]:
        print("  取得できなかった人が居る。これは『該当なし』ではない —— 再実行すること")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
