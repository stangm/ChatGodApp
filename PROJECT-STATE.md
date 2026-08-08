# Project state

**Read this first in a new chat.** It's the orientation doc: what this is, what works, what's in
flight, and what will waste your time if you don't know it.

**It indexes, it doesn't duplicate.** Design rationale lives in the `DESIGN_*.md` files and setup
lives in the README and runbook. Copying their content here guarantees two versions that disagree
within a month. Anything below that reads like a summary should end in a pointer.

---

## What this is

**ChatMob.** A rebuild of DougDoug's Chat God app: Twitch chatters are assigned to on-stream
character slots, their messages are read aloud by Azure TTS, and an animated character mouths along
in OBS.

The rebuild exists to make it **installable by someone who isn't a developer**, and extensible
without editing Python. The original required editing source to change a channel name.

**Audience is N=1 plus you.** This is being set up for one specific non-technical streamer, not
published to strangers. That shapes nearly every install decision: you'll create her Azure resource
and hand over a configured machine, so a wizard that walks someone through the Azure portal is weeks
of work with one beneficiary. The recurring cost isn't installation, it's *you being the support
desk over Discord mid-stream*. Diagnostics beat wizards. See `DESIGN_GUIDED_INSTALL.md`.

### The name

Renamed from Chat God on 7 Aug 2026 — the rebuild has diverged far enough from the original that
sharing its name misleads, and "Chat God" is DougDoug's to begin with, which gets awkward if this is
ever promoted to other streamers.

***ChatMob*** was picked over a long list. The reasoning, so it doesn't get relitigated:

- **"Mob" carries two meanings at once** — a crowd, and the gaming sense of an NPC creature that
  lives in the world. The audience already knows the second one, and creatures-on-screen is what the
  app does. It also gives useful grammar: *your mob*, *six in the mob*, *a mob slot*.
- **The trademark field is empty.** No `CHATMOB` marks exist; the nearest are three `CHATMOBILE`
  registrations in unrelated goods (calling cards, phones, a 1999 software program).
- **The only name collision is dead** — a *"Chatmob — Chat & Meet All People"* Android app,
  version 1.0, last updated May 2016, from a shovelware developer. Abandoned, not competing.
- **Styled `ChatMob`, not `Chatmob`** — the capital M keeps both halves legible.

Rejected, with the reason worth keeping: **Chatterbox** and **ChatStage** are descriptive and so
unprotectable; **ChatShow** is a dictionary term; **ChatCast** is blocked by a live Nov 2025 filing
by Chatcast Holdings covering broadcaster messaging apps; **YapChat** sits in the middle of the
random-stranger webcam-chat genre (yapchat.com since 2004, an active "Meet, Flirt and Cam" app,
yap.chat) which is not a neighbourhood to share with a streamer tool.

The pattern behind all of those: *chat + an ordinary English word* is always either taken or too
descriptive to own. Only an unexpected second half survives.

**Not yet checked:** `.gg` / `.tv` / `.io` / `.app` domains and the Twitch, X and Discord handles.
`chatmob.com` is registered but serves an empty page. None of this is a clearance opinion — get an
attorney before filing or printing anything.

#### What the rename actually changed

