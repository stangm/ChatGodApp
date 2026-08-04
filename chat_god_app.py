from twitchio.ext import commands
from twitchio import *
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional
from collections import OrderedDict, deque
from flask import Flask, abort, redirect, render_template, request, send_file, url_for
from flask_socketio import SocketIO, emit
import asyncio
import queue
import threading
import time
import wave
import pytz
import random
import os
import uuid

from azure_text_to_speech import (AZURE_VOICES, AZURE_VOICE_STYLES, NO_STYLE,
                                  VOICE_CATALOG, VOICES_SOURCE, styles_for)
import usage
from azure_text_to_speech import AzureTTSManager
import characters
from characters import (BOX_SIZES, CAPTION_FONTS, DISPLAY_FLAGS, MAX_ART_BYTES,
                       Library, size_parts)
from config import legacy_in_use, missing_required, set_command, setting, startup_report
from display_manager import DisplayManager
from players import PLAYER_CONFIG, DEFAULT_VOICE_STYLE
from voices_manager import TTSManager

# The character library, and the slot -> Character view derived from it. CHARACTERS
# is re-derived rather than reloaded whenever an assignment changes, so the overlay
# and the panel can follow along without a restart.
library = Library().load()
CHARACTERS = library.resolved()
CHARACTERS_SOURCE = library.source
display_manager = DisplayManager(CHARACTERS)

# Every setting resolves through config.py: CHATGOD_-prefixed variable, then the
# legacy unprefixed name, then a built-in default. See that module for why.
TWITCH_CHANNEL_NAME = setting('twitch_channel')

app = Flask(__name__)

# Two frames plus form overhead. Flask rejects anything larger before it reaches the
# handler, so an accidental 4K render can't be read into memory just to be refused --
# the per-file check in save_art() is the one that produces a readable message.
app.config["MAX_CONTENT_LENGTH"] = 2 * MAX_ART_BYTES + (1024 * 1024)

socketio = SocketIO(app, async_mode="threading")
print(socketio.async_mode)

# Set once the bot thread has constructed the Bot. Socket events can arrive before
# that happens, so every handler checks it.
twitchbot = None

# Set from event_ready once Twitch accepts the token. Constructing the Bot proves
# nothing -- a bad token fails at connect time, on another thread, well after
# startup has printed everything else and looked fine.
twitch_nick = None

# socket id -> which overlay players that page is showing. The control panel needs
# to know that OBS is actually connected, because a browser source pointed at the
# wrong URL looks identical to one that's working until nobody speaks.
overlay_clients = {}


# ---------------------------------------------------------------------------
# Generated audio, served to the overlay over HTTP
# ---------------------------------------------------------------------------

AUDIO_CACHE_SIZE = 50           # clips kept on disk before the oldest are deleted
_audio_cache = OrderedDict()    # token -> wav path
_audio_lock = threading.Lock()


def register_audio(path):
    """Publish a wav under a one-off token and return it."""
    token = uuid.uuid4().hex
    with _audio_lock:
        _audio_cache[token] = path
        while len(_audio_cache) > AUDIO_CACHE_SIZE:
            _, stale = _audio_cache.popitem(last=False)
            try:
                os.remove(stale)
            except OSError:
                pass
    return token


@app.route("/audio/<token>.wav")
def audio_file(token):
    with _audio_lock:
        path = _audio_cache.get(token)
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="audio/wav")


class SpeechWorker:
    """
    Synthesis on its own thread.

    Azure round-trips take a few hundred milliseconds and used to happen inline in
    the twitchio handler, so the bot stopped reading chat while it waited. One
    worker keeps clips in order without ever blocking the bot.
    """

    def __init__(self, tts_manager):
        self.tts_manager = tts_manager
        self._queue = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, number, speaker, text):
        self._queue.put((number, speaker, text))

    def _run(self):
        while True:
            number, speaker, text = self._queue.get()
            try:
                path = self.tts_manager.synthesize(text, number)
                if path:
                    speech_pacer.submit({
                        'user_number': number,
                        'current_user': speaker,
                        'audio_url': f"/audio/{register_audio(path)}.wav",
                    }, path)
            except Exception as exc:
                print(f"TTS failed for player {number}: {exc}")
            finally:
                self._queue.task_done()


# ---------------------------------------------------------------------------
# Pacing playback: one speaker at a time
# ---------------------------------------------------------------------------

# Off by default, matching how the app has always behaved. Overlap at three players
# reads as liveliness; it's at five or six that it becomes noise, so this is a switch
# rather than a rule.
SPEECH_GATE_DEFAULT = False

# How much of the next clip starts before the previous one finishes. Strict queuing
# (0) sounds like a walkie-talkie -- the dead air between clips is what makes it feel
# robotic -- and a small overlap reads as conversation instead.
#
# Kept small because Azure wavs carry trailing silence of unpredictable length, so a
# large overlap sometimes lands entirely on silence and sometimes clips a final word.
SPEECH_OVERLAP_MS = 350

# How many clips may wait. At roughly four seconds each this is about half a minute
# of backlog, past which a message is being read to a chat that has moved on -- so
# the oldest is dropped rather than queued forever.
#
# **This must stay well under AUDIO_CACHE_SIZE.** register_audio() deletes the oldest
# wav once more than 50 are registered, so a backlog approaching that number would
# have its files removed before they played, and the overlay would 404 and skip them
# with nothing to explain why.
SPEECH_QUEUE_MAX = 8

speech_gate_enabled = SPEECH_GATE_DEFAULT


def _wav_seconds(path):
    """
    Length of a wav, or a conservative guess if it can't be read.

    stdlib `wave` rather than soundfile or mutagen: it's a header read, it has no
    import cost, and the failure mode of guessing slightly wrong is a small timing
    error rather than anything breaking.
    """
    try:
        with wave.open(path, "rb") as handle:
            rate = handle.getframerate()
            return handle.getnframes() / float(rate) if rate else 3.0
    except Exception:
        return 3.0


