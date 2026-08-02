# Design: character library and setup screen

**Status: design only.** Nothing implemented yet. Written on `feature/art-setup-screen`.

**Goal.** Change a player's character art and voice between streams — or during one — without
editing a `.py` file or restarting. Target user is the streamer mid-show, one hand on the control
panel.

This is stage D of `DESIGN_BROWSER_OVERLAY.md` ("config.json — channel name, voice per player, image
paths. Nothing left to edit in `.py` files"), extended: art and voice travel together as a
**character** rather than being loose per-slot fields.

---

## The shift

Today a player slot *is* a character — slot 1 owns `player1-open.png`, `player1-closed.png` and
`en-US-DavisNeural`, and they're only related by the number 1. Swapping the cast means renaming PNGs
on disk and editing `players.py`.

After: a **character** is a thing you define once and assign to a slot.

| | Today | After |
|---|---|---|
| Character art | Filename convention, `player<N>-*.png` | A field on a character |
| Default voice | `voice_name` in `PLAYER_CONFIG` | A field on a character |
| Changing the cast | Rename files, edit Python, restart | Pick from a dropdown |
| Reusing a character | Copy files to another number | Assign it to any slot |

---

## Where config lives

Three homes, because these are three different kinds of data.

| File | Written by | In git? | Holds |
|---|---|---|---|
| `players.py` | Hand | Yes | Which slots exist, keyphrases, structural defaults |
| `characters.json` | Setup screen | **No** | The character library and slot assignments |
| `voices.json` | `fetch_voices.py` | No | Cached Azure voice/style table |

`players.py` stays the hand-edited baseline; `characters.json` is merged over it at startup. Missing
file means fall back to defaults, so a fresh clone still runs.

**Why not have the UI write `players.py`?** Generating Python from form input means a malformed write
leaves the app unable to start — and it's a web form writing executable code, which is a bad habit
even locally. JSON fails soft: bad file, log it, use defaults.

Both generated files are gitignored. They're per-machine, and `characters.json` will reference art
that only exists on your disk.

### `characters.json` shape

```json
{
  "characters": {
    "wizard": {
      "display_name": "Henry Potter",
      "art_closed": "characters/wizard-closed.png",
      "art_open":   "characters/wizard-open.png",
      "default_voice": "en-US-DavisNeural",
      "default_style": "random",
      "show_character_name": true,
      "show_chatter_name": true,
      "show_message": false
    }
  },
  "slots": {
    "1": { "character": "wizard" },
    "2": { "character": "goblin" },
    "3": { "character": null }
  }
}
```

`display_name` is the character's name as it appears on stream — "Henry Potter", not "wizard". The
key is an id; the display name is prose and can change without breaking slot references.

Art paths are relative to `static/`, the same convention `chat_god_app.py` already resolves through
`url_for('static', ...)`. The overlay route keeps that resolution and changes only where the path
comes from — the assigned character rather than a filename built from the slot number. (The
slot-level `image_closed` / `image_open` keys are removed; see *Decided* below.)

---

## Voice and style resolution

Three layers, resolved top down. Only layer 1 persists.

1. **Character default** — `default_voice` / `default_style` from the library
2. **Live slot value** — what the control panel edits, in memory
3. **Per-message prefix** — `(angry)` from the chatter, that message only

Layer 2 already exists: `TTSManager.voices` is a per-slot `{name, style}` dict that the `voicename`
and `voicestyle` socket handlers mutate. The change is where it's *initialized* from, plus a reset
hook. The override machinery is built.

### What resets an override

| Action | Effect on the live voice and display toggles |
|---|---|
| Assign a character to a slot | **Reset** to that character's defaults |
| Pick Random / Choose user | **No change** — same character, different chatter |
| Restart the app | Back to character defaults (layer 2 is in memory) |
| **Save as default** | Writes layer 2 into the library, so it becomes layer 1 |

Changing the cast is a deliberate reset point; changing who's talking isn't. **Save as default** is
what stops a good mid-stream discovery from evaporating — without it the only way to change a
character's default is editing JSON by hand.

---

## What the overlay shows

Three elements below the art, each independently toggleable, each a property of the **character** —
so assigning the Wizard brings his display settings with him, the same way his voice does.

| Element | Example | Default |
|---|---|---|
| Character name | `Henry Potter` | on |
| Chatter name | `silverstagvt` | on |
| Message text | what they typed | on |

Character name on top and larger, chatter name smaller beneath it:

```
        ┌─────────────────┐
        │   character art │
        └─────────────────┘
           Henry Potter          <- character name, larger
            silverstagvt         <- chatter name, smaller
        ┌─────────────────┐
        │ message text    │
        └─────────────────┘
```

Toggles follow the same three layers as voice: the character holds the persisted default, the
control panel edits live, **save as default** writes back. Assigning a character resets to its
values.

**Why per character rather than global.** A narrator who never shows a caption can sit alongside
players who always do, and the setting travels with the character rather than having to be
remembered per stream.

**One case to watch:** with the chatter name off and the message off, a character that isn't
currently animating shows nothing but static art. That's indistinguishable from broken. Worth a
subtle "someone is assigned" cue — a border tint, or the art at full opacity only when a chatter is
assigned — rather than leaving the operator guessing.

### Overlay sizing

An OBS browser source has a fixed width and height, but the page's content height now varies with
what's toggled on. Two ways to reconcile that.

**A. Art anchored to the top, source sized for the maximum.** Text sits below the art and collapses
when hidden, leaving transparent space at the bottom. Anchoring to the *top* is the important part:
anchor to the bottom and the character slides around the canvas every time a caption is toggled.

Cost: the source's bounding box is taller than the visible content, so dragging and scaling in OBS
means handling a box with dead air in it.

**B. Text overlaid on the lower part of the art.** Source height always equals art height, so
toggling changes nothing about the source — no resizing, no dead space, no arithmetic ever.

Cost: a different look, and captions land on the character if the art fills the frame.

**Decision: A**, because it preserves the current layout and is the smaller change. B is the more
robust answer and is the fix if the dead space turns out to be irritating in practice.

### The app should report the source size

It knows the art dimensions and the current toggle state, so it can do the arithmetic instead of a
README:

> **Player 1** · `http://127.0.0.1:5000/overlay?player=1` · **500 × 513** *(copy)*

Updating as toggles change. This removes the one piece of manual calculation left in OBS setup, and
it's the sort of thing nobody wants to re-derive six months later. It also belongs in the setup
screen's OBS step, where it's the entire content of that page.

---

## The voice table

Don't hardcode it. `SpeechSynthesizer.get_voices_async()` returns a `VoiceInfo` per voice carrying
`short_name`, `local_name`, `gender`, `locale` and — the useful one — **`style_list`**.

*(Verified against azure-cognitiveservices-speech 1.51.1.)*

This fixes a live bug. `azure_text_to_speech.py` line 29 already admits *"certain styles aren't
available on all voices"*, but the control panel offers all 9 styles for every voice, and `random`
picks from all 9 regardless. An unsupported pairing doesn't error — Azure renders it neutral and
says nothing. With `style_list` per voice:

- the style dropdown filters to what the selected voice actually supports
- `random` picks only from valid styles
- the hardcoded list of 8 voices goes away; you get everything the subscription offers, filtered by
  locale

`fetch_voices.py` calls the API once and writes `voices.json`. One network call, cached, rerun when
you want. The app reads the cache at startup and never blocks on Azure to render a dropdown.

**Edge case:** changing voice can invalidate the current style — a character on `whispering`
switched to a voice without it. Fall back to `random` and flash a note on the control panel. Silently
rendering neutral is the confusing behaviour this is meant to remove.

---

## Routes

| Route | Purpose |
|---|---|
| `GET /setup` | Character library UI — create, edit, assign, upload art |
| `POST /setup/character` | Create or update a character |
| `POST /setup/upload` | Art upload → `static/characters/` |
| `POST /setup/assign` | Assign a character to a slot |
| `POST /setup/save-default` | Write live voice/style back to the character |

Whether `/setup` is a new template or reuses the orphaned `templates/index.html` is worth deciding
when building it. `index.html` is 307 lines of the old three-panel markup and jQuery, currently
rendered by no route — possibly more to fight than a clean file.

---

## Live updates

The overlay already holds a socket. Assigning a character emits an `art_changed` event with the new
URLs and display settings; the page swaps `src` in place and shows or hides the name and message
boxes. No browser-source refresh, no OBS interaction.

Toggling a caption from the control panel is the same event with only the flags changed — the page
adds or removes a class, and the boxes collapse. Since the art is top-anchored, nothing moves.

**Cache busting is mandatory.** Browser sources cache images hard, so overwriting a PNG in place
changes nothing visible. Append the file's mtime as a query string (`?v=1722...`) and the swap is
reliable.

---

## Staging

Each stage leaves the app working.

**A. `characters.json` read path.** Load and merge over `PLAYER_CONFIG`; no UI. Hand-write the file
to test. Proves the merge and the fallback-to-defaults case.

**A2. Display toggles and the character name.** Overlay renders the character name above the chatter
name, and honours the three flags. Top-anchored art, collapsing boxes. Control panel gets the three
switches per player and the reported source size. Independent of art upload, so it can land as soon
as A does — and the message toggle alone is worth having before any of the rest.

**B. `fetch_voices.py` and `voices.json`.** Replace the hardcoded voice list; filter style dropdowns
by `style_list`. Independently useful — fixes the silent-style bug on its own, with no setup screen.

**C. `/setup` read-only.** Render the library and current assignments. No writes.

**D. Assignment and save-as-default.** The two write paths that don't involve file uploads, plus
`art_changed` on the socket.

**E. Art upload.** Last, because it's the only stage handling files from a form — needs extension and
size validation, and a decision on overwrite versus versioned filenames.

B is worth doing first if you want a win before the setup screen exists.

The `TWITCH_CHANNEL_NAME` env var is independent of all five and can land whenever.

**Docs to update as these land:** Stage 4 of the runbook describes the `player<N>-*.png` convention,
which characters replace. Each stage should carry its own doc change rather than leaving a sweep for
the end — that's how the README ended up describing the Move plugin months after it was gone. (The
env-var change already carried its own: both docs now list four variables and no source edit.)

