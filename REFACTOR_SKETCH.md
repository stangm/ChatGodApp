# Refactor sketch: collapse `user_1/2/3` into a keyed collection

> **Status: implemented.** This was written as a plan and is kept for the reasoning behind the
> shape of `players.py`, not as a description of pending work. Where the outcome diverged from the
> sketch, there's a note saying so. For how the code works now, read the README.

Goal: adding a 4th player becomes one config entry instead of a find-and-replace across
`chatmob_app.py`, `voices_manager.py`, and `templates/index.html`.

Current triplication:

| File | Duplicated blocks |
|---|---|
| `chatmob_app.py` | 4 socket handlers, `process_message` (2 × 3 branches), `randomUser` (3 branches), 6 class attrs × 3 |
| `voices_manager.py` | voice getters/setters, OBS filter on/off (3 branches each, 6 total) |
| `templates/index.html` | 3 identical control panels + 8 near-identical jQuery handlers |

Expected: `chatmob_app.py` 222 → ~130 lines, `index.html` 307 → ~120.

> **Diverged.** `chatmob_app.py` grew instead of shrinking, because the browser-overlay work
> landed in the same pass and added the audio cache, the `/audio` route and the speech worker.
> `index.html` was never rewritten — it was left untouched and superseded by two new templates,
> `control.html` for the operator and `overlay.html` for the stream. The triplication this sketch
> set out to remove is gone either way; the line counts just aren't a useful measure of it.

---

## Phase 1 — one config table (`players.py`, new file)

The only place a player is defined. Adding player 4 = adding a dict entry.

```python
PLAYER_CONFIG = {
    "1": {"keyphrase": "!player1", "voice_name": "en-US-DavisNeural",
          "obs_source": "Line In", "obs_filter": "Audio Move - DnD Player 1"},
    "2": {"keyphrase": "!player2", "voice_name": "en-US-TonyNeural",
          "obs_source": "Line In", "obs_filter": "Audio Move - DnD Player 2"},
    "3": {"keyphrase": "!player3", "voice_name": "en-US-JaneNeural",
          "obs_source": "Line In", "obs_filter": "Audio Move - DnD Player 3"},
}
DEFAULT_VOICE_STYLE = "random"
```

Keys stay **strings** because that's what the browser sends over the socket — no int/str coercion bugs.
`Bot` and `TTSManager` each read the fields they own, so the module boundary is preserved.

## Phase 2 — `Bot` state becomes `dict[str, Player]`

Class attributes today are *class*-level (shared, mutable) — a latent bug if a second `Bot` is ever
constructed. Move them to instance state.

```python
from dataclasses import dataclass, field
from datetime import datetime
from players import PLAYER_CONFIG

@dataclass
class Player:
    number: str
    keyphrase: str
    current_user: str | None = None
    tts_enabled: bool = True
    pool: dict[str, datetime] = field(default_factory=dict)  # username -> last-chat time

class Bot(commands.Bot):
    seconds_active = 450
    max_users = 2000

    def __init__(self):
        self.players = {n: Player(number=n, keyphrase=c["keyphrase"])
                        for n, c in PLAYER_CONFIG.items()}
        self.tts_manager = TTSManager()
        super().__init__(token=os.getenv("TWITCH_ACCESS_TOKEN"), prefix="?",
                         initial_channels=[TWITCH_CHANNEL_NAME])
```

### `process_message` — 60 lines → ~15

```python
    async def process_message(self, message: Message):
        author = message.author.name.lower()

        for p in self.players.values():
            if author == p.current_user:
                self._emit_player(p, message.content)
                if p.tts_enabled:
                    self.tts_manager.text_to_audio(message.content, p.number)
                break

        for p in self.players.values():
            if message.content == p.keyphrase:
                p.pool.pop(author, None)      # re-insert at the end
                p.pool[author] = message.timestamp
                self._prune(p.pool)
                break

    def _emit_player(self, p: Player, text: str):
        socketio.emit("message_send",
            {"message": text, "current_user": p.current_user, "user_number": p.number})
```

`_emit_player` is the single place the socket payload shape is defined — today it's written out
five times, so any change to the message contract has to be made in five places.

### `_prune` — fixes the eviction bug from the review

The current code evicts at most one entry per join and only when someone types a keyphrase, so
`max_users` can't actually cap the pool, and the `== self.max_users` print branch is unreachable.

```python
    def _prune(self, pool: dict[str, datetime]):
        cutoff = datetime.now(pytz.utc) - timedelta(seconds=self.seconds_active)
        while pool:                                  # drain ALL stale entries, not just one
            oldest, ts = next(iter(pool.items()))
            if ts.replace(tzinfo=pytz.utc) >= cutoff:
                break
            pool.pop(oldest)
            print(f"{oldest} popped: idle > {self.seconds_active}s")
        while len(pool) > self.max_users:             # then enforce the hard cap
            print(f"{next(iter(pool))} popped: max users")
            pool.pop(next(iter(pool)))
```

The two conditions are now separate loops, which is what the existing comments already claim happens.

### `randomUser` — the bare `except Exception` goes away

```python
    def randomUser(self, user_number: str):
        p = self.players.get(user_number)
        if p is None or not p.pool:                   # empty pool is expected, not exceptional
            print(f"No candidates in pool {user_number}")
            return
        p.current_user = random.choice(list(p.pool))
        self._emit_player(p, f"{p.current_user} was picked!")
```