class SpeechPacer:
    """
    Releases clips to the overlays one at a time when the gate is on.

    **Timed from each clip's own duration rather than from the pages reporting in.**
    The obvious design has the overlay say "finished" and the server release the
    next, which is more accurate -- but a page that closes, crashes or loses its
    socket mid-clip would stall the queue forever and mute the entire show. Being
    a few hundred milliseconds out is a much better failure than silence, so nothing
    here waits on a client.

    **Separate from SpeechWorker on purpose.** Sleeping inside the synthesis loop
    would be fewer lines, but it would also stop synthesis while waiting, so later
    clips would arrive late and the delay would compound. Synthesis runs ahead;
    this decides when each clip goes out.
    """

    def __init__(self):
        self._queue = deque()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, payload, path):
        # Gate off is the old behaviour exactly: straight out, no queue, no delay.
        if not speech_gate_enabled:
            socketio.emit('speak', payload)
            return

        with self._lock:
            self._queue.append((payload, _wav_seconds(path)))
            while len(self._queue) > SPEECH_QUEUE_MAX:
                dropped, _ = self._queue.popleft()
                print(f"Speech queue full; dropped player {dropped['user_number']}'s "
                      "oldest clip rather than reading it minutes late.")
        self._wake.set()

    def flush(self):
        """
        Send everything queued at once. Called when the gate is switched off, so
        turning it off releases the backlog rather than stranding it.
        """
        with self._lock:
            pending, self._queue = list(self._queue), deque()
        for payload, _ in pending:
            socketio.emit('speak', payload)

    def _run(self):
        while True:
            with self._lock:
                item = self._queue.popleft() if self._queue else None
            if item is None:
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                continue

            payload, seconds = item

            # Checked here rather than at submit: a slot can be switched out of the
            # show while its clip is still waiting, and playing it then would put a
            # voice on stream with no character to attach it to.
            player = twitchbot.players.get(payload['user_number']) if twitchbot else None
            if player is not None and not player.active:
                continue

            socketio.emit('speak', payload)
            time.sleep(max(0.0, seconds - SPEECH_OVERLAP_MS / 1000.0))


speech_pacer = SpeechPacer()


def _voice_label(voice_id):
    """
    Label for the dropdown: 'Aria (Female) - 16 styles'.

    The style count is there because expressive voices are rare and unevenly
    spread -- of ~119 English voices, 21 support styles and 18 of those are
    en-US. Without the count you pick an Australian voice for the accent, then
    find out later that every (angry) prefix does nothing. Better to see the
    trade before choosing than after.
    """
    entry = VOICE_CATALOG.get(voice_id)
    if not entry or not entry.get("local_name"):
        name = voice_id.split("-")[-1]
        return name[:-len("Neural")] if name.endswith("Neural") else name

    label = entry["local_name"]
    if entry.get("gender"):
        label = f"{label} ({entry['gender']})"

    count = len(entry.get("styles", []))
    if count:
        label = f"{label} — {count} style{'s' if count != 1 else ''}"
    return label


# Built from the same catalog the TTS code uses, so the dropdowns can't drift out
# of sync with what Azure will actually accept.
VOICE_OPTIONS = [(voice, _voice_label(voice)) for voice in AZURE_VOICES]
# "none" first because it's the baseline -- the voice as Azure ships it, with no
# express-as wrapper at all. "random" then means "pick one each message", which is
# only meaningful on a voice that has styles, so the dropdown drops it for voices
# that don't rather than offering a word for something that can't happen.
STYLE_OPTIONS = [NO_STYLE, "random"] + list(AZURE_VOICE_STYLES)


def _grouped_voices():
    """
    [(locale label, [(id, label), ...]), ...] for <optgroup>s.

    Pulling every English locale means the flat list runs past a hundred
    entries, which is unusable mid-stream. Grouping by country makes it
    scannable. Order follows the catalog, which fetch_voices.py sorts with the
    largest locale first.
    """
    groups, styled, order = {}, {}, []
    for voice in AZURE_VOICES:
        entry = VOICE_CATALOG.get(voice, {})
        label = entry.get("locale_name") or entry.get("locale") or "Other"
        if label not in groups:
            groups[label] = []
            styled[label] = 0
            order.append(label)
        groups[label].append((voice, _voice_label(voice)))
        if entry.get("styles"):
            styled[label] += 1

    # The group heading carries the same information one level up, so a locale
    # with no expressive voices at all -- Australia, Ireland, Canada and most of
    # the rest -- says so without being opened.
    out = []
    for label in order:
        n, s = len(groups[label]), styled[label]
        count = f"{n} voice" if n == 1 else f"{n} voices"
        heading = f"{label} ({count}, {s} with styles)" if s else f"{label} ({count}, none with styles)"
        out.append((heading, groups[label]))
    return out


VOICE_GROUPS = _grouped_voices()

# voice -> the styles it really supports, handed to both operator pages so they can
# narrow the style dropdown as the voice changes. A voice with an empty list supports
# no express-as at all, so its dropdown offers "none" alone -- offering "random"
# there would name something that can't happen.
VOICE_STYLE_MAP = {voice: styles_for(voice) for voice in AZURE_VOICES}