---

## Decided

### `TWITCH_CHANNEL_NAME` becomes a fourth environment variable — **done**

Install-time configuration, not something the web UI touches — it's set once per install, not per
stream, so it doesn't belong in a character file either.

```python
TWITCH_CHANNEL_NAME = os.getenv('TWITCH_CHANNEL_NAME', 'silverstagvt')
```

Keeping the current value as the fallback means existing installs keep working. Setup becomes "set
four environment variables" with no `.py` edit at all, replacing "set three, then edit line 21."
It also keeps the channel name out of a public repo.

### Deleting a character removes the library entry, not the art

`characters.json` loses the entry; the PNGs stay on disk. Re-adding is pointing at the same files
again. A web form that deletes someone's artwork is alarming the one time it's wrong.

**Deletion is refused while the character is assigned to a slot** — "Goblin is in use by player 2."
One guard, and it can't surprise you mid-stream. Unassign first, then delete.

### Slot-level art overrides are removed

`chat_god_app.py` currently allows a slot to override the filename convention:

```python
"closed": config.get("image_closed", f"characters/player{number}-closed.png")
```

Nothing uses those keys today. Once characters own art it's a second mechanism for the same job, and
the two can disagree — slot 1 saying `dragon.png` while its character says `goblin-open.png`. One of
them has to win, and that rule is exactly the sort of thing that's baffling six months later.

So `image_closed` / `image_open` come out of `PLAYER_CONFIG` when characters land. Art resolves
through the assigned character, one path, no precedence rules.

---

## Still open

Nothing blocking. Worth thinking about during stage E:

- **Overwrite or version uploaded art?** Uploading `goblin-open.png` twice — replace in place (simple,
  but the cache-buster becomes load-bearing) or write `goblin-open-2.png` and update the reference
  (no cache issues, accumulates files).
- **What signals "assigned but idle"** when both names and the message are hidden? Static art alone
  reads as broken. A border tint, or dimming the art until a chatter is assigned, are the obvious
  candidates — but it's a look decision, not a technical one.
- **Does the character name show when nobody is assigned?** Arguably yes: the Wizard exists whether
  or not someone is speaking as him, and a permanently-labelled slot is easier to read on stream.
  Means the overlay needs character state independent of chatter state.
