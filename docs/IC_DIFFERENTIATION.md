# IC vs GB visual differentiation — design pass

Status: **proposed, awaiting sign-off.** 2026-05-12.

Context: the current GB card design renders ICs (Interest Checks) and
GBs (Group Buys) with the same layout. After the step-2.3 extractor
audit, this is honest-but-asymmetric: ICs legitimately have **no MOQ,
no price, no end-date, no vendor list, no "live/sold-out" status** —
not because the extractor missed them, but because the designer hasn't
decided yet. An IC card with the GB chip row sitting mostly empty
looks "broken" when it's actually correctly displaying "this is a
proposal, no commerce details exist yet."

## What ICs and GBs actually are

| Dimension | IC (Interest Check) | GB (Group Buy) |
|---|---|---|
| Stage | Proposal — "would you buy this?" | Committed — "buy this now" |
| Deciding | Vendors, MOQ, price still tbd | Locked in |
| Time horizon | Weeks to months before live | Days/weeks live window |
| Reader intent | Browse / weigh-in / signal interest | Decide to buy / track deadline |
| Drop rate | Most ICs never become GBs | Once live, ~always ships |
| Engagement signal | Forum buzz (views, replies) | Forum buzz + commerce |

## Design problem

The GB card visually screams "commerce-ready":
- Image carousel (very prominent)
- Status chip (live/sold-out/ended)
- MOQ / price / end-date chips
- Vendor-region pill row

For an IC, most of that is structurally absent. The card looks like a
GB with the data missing. Two failure modes:

1. **Reader confusion** — "is the GB live? where's the end date?"
   Mistakes pre-launch interest threads for buying opportunities.
2. **Designer-content underweighted** — the *valuable* IC signal is
   the designer's pitch (text body, renders, vendor-interest gauge).
   That gets the same chrome as a $135-MOQ-50 commerce card.

## Proposed differentiation — three levers

### Lever A: explicit "IC" surface treatment

- **Type chip already exists** — `[IC]` styled as a transparent outlined
  pill, vs `[GB]` as a solid accent-color pill. This is already in v2.0.
  Keep.
- **Subtitle line under the type chip:** "Interest check · vote with the
  designer". A single descriptive line that tells a first-time reader
  what this is. Hidden on GB cards.
- **Vendor-region row replacement:** when source is IC, replace the
  "Vendors by region" pills (always empty) with a "Designer is gauging
  interest — no vendors signed yet." line. Honest copy that frames the
  emptiness as expected.

### Lever B: hide chips that don't apply

When source is IC, skip rendering entirely:
- The "live / sold-out / ended" status chip (status doesn't apply to ICs)
- The MOQ / price / end-date chips (none of these exist yet)
- The vendor-region pill row

The chip-row container collapses cleanly if all chips are absent.
Result: an IC card without empty visual real estate.

Counter-argument: some ICs *do* have soft targets — "aiming for MOQ
30", "tentative Q3 2026", "estimated $120". The extractor doesn't
currently catch these, but they exist. Forcing-hide chips would drop
this info if it were ever extracted. Compromise: hide the chip row
on IC only when *no* chip would render. If extraction someday surfaces
`gb.target_moq` or similar, show it. Today: 0 ICs have any chip data,
so the row is hidden in practice.

### Lever C: visual de-emphasis (subtle)

ICs render with slightly muted chrome to signal "speculative":
- Image carousel: same size (the image is the value), but with a thin
  outlined border instead of solid background, signaling "draft."
- Title line: same size, but the IC chip's outlined style makes the
  whole header visually quieter than a GB's solid-accent header.
- No `→ open on Geekhack` accent color on the CTA — same link, but in
  ink-soft color rather than accent-red.

This is gentle. ICs aren't hidden, they're just not screaming for
purchase decisions like GBs are.

## What does NOT change

- Carousel mechanics, image extraction, OP-body takeaway, engagement row
  (views/replies). Those are equally valuable for ICs and GBs.
- The type chip's content (`GB` / `IC`).
- The header nav. Both still live on /groupbuys/.
- Sort order. Daily blocks stay chronological.

## Should ICs and GBs share a page?

Currently both render on `/groupbuys/`. Question worth surfacing:

a. **Keep one page** (status quo). Differentiated visually but
   chronologically interleaved.
b. **Split into two sections within the page** ("Active group buys",
   then "Interest checks"). Clearer scannability.
c. **Separate pages** (`/groupbuys/` and `/interest-checks/`).
   Overkill — they share the carousel/designer/OP-body fabric.

My lean: **(b) — sectioned within one page**. Same URL, clearer order.
GBs at the top (they're time-bound, need attention now), ICs below
(browse leisurely). Each section gets a brief header.

## Phased proposal

- **v2.4** (this design): levers A + B implemented (visible IC subtitle
  line, hidden empty chip row, vendor-row replacement copy). Sectioned
  page split (lever B-page). No visual-emphasis pass yet.
- **v2.5** (next): lever C visual de-emphasis on ICs. Tighten chrome,
  reduce accent color on CTAs.
- **v2.6** (future): if an extractor someday surfaces IC-specific data
  ("aiming for MOQ 30", "Q3 2026 tentative"), wire those into a
  distinct "IC commerce intent" chip set, separate from the GB chip set.

## Open questions

1. **Sectioned page split:** GBs first, ICs second? Or interleave by
   activity (most-replied first regardless of stage)? My lean: GB then
   IC, chronological within each.
2. **Subtitle copy:** "Interest check · vote with the designer" vs
   "Interest check · pre-launch interest poll" vs just "Interest check
   · not yet for sale"? Lean: "Interest check · gauging interest, no
   vendors yet."
3. **Empty-vendors-row copy:** show the "no vendors signed yet" line,
   or just omit entirely? Lean: show it — sets expectations.
4. **CTA wording on IC:** "→ open on Geekhack" (current) vs "→ weigh
   in on Geekhack"? Lean: "→ join the discussion" (matches IC intent;
   "open" feels passive for a vote-with-feet interaction).