def player_state():
    """
    What the server currently believes about every player.

    The control panel used to render fixed defaults: the TTS checkbox hardcoded
    ticked, voice and style compared against players.py rather than the running
    values, and the assigned name blank until the next chat message arrived. None
    of that is state, so a reload silently desynced the operator from the server --
    untick TTS, reload for any reason, and the box reads ticked while the server
    has it off. Mid-stream that means "fixing" a setting that was already right.

    One function feeds both consumers, the initial Jinja render and the socket push
    on connect, so the two cannot drift apart the way template and server did.

    Before the bot thread has constructed the Bot there is no live state to report,
    so this falls back to the same defaults the app is about to start with -- which
    makes the fallback correct rather than merely safe. That window is a moment at
    startup, and the push on connect corrects any page that loaded inside it.
    """
    manager = twitchbot.tts_manager if twitchbot is not None else None
    state = {}
    for number, config in PLAYER_CONFIG.items():
        player = twitchbot.players.get(number) if twitchbot is not None else None
        voice = manager.voices.get(number) if manager is not None else None
        character = CHARACTERS.get(number)
        flags = display_manager.get(number) or {}
        state[number] = {
            "active": player.active if player else True,
            "tts_enabled": player.tts_enabled if player else True,
            "current_user": (player.current_user if player else None) or "",
            "voice_name": voice["name"] if voice else config["voice_name"],
            "voice_style": voice["style"] if voice else DEFAULT_VOICE_STYLE,
            "character_name": character.display_name if character else "",
            # Whether the character name box can be shown at all. A character with
            # no name would otherwise offer a checkbox that reserves 54px for an
            # empty box -- so the panel disables it and says why.
            "has_character_name": bool(character and character.has_name),
            "size_parts": size_parts(character, flags),
            **flags,
        }
    return state


@app.context_processor
def _cache_busting():
    """
    static_v('css/overlay.css') -> '/static/css/overlay.css?v=<mtime>'

    Browser sources cache stylesheets hard, and OBS keeps that cache across scene
    switches and app restarts. Editing the CSS therefore appears to do nothing --
    and the failure is worse than "no styling", because the page's own classes keep
    toggling against rules the browser doesn't have. Captions stop hiding, new boxes
    render unstyled, and everything points at the code rather than the cache.

    The file's mtime as a query string means the URL changes exactly when the file
    does: cached hard until edited, refetched immediately after.
    """
    def static_v(filename):
        url = url_for('static', filename=filename)
        try:
            stamp = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError:
            return url
        return f"{url}?v={stamp}"
    return {"static_v": static_v}


def art_url(path):
    """
    A static URL for character art, stamped with the file's mtime.

    Cache busting is mandatory here, not a nicety. Browser sources cache images
    hard, so swapping a character by pointing at a new file works, but overwriting
    a PNG in place would change nothing visible -- and the same trap already cost a
    debugging round with stylesheets.
    """
    if not path:
        return None
    url = url_for('static', filename=path)
    try:
        stamp = int(os.path.getmtime(os.path.join(app.static_folder, path)))
    except OSError:
        return url
    return f"{url}?v={stamp}"


def slot_payload(number):
    """Everything the overlay needs to redraw one slot after a change."""
    character = CHARACTERS.get(number)
    live = display_manager.get(number) or {}
    return {
        'user_number': number,
        'art_closed': art_url(character.art_closed) if character else None,
        'art_open': art_url(character.art_open) if character else None,
        'character_name': character.display_name if character else "",
        'show_character_name': bool(live.get('show_character_name')
                                    and character and character.has_name),
        'show_chatter_name': live.get('show_chatter_name'),
        'show_message': live.get('show_message'),
        'size_parts': size_parts(character, live),
    }


def apply_assignment(number):
    """
    Re-derive one slot after the library changed, and tell everyone.

    **Assignment is a deliberate reset point.** The new character brings its own
    voice, style and caption settings, discarding whatever was set live for the
    previous occupant -- which is the whole point: the Wizard should sound like the
    Wizard whoever was in the slot before. Changing *who is talking* is a separate
    axis and deliberately doesn't reset anything.
    """
    global CHARACTERS, CHARACTERS_SOURCE
    CHARACTERS = library.resolved()
    CHARACTERS_SOURCE = library.source

    character = CHARACTERS.get(number)
    if character is None:
        return

    display_manager.reset_to(number, character)
    if twitchbot is not None:
        twitchbot.tts_manager.reset_to(number, character)

    socketio.emit('art_changed', slot_payload(number))
    socketio.emit('state', player_state())


def status_report():
    """
    The four things that can be silently wrong, as green/red rows.

    Each of these fails in a way that only shows up mid-stream, and each looks like
    something else when it does: a logged-out bot looks like quiet chat, a rejected
    Azure key sounds like a voice change, an exhausted quota sounds like TTS
    breaking, and a mistyped browser source URL looks like a blank rectangle. The
    panel exists so all four are answerable before going live rather than during.

    'unknown' is used rather than 'bad' wherever the app genuinely can't tell yet --
    claiming something is broken when it merely hasn't happened yet trains people to
    ignore the panel.
    """
    rows = []

    # -- Twitch ---------------------------------------------------------------
    if twitch_nick:
        rows.append(("Twitch", "ok",
                     f"connected as {twitch_nick}, reading #{TWITCH_CHANNEL_NAME}"))
    elif twitchbot is None:
        rows.append(("Twitch", "unknown", "still starting up"))
    else:
        rows.append(("Twitch", "bad",
                     f"not logged in -- check CHATGOD_TWITCH_TOKEN, and that "
                     f"#{TWITCH_CHANNEL_NAME} is the right channel"))

    # -- Azure ----------------------------------------------------------------
    # The startup chime is a real synthesis, so this is answered by the time anyone
    # opens the panel -- no test call needed.
    if AzureTTSManager.last_result == "ok":
        rows.append(("Azure", "ok", "key and region working"))
    elif AzureTTSManager.last_result == "fallback":
        rows.append(("Azure", "bad",
                     f"{AzureTTSManager.last_error} -- using the robotic backup voice"))
    else:
        rows.append(("Azure", "unknown", "nothing synthesized yet"))

    # -- Quota ----------------------------------------------------------------
    quota = usage.summary()
    rows.append(("Quota", {"ok": "ok", "warn": "warn", "over": "bad"}.get(
        quota["state"], "unknown"), quota["detail"]))

    # -- Voices ---------------------------------------------------------------
    styled = sum(1 for v in VOICE_CATALOG.values() if v.get("styles"))
    if VOICES_SOURCE == "builtin":
        rows.append(("Voices", "warn",
                     f"{len(AZURE_VOICES)} built-in voices, no styles -- "
                     "run fetch_voices.py"))
    else:
        source = "from Azure" if VOICES_SOURCE == "file" else "shipped with the app"
        rows.append(("Voices", "ok",
                     f"{len(AZURE_VOICES)} loaded {source}, {styled} with styles"))

    # -- Slots in the show ----------------------------------------------------
    # Only reported when some are off, since "3 of 3" is noise. Worth reporting at
    # all because a slot switched off looks exactly like a slot that's broken.
    off = [n for n, p in (twitchbot.players.items() if twitchbot else [])
           if not p.active]
    if off:
        rows.append(("Slots", "warn",
                     f"player {', '.join(sorted(off))} switched out of the show -- "
                     "no art, no voice, keyphrase ignored"))

    # -- Overlay --------------------------------------------------------------
    count = len(overlay_clients)
    if count:
        shown = sorted({n for players in overlay_clients.values() for n in players})
        which = f" (player {', '.join(shown)})" if shown else ""
        rows.append(("Overlay", "ok",
                     f"{count} browser source{'s' if count != 1 else ''} connected{which}"))
    else:
        rows.append(("Overlay", "warn",
                     "no browser sources connected -- OBS isn't open, or a source "
                     "URL is wrong"))

    return [{"name": n, "state": s, "detail": d} for n, s, d in rows]


