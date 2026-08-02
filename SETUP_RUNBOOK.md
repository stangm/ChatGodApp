# ChatGodApp — first-run setup (Windows)

You have Python and OBS already. Remaining: dependencies, Twitch token, Azure Speech, OBS websocket config.
Work through this in order — each stage has a check you can run before moving on.

---

## Before you start: four things that will bite you

I found these by reading the repo and dry-running the dependency install. None are your fault; they're
in the upstream code.

1. **`requirements.txt` installs both `pygame` and `pygame_ce`.** They provide the same `pygame` module
   and clobber each other — whichever installs second wins. Install without `pygame_ce` (step 1.3).
2. **Nothing is version-pinned.** A dry run today resolves to `twitchio 2.10.0`, which matches the 2.x
   API the code uses (`commands.Bot(token=..., initial_channels=...)`). Pin it once it works, or a
   future install could silently pull an incompatible major version.
3. **OBS must be running *before* you launch the app.** `OBSWebsocketsManager()` is a class attribute of
   `TTSManager`, so it connects at *import* time — before Flask even starts. No OBS = a 10-second pause
   and `sys.exit()`, with the confusing "PANIC!!" message.
4. **`TWITCH_CHANNEL_NAME` is hardcoded to `'dougdoug'`** on line 13 of `chat_god_app.py`. Change it or
   you'll be reading DougDoug's chat.

---

## Stage 1 — Python environment

**1.1 Check your version.** PowerShell, in the repo folder:

```powershell
cd $HOME\OneDrive\scripts\ChatGodApp
python --version
```

Anything 3.9–3.12 is fine. On 3.13+ you may hit missing wheels for `azure-cognitiveservices-speech`;
if so, install 3.12 alongside and use `py -3.12` in place of `python` below.

**1.2 Make a virtual environment.** Keeps this project's packages out of your system Python.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the activate script:
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

> **OneDrive note:** a `.venv` inside OneDrive will sync thousands of files for no benefit. Either add
> `.venv/` to `.gitignore` **and** right-click the folder → *Always keep on this device* → off, or put
> the venv outside OneDrive entirely (`python -m venv C:\venvs\chatgod`).

**1.3 Install dependencies, minus the pygame conflict:**

```powershell
python -m pip install --upgrade pip
python -m pip install azure-cognitiveservices-speech Flask Flask-SocketIO gTTS mutagen `
    obs-websocket-py pydub pytz soundfile twitchio pygame-ce
