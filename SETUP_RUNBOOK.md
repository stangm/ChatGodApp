# ChatGodApp — first-run setup (Windows)

The README is the reference: what to install, what the URLs are, how to add a player. This is the
walkthrough — the same ground in order, with a check you can run at the end of each stage so you
find out *where* something broke rather than staring at a silent overlay.

If you've set this up before, use the README and skip this.

---

## Before you start: things that will bite you

1. **Environment variables don't reach terminals that are already open.** You'll set three of them
   below. Each time, close PowerShell and reopen it. This is the single most common "it worked for
   everyone else" failure, and it looks exactly like a bad token.
2. **`TWITCH_CHANNEL_NAME` is hardcoded** on line 21 of `chat_god_app.py`. Change it or the bot
   reads someone else's chat and ignores you entirely.
3. **Testing the overlay in a normal browser tab gives you silence.** Chrome and Firefox block
   autoplay until you interact with the page; OBS browser sources don't. The page logs
   `Autoplay blocked` to the console and carries on. Not a bug — judge audio in OBS, not in a tab.
4. **Python 3.13+ may have no wheel for `azure-cognitiveservices-speech`.** If pip can't find one,
   install 3.12 alongside and use `py -3.12` in place of `python` throughout.

Three gotchas from earlier versions of this document are now fixed in the code and no longer apply:
the `pygame`/`pygame_ce` clash (`requirements.txt` now lists only `pygame-ce`), unpinned
dependencies (all pinned), and OBS having to be open before the app would start (it no longer
connects to OBS at all by default).

---

## Stage 1 — Python environment

**1.1 Check your version.** PowerShell, in the repo folder:

```powershell
cd $HOME\OneDrive\scripts\ChatGodApp
python --version
```

Anything 3.9–3.12 is fine. See gotcha #4 for 3.13+.

**1.2 Make a virtual environment.** Keeps this project's packages out of your system Python.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the activate script:
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

> **OneDrive note:** a `.venv` inside OneDrive will sync thousands of files for no benefit. It's in
> `.gitignore` already, but also right-click the folder → *Always keep on this device* → off, or put
> the venv outside OneDrive entirely (`python -m venv C:\venvs\chatgod`).

**1.3 Install dependencies.**

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Versions are pinned, so this resolves the same way today and in six months. If you ever unpin them,
note that `twitchio` must stay below 3.0 — the code uses the 2.x `commands.Bot(token=...,
initial_channels=...)` API and 3.x won't start.

**Check:** `python -c "import pygame, twitchio, flask, azure.cognitiveservices.speech; print('ok')"`

**1.4 Optional but recommended: ffmpeg.** `pydub` needs it for the gTTS fallback path (mp3 → wav).
You only hit that path when Azure fails — which is exactly when you don't want a second crash.
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

