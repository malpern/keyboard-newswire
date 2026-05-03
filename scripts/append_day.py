#!/usr/bin/env python3
"""Append (or merge) a day's items into data/corpus.json, dedupe by id,
re-run generate.py, then commit and push.

Usage:
  append_day.py <YYYY-MM-DD> <items.json>

Where items.json is an array of item objects (output of parse_digest.py).

Idempotent: re-running for the same date merges new items in, dedupes by id,
and a no-op (empty diff) results in no commit/push.
"""
import datetime
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus.json"
DAYS_DIR = ROOT / "data" / "days"


def load_corpus():
    return json.loads(CORPUS.read_text())


def save_corpus(corpus):
    CORPUS.write_text(json.dumps(corpus, indent=2, ensure_ascii=False) + "\n")


def merge(corpus: dict, date: str, new_items: list[dict]) -> tuple[int, int]:
    """Merge new_items into corpus[date]. Returns (added, total_after)."""
    days = corpus.setdefault("days", [])
    day = next((d for d in days if d["date"] == date), None)
    if day is None:
        day = {"date": date, "items": []}
        days.append(day)
    existing_ids = {it.get("id") for it in day["items"] if it.get("id")}
    added = 0
    for it in new_items:
        if it.get("id") and it["id"] in existing_ids:
            continue
        day["items"].append(it)
        if it.get("id"):
            existing_ids.add(it["id"])
        added += 1
    days.sort(key=lambda d: d["date"], reverse=True)
    return added, len(day["items"])


def write_day_file(date: str, items: list[dict]):
    DAYS_DIR.mkdir(parents=True, exist_ok=True)
    p = DAYS_DIR / f"{date}.json"
    if p.exists():
        try:
            existing = json.loads(p.read_text())
            existing_items = existing.get("items", [])
            seen = {it.get("id") for it in existing_items if it.get("id")}
            for it in items:
                if it.get("id") and it["id"] not in seen:
                    existing_items.append(it)
                    seen.add(it["id"])
            existing["items"] = existing_items
            p.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n")
            return
        except Exception:
            pass
    p.write_text(
        json.dumps({"date": date, "items": items}, indent=2, ensure_ascii=False) + "\n"
    )


def run(*cmd, cwd=ROOT, check=True):
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def git_push_if_dirty(date: str, added: int):
    # Stage relevant paths
    run("git", "add", "data", "docs")
    diff = run("git", "diff", "--cached", "--quiet", check=False)
    if diff.returncode == 0:
        print("no changes to commit")
        return
    msg = f"keyboard-wire: {date} (+{added} items)"
    env_user = ["-c", "user.email=clawd@malpern.com", "-c", "user.name=Clawd (auto)"]
    run("git", *env_user, "commit", "-m", msg)
    # Rebase on top of any concurrent commits before pushing (handles two crons
    # appending on the same day within minutes of each other)
    fetch = run("git", "fetch", "origin", "main", check=False)
    if fetch.returncode == 0:
        rebase = run("git", *env_user, "rebase", "origin/main", check=False)
        if rebase.returncode != 0:
            run("git", "rebase", "--abort", check=False)
            print(f"rebase failed; commit kept locally:\n{rebase.stderr}", file=sys.stderr)
    push = run("git", "push", "origin", "main", check=False)
    if push.returncode != 0:
        print(f"push failed:\n{push.stderr}", file=sys.stderr)
        sys.exit(2)
    print(f"pushed: {msg}")


def main():
    if len(sys.argv) != 3:
        print("usage: append_day.py <YYYY-MM-DD> <items.json>", file=sys.stderr)
        sys.exit(1)
    date = sys.argv[1]
    datetime.date.fromisoformat(date)  # validate
    items_path = pathlib.Path(sys.argv[2])
    new_items = json.loads(items_path.read_text())
    if not isinstance(new_items, list):
        print("items.json must be an array", file=sys.stderr)
        sys.exit(1)

    if not new_items:
        print(f"{date}: no items, skipping")
        return

    corpus = load_corpus()
    added, total = merge(corpus, date, new_items)
    save_corpus(corpus)
    write_day_file(date, new_items)
    print(f"{date}: +{added} new items (day total: {total})")

    # Regenerate
    run(sys.executable, str(ROOT / "scripts" / "generate.py"))

    # Commit + push
    git_push_if_dirty(date, added)


if __name__ == "__main__":
    main()