def push_status():
    """Broadcast the status to every panel. Safe to call from the bot thread."""
    socketio.emit('status', status_report())


def diagnostics():
    """
    Everything worth pasting into a message when something is wrong.

    The point is that "click that button and paste it to me" replaces a diagnostic
    conversation. So it carries the things a person can't reliably report about their
    own machine -- versions, which config source won, whether files were found -- and
    the current status rows, which is the answer to the first question anyone asks.

    **No secrets, ever.** Settings appear as set or not set, never by value. This
    text is designed to be pasted into a chat window, and it will be, including by
    people who won't read it first. `config.startup_report()` already redacts, so the
    redaction lives in one place rather than being reimplemented here.
    """
    import platform

    lines = [
        "Chat God diagnostics",
        f"  generated   {datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"  python      {platform.python_version()} on {platform.system()} {platform.release()}",
        "",
        "Status",
    ]
    for row in status_report():
        lines.append(f"  {row['name']:<10} {row['state']:<8} {row['detail']}")

    lines += ["", "Configuration"]
    lines += [f"  {line.strip()}" for line in startup_report()]
    for prefixed, legacy in legacy_in_use():
        lines.append(f"  (using legacy name {legacy} for {prefixed})")

    lines += [
        "",
        "Files",
        f"  voices        {VOICES_SOURCE} ({len(AZURE_VOICES)} voices)",
        f"  characters    {CHARACTERS_SOURCE}",
        f"  players       {', '.join(PLAYER_CONFIG)}",
    ]

    for number, character in CHARACTERS.items():
        label = character.display_name or character.id or "(empty)"
        voice = twitchbot.tts_manager.voices.get(number) if twitchbot else None
        live = f"{voice['name']} / {voice['style']}" if voice else "not started"
        lines.append(f"  player {number}      {label} -- {live}")

    return "\n".join(lines)


@app.route("/diagnostics")
def diagnostics_text():
    """Plain text, so it can be read in a browser as well as copied."""
    return diagnostics(), 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/")
def home():
    return redirect(url_for("control"))


@app.route("/control")
def control():
    """Operator dashboard. Open in a normal browser -- never add this to OBS."""
    return render_template('control.html',
                           players=PLAYER_CONFIG,
                           voices=VOICE_OPTIONS,
                           voice_groups=VOICE_GROUPS,
                           styles=STYLE_OPTIONS,
                           voice_styles=VOICE_STYLE_MAP,
                           voices_source=VOICES_SOURCE,
                           default_style=DEFAULT_VOICE_STYLE,
                           characters_source=CHARACTERS_SOURCE,
                           status=status_report(),
                           speech_gate=speech_gate_enabled,
                           speech_overlap_ms=SPEECH_OVERLAP_MS,
                           state=player_state())


# ---------------------------------------------------------------------------
# Setup: three pages, because they're three different jobs
#
# The first version put slots and every character on one page with each character
# fully expanded. Fine at three characters, unusable at fifteen -- and it failed in a
# particular way: assigning a character is something you do often and quickly, while
# editing one is rare and detailed, so the rare task's bulk sat permanently in front
# of the frequent one and grew every time a character was added.
#
#   /setup                  slots. Bounded by player count, so it fits one screen
#                           forever no matter how large the library gets.
#   /setup/characters       the library, as a grid of art. Characters are pictures;
#                           thumbnails scan faster than a list of ids.
#   /setup/character/<id>   one character, alone, with room for everything.
#
# A page per character rather than an accordion or a modal, because both of those
# need state management that doesn't exist here -- this is a link and a form post,
# which is what the rest of setup already is.
# ---------------------------------------------------------------------------


@app.route("/setup")
def setup():
    """
    Which character is in which slot. Not for stream.

    Deliberately separate from the control panel: the panel is what you touch while
    live and it's already dense, this is what you touch between streams.
    """
    return render_template('setup.html',
                           players=PLAYER_CONFIG,
                           characters=library.characters,
                           slots=library.slots,
                           resolved=CHARACTERS,
                           characters_source=CHARACTERS_SOURCE,
                           live=(twitchbot.tts_manager.voices if twitchbot else {}))


@app.route("/setup/characters")
def setup_characters():
    """The library as a grid: art, name, and where each one is currently assigned."""
    assigned = {}
    for number, char_id in library.slots.items():
        if char_id:
            assigned.setdefault(char_id, []).append(number)

    return render_template('characters.html',
                           characters=library.characters,
                           assigned=assigned,
                           art_url=art_url,
                           characters_source=CHARACTERS_SOURCE)