Paste the token exactly as the generator gave it. The `oauth:` prefix doesn't matter either way —
twitchio does `token.replace("oauth:", "")` on input and re-adds it when authenticating, so bare and
prefixed tokens are identical on the wire. **Close and reopen PowerShell** (gotcha #1).

**2.3 Point the bot at your channel.** Edit line 21 of `chat_god_app.py`:

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

**3.4 Test TTS on its own** — the file has a built-in harness, and this isolates Azure from Twitch,
the browser and OBS entirely:

```powershell
.\.venv\Scripts\Activate.ps1
python azure_text_to_speech.py
```

You should hear a test line through your speakers, then get a prompt to type more. **If you hear
"Azure failed, using gTTS instead"**, your key or region is wrong — the code swallows the real Azure
error, so check both carefully rather than debugging elsewhere. Ctrl+C to exit.

Generated wavs go to `%TEMP%\chatgod_audio`, not the project folder. The live app caps that
directory at 50 clips and deletes the oldest as it goes; this standalone test doesn't, so if you run
it a lot you can empty the folder by hand.

**3.5 Build the voice list.** Only once Azure is confirmed working, since this call uses the same
credentials:

```powershell
python fetch_voices.py
```

It asks Azure which voices your subscription offers and which speaking styles each supports, then
writes `voices.json`. With no arguments it pulls **every English locale** — en-GB, en-AU, en-IE,
en-IN, en-ZA and the rest, not just en-US. The control panel groups the dropdown by country so the
list stays usable.

Narrow it with an argument. Without a region means the whole language, with a region means that
locale only:

```powershell
python fetch_voices.py en-US      # just American
python fetch_voices.py en-GB en-AU
python fetch_voices.py --all      # every locale Azure has, several hundred voices
```

**It leaves out premium voices, and you want that.** In `en-US` alone Azure returns around 124
voices, of which roughly 70 are HD (`DragonHD`, `Multitalker`) or Azure OpenAI (the Turbo
Multilingual set). The free F0 tier covers prebuilt *non-HD, non-AOAI* neural voices only, so those
bill separately at a higher rate. Anyone in your chat can trigger synthesis, so a premium voice
sitting in the dropdown is a billing accident waiting to happen. `--include-premium` if you're on a
paid tier and want them.

Of the ~53 standard `en-US` voices, about 18 support speaking styles — including every one the app
shipped with. The rest synthesize fine, just without expression. Other English locales have fewer
styled voices; the script prints the breakdown per locale when it finishes.

Skipping this isn't fatal: the app falls back to a built-in list of eight voices and assumes all
nine styles work on each. That assumption is wrong for some voices, and wrong in the quiet way —
Azure renders an unsupported style neutral and reports nothing. The control panel shows a warning
until you've run the fetch.

**Check:** the script prints how many voices it found and how many support styles. The control panel
warning should be gone next time you start the app.

> This stage plays through the *server's* speakers via pygame, which is the one remaining local
> playback path (it's also what the startup chime uses). Live messages don't work this way — they
> play in the browser. So hearing audio here confirms Azure, not the overlay.

---

## Stage 4 — Character art

Two PNGs per player in `static/characters/`, named by convention:

```
player1-closed.png    player1-open.png
player2-closed.png    player2-open.png
player3-closed.png    player3-open.png
```

Mouth closed and mouth open, **same dimensions** for both — the page swaps between them in place, so
differing sizes make the character jump. Transparent backgrounds sit best over gameplay.

To keep art elsewhere under `static/`, add `image_closed` / `image_open` to that player's entry in
`players.py` and they'll override the convention.

**Check:** with the app running (Stage 6), `http://127.0.0.1:5000/overlay?player=1` in a browser
should show the character. Silent — see gotcha #3 — but visible.

---

## Stage 5 — OBS

Add one **Browser** source per player:

| Source | URL |
|---|---|
| Player 1 | `http://127.0.0.1:5000/overlay?player=1` |
| Player 2 | `http://127.0.0.1:5000/overlay?player=2` |
| Player 3 | `http://127.0.0.1:5000/overlay?player=3` |

Set the width and height to roughly your character art's dimensions, then position and scale each
source independently on the canvas.

That's the entire OBS setup. No plugins, no audio capture source, no filters, no websocket password,
and OBS doesn't need to be open for the app to run.

> **Trade-off — one source or three?** `http://127.0.0.1:5000/overlay` with no `?player=` renders
> all three in a row in a single source, which is less to manage but locks their relative positions.
> Separate sources cost two extra setup steps and let you put each character wherever you want.

> **Audio:** the TTS comes out of the browser sources natively. Leave *Control audio via OBS*
> unchecked unless you specifically want TTS on its own mixer channel — ticking it routes audio
> through OBS's mixer, where it can be muted independently of your desktop audio.

**Check:** browser sources added, app not yet running — they'll be blank until it is.

---

## Stage 6 — Run it

```powershell
.\.venv\Scripts\Activate.ps1
python chat_god_app.py
```

Expect a spoken "Chat God App is now running!" and a `Logged in as | yourbotname` line. Then open
**<http://127.0.0.1:5000/control>** in a normal browser. That's your operator dashboard — don't add
it to OBS.

**Smoke test, in this order.** Each step isolates one thing, so stop at the first failure:

1. In your Twitch chat, type `!player1` from your own account.
2. Hit **Pick Random** under player 1 — your name should appear on the control panel and the overlay.
3. Type anything in chat — it should appear on the overlay and be read aloud, mouth moving.
4. Change the voice dropdown, type again, confirm the voice changed.
5. Type `(angry) hello` — confirm the style prefix is picked up.
6. Untick the TTS checkbox, type again — text should appear silently.

If step 3 gives you text but no sound, check you're listening to OBS and not a browser tab.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| No `Logged in as` line | Token missing/expired, or the terminal was open before you set the env var |
| Bot connects but ignores you | `TWITCH_CHANNEL_NAME` still wrong, or wrong case |
| "Azure failed, using gTTS instead" | Bad `AZURE_TTS_KEY`, or region as "East US" instead of `eastus` |
| Nothing happens on **Pick Random** | Empty pool — someone must type `!player1` first. The code silently swallows this |
| Overlay blank in OBS | App isn't running, or the URL has a typo. Right-click the source → *Interact* to see the page and its errors |
| Overlay shows text but never speaks | You're listening to a browser tab, not OBS (gotcha #3), or the source is muted in OBS's Audio Mixer |
| Mouth flaps on a timer instead of matching speech | WebAudio couldn't start; the page falls back to a fixed flap. Check the source's console via *Interact* |
| Mouth never closes, or barely opens | Threshold needs adjusting — top of `templates/overlay.html`, with comments |
| Style dropdown has fewer options than expected | Working as intended — it only lists styles the selected voice supports. Some voices support none |
| Control panel warns about the built-in voice list | `fetch_voices.py` hasn't been run, or it failed and `voices.json` was never written |
| `fetch_voices.py` says it can't retrieve voices | Same key/region problem as stage 3.4 — the region must be `eastus`, not "East US" |
| 404 "Unknown player" | The `?player=` number has no matching entry in `players.py` |
| `AttributeError` from twitchio on startup | twitchio 3.x got installed somehow; `pip install -r requirements.txt` pins it below 3 |
| Character jumps when the mouth opens | The two PNGs aren't the same dimensions |

---

Sources: [Azure free tier characters](https://learn.microsoft.com/en-us/answers/questions/1338662/what-happens-when-i-run-out-of-free-characters-on)
