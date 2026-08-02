# Project state

**Read this first in a new chat.** It's the orientation doc: what this is, what works, what's in
flight, and what will waste your time if you don't know it.

**It indexes, it doesn't duplicate.** Design rationale lives in the `DESIGN_*.md` files and setup
lives in the README and runbook. Copying their content here guarantees two versions that disagree
within a month. Anything below that reads like a summary should end in a pointer.

---

## What this is

A rebuild of DougDoug's Chat God app: Twitch chatters are assigned to on-stream character slots,
their messages are read aloud by Azure TTS, and an animated character mouths along in OBS.

The rebuild exists to make it **installable by someone who isn't a developer**, and extensible
without editing Python. The original required editing source to change a channel name.

**Audience is N=1 plus you.** This is being set up for one specific non-technical streamer, not
published to strangers. That shapes nearly every install decision: you'll create her Azure resource
and hand over a configured machine, so a wizard that walks someone through the Azure portal is weeks
of work with one beneficiary. The recurring cost isn't installation, it's *you being the support
desk over Discord mid-stream*. Diagnostics beat wizards. See `DESIGN_GUIDED_INSTALL.md`.

### Standing constraints

Every change gets weighed against these:

- **Install has to stay easy**, and install docs get updated in the same commit as the change
- **OBS integration stays simple** — say explicitly when a change makes OBS setup easier or harder
- **The streamer changes things mid-stream**, so live control beats config files
- **Extensibility and customization** over hardcoding

---

## Current state

The app **works end to end** and has passed a full smoke test: Twitch chat → Azure TTS → wav served
over HTTP → OBS browser source plays it → mouth animates. Verified on 2 Aug 2026.

Also verified: the voice catalogue and per-voice style narrowing, including the style-reset path when
switching to a voice with no styles (all 15 `en-AU` voices have none, which is the useful test case).

### Branches

`main` is at `e2db958`. Two branches sit ahead of it:

| Branch | Contains | State |
|---|---|---|
| `fix/control-panel-live-state` | Live control panel state; casts design | Tested, pushed |
| `refactor/config-module` | `config.py`, `CHATGOD_` prefix | **Untested, uncommitted** |

Merge order matters — the config work branches off the live-state work.

### Not done

1. **`config.json`** — stage A of the install design is half done. `config.py` owns every read; the
   JSON layer itself isn't built.
2. **Stage A2 — display toggles.** Character name above chatter name, per-character show/hide flags,
   overlay self-sizing, control panel reporting browser-source dimensions.
3. **Nothing survives a restart.** Voice, style, TTS toggle and assignments are in-memory and rebuild
   from `players.py` defaults. A crash mid-stream silently reverts everything. The control panel now
   *shows* this honestly instead of lying about it, which is an improvement but not a fix.
4. **The character library** — the large one. `DESIGN_CHARACTER_LIBRARY.md`, stages A–F.

---

## How it fits together

```
Twitch chat ──> Bot (thread) ──> SpeechWorker (queue) ──> Azure TTS ──> wav on disk
                    │                                                      │
                    │                                          register_audio() -> token
                    ▼                                                      ▼
             socket 'message_send' ────────────────> overlay page ──> GET /audio/<token>
                                                          │
                                                     WebAudio analyses the clip,
                                                     swaps open/closed PNG
```

The bot thread never waits for audio. Playback is the browser's job, which is why OBS picks up the
sound natively and no OBS plugin or Move filter is involved any more.

| File | Holds |
|---|---|
| `chat_god_app.py` | Flask + SocketIO, routes, socket handlers, the twitchio Bot, SpeechWorker |
| `config.py` | Every setting read. `setting('azure_key')` and friends |
| `players.py` | Which slots exist, keyphrases, default voices. Hand-edited |
| `voices_manager.py` | Per-slot live voice/style; the override layer the control panel edits |
| `azure_text_to_speech.py` | Synthesis, style resolution, gTTS fallback |
| `fetch_voices.py` | Builds `voices.json` from Azure. Run manually |
| `templates/control.html` | Operator panel. **Never** put this in OBS |
| `templates/overlay.html` | The on-stream graphic |
| `templates/index.html` | **Orphaned.** 307 lines, no route renders it |

Routes: `/` redirects to `/control`; `/overlay?player=N`; `/audio/<token>`.

Socket events: `tts`, `pickrandom`, `choose`, `voicename`, `voicestyle` in; `message_send`, `speak`,
`style_reset`, `state` out.

### Configuration

Resolution order, first non-empty wins:

