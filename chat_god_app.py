from twitchio.ext import commands
from twitchio import *
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional
from collections import OrderedDict
from flask import Flask, abort, redirect, render_template, request, send_file, url_for
from flask_socketio import SocketIO
import asyncio
import queue
import threading
import pytz
import random
import os
import uuid

from azure_text_to_speech import AZURE_VOICES, AZURE_VOICE_STYLES
from players import PLAYER_CONFIG, DEFAULT_VOICE_STYLE
from voices_manager import TTSManager

TWITCH_CHANNEL_NAME = 'silverstagvt' # Replace this with your channel name

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
    """'en-US-DavisNeural' -> 'Davis' for the dropdown."""
    name = voice_id.split("-")[-1]
    return name[:-len("Neural")] if name.endswith("Neural") else name


# Built from the same lists the TTS code uses, so the dropdowns can't drift out of
# sync with what Azure will actually accept.
VOICE_OPTIONS = [(voice, _voice_label(voice)) for voice in AZURE_VOICES]
STYLE_OPTIONS = ["random"] + list(AZURE_VOICE_STYLES)


@app.route("/")
def home():
    return redirect(url_for("control"))


@app.route("/control")
def control():
    """Operator dashboard. Open in a normal browser -- never add this to OBS."""
    return render_template('control.html',
                           players=PLAYER_CONFIG,
                           voices=VOICE_OPTIONS,
                           styles=STYLE_OPTIONS,
                           default_style=DEFAULT_VOICE_STYLE)


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
    Log the connection and nothing more.

    This used to broadcast a placeholder message_send ("Temp User" saying
    "Connected successfully!") pinned to player 1. Harmless when the only client
    was a control page, but the overlay renders message_send straight into the
    on-stream name and message boxes -- so every browser-source reload put fake
    text on stream until a real message replaced it. The broadcast also reached
    every client, so opening the control panel did it too.

    The control page has its own connection indicator driven by socket.io's own
    connect event, so nothing needs this.
    """
    print("Socket client connected.")


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
    twitchbot.tts_manager.update_voice_name(player.number, value['voice_name'])


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

    tts_manager = TTSManager()
    tts_manager.play_startup_chime()
    speech_worker = SpeechWorker(tts_manager)

    print(f"\nControl panel: http://127.0.0.1:5000/")
    for number in PLAYER_CONFIG:
        print(f"Overlay player {number}: http://127.0.0.1:5000/overlay?player={number}")
    print()

    # Creates and runs the twitchio bot on a separate thread
    bot_thread = threading.Thread(target=startTwitchBot, args=(tts_manager, speech_worker), daemon=True)
    bot_thread.start()

    socketio.run(app)
