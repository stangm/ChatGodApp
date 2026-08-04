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

### Stages C and D are built — `/setup` and runtime assignment (**untested**)

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

Stages F (casts), G (appearance) and H (splitting `/setup` up) are not built.

**H should come before F and G.** `/setup` currently puts slots and every character on one page with
each character fully expanded — fine at three, unusable at fifteen, and the frequently-used slots
section gets pushed further down every character you add. The plan is `/setup` for slots only,
`/setup/characters` as a grid of art, and `/setup/character/<id>` as a full-page editor. Both F and
G want to add sections to that page, so each one built first makes the split more work.

### Not done

1. **Nothing survives a restart.** Voice, style, TTS toggle, caption toggles and assignments are all
   in-memory and rebuild from character defaults. A crash mid-stream silently reverts everything. The
   control panel now *shows* this honestly instead of lying about it, which is an improvement but
   not a fix.
2. **Layer-2 state lives in two managers.** `TTSManager.voices` holds live voice, `DisplayManager`
   holds live captions, for the same slot. They should probably become one slot-state object when
   assignment lands — noted in `display_manager.py`.
3. **The rest of the character library** — `DESIGN_CHARACTER_LIBRARY.md`, stages F and G. Stage G is an
   appearance endpoint: typeface, caption sizes and mouth tuning out of source and into
   `characters.json`, applied live over the socket. Independent of F, and the sizes half is cheaper
   than it sounds because every caption size is already a CSS custom property. Font selection is the
   expensive half — doing it without a stream-time dependency on Google Fonts means downloading the
   family locally when it's picked.
4. ~~The launcher script~~ and ~~status panel~~ — **done**. Next in the install design is stage D,
   the **rolling log file**, then E onwards (the wizard) which only pays off at more than one user.
5. **`templates/index.html` is still orphaned.** 307 lines of superseded markup that no route
   renders. `/setup` was written fresh rather than repurposing it, so this is now just dead code —
   delete it.

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
CHATGOD_ variable  ->  config.json  ->  legacy unprefixed variable  ->  default
```

`CHATGOD_TWITCH_TOKEN`, `CHATGOD_TWITCH_CHANNEL`, `CHATGOD_AZURE_KEY`, `CHATGOD_AZURE_REGION`, or the
same four as `twitch_token` / `twitch_channel` / `azure_key` / `azure_region` in `config.json`. The
old unprefixed names still work; startup names any it falls back to, and reports which source each
setting came from.

**`config.json` deliberately outranks the legacy names**, against the usual "env beats files" rule.
The prefixed variable and the file are both unambiguously meant for this app; an unprefixed
`AZURE_TTS_KEY` is a guess that a generic name refers to us. Since the file is how a configured
machine gets handed over, letting a stale variable from another tool beat it would recreate exactly
the collision the prefix exists to prevent.

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

**The repo lives at `C:\dev\ChatGodApp`, deliberately outside OneDrive.** It used to sit in
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

## Picking it back up

**Two things are written but have never run: `/setup` (stages C and D) and `config.json`.**

For `/setup`, in this order — each exercises a different write path:

- Open `/setup` with no `characters.json`. It should list your three slots using the filename
  convention, and **write nothing** until you act.
- Create a character, assign it to player 1. The overlay should swap art **without a refresh**, and
  `characters.json` should appear.
- Change the voice on the control panel, then hit *Save this voice as the default*. Reassign the
  slot — it should come back with that voice.
- Try deleting a character that's assigned. It should refuse and name the slot.
- Put `_comment` back into `characters.json` by hand, then save something in `/setup`. The comment
  must survive.

For `config.json`:

- Copy `config.example.json` to `config.json`, fill it in, unset the environment variables, restart.
  Startup should print `config.json: found` and `(from config.json)` against each setting.
- Put a deliberate syntax error in it — the app should print the parse error, say it's ignoring the
  file, and still start.
- Set `CHATGOD_TWITCH_CHANNEL` as a variable while the file also has one: the variable should win.

Two things from the status panel were also never confirmed: the **Overlay** row going green as OBS
connects and amber when it closes, and the **Copy diagnostics** button (check the pasted text has no
key or token in it). The Azure and Quota rows are proven — `usage.json` recorded the startup chime.

Everything else is clean, merged and pushed.

**The status panel is the recommendation** — install stage C, and the other half of the problem the
launcher solves. Starting reliably is done; *knowing it's working before going live* isn't. Twitch,
Azure, voices and overlay connections are each silently wrong today, and every one of them surfaces
mid-stream as "it's not working". A green/red block at the top of the control panel turns most of
those into a line she reads out to you.

A few smaller checks were never run and are worth folding into whatever comes next rather than doing
on their own: deleting `characters.json` and restarting to confirm the fallback path still works end
to end, and the reported width input recalculating at values other than 500.

---

## Keeping this file honest

Update it when a branch merges, a stage completes, or a gotcha is found the hard way. A stale
orientation doc is worse than none, because it gets believed.

Last updated: 2 Aug 2026 — character library stages C, D and E built (**untested**): /setup, runtime
assignment, save-as-default, art upload. `config.json` also untested. A/A2, launcher, status panel working.
