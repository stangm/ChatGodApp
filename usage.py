"""
How many characters have gone to Azure this month.

**Why count at all.** The free F0 tier allows 500,000 characters a month. Crossing
it doesn't produce a helpful error -- synthesis simply starts failing, the app falls
back to gTTS, and on stream that reads as "the voices went weird" or "TTS randomly
stopped". It's the failure mode with the worst diagnosis story in the whole app, and
the only warning available is one you count yourself.

**Why locally.** The Speech SDK doesn't expose remaining quota; usage lives in the
Azure portal. So the number here is this app's own tally, not an authoritative
reading. It undercounts if you use the same Azure resource from somewhere else, and
it counts characters submitted rather than characters billed. Good enough to warn
before a ceiling; not good enough to argue with a bill.

**Why persisted.** A session-only count never approaches a monthly total, so it could
never warn about anything. `usage.json` is keyed by month and rolls over on its own.

**Failure is always silent and always non-fatal.** This is bookkeeping attached to
the speech path; an unwritable file must never stop someone's stream. Every operation
swallows its errors and the panel reports the count as unknown.
"""

import json
import os
import threading
from datetime import datetime

USAGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage.json")

# Azure's free tier. Only used to render "x of y" and to decide when to warn -- the
# app never blocks synthesis on it, because being wrong about the limit and refusing
# to speak would be worse than the ceiling itself.
FREE_TIER_LIMIT = 500_000

# Fraction of the limit at which the panel starts warning. Early enough to do
# something about it before a stream, rather than during one.
WARN_AT = 0.8

_lock = threading.Lock()

# Set once a write has failed. Without it a read-only folder would leave the count
# sitting at zero forever while synthesis carried on -- a counter that silently stops
# counting is worse than no counter, because it reads as reassurance.
_write_failed = False


def _month():
    return datetime.now().strftime("%Y-%m")


def _read():
    """
    The stored counts, or None if the file exists but can't be read.

    The distinction matters. No file at all means a fresh install, where zero is the
    truthful answer. A file that won't parse means the count is unknown, and showing
    a confident zero there would hide the very thing worth reporting.
    """
    if not os.path.exists(USAGE_FILE):
        return {}
    try:
        with open(USAGE_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def record(text):
    """
    Add this message's characters to the running total. Returns the new total, or
    None if it couldn't be recorded.

    Called from the synthesis path, so it holds a lock: the speech worker is a
    separate thread from the socket handlers that read the total.
    """
    global _write_failed
    if not text:
        return None
    try:
        with _lock:
            # An unreadable file gets replaced rather than abandoned: losing the
            # count is bad, but leaving it permanently stuck is worse, and the file
            # is regenerable bookkeeping rather than anything precious.
            data = _read() or {}
            month = _month()
            # Keyed by month, so rollover is automatic and last month's number stays
            # readable rather than being reset to zero on the 1st.
            data[month] = int(data.get(month, 0)) + len(text)
            tmp = USAGE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
            os.replace(tmp, USAGE_FILE)   # atomic, so a crash can't truncate it
            return data[month]
    except (OSError, ValueError, TypeError):
        _write_failed = True
        return None


def this_month():
    """Characters recorded for the current month, or None if unreadable."""
    try:
        with _lock:
            data = _read()
        if data is None:
            return None
        return int(data.get(_month(), 0))
    except (OSError, ValueError, TypeError):
        return None


def summary():
    """
    What the status panel needs: {used, limit, percent, state, detail}.

    state is 'ok', 'warn', 'over' or 'unknown'. 'unknown' is a real answer -- a
    missing or unreadable file means the count isn't trustworthy, and saying so beats
    showing a confident zero.
    """
    used = this_month()
    if used is None or _write_failed:
        detail = ("usage.json can't be written, so the count has stopped"
                  if _write_failed else
                  "usage.json can't be read, so the count is unavailable")
        return {"used": None, "limit": FREE_TIER_LIMIT, "percent": None,
                "state": "unknown",
                "detail": detail + " -- check the Azure portal for real usage"}

    percent = used / FREE_TIER_LIMIT if FREE_TIER_LIMIT else 0
    if used >= FREE_TIER_LIMIT:
        state = "over"
        detail = (f"{used:,} of {FREE_TIER_LIMIT:,} this month -- past the free tier. "
                  "Azure will start refusing, and TTS falls back to the robotic voice.")
    elif percent >= WARN_AT:
        state = "warn"
        detail = (f"{used:,} of {FREE_TIER_LIMIT:,} this month ({percent:.0%}). "
                  "Worth watching before a long stream.")
    else:
        state = "ok"
        detail = f"{used:,} of {FREE_TIER_LIMIT:,} characters this month"

    return {"used": used, "limit": FREE_TIER_LIMIT, "percent": percent,
            "state": state, "detail": detail}
