"""Cluster items by canonical article URL.

When the same article appears via multiple sources (e.g., a vendor email
and a Hacker News thread linking to it), merge them into a single
record carrying a `sources` list of contributing sources.

Primary-source priority within a cluster:
  1. email  (first-party publication wins)
  2. highest score (engagement proxy)
  3. input order
"""
from __future__ import annotations

from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

# Tracking params we strip so they don't fragment clusters.
_TRACKING = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "ref_src", "fbclid", "gclid", "mc_cid", "mc_eid",
    "_hsenc", "_hsmi", "hsctatracking", "igshid", "spm", "share_id",
}


def canonical_url(u: str) -> str:
    if not u:
        return ""
    p = urlparse(u)
    host = (p.hostname or "").lower()
    if p.port and p.port not in (80, 443):
        host = f"{host}:{p.port}"
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    qs = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=False)
          if k.lower() not in _TRACKING]
    qs.sort()
    return urlunparse((
        (p.scheme or "https").lower(),
        host,
        path,
        "",
        urlencode(qs),
        "",
    ))


def source_kind(item: dict) -> str:
    src = (item.get("source") or "").lower()
    if src == "email":
        return "email"
    if src == "reddit":
        return "reddit"
    if src in ("hackernews", "hn", "hacker-news", "hacker news"):
        return "hn"
    return src or "other"


def source_label(item: dict) -> str:
    kind = source_kind(item)
    if kind == "email":
        return item.get("via") or "email"
    if kind == "reddit":
        sr = item.get("subreddit")
        return f"r/{sr}" if sr else "Reddit"
    if kind == "hn":
        return "Hacker News"
    return item.get("via") or kind or "source"


def _primary_key(item: dict):
    # Lower is better. email always beats non-email; ties broken by score desc.
    kind = source_kind(item)
    rank_kind = 0 if kind == "email" else 1
    score = item.get("score") or 0
    return (rank_kind, -score)


def _merge(items: list[dict]) -> dict:
    items_sorted = sorted(items, key=_primary_key)
    primary = items_sorted[0]
    out = dict(primary)

    # Aggregate engagement across the cluster
    scores = [i.get("score") for i in items if i.get("score") is not None]
    comments = [i.get("comments") for i in items if i.get("comments") is not None]
    out["score"] = sum(scores) if scores else None
    out["comments"] = sum(comments) if comments else None

    # Union of topics and tags, first-occurrence order
    def _union(field):
        seen, ordered = set(), []
        for i in items_sorted:
            for v in (i.get(field) or []):
                if v not in seen:
                    seen.add(v)
                    ordered.append(v)
        return ordered

    out["topics"] = _union("topics")
    out["tags"] = _union("tags")

    # Sources row, primary first
    out["sources"] = [
        {
            "id": i["id"],
            "label": source_label(i),
            "kind": source_kind(i),
            "discussion_url": i.get("discussion_url") or i.get("url"),
            "score": i.get("score"),
            "comments": i.get("comments"),
        }
        for i in items_sorted
    ]
    return out


def cluster_items(items: list[dict]) -> list[dict]:
    """Return a new list with same-article items merged into single records.

    Items lacking a usable URL are kept as-is (each becomes its own cluster).
    """
    groups: dict[str, list[dict]] = {}
    keyless: list[dict] = []
    for it in items:
        cu = canonical_url(it.get("url") or "")
        if cu:
            groups.setdefault(cu, []).append(it)
        else:
            keyless.append(it)

    out: list[dict] = []
    # Preserve original ordering by emitting clusters in the order of their
    # first-seen item.
    seen_keys: set[str] = set()
    for it in items:
        cu = canonical_url(it.get("url") or "")
        if not cu:
            out.append(_merge([it]))
            continue
        if cu in seen_keys:
            continue
        seen_keys.add(cu)
        out.append(_merge(groups[cu]))
    return out
