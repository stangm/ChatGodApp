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

> **Keep the repo out of OneDrive, Dropbox or Google Drive.** A `.git` directory inside a synced
> folder produces lock files that can't be deleted, and every git command afterwards fails until you
> remove them by hand. `C:\dev\ChatGodApp` or similar. The venv doesn't have to live beside the code
> either — and note a venv can't be moved once created, since it stores its own absolute path.

### 2. Credentials — pick one of two ways

**Either** copy `config.example.json` to `config.json` and fill it in:

```json
{
  "twitch_token": "yourtokenhere",
  "twitch_channel": "yourchannel",
  "azure_key": "your-key-here",
  "azure_region": "eastus"
}
```

**Or** set them as environment variables:

```powershell
[Environment]::SetEnvironmentVariable("CHATGOD_TWITCH_TOKEN", "yourtokenhere", "User")
[Environment]::SetEnvironmentVariable("CHATGOD_TWITCH_CHANNEL", "yourchannel", "User")
[Environment]::SetEnvironmentVariable("CHATGOD_AZURE_KEY", "your-key-here", "User")
[Environment]::SetEnvironmentVariable("CHATGOD_AZURE_REGION", "eastus", "User")
```

**The file is easier** — you can see what's in it, edit it, and it works the moment you save. It's
also how you'd hand someone a machine that's ready to go. Variables are invisible, don't reach
terminals that are already open, and a wrong one fails looking like something else entirely.

You can mix them: a variable of the same name overrides the file, which makes it easy to test a
different channel without touching your config.

> `config.json` holds your token and key **in plain text**. It's gitignored, but treat it like a
> password — not in screenshots, not in shared folders. It isn't obfuscated on purpose: that would
> be fake security on a file in your own directory, and it would make it harder to check.

### 3. Getting the credentials

Generate a Twitch token at <https://twitchtokengenerator.com/> — choose **Bot Chat Token**, with
**`chat:read`** and **`chat:edit`** enabled. Copy the *Access Token*, not the refresh token.

The channel name is your channel, no URL and no `@` — case doesn't matter, it gets lowercased.

**If you used environment variables, close and reopen your terminal** — they don't reach already-open
shells. This is the single most common "it works for everyone else" failure, and it doesn't apply to
`config.json`, which is read fresh each time the app starts.

**Check:** `python -c "from config import setting; print(setting('twitch_token')[:10])"` should print
characters, not an error.

> **Upgrading from an older copy?** The unprefixed names — `TWITCH_ACCESS_TOKEN`,
> `TWITCH_CHANNEL_NAME`, `AZURE_TTS_KEY`, `AZURE_TTS_REGION` — are still read, so nothing you've
> already set breaks. The prefix exists because those names are ones any other Twitch or Azure tool
> would plausibly also use, and a collision hands your app someone else's credentials while looking
> like a bad key. The app names any legacy variable it falls back to at startup.

### 4. Azure Speech