@app.route("/setup/character/<char_id>")
def setup_character_page(char_id):
    """One character's editor, alone on a page so it can show everything at once."""
    entry = library.characters.get(char_id)
    if entry is None:
        return _setup_done(False, f"There's no character called {char_id!r}.",
                           endpoint="setup_characters")

    in_slots = [n for n, c in library.slots.items() if c == char_id]
    return render_template('character.html',
                           char_id=char_id,
                           entry=entry,
                           in_slots=in_slots,
                           art_url=art_url,
                           voice_groups=VOICE_GROUPS,
                           styles=STYLE_OPTIONS,
                           voice_styles=VOICE_STYLE_MAP,
                           display_flags=DISPLAY_FLAGS)


@app.route("/setup/character/new", methods=["POST"])
def setup_character_new():
    """
    Create a blank character and go straight to its editor.

    Create and edit are one form rather than two. The previous page had a separate
    "New character" form duplicating most of the editor's fields, and two forms with
    overlapping fields drift -- which is exactly how the style dropdown ended up
    disagreeing with the control panel for weeks. So creating asks only for the id,
    and everything else is the editor.
    """
    char_id = (request.form.get("id") or "").strip()
    ok, message = library.upsert(char_id, {})
    if not ok:
        return _setup_done(False, message, endpoint="setup_characters")
    return redirect(url_for("setup_character_page", char_id=char_id))


@app.route("/setup/assign", methods=["POST"])
def setup_assign():
    number = request.form.get("player", "")
    char_id = request.form.get("character") or None
    ok, message = library.assign(number, char_id)
    if ok:
        apply_assignment(number)
    return _setup_done(ok, message)


@app.route("/setup/character", methods=["POST"])
def setup_character():
    """
    Create or update one character.

    Flags arrive as checkboxes, which means an unticked box sends nothing at all --
    so they're read as presence rather than value, and every flag has to be listed
    explicitly or unticking one would silently do nothing.
    """
    char_id = request.form.get("id", "")
    fields = {key: request.form.get(key, "")
              for key in ("display_name", "art_closed", "art_open",
                          "default_voice", "default_style")}
    fields.update({flag: request.form.get(flag) is not None for flag in DISPLAY_FLAGS})

    ok, message = library.upsert(char_id, fields)
    if ok:
        # Any slot showing this character needs redrawing -- its art or captions may
        # have just changed underneath it.
        for number, assigned in library.slots.items():
            if assigned == char_id:
                apply_assignment(number)
    return _setup_done(ok, message, endpoint="setup_character_page", char_id=char_id)


@app.route("/setup/upload", methods=["POST"])
def setup_upload():
    """
    Upload one or both art frames for a character.

    Filenames are derived from the character id, never taken from the upload. A
    user-supplied filename is a path traversal waiting to happen, and derived names
    mean the file on disk always says which character owns it.

    Existing art is overwritten rather than versioned. That only works because
    `art_url()` stamps every art URL with the file's mtime -- without cache busting,
    overwriting a PNG in place would change nothing visible in OBS. The alternative
    accumulates wizard-open-2.png forever, so overwrite wins now that the
    cache-buster is carrying stylesheets anyway.

    Both frames are checked against each other before either is written, so a
    mismatched pair is refused as a pair rather than leaving one new frame beside one
    old one -- which would be exactly the jumping-character bug the check exists to
    prevent.
    """
    char_id = (request.form.get("id") or "").strip()
    if char_id not in library.characters:
        return _setup_done(False, f"There's no character called {char_id!r}.",
                           endpoint="setup_characters")

    uploads = {}
    for which in ("closed", "open"):
        item = request.files.get(f"art_{which}")
        if item and item.filename:
            uploads[which] = item.read()

    if not uploads:
        return _setup_done(False, "Pick at least one image first.",
                           endpoint="setup_character_page", char_id=char_id)

    # Establish the size to match against: the other upload if there is one,
    # otherwise whatever is already on disk for this character.
    sizes = {w: characters.png_size(d[:24]) for w, d in uploads.items()}
    if len(uploads) == 2:
        reference = sizes["closed"] or sizes["open"]
    else:
        which = next(iter(uploads))
        other = "open" if which == "closed" else "closed"
        entry = library.characters.get(char_id) or {}
        reference = characters.art_size(entry.get(f"art_{other}"))

    fields = {}
    for which, data in uploads.items():
        ok, message, relative = characters.save_art(char_id, which, data, reference)
        if not ok:
            return _setup_done(False, f"{which} image: {message}",
                               endpoint="setup_character_page", char_id=char_id)
        fields[f"art_{which}"] = relative

    ok, message = library.upsert(char_id, fields)
    if not ok:
        return _setup_done(False, message,
                           endpoint="setup_character_page", char_id=char_id)

    for number, assigned in library.slots.items():
        if assigned == char_id:
            apply_assignment(number)

    size = reference or next(iter(sizes.values()))
    note = f" ({size[0]}x{size[1]})" if size else ""
    return _setup_done(True, f"Art updated{note}. Check the browser source size on "
                             "the control panel.",
                       endpoint="setup_character_page", char_id=char_id)


@app.route("/setup/delete", methods=["POST"])
def setup_delete():
    char_id = request.form.get("id", "")
    ok, message = library.delete(char_id)
    # On success the editor page is gone, so the library is the only sensible
    # destination. On failure -- the in-use guard -- stay where the button was.
    if ok:
        return _setup_done(True, message, endpoint="setup_characters")
    return _setup_done(False, message,
                       endpoint="setup_character_page", char_id=char_id)


