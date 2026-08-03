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
  },
  "casts": {
    "dnd-night": {
      "display_name": "D&D Night",
      "slots": { "1": "wizard", "2": "goblin", "3": "bard" }
    }
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

Character name on top and larger, chatter name smaller beneath it, both drawn **over** the lower
part of the art so neither affects the source height:

```
        ┌─────────────────┐
        │   character art │
        │                 │
        │   Henry Potter  │   <- character name, larger, over the art
        │    silverstagvt │   <- chatter name, smaller, over the art
        └─────────────────┘
        ┌─────────────────┐
        │ message text    │   <- the only caption that adds height
        └─────────────────┘
```

**The size hierarchy has to be set by caps, not by fitting.** `textfill` scales each box to fit its
own text, so sizing both purely to fit made whichever name was *shorter* the larger one — string
length deciding the visual hierarchy. Each box now has a `maxFontPixels` encoding its rank (30 and
18), and shrinking only happens when a name is too long to fit.

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

> **Revised after seeing A on stream: the names moved to B, the message stayed on A.**
>
> A was built and immediately felt wrong — every caption toggle meant resizing the source in OBS,
> which is exactly the friction B exists to remove. The names are short and sit over the lower part
> of the art comfortably, so they moved. The message text didn't: it's long enough to bury the
> character, and it's the caption most likely to be left off anyway.
>
> The result is that **only the message toggle changes the source height.** Both names are free.
> That's most of B's benefit without putting a paragraph of chat over someone's chest.
>
> Consequence to remember: the captions are inside the positioned `.character` element and need
> `z-index` above the open-mouth image, or they vanish for as long as the mouth is open.

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

## Casts — loading a group of characters at once

A **cast** is a named set of slot assignments: "D&D Night" is wizard in 1, goblin in 2, bard in 3.
Applying it is one action instead of three, and it's how you'd switch shows between streams — or
between segments of the same stream.

**It is exactly N assignments, not a new mechanism.** Applying a cast loops the existing assign path
once per slot, which means it inherits everything already decided: each slot resets to its
character's default voice, style and display toggles, and each fires `art_changed` so the overlays
swap in place. Nothing new to specify about what applying one *does*. That's the whole reason to
model it this way rather than as a second kind of thing that also sets slots.

**Creating one is "save the current arrangement."** Same shape as *Save as default*, one level up:
arrange the slots by hand, like what you see, name it. Hand-authoring the JSON works too, but nobody
should have to. The two write paths — apply and save — are the whole feature.

**A cast names characters, not chatters.** Applying one changes the costumes, not who's wearing
them: whoever was assigned to slot 1 is still assigned to slot 1, now speaking as the bard. This
follows the rule already in the reset table — changing the cast is a reset point for the character,
and who's talking is a separate axis. Whether you'd *want* the pools cleared when switching shows is
listed as open below.

**Slots the cast doesn't mention are left alone.** A cast written when three slots existed, applied
after you add a fourth, leaves slot 4 as it was rather than clearing it. Silent clearing is worse:
a slot going empty mid-stream reads as breakage. `null` is still available as an explicit "empty
this slot", so the cast can say so when it means it.

**The mid-stream hazard is real and worth designing against.** One click changes every character on
screen and discards every live voice override you'd made since the last assignment. That's a much
bigger blast radius than anything else on the control panel, and it sits next to buttons you press
routinely. At minimum it wants confirmation naming what's about to change; the alternative is
keeping casts on `/setup` and out of the control panel entirely, which trades the accident risk for
not being able to switch shows quickly while live.

**Depends on stage D**, since it's built on the assignment write path. Not worth attempting before
single-slot assignment works.

---

## Appearance settings — an endpoint for the look

Everything about how the overlay *looks* is currently a constant in source. Changing a font size
means editing `characters.py`; changing the typeface means editing the stylesheet *and* a `<link>` in
the template; changing how twitchy the mouth is means editing `overlay.html`. All fine for the person
who wrote them and hopeless for anyone else — and all exactly the kind of thing you fiddle with
repeatedly before settling.

### What's currently hardcoded

| Value | Lives in | What it does |
|---|---|---|
| `CAPTIONS` fonts and boxes | `characters.py` | Caption text size and line height |
| `font-family: 'Roboto'` | `static/css/overlay.css`, loaded in `overlay.html` | The typeface, everywhere |
| `OPEN_THRESHOLD` | `templates/overlay.html` | How loud counts as mouth-open |
| `MIN_HOLD_MS` | `templates/overlay.html` | Minimum gap between mouth swaps |
| `FALLBACK_FLAP_MS` | `templates/overlay.html` | Flap rate when WebAudio is unavailable |
| `.overlay-row` gap | `static/css/overlay.css` | Spacing in the all-players view |
| Caption colours and outlines | `static/css/overlay.css` | Legibility over art |
| Default reported width (500) | `templates/control.html` | Starting point for the source size |

The mouth-tuning three are the strongest case. They're the values most likely to need adjusting for
a given piece of art, and they're buried in a template a non-developer will never open.

### Where the values live

**An `"appearance"` block in `characters.json`**, rather than a new file. Same lifecycle as the rest
of it — per-machine, gitignored, written by `/setup` — and a separate file for a dozen numbers earns
nothing but another thing to lose. It sits alongside `characters` and `slots` as a third top-level
key, defaults merged underneath, so an absent block behaves exactly as now.

*Not* `config.json`: that's install credentials, set once and never touched again. Appearance is the
opposite — fiddled with constantly, and useless to hand someone pre-configured.

### Live application, no restart

**This is the part the current structure already pays for.** Every caption size is rendered as a CSS
custom property, so applying a new value at runtime is:

```js
document.documentElement.style.setProperty('--character-name-font', '26px');
refit();
```

An `appearance_changed` socket event carrying the changed values is the whole mechanism. No restart,
no browser-source refresh, no cache problem — which matters because tuning is inherently iterative
and doing it mid-stream is the point. The mouth constants are plain JS variables and update the same
way.

**One implementation consequence:** `CAPTIONS` is a module-level constant read at import. Live
editing means it becomes mutable state with a load-and-merge on write, the same shape `characters.py`
already has for the library. Small, but it's the difference between this being easy and being a
refactor.

### Font selection

The typeface is the single biggest lever on how the overlay *feels* — a wizard captioned in Roboto
looks like a web form — and it's currently one hardcoded value in the stylesheet plus a matching
`<link>` in the template. Selecting one is part of this stage.

**Where the fonts come from is the real decision, and it isn't a style question.** `overlay.html`
loads Roboto from `fonts.googleapis.com` right now, so the overlay already depends on Google being
reachable *while streaming*. That's a live dependency on a third party for something on screen. It
has been fine, but widening it — a picker over dozens of Google families — makes a stream-time
outage more visible rather than less.

| Source | Cost |
|---|---|
| **Google Fonts** | Widest choice, zero setup, but a network dependency at stream time and the family list needs maintaining |
| **System fonts** | No network at all, but the setup page can't enumerate what's installed — the user types a name and finds out if it worked |
| **Uploaded font files** | Fully offline and fully theirs, but needs the upload machinery from stage E and a licence question nobody wants to think about |

**Leaning: a short curated list of Google families, downloaded to `static/fonts/` at pick time
rather than linked.** One fetch when you choose it, served locally forever after, no stream-time
dependency on anyone. That's more work than a `<link>` but it removes a whole class of live failure,
which is the same reasoning that took OBS websockets out of the startup path.

**Four things that bite:**

**Weights have to be loaded, not synthesised.** The character name is `font-weight: 700`. A family
loaded at 400 only will be faux-bolded by the browser, which looks smeared against an outline.
Whatever the mechanism, it fetches the weights actually used.

**Font metrics change what fits.** Box heights tuned for Roboto can clip descenders in something
taller. `textfill` handles width automatically, but the boxes don't resize themselves — so changing
family should prompt a look at the sizes, and the two controls belong on the same page.

**Preview in the actual font, not a dropdown of names.** Choosing type blind from a list is how you
end up switching six times mid-stream.

**Fallback matters more here than usual.** `font-family: 'Chosen', 'Roboto', sans-serif` — if the
chosen font fails to load, an overlay in a default sans is survivable; one that renders in a
serif-by-accident at the wrong size is not.

### Guardrails

**Clamp server-side.** A font of 400 or a threshold of 0 produces an overlay that looks broken, and
the person who typed it is now debugging live. Every value wants a sane range, enforced where it's
written rather than trusted from a form.

**A reset-to-defaults button is not optional.** It's the way back when someone has made the text
invisible and can't read the control that would fix it.

**Warn when a change affects the source size.** Raising the message box height changes how tall the
browser source must be, and OBS won't resize itself. The panel already reports the size, so the
warning is really just "look at that number again."

### Staging

**G. Appearance settings.** Independent of C–F — it needs a `/setup` page but not the character
library's write paths, so it could land before assignment does. `POST /setup/appearance` writes the
block; `appearance_changed` applies it live.

Worth doing after the launcher (install stage B), which is higher value for the same effort.

### Open

- **Global or per-character?** Everything here is global. For *sizes* that's clearly right —
  `textfill` already shrinks a long name by itself, so per-character sizes buy little against three
  more fields each. For **typeface it's less obvious**: a serif for the wizard and something blocky
  for the goblin is a real thing someone would want, and it's arguably as much a character trait as
  their voice. The counter is that mixed typefaces across slots usually look like a mistake. Global
  first, and revisit if it's the first thing anyone asks for.
- **Colours too, or just sizes?** Colour pickers are more UI than number boxes, and the outlines are
  tuned for legibility over arbitrary art. Sizes and family first.
- **How many families in the list?** Long enough to feel like a choice, short enough that someone
  picks one and moves on. A dozen, chosen for legibility at small sizes over an outline, beats
  exposing all of Google Fonts.

---

## Routes

| Route | Purpose |
|---|---|
| `GET /setup` | Character library UI — create, edit, assign, upload art |
| `POST /setup/character` | Create or update a character |
| `POST /setup/upload` | Art upload → `static/characters/` |
| `POST /setup/assign` | Assign a character to a slot |
| `POST /setup/save-default` | Write live voice/style back to the character |
| `POST /setup/cast/apply` | Apply a cast — assign every slot it names |
| `POST /setup/cast/save` | Save the current slot arrangement as a named cast |
| `GET /setup/appearance` | Caption sizes and mouth tuning, applied live |
| `POST /setup/appearance` | Write the appearance block and broadcast it |

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

> This applies to **stylesheets too**, which the first version of A2 missed — and the failure is
> worse than for images. A stale stylesheet doesn't merely look old: the page keeps toggling classes
> against rules the browser doesn't have, so captions silently stop hiding and new elements render
> unstyled, with every symptom pointing at the code. `static_v()` in `chat_god_app.py` now stamps
> stylesheet URLs with their mtime; art uploads at stage E should reuse it.

---

## Staging

Each stage leaves the app working.

**A. `characters.json` read path — done.** `characters.py` loads and merges over `PLAYER_CONFIG`; no
UI. A missing or malformed file falls back to the pre-library behaviour exactly, and the app says
which it used at startup. `characters.example.json` is the tracked template.

**A2. Display toggles and the character name — done.** Overlay renders the character name above the
chatter name and honours the three flags; boxes `display:none` so they collapse rather than leaving
gaps, and `.overlay-row` is `flex-start` so the art never moves. Control panel has the three switches
per player and reports the source size with a width input and a copy button.

> Two things worth knowing about how A2 landed. **Box heights live in `characters.py`**, rendered
> into the overlay as CSS custom properties, because the same numbers drive both the layout and the
> reported source size — defining them only in the stylesheet would let an edit silently start
> clipping the message box. And **the size arithmetic is split**: the server decides which boxes
> count (including that a character with no `display_name` never counts its name box) and sends the
> art ratio plus the box total; the browser does one multiply. That keeps the fiddly half in one
> language while still letting the width input update live.

**B. `fetch_voices.py` and `voices.json`.** Replace the hardcoded voice list; filter style dropdowns
by `style_list`. Independently useful — fixes the silent-style bug on its own, with no setup screen.

**C. `/setup` read-only.** Render the library and current assignments. No writes.

**D. Assignment and save-as-default.** The two write paths that don't involve file uploads, plus
`art_changed` on the socket.

**E. Art upload.** Last, because it's the only stage handling files from a form — needs extension and
size validation, and a decision on overwrite versus versioned filenames.

**F. Casts.** Apply and save a named group of slot assignments. Built entirely on D's assign path, so
it's small once D exists and impossible before it. Independent of art upload, so it can land before
or after E.

**G. Appearance settings.** Typeface, caption sizes and mouth tuning moved out of source into an
`appearance` block in `characters.json`, applied live over the socket. Needs a `/setup` page but none
of the library's write paths, so it's independent of D–F — see *Appearance settings* above.

Font selection is the part with a hidden cost: choosing a family is easy, but doing it without
adding a stream-time dependency on Google Fonts means downloading the family locally when it's
picked. Worth splitting if G gets long — sizes and mouth tuning first, typeface second.

B is worth doing first if you want a win before the setup screen exists.

The `TWITCH_CHANNEL_NAME` env var is independent of all five and can land whenever.

**Docs to update as these land:** Stage 4 of the runbook describes the `player<N>-*.png` convention,
which characters replace. Each stage should carry its own doc change rather than leaving a sweep for
the end — that's how the README ended up describing the Move plugin months after it was gone. (The
env-var change already carried its own: both docs now list four variables and no source edit.)

