"""
Live per-slot settings, persisted across restarts.

**What this fixes.** Voice, style, the TTS toggle, the caption toggles and the
*In the show* switch were all in memory only, so a crash mid-stream silently put
every slot back to its character's defaults. The streamer's reaction is to assume
they imagined changing it, which is a worse failure than an error message.

**What it deliberately does not restore:** `current_user` and the chatter pools.
Chat re-joins within seconds via keyphrases, pools self-empty after 450s of
silence anyway, and restoring a speaker from before a crash can put a name on
screen for someone who left during it. Settings are what someone chose; a pool is
just who happened to be talking.

**The file is slot-shaped, which is now also how they're held in memory.**

    {"1": {"character": "wizard", "voice": "...", "style": "random",
           "tts": true, "active": true, "show_message": false, ...}}

When this was written those six fields lived in three different places, and the
format was deliberately shaped around the merged form that didn't exist yet. The
merge landed hours later (`slots.py`) and needed no migration, which is the whole
argument for writing the file the way you want it rather than the way the code
currently happens to be.

**Every slot records the character it belonged to.** If a slot's character changed
while the app was down -- someone edited `characters.json`, or assigned a different
one -- its saved overrides are dropped and the new character's defaults win. Layer-2
values are overrides *of a particular character*: restoring The Narrator's voice
onto Henry Potter would be worse than restoring nothing, and much harder to
explain than "your new character came up with its own voice".

**Writes are debounced.** Dragging through the caption toggles is a burst, and each
write is a full atomic rewrite. One write a second after things settle keeps a hard
crash or a power cut cheap without doing file I/O on every click. `flush()` exists
for a clean shutdown.

Same atomic idiom as `usage.py` and `characters.py`: temp file then `os.replace`,
so a crash mid-write can't leave a truncated file. An unreadable file is reported
and ignored rather than being fatal -- the app has working defaults for all of
this, and refusing to start ten minutes before a stream over a settings file would
be indefensible.
"""

import json
import os
import threading

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

# Written and restored per slot. Anything not listed is ignored on read, so a file
# from a newer version can't inject unexpected keys into the managers.
FIELDS = ("character", "voice", "style", "tts", "active",
          "show_character_name", "show_chatter_name", "show_message")

# One reserved key for settings that aren't per-slot. Underscore-prefixed so it can
# never collide with a slot number, which is what every other top-level key is.
# Right now this is just the speech gate, but it's the obvious home for the next
# app-wide switch, and adding it later would have meant a file format change.
APP_KEY = "_app"
APP_FIELDS = ("speech_gate",)

# How long to wait for changes to stop before writing.
DEBOUNCE_SECONDS = 1.0

_lock = threading.Lock()
_timer = None
_pending = None
_write_failed = False


def load():
    """
    Saved state as {slot_number: {field: value}}, or {} if there's nothing usable.

    Never raises. A missing file is the normal first-run case; a corrupt one is
    reported once and treated as missing, because the alternative is refusing to
    start over a file whose entire contents are recoverable by clicking things.
    """
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"state.json could not be read ({exc}); starting from character "
              "defaults. It will be rewritten on the next change.")
        return {}

    if not isinstance(data, dict):
        print("state.json isn't a JSON object; ignoring it.")
        return {}

    out = {}
    for number, saved in data.items():
        if not isinstance(saved, dict):
            continue
        if number == APP_KEY:
            out[APP_KEY] = {k: v for k, v in saved.items() if k in APP_FIELDS}
            continue
        # Slot numbers are strings everywhere else -- socket payloads, PLAYER_CONFIG,
        # characters.json -- so coerce rather than trusting the file to agree.
        out[str(number)] = {k: v for k, v in saved.items() if k in FIELDS}
    return out


def _write(snapshot):
    global _write_failed
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, STATE_FILE)
        _write_failed = False
    except (OSError, TypeError, ValueError) as exc:
        # Reported once rather than every second: a full disk would otherwise fill
        # the console with the same line and bury whatever else is going wrong.
        if not _write_failed:
            print(f"Couldn't write state.json ({exc}); settings won't survive a "
                  "restart until this clears.")
            _write_failed = True


def save_soon(snapshot):
    """
    Remember this snapshot and write it once changes stop.

    Later calls replace the pending snapshot rather than queueing, so a burst of
    toggles costs one write of the final state instead of one write each. The
    caller passes a complete snapshot for exactly this reason -- a queue of deltas
    would have to be replayed in order, and dropping one would leave the file
    describing a state that never existed.
    """
    global _timer, _pending
    with _lock:
        _pending = snapshot
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(DEBOUNCE_SECONDS, _fire)
        _timer.daemon = True     # never hold up shutdown for a settings file
        _timer.start()


def _fire():
    global _timer, _pending
    with _lock:
        snapshot, _pending, _timer = _pending, None, None
    if snapshot is not None:
        _write(snapshot)


def flush():
    """Write any pending snapshot immediately. For a clean shutdown."""
    global _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
            _timer = None
    _fire()


def state_file_exists():
    """For the startup report -- whether settings were restored or defaulted."""
    return os.path.exists(STATE_FILE)
