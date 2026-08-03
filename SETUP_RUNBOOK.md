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
2. **Forgetting `CHATGOD_TWITCH_CHANNEL`** means the bot reads someone else's chat and ignores you
   entirely. It falls back to a hardcoded channel when the variable is unset, and warns loudly at
   startup — read the first few lines of output.
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
cd C:\dev\ChatGodApp
python --version
```

> **Put the repo somewhere that isn't synced** — `C:\dev\` rather than OneDrive, Dropbox or Google
> Drive. A `.git` directory inside a synced folder causes lock files that can't be deleted, which
> blocks git commands until you remove them by hand. This project learned that the slow way.

Anything 3.9–3.12 is fine. See gotcha #4 for 3.13+.

**1.2 Make a virtual environment.** Keeps this project's packages out of your system Python.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the activate script:
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

> **A venv can't be moved once created** — `pyvenv.cfg` and the `Scripts\*.exe` shims hold its own
> absolute path, so relocating the folder breaks it. If you want it elsewhere, create it there:
> `python -m venv C:\venvs\chatgod`. It doesn't need to live beside the code.

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

> **Already have the old variables set?** Leave them. The unprefixed names —
> `TWITCH_ACCESS_TOKEN`, `TWITCH_CHANNEL_NAME`, `AZURE_TTS_KEY`, `AZURE_TTS_REGION` — are still read
> as a fallback, so an existing install keeps working and you can migrate whenever. The app names
> every legacy variable it falls back to at startup.
>
> The prefix is there because those names are ones any other Twitch or Azure tool would plausibly
> also pick. If one does, whichever tool reads the variable gets the other's credentials, and the
> failure looks like a bad key rather than a name clash — which is a bad thing to debug mid-stream.

**2.1 Generate an access token** at <https://twitchtokengenerator.com/>. Choose *Bot Chat Token*, and
make sure **`chat:read`** and **`chat:edit`** are both enabled. Copy the **Access Token** (not the
refresh token).

**2.2 Set it as an environment variable.** Permanent, so it survives reboots:

```powershell
[Environment]::SetEnvironmentVariable("CHATGOD_TWITCH_TOKEN", "yourtokenhere", "User")
```

Paste the token exactly as the generator gave it. The `oauth:` prefix doesn't matter either way —
twitchio does `token.replace("oauth:", "")` on input and re-adds it when authenticating, so bare and
prefixed tokens are identical on the wire. **Close and reopen PowerShell** (gotcha #1).

**2.3 Point the bot at your channel.** Also an environment variable — no source file to edit:

```powershell
[Environment]::SetEnvironmentVariable("CHATGOD_TWITCH_CHANNEL", "yourchannel", "User")
```

Your channel, no URL and no `@`. Case doesn't matter; the app lowercases it, because twitchio
matches channels case-sensitively and typing the display name is the usual slip.

Reopen PowerShell again.

**Check:** both variables should come back non-empty:

```powershell
python -c "from config import setting; print(setting('twitch_token')[:10], setting('twitch_channel'))"
```

If either prints empty or `None`, the terminal predates the variable. The app also warns at startup
about either one being unset, and prints which channel it's actually reading.

---

## Stage 3 — Azure Speech

**3.1 Create the resource.** In the [Azure portal](https://portal.azure.com): *Create a resource* →
search **Speech** → Create. Pick any region near you and select pricing tier **F0 (Free)** — that's
500,000 characters/month of neural TTS, which is far more than a stream will use.

**3.2 Copy Key 1 and the Region** from the resource's *Keys and Endpoint* page.

**3.3 Set both variables** — the region must be the short form (`eastus`, `westus2`), **not** the
display name ("East US"):

```powershell
[Environment]::SetEnvironmentVariable("CHATGOD_AZURE_KEY", "your-key-here", "User")
[Environment]::SetEnvironmentVariable("CHATGOD_AZURE_REGION", "eastus", "User")
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