@app.route("/setup/save-default", methods=["POST"])
def setup_save_default():
    """
    Write a slot's live voice and captions back onto its character.

    Without this, the only way to keep a good mid-stream discovery is to remember it
    and hand-edit JSON later -- so in practice it evaporates. Nothing is reset here:
    the live values are already what you want, they just become the character's
    defaults too.
    """
    number = request.form.get("player", "")
    character = CHARACTERS.get(number)
    if character is None or not character.id:
        return _setup_done(False, "That slot has no character to save to.")

    voice = twitchbot.tts_manager.voices.get(number) if twitchbot else None
    if voice is None:
        return _setup_done(False, "The bot hasn't started yet.")

    fields = {"default_voice": voice["name"], "default_style": voice["style"]}
    fields.update(display_manager.get(number) or {})
    ok, message = library.upsert(character.id, fields)
    return _setup_done(ok, f"{character.display_name or character.id}: "
                           f"now defaults to {voice['name']}." if ok else message)


def _setup_done(ok, message, endpoint="setup", **values):
    """
    Back to whichever setup page the form was on, with a one-line result.

    These are plain form posts with no JavaScript, so the result has to survive a
    redirect -- it rides in the query string. Taking the destination as an argument
    is what lets an edit return to the character you were editing rather than
    bouncing you to the slots page and making you find your way back.
    """
    return redirect(url_for(endpoint, ok="1" if ok else "0", msg=message, **values))


@app.route("/overlay")
def overlay():
    """
    On-stream graphic. Add to OBS as a Browser source.

    /overlay             -> every player in a row (matches the old layout)
    /overlay?player=2    -> just that player, so each can be positioned separately
    """
    requested = request.args.get("player")
    if requested is None:
        numbers = list(PLAYER_CONFIG)
    elif requested in PLAYER_CONFIG:
        numbers = [requested]
    else:
        abort(404, f"Unknown player {requested!r}. Configured: {', '.join(PLAYER_CONFIG)}")

    # Art now comes from the assigned character rather than a filename built from
    # the slot number. With no characters.json the library synthesizes exactly the
    # old convention, so this resolves to the same files it always did.
    #
    # An empty slot has no art. Both URLs are None and the template draws nothing,
    # which is what "character": null is for.
    images, names, flags, active = {}, {}, {}, {}
    for number in numbers:
        character = CHARACTERS.get(number)
        # Rendered as well as pushed over the socket, so a browser-source reload
        # while a slot is switched off comes back blank rather than flashing the
        # character on screen until the next event arrives.
        player = twitchbot.players.get(number) if twitchbot is not None else None
        active[number] = player.active if player else True
        images[number] = {
            "closed": art_url(character.art_closed) if character else None,
            "open": art_url(character.art_open) if character else None,
        }
        names[number] = character.display_name if character else ""
        # The flag alone can't decide: a character with no name would render an
        # empty box that still occupies space in the browser source.
        live = display_manager.get(number) or {}
        flags[number] = dict(live)
        flags[number]["show_character_name"] = bool(
            live.get("show_character_name") and character and character.has_name)

    return render_template('overlay.html', numbers=numbers, images=images,
                           character_names=names, flags=flags, active=active,
                           box_sizes=BOX_SIZES, caption_fonts=CAPTION_FONTS)


@socketio.event
def connect():
    """
    Log the connection, and send the new client the current state.

    This used to broadcast a placeholder message_send ("Temp User" saying
    "Connected successfully!") pinned to player 1. Harmless when the only client
    was a control page, but the overlay renders message_send straight into the
    on-stream name and message boxes -- so every browser-source reload put fake
    text on stream until a real message replaced it. The broadcast also reached
    every client, so opening the control panel did it too.

    The control page has its own connection indicator driven by socket.io's own
    connect event, so it doesn't need one from us.

    The state push that replaced it is deliberately the opposite shape: emit()
    inside a connect handler goes to the client that just connected and nobody
    else, so the overlay pages are untouched and no other panel is disturbed. It
    covers a panel that rendered before the bot thread was ready, and it resyncs a
    page after a reconnect instead of leaving it showing whatever it had when the
    socket dropped.
    """
    print("Socket client connected.")
    emit('state', player_state())
    emit('status', status_report())
    emit('show_settings', {'speech_gate': speech_gate_enabled})


@socketio.on("overlay_here")
def overlay_here(value):
    """
    An overlay page announcing itself, so the panel can say OBS is connected.

    Needed because a browser source pointed at the wrong URL is invisible: it shows
    a blank rectangle that's indistinguishable from a correct source waiting for
    someone to speak. Counting the pages that actually loaded the overlay turns that
    into a number you can check before going live.

    Keyed by socket id so a disconnect can remove it without guessing.
    """
    numbers = value.get('players') if isinstance(value, dict) else None
    overlay_clients[request.sid] = list(numbers) if numbers else []
    print(f"Overlay connected for player(s) {', '.join(overlay_clients[request.sid]) or '?'}")
    push_status()


@socketio.on("disconnect")
def disconnect():
    if overlay_clients.pop(request.sid, None) is not None:
        print("Overlay disconnected.")
        push_status()


def _player_from(value):
    """
    Resolve the Player a socket payload refers to, or None if it can't be resolved.

    Guards three things the browser could send: an event before the bot has started,
    a payload that isn't a dict, and an unknown player number.
    """
    if twitchbot is None:
        print("Socket event arrived before the Twitch bot was ready; ignoring.")
        return None
    number = value.get('user_number') if isinstance(value, dict) else None
    player = twitchbot.players.get(number)
    if player is None:
        print(f"Socket event for unknown player {number!r}; ignoring.")
    return player


@socketio.on("tts")
def toggletts(value):
    player = _player_from(value)
    if player is None:
        return
    player.tts_enabled = bool(value.get('checked'))
    print(f"TTS for player {player.number}: {player.tts_enabled}")


