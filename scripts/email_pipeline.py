#!/usr/bin/env python3
from __future__ import annotations
"""Pull recent Keyboard-labeled emails and turn them into wire items.

Filters out:
  - Reddit notification emails (noreply@redditmail.com) — already covered by
    the Reddit pipeline
  - Threads with empty/uninteresting subjects
  - Promo emails the model classifies as content-free (SKIP)

For each candidate, calls Qwen via Ollama to extract:
  title       → cleaned-up subject (strip emoji-stuffing, bullets)
  takeaway    → one-sentence summary grounded in subject + first ~3000 chars
                of body
  primary_url → most prominent external link from the body (drops tracking
                /unsubscribe URLs); falls back to Gmail thread URL if none

Outputs JSON array of items in the same shape as parse_digest.py — ready for
tag_items / rewrite_titles / fetch_images / append_day downstream.

Usage:
  email_pipeline.py [--days N] [--max M]
  prints items JSON to stdout, log to stderr
"""
import argparse
import base64
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.parse

KEYRING = os.environ.get("GOG_KEYRING_PASSWORD", "clawd-gog-2026")
ACCOUNT = os.environ.get("KW_GMAIL_ACCOUNT", "malpern@gmail.com")
GOG = os.environ.get("GOG_BIN", "/opt/homebrew/bin/gog")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL = os.environ.get("KW_TAG_MODEL", "qwen3.6:35b-a3b")
LABEL = os.environ.get("KW_GMAIL_LABEL", "Keyboard")

# Senders we always skip (already covered by other pipelines)
SKIP_SENDERS = (
    "noreply@redditmail.com",
    "noreply@reddit.com",
)
SKIP_DOMAINS = ("redditmail.com",)

