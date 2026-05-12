# GB/IC card design

Status: **proposed, awaiting sign-off.** 2026-05-12.

Successor to the "v1 reuses news card" decision in
[GB_IC_FEED.md](./GB_IC_FEED.md). GB/IC items are inherently more
visual than news — readers ask "what does it look like?" before
"what does it say." This doc proposes a new `render_gb_item()` card
with an image carousel as the dominant element.

## Reference

The interaction is the Airbnb listing thumbnail: horizontal swipe on
mobile, hover-revealed prev/next chevrons on desktop, dot indicators
underneath, no page navigation. We can build this with CSS scroll-snap
+ a thin JS layer for the dots and chevrons — no carousel library
needed (~80 lines total).

## Card anatomy

```
┌────────────────────────────────────────────────────────────┐
│  [GB]  GMK Gregory 2                              ◧ save   │
│  Geekhack · Group Buys                                     │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                                                      │  │
│  │              IMAGE CAROUSEL (4:3)                    │  │
│  │              ←  swipe / arrow keys / chevrons  →     │  │
│  │                                                      │  │
│  └──────────────────────────────────────────────────────┘  │
│                       ● ○ ○ ○ ○                            │
│                                                            │
│   live   ·   MOQ 200   ·   $145+   ·   ends Jun 14        │
│                                                            │
│  iNN Studio · GMK ABS · Cherry profile                     │
│                                                            │
│  Short takeaway from the OP body, two lines max, the kind  │
│  of one-glance pitch a designer leads with…                │
│                                                            │
│  ⬆ 4,231 views   💬 78 replies   →  open on Geekhack       │
└────────────────────────────────────────────────────────────┘
```

Top to bottom:

1. **`[GB]` or `[IC]` chip** (styled, color-coded) + **title** (large, readable). Long-press / right-click action remains the existing buylist `♡` (the card stays inside the same `.item` data-attrs contract — buylist keeps working unchanged).
2. **Vendor / source line** below title (`Geekhack · Group Buys`, `Cannonkeys`, `NovelKeys`, etc.). Smaller, faint.
3. **Image carousel** (4:3 aspect, scroll-snap horizontal). One image is the v1 minimum; degrades to a single static image with no dots/chevrons when `len(images) == 1`.
4. **Status row** (live / sold-out / ended) + MOQ + price + end-date when extractable. Each chip independently optional — show what we have, omit what we don't.
5. **Designer / profile line** (`iNN Studio · GMK ABS · Cherry profile`) — extracted from title patterns where possible, omitted otherwise.
6. **Takeaway** — OP body summary (step 1b adds this; today we have noisy reply text).
7. **Engagement + CTA row** — views, replies, "open on Geekhack" link.

## What we have today vs what we'd need

| Field            | Today | Source for it |
|---|---|---|
| Title            | ✅ | RSS title |
| [GB]/[IC] type   | ✅ | Title prefix → `item.type` |
| Vendor / source  | ✅ | `item.via` |
| Images (1)       | ✅ | `fetch_images.py` → 320×320 crop |
| **Images (N)**   | ❌ | **Geekhack OP body scrape (step 1b) / Shopify `images[]` (step 2)** |
| Status           | ❌ | Title text heuristics ("LAST DAY", "Postponed") + Shopify `available` |
| MOQ              | ❌ | OP body parse (best effort) |
| Price            | ❌ | Shopify product.json / OP body parse |
| End date         | ❌ | Title text + OP body parse |
| Designer / profile | ❌ | Title pattern (`[GB] <Designer> <Project>`) |
| OP body takeaway | ❌ | Step 1b thread-page scrape |
| Views / replies  | ❌ | Step 1b thread-page scrape |

**Implication:** the card can ship today, but most rows below the
carousel will be empty in v1. That's fine — the card *layout*
shouldn't be gated on data we don't have yet; the card just renders
the rows that have content. As step 1b and step 2 land, rows
populate progressively. This is the right order: ship the visual
shell with real images first, fill in metadata as ingestors get
smarter.

## Schema additions

