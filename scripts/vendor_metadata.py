"""Vendor metadata refresher.

For every URL stored in `item.gb.vendor_links`, fetch the vendor's
Shopify product.json endpoint (`<url>.json`) and extract the canonical
price + currency. Mutates the vendor_link dict in place; the render
layer then displays a "$135" chip beside each vendor pill.

What we *can* extract reliably across Shopify stores:
  - price (variants[*].price as decimal string)
  - currency (variants[*].price_currency, ISO-4217)

What we *can't* extract from products.json (returns None):
  - availability / in-stock / sold-out
  - inventory_quantity
That signal lives on the HTML product page and would require scraping;
v1 ships price-only and we can layer availability later if useful.

Politeness: HostThrottle from http_polite spaces same-host requests.
Per-link freshness window: if a link was refreshed within --max-age
hours, skip the refetch (so re-runs during a day don't hammer
vendors).
"""
import argparse
import datetime
import json
import pathlib
import re
import sys
import urllib.request
import urllib.parse

import http_polite

ROOT = pathlib.Path(__file__).resolve().parent.parent
USER_AGENT = "keyboard-wire/1.0 (+https://keyboard-newswire.com)"

# Per-host throttle for vendor fetches — same instance type used in
# fetch_images.py, distinct instance because different code paths.
_THROTTLE = http_polite.HostThrottle(min_interval=1.0)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def product_json_url(product_page_url: str) -> str | None:
    """Convert a vendor's product page URL to its Shopify .json endpoint.

    `https://novelkeys.com/products/foo`   → `https://novelkeys.com/products/foo.json`
    `https://novelkeys.com/products/foo/`  → `https://novelkeys.com/products/foo.json`
    Strips any trailing query string or fragment.
    Returns None if the URL doesn't have the expected `/products/<handle>`
    shape (most non-Shopify hosts don't).
    """
    if not product_page_url:
        return None
    parsed = urllib.parse.urlparse(product_page_url)
    if not parsed.scheme or not parsed.netloc:
        return None
    path = parsed.path.rstrip("/")
    # Common shape: /products/<handle>. Some stores have additional
    # path segments (collections/<col>/products/<handle>) — still
    # supported.
    m = re.search(r"(/products/[^/]+)$", path)
    if not m:
        return None
    new_path = path[: m.start()] + m.group(1) + ".json"
    return urllib.parse.urlunparse((
        parsed.scheme, parsed.netloc, new_path, "", "", "",
    ))


def parse_product_metadata(payload: dict) -> dict | None:
    """Extract price/currency from a Shopify product.json payload.

    Returns `{price_low, price_high, currency}` in cents + ISO code,
    or None if no usable variant prices found.
    """
    if not isinstance(payload, dict):
        return None
    product = payload.get("product") or {}
    variants = product.get("variants") or []
    prices: list[int] = []
    currency: str | None = None
    for v in variants:
        raw_price = v.get("price")
        if raw_price is None:
            continue
        try:
            # Shopify gives prices as decimal strings: "135.00".
            dollars, _, cents = str(raw_price).partition(".")
            cents = (cents + "00")[:2]  # pad/truncate to 2 digits
            total_cents = int(dollars) * 100 + int(cents)
        except (ValueError, TypeError):
            continue
        if total_cents <= 0:
            continue
        prices.append(total_cents)
        if currency is None:
            currency = v.get("price_currency") or None
    if not prices:
        return None
    out: dict = {"price_low": min(prices)}
    if max(prices) > min(prices):
        out["price_high"] = max(prices)
    if currency:
        out["currency"] = currency
    return out