```
CHATGOD_ variable  ->  legacy unprefixed variable  ->  (config.json, not built)  ->  default
```

`CHATGOD_TWITCH_TOKEN`, `CHATGOD_TWITCH_CHANNEL`, `CHATGOD_AZURE_KEY`, `CHATGOD_AZURE_REGION`. The
old unprefixed names still work; startup names any it falls back to.

| File | Written by | Tracked? |
|---|---|---|
| `players.py` | Hand | Yes |
| `voices.json` | `fetch_voices.py` | No — `voices.default.json` is the tracked fallback |
| `characters.json` | Setup screen | No, and doesn't exist yet |

---

## Things that will waste your time

**Git can't be driven from the sandbox.** The OneDrive mount lets git *create* `.git/index.lock` but
not remove it, so every commit and push has to be run by Mark in PowerShell. A failed attempt leaves
a stale lock that blocks his next command too — clear it with `Remove-Item .git\index.lock`. Write
the files, hand over the commit command.

**`.venv/` lives inside the repo.** It's gitignored, but recursive greps hit thousands of dependency
files. Exclude it.

**Environment variables don't reach terminals that are already open.** This is the single most common
"it works for everyone else" failure and it looks exactly like a bad token.

**A plain browser tab plays no audio; OBS does.** Browsers block autoplay until you interact with the
page. Silence in a tab is the *expected* result and not a bug — don't debug it.

**Two OBS browser source settings matter more than they look.** *Shutdown source when not visible*
must be **off**, or OBS tears the page down and drops the socket. *Control audio via OBS* should be
**on**, but OBS then defaults to Monitor Off — so it's in the stream and not your headphones. Set
Audio Monitoring to *Monitor and Output*.

**Browser source height** = width × art aspect ratio + 125px for the boxes. At 500 wide: player 1
is 513, player 2 is 445, player 3 is 451. Too short clips the message box. This arithmetic is meant
to be replaced by the app reporting the size — see `DESIGN_CHARACTER_LIBRARY.md`.

**Browser sources cache images hard.** Any art swap needs a cache-busting query string or nothing
visibly changes.

**Flask-SocketIO refuses to start when `sys.stdin` isn't a TTY**, raising a Werkzeug "not designed
for production" error. Running from PowerShell is fine, so this hasn't bitten yet — but it will
break the launcher the moment it hides the console or uses `pythonw`. One keyword argument fixes it.

**Azure F0 is 500,000 characters/month.** Hitting the ceiling mid-stream looks exactly like "TTS
randomly stopped."

---

## Decisions already made

Don't relitigate these without a reason. Rationale is in the design docs; this is the index.

| Decision | Where |
|---|---|
| Audio plays in the browser, not via OBS Move filters | `DESIGN_BROWSER_OVERLAY.md` |
| `characters.json`, not a UI that writes `players.py` | `DESIGN_CHARACTER_LIBRARY.md` |
| Three-layer voice resolution: character default → live slot → message prefix | `DESIGN_CHARACTER_LIBRARY.md` |
| Per-**character** display toggles, not per-slot or global | `DESIGN_CHARACTER_LIBRARY.md` |
| Art top-anchored so it never moves when captions toggle | `DESIGN_CHARACTER_LIBRARY.md` |
| Deleting a character keeps the art files | `DESIGN_CHARACTER_LIBRARY.md` |
| A cast is N assignments, not a new mechanism | `DESIGN_CHARACTER_LIBRARY.md` |
| Launcher script, not a PyInstaller build | `DESIGN_GUIDED_INSTALL.md` |
| Premium Azure voices excluded by default (they bill separately) | `fetch_voices.py` |
| Legacy env names kept, but announced loudly at startup | `config.py` |

---

## Open questions

Design docs carry the full list. The ones that need Mark's judgement rather than a technical answer:

- **What signals "assigned but idle"** when a character has every caption hidden? Static art alone
  reads as broken — which is when you'd start debugging something that's fine.
- **Does the character name show when nobody is assigned?**
- **Do casts belong on the control panel or `/setup`?** One click changes every character and
  discards every live override. Fast versus safe.
- **Whose Azure subscription** for the second streamer? Shared key means shared quota and one busy
  night breaks the other person's stream.

---

## Keeping this file honest

Update it when a branch merges, a stage completes, or a gotcha is found the hard way. A stale
orientation doc is worse than none, because it gets believed.

Last updated: 2 Aug 2026 — after the control-panel live-state fix and the `config.py` refactor.