@socketio.on("speech_gate")
def toggle_speech_gate(value):
    """
    Turn one-speaker-at-a-time on or off, live.

    Switching it **off flushes the backlog** rather than stranding it. Anything
    already queued was about to be read; leaving it stuck would look like the app
    swallowing messages at exactly the moment you asked for less restriction.
    """
    global speech_gate_enabled
    speech_gate_enabled = bool(value.get('checked')) if isinstance(value, dict) else False
    print(f"Speech gate {'on -- one at a time' if speech_gate_enabled else 'off'}")
    if not speech_gate_enabled:
        speech_pacer.flush()
    socketio.emit('show_settings', {'speech_gate': speech_gate_enabled})


@socketio.on("slot_active")
def toggle_slot_active(value):
    """
    Put a slot in or out of the show.

    Broadcast, not replied: the overlay is the point of the change and it's a
    different client. The panel that sent it has already moved its own switch.

    Turning a slot off deliberately **keeps its pool**. Re-enabling restores everyone
    who had already typed the keyphrase rather than making them join again -- and
    since the pool self-empties after 450 seconds of someone being quiet, keeping it
    only really matters for short toggles, which is exactly the case where clearing
    would be most annoying.
    """
    player = _player_from(value)
    if player is None:
        return
    player.active = bool(value.get('checked'))
    print(f"Player {player.number} is {'in' if player.active else 'out of'} the show")

    socketio.emit('slot_active', {'user_number': player.number,
                                  'active': player.active})
    socketio.emit('state', player_state())
    push_status()


@socketio.on("pickrandom")
def pickrandom(value):
    player = _player_from(value)
    if player is None:
        return
    if not player.active:
        print(f"Player {player.number} is out of the show; not picking anyone.")
        return
    twitchbot.random_user(player.number)


@socketio.on("choose")
def chooseuser(value):
    player = _player_from(value)
    if player is None:
        return
    if not player.active:
        print(f"Player {player.number} is out of the show; not assigning anyone.")
        return
    chosen = (value.get('chosen_user') or "").strip().lower()
    if not chosen:
        return
    player.current_user = chosen
    twitchbot.announce(player, f"{chosen} was picked!")


@socketio.on("voicename")
def choose_voice_name(value):
    player = _player_from(value)
    if player is None or not value.get('voice_name'):
        return
    voice_name = value['voice_name']
    reset_to = twitchbot.tts_manager.update_voice_name(player.number, voice_name)
    if reset_to is not None:
        # The style that was selected isn't available on the new voice. Say so,
        # rather than leaving a dropdown showing something that won't happen.
        socketio.emit('style_reset', {
            'user_number': player.number,
            'voice_style': reset_to,
            'available': styles_for(voice_name),
        })


@socketio.on("display")
def toggle_display(value):
    """
    Show or hide one caption on one slot, live.

    Broadcast rather than sent to the caller: the overlay is the whole point of the
    change, and it's a different client. The panel that sent it already updated its
    own checkbox, and re-applying the same value is a no-op there.

    The new source size rides along, because toggling a caption changes how tall the
    browser source needs to be and that number is only useful at the moment it
    changes.
    """
    player = _player_from(value)
    if player is None:
        return
    if not display_manager.update(player.number, value.get('flag'), value.get('checked')):
        return

    character = CHARACTERS.get(player.number)
    flags = display_manager.get(player.number)
    socketio.emit('display_changed', {
        'user_number': player.number,
        # What the overlay should actually draw, which isn't the raw flag: a
        # character with no name never shows the character-name box.
        'show_character_name': bool(flags.get('show_character_name')
                                    and character and character.has_name),
        'show_chatter_name': flags.get('show_chatter_name'),
        'show_message': flags.get('show_message'),
        'size_parts': size_parts(character, flags),
    })


@socketio.on("voicestyle")
def choose_voice_style(value):
    player = _player_from(value)
    if player is None or not value.get('voice_style'):
        return
    twitchbot.tts_manager.update_voice_style(player.number, value['voice_style'])


@dataclass
class Player:
    number: str                                              # "1", "2", ... matches socket payloads
    keyphrase: str                                           # what a viewer types to join this pool
    current_user: Optional[str] = None                       # whose messages get read out
    tts_enabled: bool = True
    pool: Dict[str, datetime] = field(default_factory=dict)  # username -> when they last opted in

    # Whether this slot is in the show at all. Distinct from tts_enabled, which
    # silences a slot that's still on screen, and from an empty character, which
    # hides a slot that still speaks. This is the single "out of the show" switch:
    # nothing drawn, nothing spoken, no pool joins, no picking.
    #
    # It exists so a scene can be built for six players and run with four without
    # the app pooling chatters into characters nobody can see, or spending Azure
    # characters on them. Layout stays an OBS concern -- a second scene -- because
    # fixed browser sources can't re-centre themselves when two go dark.
    active: bool = True


