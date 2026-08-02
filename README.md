# ChatGodApp

Reads your Twitch chatters' messages aloud with Azure TTS and animates a character's mouth
in time with the audio, as an OBS browser source.

Originally written by [DougDoug](https://github.com/DougDougGithub/ChatGodApp), with help from
Banana. This fork moves the animation and audio into the browser — see
[What's different in this fork](#whats-different-in-this-fork). You're welcome to adapt or use
this code for whatever you'd like.

---

## What's different in this fork

The upstream version played TTS through the server's speakers, routed that audio into OBS, and
used the **Move** plugin to nudge image sources based on the waveform. That meant a virtual audio
cable, an audio capture source with an exact name, three filters with exact names, threshold
tuning, and OBS having to be running before the app would start at all.

Here, the overlay page does all of it:

| | Upstream | This fork |
|---|---|---|
| Audio playback | pygame, on the server | `<audio>` in the overlay page |
| Audio into OBS | VB-Cable + per-app routing | Browser source audio, native |
| Mouth animation | Move plugin filter | WebAudio amplitude, in the page |
| Per-player OBS setup | 2 image sources + 1 named filter | 1 browser source |
| OBS required to start? | Yes — app exited without it | No |

No Move plugin, no VB-Cable, no websocket password, no OBS running requirement.

---

## Setup

### 1. Python and dependencies

Python 3.9–3.12. On 3.13+ you may hit missing wheels for `azure-cognitiveservices-speech`; if so,
install 3.12 alongside and use `py -3.12` below.

```powershell
cd path\to\ChatGodApp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks the activate script:
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

**Check:** `python -c "import pygame, twitchio, flask, azure.cognitiveservices.speech; print('ok')"`

> **Optional:** `winget install ffmpeg`. `pydub` needs it for the gTTS fallback, which is the path
> you land on when Azure fails — exactly when you don't want a second error.

> **OneDrive users:** a `.venv` inside a synced folder uploads thousands of files for no benefit.
> It's in `.gitignore`, but also right-click the folder → *Always keep on this device* → off, or
> put the venv elsewhere entirely (`python -m venv C:\venvs\chatgod`).

### 2. Twitch

Generate a token at <https://twitchtokengenerator.com/> — choose **Bot Chat Token**, with
**`chat:read`** and **`chat:edit`** enabled. Copy the *Access Token*, not the refresh token.

```powershell
[Environment]::SetEnvironmentVariable("CHATGOD_TWITCH_TOKEN", "yourtokenhere", "User")
[Environment]::SetEnvironmentVariable("CHATGOD_TWITCH_CHANNEL", "yourchannel", "User")
```

The channel name is your channel, no URL and no `@` — case doesn't matter, it gets lowercased.

**Close and reopen your terminal** — environment variables don't reach already-open shells. This is
the single most common "it works for everyone else" failure.

**Check:** `python -c "from config import setting; print(setting('twitch_token')[:10])"` should print
characters, not an error.

> **Upgrading from an older copy?** The unprefixed names — `TWITCH_ACCESS_TOKEN`,
> `TWITCH_CHANNEL_NAME`, `AZURE_TTS_KEY`, `AZURE_TTS_REGION` — are still read, so nothing you've
> already set breaks. The prefix exists because those names are ones any other Twitch or Azure tool
> would plausibly also use, and a collision hands your app someone else's credentials while looking
> like a bad key. The app names any legacy variable it falls back to at startup.

### 3. Azure Speech

In the [Azure portal](https://portal.azure.com): *Create a resource* → **Speech** → Create. Any
nearby region, pricing tier **F0 (Free)** — 500,000 characters/month, far more than a stream uses.

Copy Key 1 and the Region from *Keys and Endpoint*. The region must be the short form
(`eastus`, `westus2`), **not** the display name:

```powershell
[Environment]::SetEnvironmentVariable("CHATGOD_AZURE_KEY", "your-key-here", "User")
[Environment]::SetEnvironmentVariable("CHATGOD_AZURE_REGION", "eastus", "User")
```

Reopen the terminal again, then test Azure on its own:

```powershell
python azure_text_to_speech.py
```

You should hear a test line. **If you hear "Azure failed, using gTTS instead"**, your key or region
is wrong — the code swallows the real Azure error, so check both rather than debugging elsewhere.

Once that works, build the voice list:

```powershell
python fetch_voices.py
```

This asks Azure which voices your subscription offers and which speaking styles each one supports,
and caches the answer in `voices.json`. Skipping it isn't fatal — the repo ships
`voices.default.json`, a real fetch covering every English locale, and the app uses that instead.
Your own fetch gets you the current catalogue and whichever locales you want, and the control panel
notes which of the two it's running on.

**It fetches every English locale by default** — en-GB, en-AU, en-IE, en-IN, en-ZA and the rest
alongside en-US. The control panel groups the dropdown by country, so a long list stays navigable.
An argument without a region means "the whole language", one with a region means just that locale:

```powershell
python fetch_voices.py            # all English
python fetch_voices.py en-GB      # British only
python fetch_voices.py en fr      # English and French
python fetch_voices.py --all      # every locale Azure has
```

**Premium voices are left out.** Azure's free F0 tier covers prebuilt *non-HD, non-AOAI* neural
voices, so the HD families (`DragonHD`, `Multitalker`) and the Azure OpenAI voices (the Turbo
Multilingual set — Alloy, Echo, Fable, Nova, Onyx, Shimmer) bill separately at a higher rate. In
`en-US` alone that's about 70 of the ~124 voices Azure returns. Since anyone in chat can trigger
synthesis, leaving them in the dropdown is a way to run up a bill by accident. Pass
`--include-premium` if you're on a paid tier and want them.

### 4. Character art

Drop two PNGs per player in `static/characters/`, named by convention:

```
player1-closed.png    player1-open.png
player2-closed.png    player2-open.png
player3-closed.png    player3-open.png
```

Same dimensions for both, mouth closed and mouth open. Transparent backgrounds work best. To keep
files elsewhere under `static/`, add `image_closed` / `image_open` to that player's entry in
`players.py`.

### 5. OBS

Add one **Browser** source per player:

| Source | URL |
|---|---|
| Player 1 | `http://127.0.0.1:5000/overlay?player=1` |
| Player 2 | `http://127.0.0.1:5000/overlay?player=2` |
| Player 3 | `http://127.0.0.1:5000/overlay?player=3` |

Position and scale each independently. Leave **Control audio via OBS** unchecked unless you want
the TTS on a dedicated mixer channel.

`http://127.0.0.1:5000/overlay` with no parameter renders all players in a row, matching the old
single-source layout, if you'd rather have one source.

That's the whole OBS setup. No plugins, no audio capture source, no filters.

---

## Running it

```powershell
.\.venv\Scripts\Activate.ps1
python chat_god_app.py
```

Open **<http://127.0.0.1:5000/control>** in a normal browser — this is your operator dashboard.
Don't add it to OBS; it's not meant for stream.

From the control panel you can assign a chatter to each player slot, pick voices and styles, and
toggle TTS per player, all live.

**Smoke test:**

1. Type `!player1` in your own chat.
2. Hit **Pick Random** under player 1 — your name appears.
3. Type anything in chat — it should appear on the overlay and be read aloud, with the mouth moving.
4. Change the voice dropdown, type again, confirm it changed.
5. Type `(angry) hello` — confirm the style prefix is picked up.
6. Untick TTS, type again — text appears silently.

### Assigning players

Chatters join a pool by typing `!player1`, `!player2` or `!player3`. **Pick Random** draws one from
that pool. Or type a username directly into *Choose user* and hit enter.

### Voice styles

A chatter can override the style by prefixing their message: `(angry)`, `(cheerful)`, `(excited)`,
`(hopeful)`, `(sad)`, `(shouting)`, `(shout)`, `(terrified)`, `(unfriendly)`, `(whispering)`,
`(whisper)`, or `(random)`.

Styles aren't supported by every voice, and Azure's response to an unsupported one is to render the
line neutral without reporting anything. So the style dropdown only offers what the selected voice
can actually do, `random` picks from that same set, and a prefix asking for something unavailable
falls back to random rather than silently doing nothing. Change to a voice that can't do the style
you had selected and the control panel tells you it switched.

**Expressive voices are rarer than you'd expect, and concentrated in en-US.** Of roughly 119 English
voices, 21 support styles — and 18 of those are American. Outside the US it's `en-GB` Ryan and Sonia
and `en-IN` Neerja, and nothing else at all: every Australian, Irish, Canadian, New Zealand and South
African voice is styleless. So the voice dropdown shows each voice's style count, and each country
heading shows how many of its voices have any, letting you weigh accent against expression before
picking rather than after.

Some voices support no styles at all. Those are synthesized without a style wrapper, and the panel
shows "this voice has no speaking styles" rather than offering options that won't apply.

---

## Customizing

**Adding a fourth player** is one entry in `players.py`:

```python
"4": {
    "keyphrase": "!player4",
    "voice_name": "en-US-JennyNeural",
},
```

Add `player4-closed.png` / `player4-open.png`, restart, and add a browser source pointing at
`?player=4`. Nothing else needs to change.

**Mouth too twitchy, or barely opening?** The threshold and the minimum gap between mouth swaps
are both at the top of `templates/overlay.html`, with comments explaining which way to move them.

**Default voices per player** are the `voice_name` values in `players.py`.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| No `Logged in as` line | Token missing or expired, or the terminal was open before you set the env var |
| Bot connects but ignores you | `CHATGOD_TWITCH_CHANNEL` is wrong or wrong case |
| "Azure failed, using gTTS instead" | Bad `CHATGOD_AZURE_KEY`, or region as "East US" instead of `eastus` |
| Nothing on **Pick Random** | Pool is empty — someone must type `!player1` first |
| Overlay blank in OBS | App isn't running, or the URL has a typo. Right-click the source → *Interact* to see the page |
| Text appears, no audio | Check the browser source isn't muted in OBS's Audio Mixer |
| Mouth never closes / never opens | Adjust the threshold in `templates/overlay.html` |
| `AttributeError` from twitchio at startup | twitchio 3.x got installed — `pip install -r requirements.txt` pins it below 3 |
| 404 "Unknown player" | The `?player=` number has no entry in `players.py` |

---

## Files

| | |
|---|---|
| `PROJECT-STATE.md` | Where the project currently stands — what works, what's in flight, what wastes your time. Start here if you're picking the project back up |
| `chat_god_app.py` | Flask app, Twitch bot, socket handlers, routes |
| `config.py` | Resolves every setting: `CHATGOD_` variable, then the legacy name, then a default |
| `players.py` | Player config — the only file you edit to add or retune a player |
| `voices_manager.py` | Voice state per player, synthesis calls |
| `azure_text_to_speech.py` | Azure TTS with a gTTS fallback, and the voice/style catalog |
| `fetch_voices.py` | Asks Azure for the voice list and writes `voices.json`. Run once at setup, again whenever you want to refresh |
| `voices.default.json` | The voice catalog shipped with the repo — a real fetch, all English locales, free-tier voices. Used when you haven't run `fetch_voices.py`. Your own `voices.json` overrides it and is gitignored |
| `templates/overlay.html` | On-stream graphic, lip sync |
| `templates/control.html` | Operator dashboard |
| `audio_player.py`, `obs_websockets.py` | Legacy server-side playback and OBS filter toggling, kept for the startup chime and test scripts. Off by default (`OBS_WEBSOCKETS_ENABLED` in `players.py`) |
| `tts_test.py` | Synthesis and local playback without Twitch or a browser — checks voices and Azure credentials on their own |
| `voice_test.py` | Walks the voice and style lists, so you can hear combinations before assigning them |
| `autoplay_test.html` | Standalone check that a browser source can play audio with no user gesture. Open it as a Browser source if autoplay behaviour ever changes |
