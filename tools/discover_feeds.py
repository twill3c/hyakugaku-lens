# -*- coding: utf-8 -*-
"""公式サイトから RSS・Atom フィードを見つけ、**本人のものだと確かめてから**採る(F-06)。

見つけ方は二つ。
  1. 公式サイトの `<link rel="alternate" type="application/rss+xml">`(自動発見)
  2. 媒体ごとの既知の型(Substack `/feed`、note `/rss`、Blogger `/feeds/posts/default`、
     WordPress `/feed/`)

**採る条件**は、パースできて 1 件以上あることに加えて、次のどれかで本人のものだと言えること:

  item-author 記事の著者名に本人の名前が入っている(`author` 条件として記録し、収集時に絞る)
  own-domain  フィードの host が公式サイトの host と同じ**かつ**、公式サイトがその host の
              根にあるか、フィードの経路が公式サイトの下にある
  feed-title  フィードの表題に本人の名前が入っている

これに加えて、`data/feed_declared.jsonl` に理由付きで置く二種がある。

  declared-*      自動判定に落ちるが、中身を実測して人が採ると決めたもの(note 必須)
  standing-author Project Syndicate・Aeon・Noema のような多著者の論説媒体。確かめるのは
                  「その媒体が項目ごとに著者名を持つこと」で、本人の記事が今あるかとは独立。
                  載っていない日は 0 件になって既存が残る

判定の順は上から。**著者名が 2 つ以上あるフィード(共著)は item-author でしか採らない** ——
表題やホストが一致しても、誰の記事かは項目ごとに違うからである。

どれも言えないフィードは捨てる。捨てる理由は二つの実例から来ている(いずれも loop_002):

  - The Conversation の著者フィードは、HTTP 200 かつ Atom として妥当なまま**別人**を返した。
    **取得できることは本人のものであることを意味しない**
  - ホスト一致だけを証拠にしたところ、MIT 経済学部・コーネル法科大学院・OII・CEPR・note.com の
    **サイト全体のフィード**が本人の発信として 8 件混入した。公式サイトが大きなサイトの
    1 ページであるとき、ホスト一致は何も言っていない

  python tools/discover_feeds.py            # 探索して data/feed_discovery.json を書く
  python tools/discover_feeds.py --apply    # さらに data/sources.json を生成する
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.feedparse import parse_feed          # noqa: E402
from tools.verify_links import fetch, tokens  # noqa: E402

LINK_RE = re.compile(
    r'<link[^>]+(?:type="application/(?:rss|atom)\+xml"[^>]*href="([^"]+)"'
    r'|href="([^"]+)"[^>]*type="application/(?:rss|atom)\+xml")', re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)

# 媒体ごとの型。host の判定 → 付ける接尾辞
PATTERNS = [
    ("substack.com", ["/feed"], "substack"),
    ("note.com", ["/rss"], "note"),
    ("blogspot.com", ["/feeds/posts/default"], "blog"),
    ("wordpress.com", ["/feed/"], "blog"),
]
GENERIC = ["/feed", "/feed/", "/rss", "/rss.xml", "/index.xml", "/atom.xml", "/feed.xml"]


# ホストで決まる種別。新聞の署名コラムを「ブログ」と呼ぶと表示が嘘になる
HOST_KIND = {
    "nytimes.com": "media", "washingtonpost.com": "media", "theguardian.com": "media",
    "ft.com": "media", "project-syndicate.org": "media", "theconversation.com": "media",
    "researchmap.jp": "lab", "megaphone.fm": "podcast", "libsyn.com": "podcast",
}


def kind_of(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc
    for frag, _, kind in PATTERNS:
        if frag in host:
            return kind
    for frag, kind in HOST_KIND.items():
        if host == frag or host.endswith("." + frag):
            return kind
    return "blog"


def candidates(home: str) -> list[str]:
    """公式サイトから候補フィード URL を列挙する(自動発見 + 型)。"""
    out: list[str] = []
    try:
        _, html, final = fetch(home)
    except Exception:                                       # noqa: BLE001
        html, final = "", home
    for m in LINK_RE.finditer(html):
        href = m.group(1) or m.group(2)
        if href:
            out.append(urllib.parse.urljoin(final, href))
    host = urllib.parse.urlparse(final).netloc
    base = f"{urllib.parse.urlparse(final).scheme}://{host}"
    path = urllib.parse.urlparse(final).path.rstrip("/")
    for frag, sufs, _ in PATTERNS:
        if frag in host:
            for s in sufs:
                out.append(base + path + s if path else base + s)
    for s in GENERIC:
        out.append(base + s)
    seen, uniq = set(), []
    for u in out:
        if u not in seen and u.startswith(("http://", "https://")):
            seen.add(u)
            uniq.append(u)
    return uniq[:12]


def feed_title(raw: bytes) -> str:
    m = TITLE_RE.search(raw.decode("utf-8", "replace"))
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""


def judge(person: dict, home: str, url: str, get=None) -> dict:
    """1 本のフィードを取得し、本人のものと言えるかを判定する。

    get は (url) -> フィード本文(bytes)。既定は実際の HTTP 取得で、テストが差し替える。
    """
    rec = {"n": person["n"], "feed": url, "ok": False}
    try:
        raw = get(url) if get else fetch(url)[1].encode("utf-8")
        items = parse_feed(raw)
    except Exception as e:                                  # noqa: BLE001
        rec["error"] = f"{type(e).__name__}: {e}"[:120]
        return rec
    items = [i for i in items if i["title"] and i["url"]]
    if not items:
        rec["error"] = "title/link のある項目が無い"
        return rec
    rec["count"] = len(items)
    toks = [t.lower() for t in tokens(person)]
    fhost = urllib.parse.urlparse(url).netloc
    hhost = urllib.parse.urlparse(home).netloc
    title = feed_title(raw)
    rec["feed_title"] = title[:80]

    # 著者名が 2 つ以上あるフィードは共著。表題やホストが一致しても、
    # 誰の記事かは項目ごとに違う —— 著者一致でしか本人のものだと言えない
    writers = {(i.get("author") or "").strip() for i in items}
    writers.discard("")
    rec["writers"] = sorted(writers)[:6]
    hits = [t for t in toks if any(t in w.lower() for w in writers)]
    if hits:
        matched = sorted({w for w in writers if any(t in w.lower() for t in hits)})
        rec.update(ok=True, evidence="item-author", author=matched)
        return rec
    if len(writers) > 1:
        rec["error"] = f"共著フィード(著者 {len(writers)} 名)だが本人の記事を選り分けられない"
        return rec

    # ホスト一致が本人性の証拠になるのは、公式サイトがそのホストの**根**にあるとき、
    # または経路が公式サイトの下にあるとき。大きなサイトの 1 ページに過ぎない場合、
    # ホスト一致はサイト全体のフィードを本人の発信に化けさせる(loop_002 で 8 件混入)
    hpath = urllib.parse.urlparse(home).path.rstrip("/")
    fpath = urllib.parse.urlparse(url).path
    if fhost and fhost == hhost and (hpath in ("", "/") or fpath.startswith(hpath)):
        rec.update(ok=True, evidence="own-domain")
    elif any(t in title.lower() for t in toks):
        rec.update(ok=True, evidence="feed-title")
    else:
        rec["error"] = "本人のものだと言える手がかりが無い"
    return rec


def extras() -> dict[str, list[str]]:
    """手で足した候補フィード。発見できないが在ることを知っているものを、同じ関門に通す。"""
    path = ROOT / "data" / "feed_extra.jsonl"
    if not path.exists():
        return {}
    out: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            out.setdefault(d["n"], []).extend(d["feeds"])
    return out


def declared() -> list[dict]:
    """自動判定に落ちるが、**中身を実測したうえで**人が採ると決めたフィード。

    自動の関門を緩めるのではなく、緩めた分を一件ずつ理由付きで外に出す。
    note は必須で、そこに何を確かめたかを書く(T-13 が空でないことを固定する)。
    """
    path = ROOT / "data" / "feed_declared.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def check_declared(people: dict[str, dict], get=None) -> list[dict]:
    """宣言フィードが今も取得でき、条件を満たす項目があることを機械で確かめる。

    `standing-author`(Project Syndicate のような多著者の論説媒体)だけは扱いが違う。
    その人の記事が**今この瞬間**フィードに載っているとは限らないからで、
    確かめるのは「この媒体が項目ごとに著者名を持つこと」——
    著者で絞れるという性質そのもの——にする。載っていない日は 0 件で劣化継続になる。
    """
    out = []
    for d in declared():
        p = people[d["n"]]
        try:
            raw = get(d["feed"]) if get else fetch(d["feed"])[1].encode("utf-8")
            items = [i for i in parse_feed(raw) if i["title"] and i["url"]]
        except Exception as e:                              # noqa: BLE001
            print(f"  NG {d['n']:16s} 宣言フィードが取れない: {type(e).__name__}")
            continue
        if d["evidence"] == "standing-author":
            named = [i for i in items if (i.get("author") or "").strip()]
            if not named:
                print(f"  NG {d['n']:16s} 常設の著者条件を置いたが、この媒体は著者名を持たない")
                continue
            mine = [i for i in named if any(a.lower() in (i.get("author") or "").lower()
                                            for a in d["author"])]
            print(f"  ok {d['n']:16s} [{d['s']}] {d['feed']}  "
                  f"(standing-author・著者付き {len(named)} 件 / 本人 {len(mine)} 件)")
            out.append(dict(d, site=p["h"]))
            continue
        if d.get("author"):
            keys = [a.lower() for a in d["author"]]
            items = [i for i in items if any(k in (i.get("author") or "").lower() for k in keys)]
        if not items:
            print(f"  NG {d['n']:16s} 宣言フィードに条件を満たす項目が無い")
            continue
        rec = dict(d)
        rec["site"] = p["h"]
        out.append(rec)
        print(f"  ok {d['n']:16s} [{d['s']}] {d['feed']}  ({d['evidence']}・{len(items)} 件)")
    return out


def write_sources(rows: list[dict]) -> None:
    rows.sort(key=lambda s: s["n"])
    (ROOT / "data" / "sources.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str]) -> int:
    people = json.loads((ROOT / "data" / "people.json").read_text(encoding="utf-8"))
    by_name = {p["n"]: p for p in people}
    if "--declared-only" in argv:
        cur = json.loads((ROOT / "data" / "sources.json").read_text(encoding="utf-8"))
        # 宣言ファイルに載っている (人, フィード) の組を落として入れ直す。
        # evidence の名前で判定すると、種類が増えたときに二重登録になる
        dec = {(d["n"], d["feed"]) for d in declared()}
        auto = [s for s in cur if (s["n"], s["feed"]) not in dec]
        merged = auto + check_declared(by_name)
        merged.sort(key=lambda s: s["n"])
        write_sources(merged)
        print(f"自動 {len(auto)} 本 + 宣言 {len(merged) - len(auto)} 本 = {len(merged)} 本")
        return 0
    extra = extras()
    # --extra-only は data/feed_extra.jsonl の候補だけを試す。公式サイトの自動発見
    # (1 人あたり最大 12 本)を飛ばすので、候補を足したときの試し直しが速い
    only_extra = "--extra-only" in argv
    keep = ({s["n"] for s in json.loads((ROOT / "data" / "sources.json").read_text(encoding="utf-8"))}
            if only_extra else set())
    log, found = [], []
    for p in people:
        if only_extra and (p["n"] in keep or p["n"] not in extra):
            continue
        if not p["h"] and p["n"] not in extra:
            continue
        home = p["h"] or ""
        cand = extra.get(p["n"], []) if only_extra else \
            extra.get(p["n"], []) + (candidates(home) if home else [])
        for url in cand:
            rec = judge(p, home or url, url)
            log.append(rec)
            if rec["ok"]:
                src = {"n": p["n"], "s": kind_of(url), "feed": url, "site": home,
                       "evidence": rec["evidence"]}
                if rec.get("author"):
                    src["author"] = rec["author"]
                found.append(src)
                print(f"  ok {p['n']:16s} [{src['s']}] {url}  ({rec['evidence']})")
                break
        else:
            print(f"  -- {p['n']}: フィードなし")
    out = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "attempted": len(log), "found": len(found), "results": log}
    (ROOT / "data" / "feed_discovery.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"試行 {len(log)} 本 / 採用 {len(found)} 名")
    if "--apply" in argv:
        if only_extra:
            # 既存の採用はそのまま残し、新しく通った分だけを足す
            cur = json.loads((ROOT / "data" / "sources.json").read_text(encoding="utf-8"))
            found = cur + [f for f in found if f["feed"] not in {c["feed"] for c in cur}]
        else:
            found += check_declared(by_name)
        write_sources(found)
        print(f"data/sources.json を書いた({len(found)} 本)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