In the [Azure portal](https://portal.azure.com): *Create a resource* → **Speech** → Create. Any
nearby region, pricing tier **F0 (Free)** — 500,000 characters/month, far more than a stream uses.

Copy Key 1 and the Region from *Keys and Endpoint* into whichever of the two you chose above. The
region must be the short form (`eastus`, `westus2`), **not** the display name — "East US" is the
single most common mistake here, and it fails looking like a bad key.

Then test Azure on its own:

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

### 5. Character art

Drop two PNGs per player in `static/characters/`, named by convention:

```
player1-closed.png    player1-open.png
player2-closed.png    player2-open.png
player3-closed.png    player3-open.png
```

Same dimensions for both, mouth closed and mouth open. Transparent backgrounds work best. To keep
files elsewhere under `static/`, add `image_closed` / `image_open` to that player's entry in
`players.py`.

### 6. OBS

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

**Double-click `start.bat`.** It finds Python, creates the virtual environment the first time,
installs what's needed, starts the app and opens the control panel. Run it again and it just starts.
Leave the window open while you stream; closing it stops Chat God.

If it can't do something it says which thing and what to do about it, and keeps the window open so
you can read it. Double-clicking it while it's already running just reopens the control panel.

<details>
<summary>Running it by hand instead</summary>

```powershell
.\.venv\Scripts\Activate.ps1
python chat_god_app.py
```

Equivalent, and better when you're changing code — you see the output directly and can Ctrl-C it.
`start.bat` will reuse a `.venv` or `venv` beside the app, or whatever `CHATGOD_VENV` points at.

</details>

Open **<http://127.0.0.1:5000/control>** in a normal browser — this is your operator dashboard.
Don't add it to OBS; it's not meant for stream.

**The block at the top is a pre-flight check.** Twitch login, Azure credentials, monthly character
quota, the voice catalogue, and how many OBS browser sources are connected. All five fail silently
otherwise, and all five first show themselves mid-stream disguised as something else. **Copy
diagnostics** puts the whole picture on the clipboard with secrets redacted, so "paste me that"
replaces a diagnostic conversation.

From the control panel you can assign a chatter to each player slot, pick voices and styles, and
toggle TTS per player, all live.

**"One speaker at a time"** queues messages so characters don't talk over each other, with a small
overlap so it sounds like conversation rather than a walkie-talkie. Off by default — at three
players overlap reads as liveliness, and it's at five or six that it becomes noise. Busy chat builds
a backlog, so the oldest waiting message is dropped rather than read a minute late. The tuning
constants (`SPEECH_OVERLAP_MS`, `SPEECH_QUEUE_MAX`) are at the top of `chat_god_app.py`.

**"In the show"** takes a slot out entirely: nothing drawn, nothing spoken, its keyphrase ignored,
and no Azure characters spent on it. That's what lets you build one OBS scene for six players and
run a four-player night without the app queueing chatters for characters nobody can see. Layout
stays an OBS job — a second scene — because fixed browser sources can't re-centre when two go dark.

Switching a slot off **keeps its pool**, so re-enabling doesn't make everyone type the keyphrase
again. It's distinct from unticking TTS (silent but still on screen) and from an empty character
(invisible but still speaking).

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
can actually do, and anything unavailable falls back to **none** — the line is read plainly rather
than in some other emotion nobody asked for. Change to a voice that can't do the style you had
selected and the control panel tells you it switched.

**`none` and `random` are different.** `none` means no expression at all, the voice exactly as Azure
ships it. `random` picks a different style each message, and is only offered on voices that have
styles to pick from. If you want an expressive voice delivered straight — Aria without one of her 16
moods on every line — that's `none`.

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

**Naming your characters** — open **<http://127.0.0.1:5000/setup/characters>**, or the *characters*
link in the control panel header. Create a character, upload its two PNGs and give it a voice, then
assign it to a slot on **<http://127.0.0.1:5000/setup>**. The art swaps on stream immediately — no restart, no browser-source refresh.

Uploads are checked before anything is written: both frames must be PNG, under 8MB, and **the same
dimensions as each other**. Mismatched frames make the character jump every time it speaks, which on
stream looks like a bug rather than like mismatched art. Files are named after the character id and
overwrite in place, so re-uploading is safe.

Changing art can change the browser source height, since it's derived from the art's aspect ratio —
check the size the control panel reports afterwards.

*Save this voice as the default* on a slot writes whatever you've currently got selected back onto
the character, which is how a good mid-stream discovery survives instead of evaporating.

Deleting a character is refused while it's assigned to a slot, and never touches the PNGs.

<details>
<summary>Editing <code>characters.json</code> by hand instead</summary>

Copy `characters.example.json` to `characters.json`. A character has a display name that shows on
stream, its own art, a default voice and style, and three switches for what appears beneath it:

```json
"wizard": {
  "display_name": "Henry Potter",
  "art_closed": "characters/wizard-closed.png",
  "art_open":   "characters/wizard-open.png",
  "default_voice": "en-US-DavisNeural",
  "show_character_name": true,
  "show_chatter_name": true,
  "show_message": false
}
```

Assign it with `"slots": { "1": { "character": "wizard" } }`. Slots you don't mention keep using
`players.py` and the `player<N>-*.png` convention, so you can convert one at a time. The file is
gitignored, and `/setup` writes to this same file — hand-edits and the screen are interchangeable.

</details>

Both names are drawn **over** the lower part of the art — "Henry Potter" larger, `silverstagvt`
smaller underneath. Because they sit on the art rather than below it, turning either on or off never
changes how tall the browser source needs to be, so there's nothing to resize in OBS. All three
switches are live on the control panel, so you can change what's shown mid-stream.

The message text is the exception: it's stacked below the art, so **it's the only toggle that
changes the source height.**

**Browser source size** is reported by the control panel per player and updates as you toggle. Don't
calculate it by hand.

**Mouth too twitchy, or barely opening?** The threshold and the minimum gap between mouth swaps
are both at the top of `templates/overlay.html`, with comments explaining which way to move them.

**Caption text too big or too small?** `CAPTIONS` at the top of `characters.py` — one dict, and the
only place these numbers live:

```python
CAPTIONS = {
    "character_name": {"font": 30, "box": 36},
    "chatter_name":   {"font": 18, "box": 24},
    "message":        {"font": 15, "box": 85},
}
```

`font` is the size text is drawn at when it fits; longer text is shrunk to fit rather than
overflowing. `box` is the space the line occupies — keep it above `font` by about 6 or descenders
clip. Restart and refresh the source.

Don't set these in the CSS: the overlay sizes text with a script that writes an inline `font-size`,
which beats the stylesheet, so a CSS-only edit looks like it did nothing. `overlay.css` reads these
same values as custom properties.

Raising the `message` box changes the browser source height — the names don't, since they're drawn
over the art.

**Restyling anything else** — `static/css/overlay.css`. Stylesheet URLs carry the file's timestamp,
so an edit reaches OBS on the next source refresh instead of being masked by its cache.

**Default voices per player** are the `voice_name` values in `players.py`, or `default_voice` on the
character once you have a `characters.json`.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| No `Logged in as` line | Token missing or expired, or the terminal was open before you set the env var |
| Bot connects but ignores you | `CHATGOD_TWITCH_CHANNEL` is wrong or wrong case |
| "Azure failed, using gTTS instead" | Bad `CHATGOD_AZURE_KEY`, or region as "East US" instead of `eastus` |
| Nothing on **Pick Random** | Pool is empty — someone must type `!player1` first, or the slot is switched out of the show |
| A player is missing from stream | Check *In the show* on the control panel — the panel dims when a slot is switched out |
| Overlay blank in OBS | App isn't running, or the URL has a typo. Right-click the source → *Interact* to see the page |
| Text appears, no audio | Check the browser source isn't muted in OBS's Audio Mixer |
| Mouth never closes / never opens | Adjust the threshold in `templates/overlay.html` |
| Character name doesn't appear | The character has no name on stream, or *character name* is unticked for it in `/setup` |
| Caption toggles change nothing on stream | Refresh the browser source. If it persists, check the server console prints `show_message is now False` when you click |
| Edited `characters.json` by hand, nothing changed | Restart the app. Hand edits aren't re-read while running; changes made in `/setup` apply immediately |
| `AttributeError` from twitchio at startup | twitchio 3.x got installed — `pip install -r requirements.txt` pins it below 3 |
| 404 "Unknown player" | The `?player=` number has no entry in `players.py` |

---

## Files

| | |
|---|---|
| `PROJECT-STATE.md` | Where the project currently stands — what works, what's in flight, what wastes your time. Start here if you're picking the project back up |
| `start.bat` | Double-click launcher. Finds Python, builds the venv on first run, starts the app, opens the control panel |
| `chat_god_app.py` | Flask app, Twitch bot, socket handlers, routes |
| `config.py` | Resolves every setting: `CHATGOD_` variable, then the legacy name, then a default |
| `players.py` | Player config — which slots exist, keyphrases, fallback voices |
| `characters.py` | Reads and writes `characters.json`, resolves each slot to a character, and works out the OBS browser source size |
| `characters.example.json` | Template for your own `characters.json` — names, art, default voices, caption switches. Copy it to start. Your copy is gitignored |
| `display_manager.py` | Live caption visibility per slot, what the control panel toggles |
| `usage.py` | Counts characters sent to Azure, in a gitignored `usage.json` keyed by month, so the panel can warn before the free tier's 500,000 ceiling |
| `voices_manager.py` | Voice state per player, synthesis calls |
| `azure_text_to_speech.py` | Azure TTS with a gTTS fallback, and the voice/style catalog |
| `fetch_voices.py` | Asks Azure for the voice list and writes `voices.json`. Run once at setup, again whenever you want to refresh |
| `voices.default.json` | The voice catalog shipped with the repo — a real fetch, all English locales, free-tier voices. Used when you haven't run `fetch_voices.py`. Your own `voices.json` overrides it and is gitignored |
| `templates/overlay.html` | On-stream graphic, lip sync |
| `templates/control.html` | Operator dashboard |
| `templates/setup.html` | Slot assignments |
| `templates/characters.html` | Character library, as a grid of art |
| `templates/character.html` | One character's editor — voice, captions, art upload, delete |
| `audio_player.py`, `obs_websockets.py` | Legacy server-side playback and OBS filter toggling, kept for the startup chime and test scripts. Off by default (`OBS_WEBSOCKETS_ENABLED` in `players.py`) |
| `tts_test.py` | Synthesis and local playback without Twitch or a browser — checks voices and Azure credentials on their own |
| `voice_test.py` | Walks the voice and style lists, so you can hear combinations before assigning them |
| `autoplay_test.html` | Standalone check that a browser source can play audio with no user gesture. Open it as a Browser source if autoplay behaviour ever changes |