Add two new optional fields to GB items (existing news items
unaffected — they don't read these):

- `images: [str]` — list of image paths or remote URLs, in display
  order. v1: pilots emit `images: [item.image]` when only one is
  known. Step 1b/2: pilots emit multi-image arrays.
- `gb` (object): structured GB metadata, populated as we extract it.
  All keys optional.
  ```jsonc
  {
    "type": "GB" | "IC",      // already on item.type, mirrored for grouping
    "status": "live" | "sold-out" | "ended" | "postponed",
    "moq": 200,
    "price_low": 14500,       // cents
    "price_high": 16000,
    "currency": "USD",
    "ends_at": "2026-06-14",
    "starts_at": "2026-05-01",
    "designer": "iNN Studio",
    "profile": "Cherry",
    "material": "ABS",
    "vendor": "Cannonkeys"    // structured, separate from item.via
  }
  ```

Empty fields are simply absent. The renderer treats every chip as
"if present, show; else skip."

## Carousel mechanics

CSS-first, JS-light. Pattern:

- **Container:** `<div class="gb-carousel" role="region" aria-label="…">`
  with `overflow-x: auto; scroll-snap-type: x mandatory;
  scroll-behavior: smooth; scrollbar-width: none;`.
- **Slides:** each `<img>` or `<picture>` wrapped in `<div class="gb-slide" scroll-snap-align: center;>`. First slide `loading="eager"`; rest `loading="lazy"`.
- **Dot indicators:** ordered list of `<button>`s; click scrolls to slide N. JS listens to `scroll` on container, computes current index from `scrollLeft`, updates `aria-current` on the matching dot.
- **Chevrons** (desktop only via `@media (hover: hover)`): `prev` / `next` buttons absolutely positioned, scroll container by container width.
- **Keyboard:** when carousel has focus, `←` / `→` arrows trigger prev/next; `Home` / `End` jump to first/last. Tab order: carousel container, dots, chevrons.
- **Touch:** native horizontal scroll handles swipe — no JS needed.
- **Accessibility:** `role="region"`, `aria-label` describing item, each slide has descriptive `alt`. `aria-current="true"` on active dot. Respect `prefers-reduced-motion` (instant scroll instead of smooth).

**Edge cases:**

- `len(images) == 1` → render single `<img>` with no dots / no
  chevrons / no JS. Just an image.
- `len(images) == 0` → no carousel block at all. Card collapses to
  title + metadata rows. Should be rare once step 1b lands but
  realistic in v1.
- All images failed `fetch_images.py` validation → same as
  `len == 0`.
- Image lazy-load failure → broken-image icon. Don't bother
  retrying.

## Page weight + performance

GB items are bursty (10 thread bootstrap, then ~1-5/day). Realistic
ceiling: ~50 items on `/groupbuys/` at a time, average 3 images each
= 150 images. With lazy loading (slides 2+, items below the fold):

- First contentful paint: title + first image of first ~3 items.
- Eager: ~3 images. Lazy: rest.
- Image budget: 320×240 4:3 crop at ~30KB each → first-paint ~90KB
  images + HTML. Acceptable.

We already crop to 320×320 in `fetch_images.py`; for carousel I'd
shift to 320×240 (4:3) for slides 1+ and keep 320×320 only as the
share-card-style square (used in topic page tile views). Decide:
either crop to two sizes server-side, or use a single larger source
and let CSS aspect-ratio handle the crop.

My lean: store images at 480×360 (4:3) inside `docs/img/`, let CSS
`aspect-ratio: 4/3; object-fit: cover;` do the rest. Single asset,
crisp on retina, ~50KB each.

## Open questions for the user before coding

1. **Image aspect ratio: 4:3 or 16:9 or 1:1?** Most keyboard / keycap
   product photography is shot square or 4:3. Airbnb is closer to
   5:3. My lean: **4:3** (familiar product-photo ratio, fits more
   detail than 16:9).
2. **`gb` object schema** — sign off on the field set above, or
   prefer to start with a smaller subset and grow it? My lean: ship
   the schema empty (only populate as extractors land) but reserve
   the keys now so future data lands without a migration.
3. **Chevrons always visible or hover-revealed?** Airbnb hover-reveals
   on desktop, hides on mobile (touch swipe handles it). My lean:
   **hover-reveal on desktop, hidden on mobile.**
4. **Dots position** — under image (proposed) or overlaid on the
   image bottom-edge (more Airbnb-like, more visual)? Lean: overlay
   with a semi-transparent backdrop for legibility.
5. **Open the thread on click vs. open the carousel image fullscreen
   on click?** Airbnb opens the listing. Step-1 GB cards open the
   Geekhack thread. Lean: click-image opens the source URL (same as
   clicking title). Lightbox fullscreen is a future enhancement.
6. **Should the existing 320×320 crop stay** (for topic page /
   `/topics/group-buys-vendors/` tile view) **and the 480×360 be a
   new second asset**, or replace? Lean: replace — one asset path.
   Topic-page rendering can use the larger image with a smaller CSS
   crop.

## Phased build proposal

- **GB v2.0 (this design):** new `render_gb_item()` + carousel CSS/JS.
  Reads `images[]` (v1 ingestors emit a single-element array — graceful
  degradation). New `gb` object honored where present. Topic page
  `/topics/group-buys-vendors/` opts into the same render. Layout-only
  pass: no new extractors yet, most metadata rows will be empty.
- **GB v2.1:** geekhack pilot starts scraping OP body for multi-image
  arrays + reply/view counts (step 1b in GB_IC_FEED.md). Carousel
  starts having ≥2 slides. Engagement row populates.
- **GB v2.2:** Shopify pilot lands. `images[]` from `products.json`,
  `gb.price_low/high`, `gb.status` from `variants[].available`.
  Carousel + metadata fully populated.
- **GB v2.3:** title-pattern extractor for `gb.designer`, `gb.profile`,
  `gb.material`. End-date / start-date heuristics from titles + OP body.

This sequence ships visible UI improvements at every step instead of
hoarding behind a "wait for all the data" gate.

## What does NOT change

- News card (`render_item`) stays as-is.
- Buylist contract — GB card preserves `.item` `data-*` attrs.
- Quarantine — GB items still excluded from main feed, RSS, Slack,
  X, email.
- `data/corpus.json` shape — only adds optional fields to GB items.