```

That's `requirements.txt` with `pygame_ce` dropped. Don't use `-r requirements.txt` directly until
that line is removed.

**Check:** `python -c "import pygame, twitchio, flask, azure.cognitiveservices.speech; print('ok')"`

**1.4 Optional but recommended: ffmpeg.** `pydub` needs it for the gTTS fallback path (mp3 → wav). You
only hit that path when Azure fails — which is exactly when you don't want a second crash.
`winget install ffmpeg`, then reopen the terminal.

---

## Stage 2 — Twitch

**2.1 Generate an access token** at <https://twitchtokengenerator.com/>. Choose *Bot Chat Token*, and
make sure **`chat:read`** and **`chat:edit`** are both enabled. Copy the **Access Token** (not the
refresh token).

**2.2 Set it as an environment variable.** Permanent, so it survives reboots:

```powershell
[Environment]::SetEnvironmentVariable("TWITCH_ACCESS_TOKEN", "yourtokenhere", "User")
```

Paste the token exactly as the generator gave it. The prefix doesn't matter either way — twitchio does
`token.replace("oauth:", "")` on input and re-adds it when authenticating, so bare and prefixed tokens
are identical on the wire. **Close and reopen PowerShell** — env vars
don't apply to already-open terminals. This is the single most common "it worked for everyone else"
failure.

**2.3 Point the bot at your channel.** Edit line 13 of `chat_god_app.py`:

```python
TWITCH_CHANNEL_NAME = 'yourchannelname'   # lowercase, no URL, no @
```

**Check:** `python -c "import os; print(os.getenv('TWITCH_ACCESS_TOKEN')[:10])"` — should print the
first characters of your token, not `None`.

---

## Stage 3 — Azure Speech

**3.1 Create the resource.** In the [Azure portal](https://portal.azure.com): *Create a resource* →
search **Speech** → Create. Pick any region near you and select pricing tier **F0 (Free)** — that's
500,000 characters/month of neural TTS, which is far more than a stream will use.

**3.2 Copy Key 1 and the Region** from the resource's *Keys and Endpoint* page.

**3.3 Set both variables** — the region must be the short form (`eastus`, `westus2`), **not** the
display name ("East US"):

```powershell
[Environment]::SetEnvironmentVariable("AZURE_TTS_KEY", "your-key-here", "User")
[Environment]::SetEnvironmentVariable("AZURE_TTS_REGION", "eastus", "User")
```

Reopen PowerShell again.

**3.4 Test TTS on its own** — the file has a built-in harness, and this isolates Azure from Twitch and
OBS entirely:

```powershell
.\.venv\Scripts\Activate.ps1
python azure_text_to_speech.py
```

You should hear a test line, then get a prompt to type more. **If you hear "Azure failed, using gTTS
instead"**, your key or region is wrong — the code swallows the real Azure error, so check both
carefully rather than debugging elsewhere. Ctrl+C to exit.

This step leaves `_Msg*.wav` files in the folder; they're safe to delete.

---

## Stage 4 — OBS

**4.1 Enable websockets.** OBS → *Tools* → *WebSocket Server Settings* → check **Enable WebSocket
server**, port **4455**, password **`TwitchChat9`** (that exact value — it's hardcoded in
`websockets_auth.py`).

**4.2 Install the Move plugin** from <https://obsproject.com/forum/resources/move.913/> and restart OBS.

**4.3 Match the names the code expects.** `voices_manager.py` calls
`set_filter_visibility("Line In", "Audio Move - DnD Player N", ...)`. So you need an audio source named
exactly **`Line In`** carrying an **Audio Move** filter named exactly **`Audio Move - DnD Player 1`**
(and 2, 3).

For a first test you have two options:

- **Skip the animation for now** — edit `voices_manager.py` and comment out the six
  `self.obswebsockets_manager.set_filter_visibility(...)` lines. TTS and the overlay work fine without
  them. You still need OBS *open* (see gotcha #3) but the source and filters don't have to exist.
- **Do it properly** — walk through 4.4 to 4.9 below.

**Check:** OBS open, websocket server enabled, app not yet running.

---

### How the animation actually works

Worth understanding before you click anything, because the design is not obvious.

The **Audio Move** filter is an *audio* filter. You attach it to an audio source, and it continuously
reads that source's volume level and uses it to drive some property of a *different* source — say, the
vertical position of a character image. Loud audio = image moves. Silence = image rests.

Here, **all three filters live on the same audio source** (`Line In`) and listen to the same TTS audio.
What makes only the right character bob is that the app **enables and disables the filters**: when
player 2's message plays, it flips `Audio Move - DnD Player 2` on, plays the audio, then flips it off.
The other two filters stay disabled and their images sit still.

So: one audio source, three filters on it, three image targets, and the app is just a switchboard
toggling which filter is live.

### 4.4 Create the audio source named `Line In`

The filter needs an audio source carrying the TTS audio. pygame plays through your **default Windows
output device**, so OBS's Desktop Audio capture will pick it up.

1. In the **Sources** panel, check whether you already have a Desktop Audio source. (If it only appears
   in the *Audio Mixer* panel and not in Sources, it's the global one from Settings → Audio — add a
   fresh one instead, as below.)
2. **+** → **Audio Output Capture** → name it exactly **`Line In`** → OK.
3. Device: **Default**, or pick your speakers/headphones explicitly.

> Name it `Line In` exactly — capital L, capital I, one space. This is the string hardcoded in
> `voices_manager.py`. If OBS says the name is taken, the source already exists somewhere; rename that
> one instead (double-click → Rename).

**Trade-off:** Desktop Audio captures *everything* — game audio, Discord, browser. Since the filter is
only enabled while TTS plays, stray audio mostly doesn't matter, but anything playing *during* a TTS
message will also drive the animation. Living with it is fine to start. The clean fix is routing TTS to
a separate virtual audio device (VB-Cable) and capturing only that — worth doing later if the bobbing
looks jittery.

### 4.5 Add your three character images

**+** → **Image** for each player, and position them where you want on canvas. Any PNG works for
testing. Name them something you'll recognise in a dropdown — `Player 1 Image`, etc.

These must be in the **same scene** as `Line In` for the filter to find them.

### 4.6 Add the three Audio Move filters

Right-click **`Line In`** → **Filters**. Audio Move appears under **Audio Filters** (the lower box), not
Effect Filters — if it's not listed there, the plugin didn't load or your OBS is older than the plugin
requires (see 4.2).

Click **+** under Audio Filters → **Audio Move** → name it exactly:

```
Audio Move - DnD Player 1
```

Repeat for `Audio Move - DnD Player 2` and `Audio Move - DnD Player 3`. Spaces and capitalisation must
match — the app addresses these filters by name and a typo means silence, not an error.

### 4.7 Configure one filter

Exact field labels shift between plugin versions, so match by function rather than hunting for exact
wording. With `Audio Move - DnD Player 1` selected, you're setting three things:

1. **What it controls** — a *Source* (or *Target*) dropdown listing the sources in your scene. Pick
   `Player 1 Image`. Then a property selector: choose **Transform**, and within it something like
   *Position Y* (up/down bob) or *Scale* (pulse). Position Y is the classic talking-head look.
2. **The value range** — two numbers mapping quiet→loud onto the property. For Position Y, set the
   first to your image's resting Y and the second maybe 20–30 px higher. Note OBS Y increases
   *downward*, so a *smaller* second number moves the image up.
3. **Threshold** — the volume floor below which nothing happens. The default is usually fine; raise it
   if the image twitches during silence.

Then duplicate the settings for filters 2 and 3, each pointing at its own image.

### 4.8 Leave all three filters **disabled**

This is the step people miss. Each filter has a checkbox / eye icon next to its name in the filter
list — **uncheck all three**. The app turns them on and off. If you leave them enabled, every character
bobs on every message and it'll look broken.

### 4.9 Verify before wiring up the app

With OBS still open and the filters *temporarily* enabled, play any sound on your PC — the images
should move. That confirms the filter chain works. Then **disable all three again** and move to Stage 5.

If nothing moves: `Line In` isn't capturing the audio (check its level meter in the Audio Mixer bounces
when sound plays), or the filter is pointed at the wrong source, or your value range is too narrow to
see.

---

## Stage 5 — Run it

With OBS open and your venv active:

```powershell
python chat_god_app.py
```

Expect, in order: `Connected to OBS Websockets!`, a spoken "Chat God App is now running!", `threading`,
and `Logged in as | yourbotname`. Then open <http://127.0.0.1:5000> in a browser.

**Smoke test, in this order:**

1. In your Twitch chat, type `!player1` from your own account.
2. Hit **Pick Random** under player 1 — your name should appear in the overlay box.
3. Type anything in chat — it should appear on the overlay and be read aloud.
4. Change the voice dropdown, type again, confirm the voice changed.
5. Type `(angry) hello` — confirm the style prefix is picked up.
6. Untick the TTS checkbox, type again — text should appear silently.

Once that works, add the page as an OBS **Browser Source** pointed at `http://127.0.0.1:5000`.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| "PANIC!! COULD NOT CONNECT TO OBS" | OBS not open, websocket server off, wrong port, or password ≠ `TwitchChat9` |
| Exits instantly, no output | Same as above — the message scrolls past fast, and it `sys.exit()`s after 10s |
| "Azure failed, using gTTS instead" | Bad `AZURE_TTS_KEY`, or region as "East US" instead of `eastus` |
| No `Logged in as` line | Token missing/expired, or terminal opened before you set the env var |
| Bot connects but ignores you | `TWITCH_CHANNEL_NAME` still `'dougdoug'`, or wrong case |
| Nothing happens on **Pick Random** | Empty pool — someone must type `!player1` first. The code silently swallows this |
| `AttributeError` from twitchio on startup | twitchio 3.x got installed; `pip install "twitchio<3"` |
| Text appears but no sound | pygame using the wrong output device; check Windows volume mixer for python.exe |

---

## Before you commit anything

`git status` currently shows **all 11 files as modified** — but `git diff --stat` shows 1065 insertions
and 1065 deletions, i.e. every line "changed". That's CRLF line-ending conversion, not real edits.

If you commit as-is, every file becomes a full rewrite in history and the diff is useless for review.
Fix before your first commit:

```powershell
git config core.autocrlf true
git checkout -- .          # discards the line-ending-only changes
```

Then re-apply your two real edits (channel name, and the OBS lines if you commented them out) and
`git diff` will show just those.

---

Sources: [Azure free tier characters](https://learn.microsoft.com/en-us/answers/questions/1338662/what-happens-when-i-run-out-of-free-characters-on)
