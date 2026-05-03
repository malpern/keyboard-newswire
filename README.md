# malpern's keyboard wire

Daily mechanical keyboards, firmware & tools — auto-curated from Hacker News, r/olkb, r/zmk, r/MechanicalKeyboards, r/ErgoMechKeyboards, and Kanata-related searches.

Live: https://malpern.github.io/keyboard-wire/
RSS:  https://malpern.github.io/keyboard-wire/feed.xml

## How it works
- Two crons run nightly at 5:02 / 5:03 PT on a Mac Mini, querying HN's Algolia API and Reddit JSON.
- A local Qwen3.6 model classifies each item (`breaking` vs `evergreen`) and writes a one-line takeaway.
- A generator emits `docs/index.html` + `docs/feed.xml` and pushes to this repo.
- GitHub Pages serves from `/docs` on `main`.

Data lives in `data/corpus.json`. Day files in `data/days/<YYYY-MM-DD>.json`.

## Repo layout
```
data/
  corpus.json           rolling combined corpus (source of truth)
  days/                 individual day files (easier to diff)
docs/                   GitHub Pages root
  index.html            generated
  feed.xml              generated
  style.css
scripts/
  generate.py           reads corpus.json, emits docs/{index.html,feed.xml}
  append-day.py         called by daily cron after digest
  backfill.py           one-shot: parse historical digests
```