Skipping this isn't fatal. The repo ships `voices.default.json` — a real fetch covering every
English locale, free-tier voices only — and the app falls back to it, so a fresh clone gets accurate
voices and real style lists with no Azure account at all. Running the fetch yourself gets you the
current catalogue (Azure's moves) and your own choice of locales.

**Check:** the script prints how many voices it found and how many support styles. The control panel
notes which catalogue it's using; that note disappears once your own `voices.json` exists.

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

**The control panel tells you the size.** Each player's block shows its source URL and the exact
dimensions, with a width you can change and a copy button. Use those numbers rather than guessing —
too short clips the message box, and the right height depends on which captions you have switched on.

Then position and scale each source independently on the canvas.

> **Only the message text changes the size.** Both names are drawn over the art, so toggling them
> needs no resizing. Turning the message on or off does, and the panel's number updates as you click.
> The art is anchored to the top of the source, so a source that's too tall only leaves transparent
> space at the bottom — your character doesn't move.

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

**Double-click `start.bat`.** It handles the venv, the dependencies and the browser. Everything in
stage 1 that you did by hand, it does for you on a machine that hasn't been set up yet — so once
credentials are in place, this is the only step anyone needs day to day.

Running by hand is equivalent and better when you're changing code:

```powershell
.\.venv\Scripts\Activate.ps1
python chat_god_app.py
```

Expect a spoken "Chat God App is now running!" and a `Logged in as | yourbotname` line. Then open
**<http://127.0.0.1:5000/control>** in a normal browser. That's your operator dashboard — don't add
it to OBS.

**Read the block at the top of the panel before every stream.** Five rows, green when they're fine:

```
Twitch    connected as silverstagbot, reading #silverstagvt
Azure     key and region working
Quota     18,400 of 500,000 characters this month
Voices    119 loaded from Azure, 21 with styles
Overlay   2 browser sources connected (player 1, 2)
```

Every one of those fails silently and only announces itself mid-stream — and each looks like
something else when it does. A logged-out bot looks like quiet chat. A rejected Azure key sounds like
the voice changed. An exhausted monthly quota sounds like TTS breaking for no reason. A mistyped
browser source URL looks like an empty rectangle.

*Overlay* stays amber until OBS is open with the sources loaded, so it's the row that tells you your
URLs are actually right.

If something is wrong and the row doesn't explain it, hit **Copy diagnostics** and paste that
somewhere useful. It contains versions, which settings are set (never their values), and the current
status — no keys or tokens, so it's safe to paste into a chat.

> **Make a desktop shortcut to `start.bat`** for whoever streams with this. Right-click it → *Send
> to* → *Desktop (create shortcut)*. That's the difference between "run the app" being a task and
> being a double-click.

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
| Bot connects but ignores you | `CHATGOD_TWITCH_CHANNEL` still wrong, or wrong case |
| "Azure failed, using gTTS instead" | Bad `CHATGOD_AZURE_KEY`, or region as "East US" instead of `eastus` |
| Nothing happens on **Pick Random** | Empty pool — someone must type `!player1` first. The code silently swallows this |
| Overlay blank in OBS | App isn't running, or the URL has a typo. Right-click the source → *Interact* to see the page and its errors |
| Overlay shows text but never speaks | You're listening to a browser tab, not OBS (gotcha #3), or the source is muted in OBS's Audio Mixer |
| Mouth flaps on a timer instead of matching speech | WebAudio couldn't start; the page falls back to a fixed flap. Check the source's console via *Interact* |
| Mouth never closes, or barely opens | Threshold needs adjusting — top of `templates/overlay.html`, with comments |
| Style dropdown has fewer options than expected | Working as intended — it only lists styles the selected voice supports. Some voices support none |
| Control panel says it's using the shipped voice list | `fetch_voices.py` hasn't been run, or it failed and `voices.json` was never written. Harmless — that list is real data, just possibly out of date |
| Control panel says no catalogue found | `voices.default.json` is missing from the repo. Restore it, or run `fetch_voices.py` |
| `fetch_voices.py` says it can't retrieve voices | Same key/region problem as stage 3.4 — the region must be `eastus`, not "East US" |
| 404 "Unknown player" | The `?player=` number has no matching entry in `players.py` |
| `AttributeError` from twitchio on startup | twitchio 3.x got installed somehow; `pip install -r requirements.txt` pins it below 3 |
| Character jumps when the mouth opens | The two PNGs aren't the same dimensions |

---

Sources: [Azure free tier characters](https://learn.microsoft.com/en-us/answers/questions/1338662/what-happens-when-i-run-out-of-free-characters-on)