Everything except the two things below. The entry point is now `chatmob_app.py` (nothing imported
it — it was only ever named by `start.bat`'s `set "APP="` and by docs), generated wavs go to
`%TEMP%\chatmob_audio`, `CHATMOB_VENV` replaces `CHATGOD_VENV` (the old name is still honoured by
`start.bat`, which is the one place a stale value can't do any harm),
and every page title, heading, launcher message and doc says ChatMob.

**The environment prefix is now `CHATMOB_`.** Resolution is three layers:

```
CHATMOB_ variable  ->  config.json  ->  default
```

The legacy layer was added during the rename and **removed the same day** — see *The legacy
fallback, and why it went* below.

#### What is still called ChatGod, deliberately

| Kept | Why |
|---|---|
| The DougDoug attribution and link in `README.md` | Factual credit, and the URL is theirs |
| `LICENSE` | MIT requires the copyright notice preserved. It never said "Chat God" anyway — it says *Copyright (c) 2024 DougDougGithub* |

Note the license constrained almost nothing: the mandatory footprint was two lines, neither of which
contains the old product name.

#### Done, 7 Aug 2026

The folder is `C:\dev\ChatMobApp`, the GitHub repo is `stangm/ChatMobApp` with the remote updated,
`.venv` was rebuilt at the new path, and **the renamed app has started and synthesized** — the run
regenerated `__pycache__` and touched `usage.json`, which is only written from inside
`text_to_audio()`. So the whole chain works under the new name.

One gotcha worth keeping: **a PowerShell window open across the folder rename keeps a stale working
directory** and every git command in it fails with *"not a git repository"*, which reads like repo
damage. Open a fresh terminal instead of trying to `cd` out of it.

#### The legacy fallback, and why it went

Same day as the rename. Resolution is now `CHATMOB_` → `config.json` → default, and **no older
variable name is read at all**. `Spec.legacy`, the loop in `resolve()`, `legacy_in_use()` and the
startup migration block are gone.

"Keep the fallback, it costs nothing" was the obvious call and it was wrong, for a reason worth
remembering:

- **The `CHATGOD_` generation had never been set anywhere.** Auditing the machine found the prefixed
  names absent at every scope. They existed in code for five days and protected nobody.
- **This machine had been running on the *unprefixed* names the whole time** —
  `TWITCH_ACCESS_TOKEN`, `AZURE_TTS_KEY` and friends. The prefix work in early August changed the
  code and the docs but was never applied to the actual environment, and nothing noticed because the
  fallback worked.
- **The warning was there and it failed.** Startup printed a migration block naming every legacy
  variable, at every launch, for months. It got scrolled past. A safety net that only works if
  someone reads a paragraph they've already seen a hundred times is not a safety net.

So the trade was made deliberately: an old-only machine now fails loudly with `Not set:
CHATMOB_AZURE_KEY` and instructions — a minute's work — instead of succeeding quietly on a generic
name that another Azure tool could claim at any time. **Loud failure over quiet success on the wrong
value.**

`start.bat` still honours `CHATGOD_VENV`, which is the one exception and a deliberate one: it points
at a folder, not a credential, so a stale value can misdirect nothing worse than which venv is used.

#### Still outstanding from the rename

**The name's loose ends.** `.gg`, `.tv`, `.io` and `.app` domains and the Twitch, X, Discord and
GitHub handles have never been checked. `chatmob.com` is registered but serves an empty page.

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

### Git state

Everything lives on `main`; the feature branches were merged and deleted. To confirm nothing is
outstanding at any point: `git fetch --prune` then `git branch -a --no-merged main` — empty output
means everything is in.

### Character library — stages A and A2 are done and verified

Confirmed on stream: the character name renders, both names sit over the art and survive the mouth
opening, and all three caption toggles take effect live.

Two things that cost time getting here, both worth not repeating:

- **Stale cached CSS in the browser source.** The page kept toggling classes against a stylesheet the
  browser had cached from before those rules existed, so captions silently stopped hiding and new
  elements rendered unstyled — with every symptom pointing at the code. Fixed by `static_v()`
  stamping stylesheet URLs with the file's mtime.
- **`textfill` sized each name to fit its own text**, so the *shorter* name came out larger and the
  hierarchy was set by string length. Fixed by capping each with `maxFontPixels`.

Also verified by direct test rather than by running the app: all four `characters.json` fallback
paths, the size arithmetic against the real art, both templates rendering, the control panel's
JavaScript parsing, and that every socket event has a matching sender and listener.

**How it works.** `characters.json` (gitignored; `characters.example.json` is the tracked template)
defines characters with a display name, art, default voice and style, and three caption switches.
Slots it doesn't mention fall back to `players.py` and the `player<N>-*.png` convention, so **an
install with no `characters.json` behaves exactly as it did before** — the main compatibility
guarantee, and worth preserving.

The overlay draws the character name above the chatter name, **both over the lower part of the art**
so neither affects the browser source height. The message text stays stacked below and is the only
toggle that changes the size. The control panel toggles all three live and reports the size.

Mark's own `characters.json` is currently a copy of the example — Henry Potter in slot 1, The
Narrator in slot 2.

### Stages C and D — `/setup` and runtime assignment

`/setup` lists the player slots and the character library. You can create and edit characters, assign
them to slots, save a slot's live voice back onto its character, and delete (refused while assigned).
`characters.py` grew a `Library` class with an atomic write path; the module-level `load()` is kept
as a shim so nothing else changed.

Assigning is the deliberate reset point — voice, style and captions snap to the new character's
defaults, and the overlay swaps art in place over an `art_changed` socket event with cache-busted
URLs. Editing a character that's already on screen redraws it *without* resetting live values.

**`Library.save()` preserves top-level keys it doesn't understand**, so the `_comment` block and the
future `casts` / `appearance` sections survive a rewrite. Losing those silently is the obvious way
this could have gone wrong.

Stage E is built too: art uploads on `/setup`. Filenames are derived from the character id rather
than taken from the upload — a user-supplied filename is a path traversal, so ids are constrained to
letters, numbers, hyphens and underscores. The closed/open pair is validated together before either
frame is written, because mismatched dimensions make the character jump when it speaks and writing
one frame would create exactly that state. Art overwrites in place, which only works because
`art_url()` cache-busts on mtime.

**Fixed 5 Aug 2026: saving the character editor wiped the art.** Editing a name or voice and
clicking save blanked `art_closed` and `art_open` in `characters.json` — the character went blank
on stream and the art had to be re-uploaded. `setup_character()` listed the two art keys in the
fields it read from the form, but the details form has no input for them (they belong to the
separate upload form), so `request.form.get` returned `""` on every save and `upsert` reads empty
as "no opinion" and pops the key. The PNGs were never touched, which is why re-uploading appeared
to fix it — it only wrote the paths back.

The general shape is worth remembering: **`upsert` merges precisely so a partial form is safe, and
sending keys the form doesn't render is what defeats that.** Any new field on these pages belongs
in exactly one route's field list — the one whose form actually has the input.

**Stage H** — `/setup` is three pages, which is what keeps it usable as the library
grows:

| Page | Holds |
|---|---|
| `/setup` | Slots. Bounded by player count, so it fits one screen however many characters exist |
| `/setup/characters` | The library as a grid of art, with badges for what's in a slot |
| `/setup/character/<id>` | One character's editor, alone on a page |

Create and edit are one path now: *New character* takes an id, creates a blank entry and redirects
into the editor. Two forms with overlapping fields is what let the style dropdown drift.

Stages F (casts) and G (appearance) are not built. Both wanted this split first, since both add
sections to these pages.

### Slot enable/disable

`Player.active` and an *In the show* switch at the top of each control panel. Off means: overlay
draws nothing, no synthesis, keyphrase ignored, Pick Random and Choose user refused. It exists so a
six-player OBS scene can be run with four without the app pooling chatters into invisible slots or
spending quota on them.

Three distinctions worth keeping straight — they look similar and aren't:

| Control | Effect |
|---|---|
| *In the show* off | Out entirely — no art, no voice, no pool joins |
| TTS unticked | Silent, but still on screen and still pooling |
| Character set to *(empty)* | Invisible, but still speaks |

Disabling **keeps the pool**, so a short toggle doesn't make everyone rejoin. The pool self-empties
after 450s of a chatter being quiet anyway, so keeping it only matters for exactly the short-toggle
case where clearing would annoy people most.

**Layout stays an OBS concern.** Fixed browser sources can't re-centre when two go dark, so the
answer for a 6-vs-4 night is two OBS scenes, not app-side reflow.

### Voice preview (verified 7 Aug 2026)

**Hear this voice** on the character editor. `POST /setup/preview` synthesizes `PREVIEW_TEXT` with
the selected voice and style and returns JSON; the page plays it. JSON rather than a redirect because
it's the one action on these pages that shouldn't reload a half-filled form.

**Preview clips use their own cache** (`_preview_cache`, 4) rather than the shared one. Sharing would
let a burst of auditioning evict speech that's queued but unplayed — the same class of bug as the
speech gate's backlog, and stepping through a voice's styles is exactly that kind of burst. Separate
caches remove the question rather than relying on the numbers staying favourable.

**It plays through the operator's browser**, so OBS Desktop Audio would capture it mid-stream. That's
warned on the page, and it's why the button is on the character editor rather than the control panel.
Quota is counted automatically, since `usage.record()` fires inside `text_to_audio()`.

### Dimming and the speech gate (both verified 7 Aug 2026)

**Dimming** — characters sit at `IDLE_BRIGHTNESS` (0.7) and go to full while speaking. Entirely
local to each overlay page: it only needs to know about its own slot, so there's no socket traffic
and no server involvement. `filter: brightness` rather than `opacity`, because opacity would let the
scene show through a transparent PNG and make the character look ghostly rather than dim. The class
is cleared in `done()`, which also runs on the error and autoplay-blocked paths, so a failed clip
can't leave a character lit for the rest of the stream. `SPEAKING_HOLD_MS` (200) stops consecutive
messages strobing.

### Speech gate

*One speaker at a time* on the control panel. Off by default, matching how the app has always
behaved. `SpeechPacer` sits after synthesis and releases clips one at a time, timed from each wav's
real duration with a 350ms overlap so it reads as conversation rather than strict queuing.

Three decisions that matter more than the feature:

- **Timed from the clip, not from pages reporting in.** A page that closes or drops its socket
  mid-clip would stall a report-based queue forever and mute the whole show. Being a few hundred
  milliseconds out is a far better failure than silence, so nothing waits on a client.
- **Separate thread from `SpeechWorker`.** Sleeping inside the synthesis loop would be fewer lines
  but would delay later clips, compounding the lag.
- **`SPEECH_QUEUE_MAX` (8) must stay well under `AUDIO_CACHE_SIZE` (50).** `register_audio()` deletes
  the oldest wav past 50, so a long backlog would have its files removed before playing and the
  overlay would 404 and skip them with nothing to explain why.

Turning the gate off flushes the backlog rather than stranding it. A clip whose slot was switched out
of the show while it waited is skipped at release time.

### `test_playback.py` — the gate and the caches, without a stream

Run it with the venv active: `python test_playback.py`. 24 checks, no server, no Twitch, no Azure —
it imports the real `chatmob_app` and swaps `socketio.emit` for a list, so "what reached the overlay"
becomes something to assert on.

Covers the gate off and on, the queue cap dropping oldest-first while preserving order, `flush()`,
the inactive-slot skip **and that the skip costs no sleep** (four dead 3s clips drain in 0.05s rather
than holding the show for 10.6s), preview eviction never touching queued speech, and an evicted token
404ing.

**The trap it documents, because it caught the first version of the test itself: an empty queue is
not an idle thread.** After releasing a 4s clip the pacer sleeps ~3.65s regardless of what's queued,
and `flush()` empties the queue without waking it — so a helper that waited on the queue returned
early and the *next* test failed with an unrelated-looking symptom. `settle()` now probes with a clip
of its own and waits for it to come back out; nothing but a free thread can do that.

Also worth knowing in normal use: **toggling the gate off and back on mid-clip delays the next clip**
by up to the remainder of the flushed one, for the same reason. Harmless, not worth fixing.

Two things it deliberately doesn't assert: which specific clip is playing after an over-cap burst
(whether the thread pops before or during the submitting loop is a genuine race — it asserts the
survivors are a contiguous newest-run instead), and anything needing a browser.

### Not done

1. **Nothing survives a restart.** Voice, style, TTS toggle, caption toggles and assignments are all
   in-memory and rebuild from character defaults. A crash mid-stream silently reverts everything. The
   control panel now *shows* this honestly instead of lying about it, which is an improvement but
   not a fix.
2. **Layer-2 state lives in two managers.** `TTSManager.voices` holds live voice, `DisplayManager`
   holds live captions, for the same slot. They should probably become one slot-state object when
   assignment lands — noted in `display_manager.py`.
3. **Per-style art** — an angry face for `(angry)`, a sad one for `(sad)`. From stream feedback,
   not scheduled, and Mark is still thinking about the shape. Constraints are written up in
   `DESIGN_CHARACTER_LIBRARY.md` under *Idea: art that changes with the speaking style* — the one
   that would be easy to get wrong is that art must follow the **resolved** style, not the requested
   one, or a dropped prefix puts an angry face over a neutral delivery.
4. **The rest of the character library** — `DESIGN_CHARACTER_LIBRARY.md`, stages F and G. Stage G is an
   appearance endpoint: typeface, caption sizes and mouth tuning out of source and into
   `characters.json`, applied live over the socket. Independent of F, and the sizes half is cheaper
   than it sounds because every caption size is already a CSS custom property. Font selection is the
   expensive half — doing it without a stream-time dependency on Google Fonts means downloading the
   family locally when it's picked.
5. ~~A global speech gate~~ — **built**, see above.
6. ~~The launcher script~~ and ~~status panel~~ — **done**. Next in the install design is stage D,
   the **rolling log file**, then E onwards (the wizard) which only pays off at more than one user.
7. ~~`templates/index.html` orphaned~~ — deleted.

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
| `chatmob_app.py` | Flask + SocketIO, routes, socket handlers, the twitchio Bot, SpeechWorker |
| `config.py` | Every setting read. `setting('azure_key')` and friends |
| `characters.py` | The library read path, plus the browser-source size arithmetic and `BOX_HEIGHTS` |
| `display_manager.py` | Live caption visibility per slot |
| `usage.py` | Persisted monthly Azure character count, for the quota warning |
| `players.py` | Which slots exist, keyphrases, fallback voices. Hand-edited |
| `voices_manager.py` | Per-slot live voice/style; the override layer the control panel edits |
| `azure_text_to_speech.py` | Synthesis, style resolution, gTTS fallback |
| `fetch_voices.py` | Builds `voices.json` from Azure. Run manually |
| `templates/control.html` | Operator panel. **Never** put this in OBS |
| `templates/setup.html` | Character library — create, edit, assign, delete |
| `templates/overlay.html` | The on-stream graphic |
| `templates/index.html` | **Orphaned.** 307 lines, no route renders it |

Routes: `/` redirects to `/control`; `/overlay?player=N`; `/audio/<token>`.

Socket events: `tts`, `pickrandom`, `choose`, `voicename`, `voicestyle` in; `message_send`, `speak`,
`style_reset`, `state` out.

### Configuration

Resolution order, first non-empty wins:

```
CHATMOB_ variable  ->  config.json  ->  default
```

`CHATMOB_TWITCH_TOKEN`, `CHATMOB_TWITCH_CHANNEL`, `CHATMOB_AZURE_KEY`, `CHATMOB_AZURE_REGION`, or the
same four as `twitch_token` / `twitch_channel` / `azure_key` / `azure_region` in `config.json`.
Startup reports which source each setting came from. Older names are not read — see *The legacy
fallback, and why it went*.

Both remaining layers are unambiguous — a `CHATMOB_` variable and a `config.json` next to the app
are each unmistakably meant for this app — so the ordering between them is just specificity, and the
variable wins as the easier thing to override for one run.

While the legacy layer existed, `config.json` deliberately outranked it, against the usual "env
beats files" rule: an unprefixed `AZURE_TTS_KEY` is a *guess* that a generic name refers to us, and
since the file is how a configured machine gets handed over, letting a stale variable from another
tool beat it would have recreated exactly the collision the prefix exists to prevent. That argument
is what eventually killed the layer outright.

Nothing writes `config.json` yet — that's the wizard, install stage E. `config.reload()` exists for
it.

| File | Written by | Tracked? |
|---|---|---|
| `config.json` | Hand, for now — wizard at stage E | **No, it holds secrets** — `config.example.json` is tracked |
| `players.py` | Hand | Yes |
| `voices.json` | `fetch_voices.py` | No — `voices.default.json` is the tracked fallback |
| `characters.json` | Hand, for now — setup screen at stage D | No — `characters.example.json` is tracked |

---

## Things that will waste your time

**The repo lives at `C:\dev\ChatMobApp`, deliberately outside OneDrive.** It used to sit in
`OneDrive\scripts\`, and a `.git` directory inside a synced folder caused three separate problems in
one session: `.git/index.lock` files that couldn't be removed (blocking every subsequent git
command), sync churn over `.venv`, and ref directories held open during branch deletion. All three
went away with the move. **Don't put it back**, and don't put the venv inside the repo.

**What the move did and didn't fix.** The `index.lock` problem is gone — plain `git status` from the
sandbox no longer leaves one, so reads are safe without `--no-optional-locks`. But the underlying
cause was the *mount*, not OneDrive: the sandbox still can't unlink files it creates under `.git`, so
`git add` leaves stray `tmp_obj_*` files in `.git/objects` and **writes still belong to Mark**. The
sandbox also has no git identity, so a commit fails outright.

- Reads from the sandbox: fine.
- Writes: still hand Mark the command.
- Stray temp objects are harmless; `git gc --prune=now` clears them.
- Stale `index.lock`: `Remove-Item .git\index.lock`, safe when no git command is running.

**The commit identity is repo-local.** `user.email` is
`79151320+stangm@users.noreply.github.com`, set on this clone rather than globally. GitHub rejects
pushes carrying the private gmail address, so a fresh clone that inherits only the global config
will push once and be refused. Fix is `git config user.email` then
`git commit --amend --reset-author --no-edit`.

**Environment variables don't reach terminals that are already open.** This is the single most common
"it works for everyone else" failure and it looks exactly like a bad token.

**A plain browser tab plays no audio; OBS does.** Browsers block autoplay until you interact with the
page. Silence in a tab is the *expected* result and not a bug — don't debug it.

**Two OBS browser source settings matter more than they look.** *Shutdown source when not visible*
must be **off**, or OBS tears the page down and drops the socket. *Control audio via OBS* should be
**on**, but OBS then defaults to Monitor Off — so it's in the stream and not your headphones. Set
Audio Monitoring to *Monitor and Output*.

**Don't calculate the browser source size by hand any more** — the control panel reports it per
player and updates as captions are toggled.

**Caption sizes belong in `CAPTIONS` in `characters.py`, never in the CSS.** The overlay sizes text
with `textfill`, which writes an inline `font-size` that beats the stylesheet — so a CSS-only edit
appears to do nothing at all. `overlay.css` reads the same values as custom properties, and the same
dict feeds the source-height arithmetic.

**Browser sources cache CSS and images hard**, across scene switches and app restarts. Stylesheet
links go through `static_v()` (a Flask context processor appending the file's mtime) so an edit
always reaches the browser. Art swaps will need the same treatment.

This failure is nastier than it sounds: the page keeps toggling classes against rules the cached
stylesheet doesn't have, so captions stop hiding and new elements render unstyled — and every symptom
points at the code rather than the cache. It cost a debugging round the first time it happened.

**Flask-SocketIO refuses to start when `sys.stdin` isn't a TTY**, raising a Werkzeug "not designed
for production" error — which reads as a crash rather than a refusal. Fixed with
`allow_unsafe_werkzeug=True` in `socketio.run()`. Don't remove it: anything that starts the app
detached, scheduled, or without a console hits this immediately.

**Azure F0 is 500,000 characters/month.** Hitting the ceiling mid-stream looks exactly like "TTS
randomly stopped." The control panel now warns from 80%, counting locally in `usage.json` — the SDK
doesn't expose real usage, so that number is this app's own tally and undercounts if the same Azure
resource is used from anywhere else. Check the portal before believing it about a bill.

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
| Names drawn over the art (no resizing); message stacked below (would bury the character) | `DESIGN_CHARACTER_LIBRARY.md` |
| Name size hierarchy set by `maxFontPixels` caps, not by fitting — fitting let string length decide which name looked bigger | `templates/overlay.html` |
| Caption boxes `display:none` so the source can shrink; art top-anchored so it never moves | `static/css/overlay.css` |
| Size arithmetic split — policy on the server, one multiply in the browser | `characters.py` |
| Style narrowing shared in `static/js/voice-styles.js`, and clamped again server-side | `DESIGN_CHARACTER_LIBRARY.md` |
| Launcher script, not a PyInstaller build | `DESIGN_GUIDED_INSTALL.md` |
| Premium Azure voices excluded by default (they bill separately) | `fetch_voices.py` |
| Legacy env names kept, but announced loudly at startup | `config.py` |
| Named **ChatMob**; full rename, and no legacy variable names are read at all | *The name*, above |

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
- **ElevenLabs voices alongside Azure?** Parked, not rejected — revisit if the voices themselves
  become the complaint. Assessed 5 Aug 2026; nothing built.

  The synthesis call is the cheap half. `TTSManager.synthesize()` is a real choke point — text in,
  wav path out — and ElevenLabs' mp3 goes through the same pydub conversion the gTTS fallback
  already uses, so `register_audio`, `_wav_seconds`, `SPEECH_OVERLAP_MS` timing and the overlay's
  WebAudio analysis are all untouched. **No OBS impact**: the browser source contract doesn't
  change.

  Three things make it more than an afternoon:

  1. **The catalogue is wired into the app, not behind the manager.** `chatmob_app.py` imports
     `AZURE_VOICES`, `AZURE_VOICE_STYLES`, `VOICE_CATALOG` and `styles_for` directly and builds
     `VOICE_OPTIONS` / `STYLE_OPTIONS` / `VOICE_STYLE_MAP` at module level; `characters.py`,
     `control.html`, `character.html` and `voice-styles.js` all consume that shape. Decoupling that
     is the bulk of the work. Voice ids would need namespacing (`azure:en-US-AriaNeural` /
     `eleven:21m00Tcm...`) so `characters.json` can name either — which is also what makes this
     **additive** rather than a swap, with the provider chosen per slot and switchable mid-stream.
  2. **Styles have no equivalent.** The `(angry)` prefixes, `resolve_style()` and the dropdown
     narrowing are all built on Azure's `mstts:express-as`. ElevenLabs has continuous
     `voice_settings` and v3 audio tags — a different axis. Either the style control becomes
     provider-shaped, or the prefixes map onto settings presets and become approximate. Note that
     `resolve_style`'s own rationale — substituting a wrong emotion is worse than applying none —
     argues against faking them.
  3. **Cost is what actually threatens the "installable by a non-developer" goal.** F0 is 500,000
     characters/month free. ElevenLabs has no comparable free tier at chat volume: roughly
     $0.05/1k characters on Flash/Turbo, ~$0.10/1k on Multilingual v2, so the same 500k is about
     $25–50/month. For a streamer being handed a configured machine that's a card on file and a
     bill to understand. Also unchecked: **concurrent request limits** against six slots
     synthesizing at once.

  Two smaller consequences: `usage.py` hardcodes `FREE_TIER_LIMIT = 500_000` with Azure-specific
  warning text, and the status panel reads `AzureTTSManager.last_result` while `_failure_reason()`
  parses Azure cancellation details. Both would need a provider-neutral shape.

  **If it's ever picked up**, the version that makes economic sense is a handful of premium
  signature voices for named characters while chat-at-large stays on Azure — not wholesale
  replacement. Flash v2.5 rather than Multilingual v2: half the credits, built for realtime.

---

## Picking it back up

Everything through stage H is built and exercised: the character library and `/setup`'s three pages,
art upload, runtime assignment, the slot *In the show* switch, the status panel, `start.bat`, and
`none` as a distinct style.

**The one exception is `config.json`.** It has never had a file on disk, so credentials have only
ever resolved from environment variables. That matters more than the others because it's the
mechanism for handing over a configured machine — worth ten minutes before you set the second
streamer up:

- Copy `config.example.json` to `config.json`, fill it in, unset the `CHATMOB_*` variables, restart.
  Startup should print `config.json: found` and `(from config.json)` against each setting.
- Put a deliberate syntax error in it — the app should print the parse error, say it's ignoring the
  file, and still start.
- Set one variable while the file also has it: the variable should win.

Then pick from *Not done* above.

---

## Keeping this file honest

Update it when a branch merges, a stage completes, or a gotcha is found the hard way. A stale
orientation doc is worse than none, because it gets believed.

Last updated: 7 Aug 2026 — renamed the app to **ChatMob** throughout, including the environment
prefix, the entry point, the folder and the GitHub repo, and confirmed it runs under the new name;
`config.json` resolution verified for the first time (see *The
name* above for why, and for the folder and GitHub renames still to do by hand).
Before that, 5 Aug 2026: fixed the character editor wiping art on save; added the ElevenLabs
open question (assessed, parked, nothing built).
Before that, 2 Aug 2026: character library through stage H built and tested, plus the slot
*In the show* switch. `config.json` remains the one untested path.