def fetch_product_metadata(product_page_url: str, *,
                           throttle: http_polite.HostThrottle | None = None,
                           timeout: float = 12) -> dict | None:
    """One-shot fetch + parse. Returns metadata dict or None on any
    failure. Honors the per-host throttle when given."""
    json_url = product_json_url(product_page_url)
    if not json_url:
        return None
    if throttle is not None:
        throttle.wait(json_url)
    req = urllib.request.Request(json_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except Exception:
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    return parse_product_metadata(payload)


def is_stale(link: dict, *, max_age_hours: float) -> bool:
    """True if `link['fetched_at']` is older than max_age_hours, or
    if no fetched_at is recorded yet."""
    ts = link.get("metadata_fetched_at")
    if not ts:
        return True
    try:
        when = datetime.datetime.fromisoformat(ts)
    except Exception:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    age_hours = (datetime.datetime.now(datetime.timezone.utc) - when).total_seconds() / 3600
    return age_hours >= max_age_hours


def refresh_corpus(corpus: dict, *,
                   max_age_hours: float = 6.0,
                   throttle: http_polite.HostThrottle | None = None,
                   dry_run: bool = False) -> tuple[int, int]:
    """Walk corpus.days[*].items[*].gb.vendor_links and refresh each
    link's metadata when stale. Returns (refreshed, total)."""
    throttle = throttle or _THROTTLE
    refreshed = 0
    total = 0
    for day in corpus.get("days", []):
        for it in day.get("items", []):
            gb = it.get("gb") or {}
            links = gb.get("vendor_links") or []
            for link in links:
                total += 1
                if not is_stale(link, max_age_hours=max_age_hours):
                    continue
                if dry_run:
                    continue
                meta = fetch_product_metadata(link.get("url") or "",
                                              throttle=throttle)
                # Always stamp the fetched_at — even on failure — so a
                # broken URL doesn't get retried every cron run.
                link["metadata_fetched_at"] = _now_iso()
                if meta:
                    # Merge into the link dict; remove stale fields
                    # if they were set but the new fetch returns nothing.
                    for k in ("price_low", "price_high", "currency"):
                        if k in meta:
                            link[k] = meta[k]
                        elif k in link:
                            del link[k]
                    refreshed += 1
    return refreshed, total


def _load_corpus(path: pathlib.Path) -> dict:
    return json.loads(path.read_text())


def _save_corpus(path: pathlib.Path, corpus: dict) -> None:
    path.write_text(json.dumps(corpus, indent=2, ensure_ascii=False) + "\n")


def _mirror_per_day(corpus: dict, days_dir: pathlib.Path) -> None:
    """Update each data/days/<date>.json so the per-day file mirrors
    the corpus-level updates. Only writes the `gb` block on each item."""
    for day in corpus.get("days", []):
        p = days_dir / f"{day['date']}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        by_id = {it["id"]: it for it in day.get("items", []) if it.get("id")}
        for di in d.get("items", []):
            if di.get("id") in by_id and "gb" in by_id[di["id"]]:
                di["gb"] = by_id[di["id"]]["gb"]
        p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(ROOT / "data" / "corpus.json"))
    ap.add_argument("--days-dir", default=str(ROOT / "data" / "days"))
    ap.add_argument("--max-age", type=float, default=6.0,
                    help="hours; skip links refreshed more recently "
                         "(default: 6.0)")
    ap.add_argument("--throttle", type=float, default=1.0,
                    help="seconds between same-host fetches "
                         "(default: 1.0)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    corpus_path = pathlib.Path(args.corpus)
    days_dir = pathlib.Path(args.days_dir)
    corpus = _load_corpus(corpus_path)
    throttle = http_polite.HostThrottle(min_interval=args.throttle)

    refreshed, total = refresh_corpus(
        corpus,
        max_age_hours=args.max_age,
        throttle=throttle,
        dry_run=args.dry_run,
    )
    sys.stderr.write(
        f"vendor metadata: refreshed {refreshed}/{total} links "
        f"({'dry-run' if args.dry_run else 'live'})\n"
    )
    if not args.dry_run and refreshed:
        _save_corpus(corpus_path, corpus)
        _mirror_per_day(corpus, days_dir)


if __name__ == "__main__":
    main()
