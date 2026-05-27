"""Cross-source dedup audit.

Scans data/corpus.json (+ optional data/backfill.json) for items that look
like the same upstream project showing up under multiple sources. Prints
candidate clusters sorted by Jaccard token overlap of normalized titles.

This is a *diagnostic*, not part of the daily pipeline. Run it
periodically (especially after Geekhack + Shopify ingestors land) to
decide whether title-based fuzzy clustering is worth building. Existing
URL-based merging lives in scripts/cluster.py and handles the easy case
(identical canonical URL); this audit finds the harder cross-source case
where each source has a different URL pointing at writeups of the same
project.

Usage:
    python3 scripts/dedup_audit.py                    # corpus only, default threshold
    python3 scripts/dedup_audit.py --include-backfill # add backfill.json
    python3 scripts/dedup_audit.py --threshold 0.2    # widen the net
    python3 scripts/dedup_audit.py --json             # machine-readable output
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "with",
    "is", "at", "by", "from", "this", "that", "my", "your", "our",
    "i", "we", "you", "it", "its", "as", "be", "are", "was", "were",
    "will", "can", "just", "about", "what", "how", "why", "out", "up",
    "down", "one", "two", "any", "some", "all", "more", "most", "no",
    "not", "if", "but", "so", "than", "then", "when", "where", "which",
    "who", "via", "using", "use", "used", "new", "have", "has",
    # domain-generic words that hurt signal more than they help
    "keyboard", "keyboards", "mechanical", "build", "review",
}


def tokens(title: str) -> set[str]:
    title = (title or "").lower()
    title = re.sub(r"[^a-z0-9 ]", " ", title)
    return {w for w in title.split() if len(w) > 2 and w not in STOPWORDS}


def load_items(include_backfill: bool) -> list[dict]:
    paths = [ROOT / "data" / "corpus.json"]
    if include_backfill:
        bf = ROOT / "data" / "backfill.json"
        if bf.exists():
            paths.append(bf)
    items: list[dict] = []
    seen_ids: set[str] = set()
    for p in paths:
        doc = json.loads(p.read_text())
        for day in doc.get("days", []):
            for it in day.get("items", []):
                iid = it.get("id")
                if iid and iid in seen_ids:
                    continue
                if iid:
                    seen_ids.add(iid)
                items.append({**it, "_day": day.get("date")})
    return items


def find_pairs(items: list[dict], threshold: float) -> list[tuple[float, dict, dict]]:
    pairs: list[tuple[float, dict, dict]] = []
    for a, b in combinations(items, 2):
        if a.get("source") == b.get("source"):
            continue
        ta, tb = tokens(a.get("title")), tokens(b.get("title"))
        if not ta or not tb:
            continue
        j = len(ta & tb) / len(ta | tb)
        if j >= threshold:
            pairs.append((j, a, b))
    pairs.sort(key=lambda x: -x[0])
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-backfill", action="store_true")
    ap.add_argument("--threshold", type=float, default=0.25)
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()

    items = load_items(args.include_backfill)
    pairs = find_pairs(items, args.threshold)

    if args.as_json:
        out = [
            {
                "jaccard": round(j, 3),
                "a": {k: a.get(k) for k in ("id", "source", "title", "url", "_day")},
                "b": {k: b.get(k) for k in ("id", "source", "title", "url", "_day")},
            }
            for j, a, b in pairs[: args.limit]
        ]
        print(json.dumps({"item_count": len(items), "pairs": out}, indent=2))
        return

    src_counts = Counter(i.get("source") for i in items)
    print(f"items: {len(items)}  sources: {dict(src_counts)}")
    print(f"threshold: {args.threshold}  cross-source pairs: {len(pairs)}")
    for j, a, b in pairs[: args.limit]:
        print()
        print(f"  J={j:.2f}  {a['_day']} vs {b['_day']}")
        print(f"    [{a.get('source'):7}] {(a.get('title') or '')[:90]}")
        print(f"    [{b.get('source'):7}] {(b.get('title') or '')[:90]}")
        print(f"    {(a.get('url') or '')[:80]}")
        print(f"    {(b.get('url') or '')[:80]}")


if __name__ == "__main__":
    main()
