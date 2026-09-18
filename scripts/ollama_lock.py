"""One shared lock around every local-model call, so callers queue deliberately.

A single Ollama instance on 127.0.0.1:11435 serves email triage, four keyboard-wire news
drivers, three shadow comparisons, the keyboard-wire health check and the Mets watcher.
Nothing coordinated them: each just opened a request and started its own timeout, so a
caller could spend that whole timeout waiting for someone else's turn and be killed before
receiving a single byte. That is exactly how 2026-09-16/17/18 lost a day of archive items
each (`curl (28) ... 0 bytes received` after 90s) and how the evening shadow comparison
failed on batch 1 more than once.

The fix is not a bigger timeout — a queue can outlast any fixed value. Acquire this lock
BEFORE opening the request, and the request's own timeout then measures only its service
time, never the queue. "Timed out waiting" becomes "waited its turn".

Deliberately degrades rather than blocks: if the lock cannot be taken within `wait`, the
call proceeds anyway. The lock is coordination, not correctness, and a stuck holder must
never be able to stop every scheduled job on the machine.

A copy of this module lives in both repos that call the model (clawd/scripts and
keyboard-wire/scripts) because they are separate checkouts; keep them in step.
"""
import contextlib
import fcntl
import os
import pathlib
import time

LOCK_PATH = pathlib.Path(os.environ.get(
    "OLLAMA_LOCK_PATH", os.path.expanduser("~/.local/state/ollama-inference.lock")))
DEFAULT_WAIT = float(os.environ.get("OLLAMA_LOCK_WAIT", "600"))


@contextlib.contextmanager
def inference_lock(wait: float = DEFAULT_WAIT, label: str = ""):
    """Hold the shared model lock for the duration of the block.

    Yields True if the lock was held, False if it timed out and the caller is proceeding
    uncoordinated — callers may record that, but should not treat it as an error.
    """
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        handle = LOCK_PATH.open("a+")
    except OSError:
        yield False          # cannot even open the lock file; never block real work on it
        return
    deadline = time.monotonic() + wait
    held = False
    try:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.5)
        yield held
    finally:
        if held:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()