# URL patterns we drop when picking the "primary" link in a body
LINK_BLOCKLIST = re.compile(
    r"(unsubscribe|mailto:|view\.|view-online|preferences|opt[-_]?out|"
    r"youtube\.com/@|t\.me/|facebook\.com|twitter\.com|x\.com|"
    r"instagram\.com|linkedin\.com)",
    re.IGNORECASE,
)
# Tracking-redirector hosts whose links should be deprioritized but still kept
TRACKING_HOSTS = re.compile(
    r"^(mpzgva\.clicks\.|click\.|track\.|email\.|news\.|t\.[a-z]+/)",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")


def gog_call(*args: str) -> str:
    env = dict(os.environ)
    env["GOG_KEYRING_PASSWORD"] = KEYRING
    try:
        r = subprocess.run([GOG, *args], env=env, capture_output=True, text=True, timeout=45)
        if r.returncode != 0:
            sys.stderr.write(f"gog error: {r.stderr[:300]}\n")
            return ""
        return r.stdout
    except subprocess.TimeoutExpired:
        sys.stderr.write("gog timeout\n")
        return ""


def list_threads(label: str, days: int, max_n: int) -> list[dict]:
    raw = gog_call(
        "gmail", "search", "-a", ACCOUNT, "-j",
        f"label:{label} newer_than:{days}d",
        "--max", str(max_n),
    )
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    return data.get("threads", []) or []


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_ENT_RE = re.compile(r"&(amp|lt|gt|quot|apos|nbsp|#\d+|#x[0-9a-fA-F]+);")
_HTML_ENT_MAP = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": " "}


def _decode_entity(m: re.Match) -> str:
    e = m.group(1)
    if e in _HTML_ENT_MAP:
        return _HTML_ENT_MAP[e]
    if e.startswith("#x"):
        try: return chr(int(e[2:], 16))
        except: return ""
    if e.startswith("#"):
        try: return chr(int(e[1:]))
        except: return ""
    return ""


def html_to_text(s: str) -> str:
    """Crude HTML-to-text. Keeps URLs intact (parser walks raw text after stripping tags)."""
    if not s:
        return ""
    # Drop scripts/styles
    s = re.sub(r"<script[\s\S]*?</script>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"<style[\s\S]*?</style>", "", s, flags=re.IGNORECASE)
    # Pull href attribute values out as visible URLs (so URL_RE catches them later)
    s = re.sub(r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>',
               lambda m: f" {m.group(1)} ", s, flags=re.IGNORECASE)
    s = _HTML_TAG_RE.sub(" ", s)
    s = _HTML_ENT_RE.sub(_decode_entity, s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _walk_parts(payload: dict) -> tuple[str, str]:
    """Return (text/plain body, text/html body) by walking the MIME tree."""
    plain, html_ = "", ""
    parts = [payload]
    while parts:
        p = parts.pop(0)
        mime = (p.get("mimeType") or "").lower()
        body = p.get("body") or {}
        data = body.get("data")
        if data:
            try:
                # Gmail uses URL-safe base64; padding may be missing
                pad = "=" * (-len(data) % 4)
                decoded = base64.urlsafe_b64decode(data + pad).decode("utf-8", errors="replace")
            except Exception:
                decoded = ""
            if mime == "text/plain" and not plain:
                plain = decoded
            elif mime == "text/html" and not html_:
                html_ = decoded
        if "parts" in p:
            parts.extend(p["parts"])
    return plain, html_


def load_thread_body(thread_id: str) -> tuple[str, str, str, str]:
    """Returns (subject, sender, date_str, plain_body)."""
    raw = gog_call("gmail", "thread", "get", "-a", ACCOUNT, "--full", "-j", thread_id)
    if not raw:
        return "", "", "", ""
    try:
        data = json.loads(raw)
    except Exception:
        return "", "", "", ""
    thread = data.get("thread") if isinstance(data, dict) else None
    msgs = (thread or data or {}).get("messages") if isinstance(data, dict) else None
    if not msgs:
        return "", "", "", ""
    m = msgs[0]
    payload = m.get("payload") or {}
    headers = {h.get("name", ""): h.get("value", "") for h in (payload.get("headers") or [])}
    subject = headers.get("Subject", "")
    sender = headers.get("From", "")
    date_str = headers.get("Date", "")
    plain, html_ = _walk_parts(payload)
    if not plain and html_:
        plain = html_to_text(html_)
    if not plain:
        plain = m.get("snippet", "")
    return subject, sender, date_str, plain


def is_skipped_sender(sender: str) -> bool:
    s = sender.lower()
    if any(skip in s for skip in SKIP_SENDERS):
        return True
    if any(d in s for d in SKIP_DOMAINS):
        return True
    return False


def pick_primary_url(body: str) -> str | None:
    """Find the most-likely article URL in an email body."""
    if not body:
        return None
    urls = URL_RE.findall(body)
    if not urls:
        return None
    # Strip trailing punctuation
    cleaned = [u.rstrip(".,;:!?)]\"'") for u in urls]
    # First filter: drop blocklisted (unsubscribe, social)
    primary = [u for u in cleaned if not LINK_BLOCKLIST.search(u)]
    if not primary:
        primary = cleaned
    # Demote tracking-redirector hosts but keep them as fallback
    non_tracking = [u for u in primary if not TRACKING_HOSTS.search(urllib.parse.urlparse(u).netloc)]
    if non_tracking:
        return non_tracking[0]
    return primary[0]


def thread_url(thread_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#all/{thread_id}"


# ── Qwen interaction ─────────────────────────────────────────────


def call_qwen(messages: list[dict], timeout: int = 90) -> str:
    payload = json.dumps({
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.2, "num_predict": 350},
    })
    try:
        r = subprocess.run(
            ["curl", "-sS", "-X", "POST", OLLAMA_URL,
             "-H", "Content-Type: application/json", "-d", payload],
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode != 0:
            return ""
        return json.loads(r.stdout).get("message", {}).get("content", "")
    except Exception as e:
        sys.stderr.write(f"qwen err: {e}\n")
        return ""


def parse_json_obj(raw: str) -> dict:
    if not raw:
        return {}
    raw = re.sub(r"```(?:json)?", "", raw).replace("```", "")
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


SYSTEM = """You are summarizing emails for a personal mechanical-keyboard / firmware / tools news archive.

Each email arrives with a subject, sender, and body. Decide if the email contains keyboard-related news, vendor announcements, blog posts, or product updates worth archiving — OR if it's pure promotional fluff with no specific content (e.g., generic "we miss you", logo redesigns, generic discount banners).

Return a single JSON object on one line:

  - If worth archiving:
    {"keep": true, "title": "<clean factual headline, ≤80 chars, no bullet/emoji>", "takeaway": "<one sentence summary, ≤200 chars>"}

  - If not worth archiving (pure promo):
    {"keep": false, "reason": "<one short clause>"}

Title guidance: prefer the actual news/product if obvious from the body (e.g., "Treasure releases TYPE-9 Series IV"). If the body is opaque, fall back to the original subject cleaned up. Do NOT invent product details not in the body.
Takeaway: factual, no fluff, no marketing adjectives."""


def summarize(subject: str, sender: str, body: str) -> dict:
    body_short = (body or "")[:3000]
    user = f"""SUBJECT: {subject}
SENDER: {sender}

BODY (truncated):
{body_short}"""
    raw = call_qwen([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user},
    ])
    return parse_json_obj(raw)


# ── Main ─────────────────────────────────────────────────────────


def to_item(thread_id: str, subject: str, sender: str, primary_url: str,
            title: str, takeaway: str) -> dict:
    sender_email = ""
    if "<" in sender and ">" in sender:
        sender_email = sender.split("<", 1)[1].split(">", 1)[0]
    elif "@" in sender:
        sender_email = sender.split()[-1].strip()
    domain = sender_email.split("@")[-1].lower() if "@" in sender_email else ""
    # Friendly name from domain: "scottokeebs.com" → "ScottoKeebs"
    pretty = ""
    if domain:
        bare = domain.split(".")[0]
        pretty = bare.replace("_", " ").title()
    return {
        "id": f"email-{thread_id}",
        "title": title or subject,
        "url": primary_url,
        "discussion_url": primary_url,
        "source": "email",
        "subreddit": None,
        "via": pretty or domain or "Inbox",
        "score": None,
        "comments": None,
        "category": "evergreen",
        "takeaway": takeaway,
        "sender": sender,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=1)
    p.add_argument("--max", type=int, default=30)
    p.add_argument("--label", default=LABEL)
    args = p.parse_args()

    threads = list_threads(args.label, args.days, args.max)
    sys.stderr.write(f"found {len(threads)} threads in label={args.label} (last {args.days}d)\n")

    items = []
    seen_subjects = set()
    for t in threads:
        tid = t.get("id")
        sender = t.get("from", "")
        subject = (t.get("subject") or "").strip().strip('"')
        if not tid or not subject:
            continue
        if is_skipped_sender(sender):
            sys.stderr.write(f"  skip (Reddit notif): {subject[:60]}\n")
            continue
        # De-dup near-duplicates by subject prefix
        key = subject[:80].lower()
        if key in seen_subjects:
            sys.stderr.write(f"  skip (dup subject): {subject[:60]}\n")
            continue
        seen_subjects.add(key)

        # Fetch body
        full_subj, full_sender, _, body = load_thread_body(tid)
        if not body:
            body = subject  # bare-bones fallback
        primary_url = pick_primary_url(body) or thread_url(tid)

        # Summarize
        sys.stderr.write(f"  summarizing: {subject[:60]}\n")
        out = summarize(full_subj or subject, full_sender or sender, body)
        if not out.get("keep"):
            reason = out.get("reason", "low signal")
            sys.stderr.write(f"    skip ({reason})\n")
            continue

        items.append(to_item(
            tid, subject, full_sender or sender, primary_url,
            (out.get("title") or "").strip() or subject,
            (out.get("takeaway") or "").strip(),
        ))

    json.dump(items, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.stderr.write(f"\nemitted {len(items)} items\n")


if __name__ == "__main__":
    main()