class Bot(commands.Bot):
    seconds_active = 450  # seconds of silence before a chatter is dropped from a pool
    max_users = 2000      # hard cap on pool size

    def __init__(self, tts_manager, speech_worker):
        # Instance state, not class attributes. As class attributes these were shared
        # across every instance, which is a latent bug even if only one Bot exists.
        self.players = {
            number: Player(number=number, keyphrase=config["keyphrase"])
            for number, config in PLAYER_CONFIG.items()
        }
        self.tts_manager = tts_manager
        self.speech_worker = speech_worker
        # Pools are written on the twitchio thread and read on the Flask thread.
        self._pool_lock = threading.Lock()

        #connects to twitch channel
        super().__init__(token=setting('twitch_token'), prefix='?', initial_channels=[TWITCH_CHANNEL_NAME])

    async def event_ready(self):
        print(f'Logged in as | {self.nick}')
        print(f'User id is | {self.user_id}')
        # Recorded rather than only printed: "did the bot actually log in" is the
        # single most useful thing to know before going live, and a line that
        # scrolled past twenty minutes ago answers it for nobody.
        global twitch_nick
        twitch_nick = self.nick
        push_status()

    async def event_message(self, message):
        await self.process_message(message)

    def announce(self, player: Player, text: str):
        """The single place the overlay's socket payload shape is defined."""
        socketio.emit('message_send',
            {'message': text,
            'current_user': player.current_user,
            'user_number': player.number})

    async def process_message(self, message: Message):
        author = message.author.name.lower()

        # If this is a current player, show and speak their message.
        # The text goes out immediately; audio follows from the worker once Azure
        # has rendered it, so neither step blocks the bot.
        for player in self.players.values():
            if player.current_user and author == player.current_user:
                # An inactive slot is out of the show entirely -- nothing drawn,
                # nothing spoken, and no Azure characters spent on a character
                # nobody can see.
                if not player.active:
                    break
                self.announce(player, message.content)
                if player.tts_enabled:
                    self.speech_worker.submit(player.number, player.current_user, message.content)
                break

        # If this is a keyphrase, add the chatter to that player's pool
        for player in self.players.values():
            if message.content == player.keyphrase:
                # Deliberately ignored while inactive rather than queued: pooling
                # people for a slot that can't appear leaves them waiting for a turn
                # that will never come.
                if not player.active:
                    break
                with self._pool_lock:
                    player.pool.pop(author, None)          # re-insert so they land at the end
                    player.pool[author] = message.timestamp
                    self._prune(player)
                break

    def _prune(self, player: Player):
        """
        Drop everyone past the activity threshold, then enforce the size cap.

        The original checked only the single oldest entry, so max_users could never
        actually cap the pool and one stale entry blocked the next from being evicted.
        Two loops, which is what the original's comments always claimed happened.

        Callers hold self._pool_lock.
        """
        cutoff = datetime.now(pytz.utc) - timedelta(seconds=self.seconds_active)
        pool = player.pool

        while pool:
            oldest = next(iter(pool))
            if pool[oldest].replace(tzinfo=pytz.utc) >= cutoff:
                break
            pool.pop(oldest)
            print(f"Player {player.number}: dropped {oldest} (idle over {self.seconds_active}s)")

        while len(pool) > self.max_users:
            oldest = next(iter(pool))
            pool.pop(oldest)
            print(f"Player {player.number}: dropped {oldest} (pool at max of {self.max_users})")

    def random_user(self, user_number: str):
        """Pick a random chatter from that player's pool."""
        player = self.players.get(user_number)
        if player is None:
            return

        with self._pool_lock:
            candidates = list(player.pool)

        # An empty pool is the expected case, not an error. The original swallowed
        # every exception here, which also hid genuine bugs.
        if not candidates:
            print(f"Player {user_number}: pool is empty (viewers join by typing {player.keyphrase})")
            return

        player.current_user = random.choice(candidates)
        print(f"Player {user_number}: random user is {player.current_user}")
        self.announce(player, f"{player.current_user} was picked!")


def startTwitchBot(tts_manager, speech_worker):
    global twitchbot
    asyncio.set_event_loop(asyncio.new_event_loop())
    twitchbot = Bot(tts_manager, speech_worker)
    twitchbot.run()


if __name__=='__main__':

    # Configuration first, before anything slow or noisy, so a missing variable is
    # the first thing on screen rather than something to scroll back for.
    print("\nConfiguration:")
    for line in startup_report():
        print(line)

    # One block however many are legacy. Repeating the same paragraph four times
    # is how a useful warning becomes something you learn to scroll past.
    legacy = legacy_in_use()
    if legacy:
        print(f"\n{len(legacy)} setting{'s' if len(legacy) > 1 else ''} still using the older "
              "unprefixed variable name:")
        for prefixed, old in legacy:
            print(f"  {old} -> {prefixed}")
        print("  These work. The prefix exists because names like AZURE_TTS_KEY are ones\n"
              "  another tool could also be using, and a clash looks like a bad key rather\n"
              "  than a name collision. Switch when convenient:\n"
              f"  {set_command(legacy[0][0], 'value')}")

    missing = missing_required()
    if missing:
        print(f"\nNot set: {', '.join(missing)}.\n"
              "  Either copy config.example.json to config.json and fill it in, or set\n"
              "  them as environment variables. If you set variables recently, reopen the\n"
              "  terminal -- they don't reach shells that were already open, which is the\n"
              "  single most common cause of this message.")

    if CHARACTERS_SOURCE == "file":
        print("\nCharacters: read from characters.json")
        for number, character in CHARACTERS.items():
            label = character.display_name or character.id or "(empty)"
            print(f"  Player {number}: {label}")
    else:
        print("\nCharacters: none configured -- using players.py and the "
              "characters/player<N>-*.png convention.\n"
              "  Copy characters.example.json to characters.json to name your "
              "characters and control what shows on stream.")

    tts_manager = TTSManager(CHARACTERS)
    tts_manager.play_startup_chime()
    speech_worker = SpeechWorker(tts_manager)

    print(f"\nReading Twitch channel: #{TWITCH_CHANNEL_NAME}")
    print(f"Control panel: http://127.0.0.1:5000/")
    for number in PLAYER_CONFIG:
        print(f"Overlay player {number}: http://127.0.0.1:5000/overlay?player={number}")
    print()

    # Creates and runs the twitchio bot on a separate thread
    bot_thread = threading.Thread(target=startTwitchBot, args=(tts_manager, speech_worker), daemon=True)
    bot_thread.start()

    # allow_unsafe_werkzeug is required, not optional, for anything but a terminal.
    #
    # Flask-SocketIO refuses to start the Werkzeug server when sys.stdin isn't a TTY,
    # raising "The Werkzeug web server is not designed to run in production". Running
    # this by hand in PowerShell is fine, which is why it went unnoticed -- but a
    # launcher, a scheduled task, or anything that starts the app detached trips it
    # instantly, and the failure reads as a crash on startup rather than a refusal.
    #
    # The warning is about exposing Werkzeug to the internet. This binds to localhost
    # and serves one operator and their own OBS, so it doesn't apply.
    socketio.run(app, allow_unsafe_werkzeug=True)