Real bugs now surface instead of being swallowed.

### Socket handlers — ~40 lines → ~15

```python
@socketio.on("tts")
def toggletts(value):
    twitchbot.players[value["user_number"]].tts_enabled = value["checked"]

@socketio.on("choose")
def chooseuser(value):
    p = twitchbot.players[value["user_number"]]
    p.current_user = value["chosen_user"].lower()
    twitchbot._emit_player(p, f"{p.current_user} was picked!")
```

**Guard the lookups.** `players[value["user_number"]]` raises `KeyError` on an unknown number and
`TypeError` on a missing key — a malformed socket payload shouldn't take down the handler thread.
A small `_player_or_none(value)` helper that logs and returns `None` covers all four handlers.

## Phase 3 — `TTSManager` reads the same config

```python
class TTSManager:
    def __init__(self):
        self.voices = {n: {"name": c["voice_name"], "style": DEFAULT_VOICE_STYLE}
                       for n, c in PLAYER_CONFIG.items()}
        ...

    def update_voice_name(self, user_number, voice_name):
        self.voices[user_number]["name"] = voice_name

    def text_to_audio(self, text, user_number):
        v = self.voices[user_number]
        cfg = PLAYER_CONFIG[user_number]
        tts_file = self.azuretts_manager.text_to_audio(text, v["name"], v["style"])
        try:
            self.obswebsockets_manager.set_filter_visibility(cfg["obs_source"], cfg["obs_filter"], True)
            self.audio_manager.play_audio(tts_file, True, True, True)
        finally:
            self.obswebsockets_manager.set_filter_visibility(cfg["obs_source"], cfg["obs_filter"], False)
```

The `try/finally` is a small reliability win beyond the dedup: today, if Azure or pygame throws
mid-playback, the Move filter is left **on** and the character bobs forever until you restart.

Also note `azuretts_manager`/`audio_manager`/`obswebsockets_manager` are class attributes, so they
are constructed at *import* time — that's why a missing OBS kills startup before `main` even runs.
Moving them into `__init__` doesn't fix the `sys.exit()` but makes the failure point predictable.

## Phase 4 — template loop (optional, biggest line saving)

`home()` passes the config through; the three hand-copied panels become one Jinja loop.

```python
@app.route("/")
def home():
    return render_template("index.html", players=PLAYER_CONFIG.keys(),
                           voices=VOICE_OPTIONS, styles=STYLE_OPTIONS)
```

```html
{% for n in players %}
<div class="player-panel">
    <form class="pickrandom" data-player="{{ n }}">
        <input type="submit" value="Pick Random">
    </form>
    <form class="tts" data-player="{{ n }}">
        <label>TTS {{ n }}:</label>
        <input type="checkbox" class="tts-checkbox" checked>
    </form>
    <form class="choose" data-player="{{ n }}">
        <label>Choose User:</label><input type="text" class="choose-input">
    </form>
    <select class="voicename" data-player="{{ n }}">
        {% for value, label in voices %}<option value="{{ value }}">{{ label }}</option>{% endfor %}
    </select>
    <div class="user-name-box" id="user-name-box-{{ n }}">
        <span class="user-name" id="user-name-{{ n }}">Temp User</span>
    </div>
    <div class="user-message-box" id="user-message-box-{{ n }}">
        <span class="user-message" id="user-message-{{ n }}">Temp message</span>
    </div>
</div>
{% endfor %}
```

The eight jQuery blocks collapse into handlers keyed off `data-player`:

```js
$('form.pickrandom').submit(function() {
    socket.emit('pickrandom', {user_number: $(this).data('player') + ''});
    return false;
});
$('select.voicename').change(function() {
    socket.emit('voicename', {user_number: $(this).data('player') + '', voice_name: $(this).val()});
});
```

`+ ''` matters — `data-player` is coerced to a JS number, and the Python side keys on strings.
The `textfill` init loop also needs to iterate players rather than name boxes 1/2/3 explicitly.

---

## Suggested order & verification

1. Phase 1 + 2 (`chatmob_app.py` only) — biggest win, no template changes, testable alone.
2. Phase 3 (`voices_manager.py`).
3. Phase 4 (template) last — cosmetic, easiest to defer.

Nothing here has test coverage, so verify by running with `TWITCH_CHANNEL_NAME` pointed at your own
channel: type each keyphrase from two accounts, Pick Random, type a name manually, change voice and
style, and confirm the Move filter turns on *and off*. Worth checking pool eviction by dropping
`seconds_active` to ~15 temporarily.

## Out of scope but adjacent

- **Blocking TTS.** `audio_player.play_audio` does a synchronous `time.sleep(file_length)` inside a
  twitchio event handler, so a long message stalls the bot for all players. A `queue.Queue` + worker
  thread fixes this and is independent of this refactor — but the fix is *much* easier once per-player
  state is in one object.
- **Cross-thread access.** `self.players` is written on the twitchio thread and read on the Flask
  thread. Individual dict ops are safe under the GIL, but `_prune` running mid-`randomUser` is a real
  (if unlikely) race. A single `threading.Lock` around pool mutation would close it.
- **`socketio = SocketIO`** on line 15 is dead — delete while you're in there.
- **Hardcoded OBS password** in `websockets_auth.py` should read from env with that value as fallback.
