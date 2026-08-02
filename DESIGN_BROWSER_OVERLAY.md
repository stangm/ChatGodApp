# Design: move animation into the browser source

**Goal.** Reduce OBS setup from ~20 manual steps to "add a browser source, paste a URL" — per player.
Target user is comfortable with OBS but will not edit Python.

**Model.** Fugi's [Discord Reactive Images](https://reactive.fugi.tech): the page does the work, OBS just
displays a rectangle.

---

## Where the work lives now vs. after

| Concern | Today | After |
|---|---|---|
| Character images | OBS image sources (2 per player) | `<img>` in the overlay page |
| Mouth animation | Move plugin filter, threshold-tuned | CSS class swap driven by WebAudio |
| Which player animates | Python toggles filters by name over websockets | Page only listens for its own player's events |
| Audio playback | pygame on the server, blocking | `<audio>` in the browser |
| Audio into OBS | VB-Cable + per-app routing + monitoring | Browser source audio, native |
| Per-player setup | 2 images + 1 filter + exact names | 1 browser source + URL |

Deleted along the way: the Move plugin, VB-Cable, the websocket password, threshold tuning, the
`time.sleep(file_length)` that blocks the bot, and the `sys.exit()` when OBS isn't running.

---

## Architecture

One browser source per player:

```
http://127.0.0.1:5000/overlay?player=1
http://127.0.0.1:5000/overlay?player=2
...
```

Each is positioned and scaled independently on the OBS canvas, so you keep the compositing freedom you
have today. The page subscribes to socket events and ignores any whose `user_number` isn't its own.

Server flow when a chosen player sends a message:

1. twitchio receives the message.
2. Azure synthesizes a wav to a temp directory.
3. Server emits `speak` with the text and a URL to the audio.
4. Browser loads the audio, plays it, and animates the mouth from the live waveform.
5. Server does **not** block — it returns immediately and is ready for the next message.

### Socket payload

```python
socketio.emit("speak", {
    "user_number": "1",
    "current_user": "someviewer",
    "message": "roll for initiative",
    "audio_url": f"/audio/{token}.wav",
})
```

### Audio route

Serve the file rather than embedding it in the socket frame — smaller messages, and the browser gets
normal streaming and caching.

```python
@app.route("/audio/<token>.wav")
def audio(token):
    path = AUDIO_CACHE.get(token)          # token -> temp file path
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="audio/wav")
```

`AUDIO_CACHE` is a bounded dict (say 50 entries) that deletes files as they age out. This also fixes the
current `_Msg*.wav` accumulation — today those files pile up in the repo root because the filename is
built from `hash(text)`, which changes every run.

---

## Lip sync

The browser plays the audio, so it can analyse it directly. No server-side envelope, no threshold
guessing, and sync is exact because it's one clock.

```js
const audio = new Audio(msg.audio_url);
const ctx = new AudioContext();
const src = ctx.createMediaElementSource(audio);
const analyser = ctx.createAnalyser();
analyser.fftSize = 512;
src.connect(analyser);
analyser.connect(ctx.destination);

const buf = new Uint8Array(analyser.frequencyBinCount);
let mouthOpen = false, lastSwap = 0;

function frame(now) {
    analyser.getByteTimeDomainData(buf);
    // RMS deviation from the 128 midpoint
    let sum = 0;
    for (const v of buf) { const d = v - 128; sum += d * d; }
    const level = Math.sqrt(sum / buf.length) / 128;

    // Minimum hold time stops the strobing that makes PNGTubers look cheap
    if (now - lastSwap > 60) {
        const open = level > OPEN_THRESHOLD;
        if (open !== mouthOpen) { mouthOpen = open; lastSwap = now; render(); }
    }
    if (!audio.ended) requestAnimationFrame(frame);
    else { mouthOpen = false; render(); }   // always land closed
}
audio.play();
requestAnimationFrame(frame);
```

`render()` is a class toggle:

```js
function render() {
    document.body.classList.toggle("talking", mouthOpen);
}
```

```css
#mouth-open   { display: none; }
.talking #mouth-open   { display: block; }
.talking #mouth-closed { display: none; }
```

Note the `else` branch: the mouth is forced closed when playback ends. That's the fix for the
freeze-mid-flap problem, and it's structurally impossible to get wrong here — unlike the OBS filter
approach, where the last state simply persists.

**Fallback if CEF misbehaves:** compute the envelope server-side with `soundfile` (already a dependency)
and ship it in the payload as an array of levels at a fixed frame interval, then step through it against
`audio.currentTime`. Slightly more code, no WebAudio dependency. Only reach for this if needed.

---

## Character images

Convention over configuration — the user drops files in a folder, no config editing:

```
static/characters/player1-closed.png
static/characters/player1-open.png
static/characters/player2-closed.png
...
```

The overlay builds the paths from its `player` query param. Missing files should render nothing rather
than a broken-image icon, so a half-configured setup still streams cleanly.

---

## What OBS setup becomes

1. Add a **Browser** source, URL `http://127.0.0.1:5000/overlay?player=1`, size to taste.
2. Tick **Control audio via OBS** so the TTS goes into the mixer rather than out the desktop device.
3. Position it.
4. Repeat per player.

No plugin. No filters. No audio routing. No exact-name matching. Nothing that fails silently.

---

## Risks worth checking early

**Autoplay.** OBS's embedded browser is normally configured to allow autoplay without a user gesture,
but this is the assumption the whole design rests on — verify it in stage B before building anything on
top. In a regular Chrome tab it *will* be blocked, so the control page needs a one-time "enable audio"
click for desktop testing.

**Browser source audio.** "Control audio via OBS" is per-source and off by default in some versions. If
it's unticked the audio still plays, just not through OBS — a confusing half-working state worth calling
out in the setup doc.

**Multiple audio-capable sources.** Every player's browser source can emit audio. Only one plays at a
time in practice, but they all appear in the mixer. Acceptable; alternatively route all audio through a
single silent `/audio-sink` source and keep the overlays visual-only, at the cost of split sync.

**Losing OBS-native filters.** You give up the ability to apply Move transitions and OBS effect filters
to the characters, since they're no longer OBS sources. CSS covers the equivalent ground, but it's a
different toolbox.

---

## Staging

Each stage is independently testable and leaves the app working.

**A. Split `/control` and `/overlay`.** No behaviour change. Today `index.html` is both the operator
panel and the on-stream graphic, which is why neither can be designed properly. Prerequisite for
everything below.

**B. Move audio to the browser.** Serve wavs over HTTP, play with `<audio>`, delete the pygame path and
the blocking sleep. Biggest single win: it removes VB-Cable *and* fixes the serial-TTS stall. Verify
autoplay here.

**C. Animation in the page.** WebAudio analyser, two-image swap, per-player query param. The Move plugin
and all filter setup become unnecessary.

**D. `config.json`.** Channel name, voice per player, image paths. Nothing left to edit in `.py` files.

**E. Make OBS websockets optional.** Keep the module for anyone using the old filter setup, but never
fatal — "OBS not connected, animations disabled" instead of `sys.exit()`.

Stages A–C are the ones that deliver the setup reduction. D and E are polish for handoff.

---

## Interaction with the player refactor

Do the dict refactor (`REFACTOR_SKETCH.md`) **before** stage C, not after. Stage C touches every place
player state is read, and doing it against six copy-pasted branches means writing the new code six times
too. With `PLAYER_CONFIG` in place, the overlay's player count comes from one source of truth that the
Jinja template, the socket handlers, and the config file all read.
