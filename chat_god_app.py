from twitchio.ext import commands
from twitchio import *
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional
from collections import OrderedDict
from flask import Flask, abort, redirect, render_template, request, send_file, url_for
from flask_socketio import SocketIO, emit
import asyncio
import queue
import threading
import pytz
import random
import os
import uuid

from azure_text_to_speech import (AZURE_VOICES, AZURE_VOICE_STYLES, VOICE_CATALOG,
                                  VOICES_SOURCE, styles_for)
from players import PLAYER_CONFIG, DEFAULT_VOICE_STYLE
from voices_manager import TTSManager

# Set TWITCH_CHANNEL_NAME as an environment variable alongside the other three.
# The fallback keeps existing installs working, but setting the variable means
# setup is four env vars and no source edits -- and keeps the channel name out of
# a public repo. Lowercased because twitchio matches channels case-sensitively
# and the common mistake is typing the display name.
TWITCH_CHANNEL_NAME = os.getenv('TWITCH_CHANNEL_NAME', 'silverstagvt').strip().lower()

app = Flask(__name__)
socketio = SocketIO(app, async_mode="threading")
print(socketio.async_mode)

# Set once the bot thread has constructed the Bot. Socket events can arrive before
# that happens, so every handler checks it.
twitchbot = None


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
                    socketio.emit('speak', {
                        'user_number': number,
                        'current_user': speaker,
                        'audio_url': f"/audio/{register_audio(path)}.wav",
                    })
            except Exception as exc:
                print(f"TTS failed for player {number}: {exc}")
            finally:
                self._queue.task_done()


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
STYLE_OPTIONS = ["random"] + list(AZURE_VOICE_STYLES)


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

# voice -> the styles it really supports, handed to the control panel so it can
# narrow the style dropdown as the voice changes. A voice with an empty list
# supports no express-as at all, and only "random" (meaning "none") applies.
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
        state[number] = {
            "tts_enabled": player.tts_enabled if player else True,
            "current_user": (player.current_user if player else None) or "",
            "voice_name": voice["name"] if voice else config["voice_name"],
            "voice_style": voice["style"] if voice else DEFAULT_VOICE_STYLE,
        }
    return state


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
                           state=player_state())


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

    # Convention: static/characters/player<N>-closed.png and -open.png.
    # A player entry can override with "image_closed" / "image_open" if the files
    # live somewhere else under static/.
    images = {}
    for number in numbers:
        config = PLAYER_CONFIG[number]
        images[number] = {
            "closed": url_for('static', filename=config.get(
                "image_closed", f"characters/player{number}-closed.png")),
            "open": url_for('static', filename=config.get(
                "image_open", f"characters/player{number}-open.png")),
        }

    return render_template('overlay.html', numbers=numbers, images=images)


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


@socketio.on("pickrandom")
def pickrandom(value):
    player = _player_from(value)
    if player is None:
        return
    twitchbot.random_user(player.number)


@socketio.on("choose")
def chooseuser(value):
    player = _player_from(value)
    if player is None:
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
        super().__init__(token=os.getenv('TWITCH_ACCESS_TOKEN'), prefix='?', initial_channels=[TWITCH_CHANNEL_NAME])

    async def event_ready(self):
        print(f'Logged in as | {self.nick}')
        print(f'User id is | {self.user_id}')

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
                self.announce(player, message.content)
                if player.tts_enabled:
                    self.speech_worker.submit(player.number, player.current_user, message.content)
                break

        # If this is a keyphrase, add the chatter to that player's pool
        for player in self.players.values():
            if message.content == player.keyphrase:
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

    if not os.getenv('TWITCH_CHANNEL_NAME'):
        print(f"\nTWITCH_CHANNEL_NAME isn't set -- reading #{TWITCH_CHANNEL_NAME}.\n"
              "  Set it alongside your other environment variables:\n"
              '  [Environment]::SetEnvironmentVariable("TWITCH_CHANNEL_NAME", '
              '"yourchannel", "User")\n'
              "  then reopen the terminal.")
    if not os.getenv('TWITCH_ACCESS_TOKEN'):
        print("\nTWITCH_ACCESS_TOKEN isn't set. The bot won't be able to log in.\n"
              "  If you set it recently, reopen the terminal -- environment variables\n"
              "  don't reach shells that were already open.")

    tts_manager = TTSManager()
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

    socketio.run(app)