---

## Decided

### The channel name becomes a fourth environment variable — **done**

Install-time configuration, not something the web UI touches — it's set once per install, not per
stream, so it doesn't belong in a character file either.

```python
TWITCH_CHANNEL_NAME = setting('twitch_channel')   # CHATGOD_TWITCH_CHANNEL
```

Keeping the current value as the fallback means existing installs keep working. Setup becomes "set
four environment variables" with no `.py` edit at all, replacing "set three, then edit line 21."
It also keeps the channel name out of a public repo.

All four variables since moved behind `config.py` and gained the `CHATGOD_` prefix, with the
unprefixed names still read as a fallback. See the guided-install design for the resolution order.

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

And during stage F:

- **Should applying a cast clear the chatter pools?** Keeping them treats a cast as a costume change,
  which is right mid-stream. Switching to an entirely different show with the last show's viewers
  still queued in slot 2 is the case for clearing. Possibly a checkbox on the confirmation rather
  than a fixed rule.
- **Can a cast carry voice overrides?** As specced it names characters only, so voices come from each
  character's defaults. Letting a cast pin a voice would mean the same character sounding different
  between shows — useful, but it adds a fourth layer to a resolution order that's currently three
  and readable.
- **Where do casts live in the UI?** `/setup` is safe; the control panel is fast. See the mid-stream
  hazard above — this is the decision that section is really about.
