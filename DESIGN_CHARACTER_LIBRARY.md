# Design: character library and setup screen

**Status: stages A, A2, B, C, D, E and H are built.** Remaining: F (casts) and G (appearance). The
staging section at the bottom marks each one, and the notes under the built stages record what
changed during implementation — several decisions here were revised once they met reality, and those
revisions are marked inline rather than by rewriting the original reasoning.

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

Art paths are relative to `static/`, the same convention `chatmob_app.py` already resolves through
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

> **This has to hold in three places, which took two attempts to get right.** The control panel
> narrowed its dropdown from the start; `/setup` was built later and didn't, so it displayed
> "Aria — 16 styles" beside a list of all thirty. Worse than the panel's version of the same bug,
> because a bad *default* is wrong every time that character is assigned rather than for one session.
>
> The narrowing logic now lives in `static/js/voice-styles.js`, shared by both screens — copying it
> is what let them drift in the first place. And `Library.upsert()` clamps server-side, because the
> dropdown is only a UI guard and the docs actively encourage hand-editing `characters.json`.
>
> Deliberately **not** clamped on load: rewriting someone's file at startup without being asked is
> worse than showing the problem. `/setup` surfaces it as a note when the page opens, and synthesis
> already falls back safely regardless, so nothing misbehaves in the meantime.

> **`none` became a first-class style**, which the original design missed. `random` was serving as
> both "pick one each message" and "do nothing", depending on whether the voice had any styles —
> one word, two behaviours — and there was no way at all to ask an expressive voice to speak plainly.
> Aria has 16 styles, so `random` guaranteed every line got an emotional delivery.
>
> Unsupported styles now fall back to `none` rather than to a random one. Substituting a different
> emotion for the one that was requested is a bigger change than declining to apply any: a chatter
> who types `(whispering)` and hears shouting has been actively misled, where plain delivery is
> simply the request not landing. `random` is also no longer offered on voices without styles, since
> there it named something that couldn't happen.

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

## Splitting `/setup` up

The first version put slots and the whole character library on one page, with every character fully
expanded — roughly ten form controls each. Fine at three characters, unusable at fifteen, and it gets
worse in a specific way: **the frequently-used part gets pushed further down every time you add a
character you rarely touch.**

**The real problem is one page doing two unrelated jobs.**

| Task | How often | What it needs |
|---|---|---|
| Assigning characters to slots | Often — between streams, sometimes during | One screen, no scrolling, no thinking |
| Editing a character's voice, art, captions | Rarely — once when created, occasionally after | Room to show everything at once |

Bundling them means the rare task's bulk is permanently in the way of the frequent one.

### The shape

**`/setup` becomes slots only.** One compact row per player: current character, a dropdown to change
it, the live voice, and *save as default*. **Bounded by the number of players, not the number of
characters**, so it fits on one screen permanently — which is the whole point.

**`/setup/characters` is the library, as a grid of art.** Characters are *pictures*; a wall of
thumbnails with names under them lets you find the goblin by looking rather than by reading a list of
ids. Each card carries the art, the display name, and a badge when it's in a slot. Nothing else — no
fields, no buttons beyond opening it.

**`/setup/character/<id>` is one character, alone on a page.** This is the move that actually solves
the clutter, because the editor stops competing for space: voice, style, the three caption toggles,
both art frames shown large, upload controls and delete, all comfortably laid out.

### Why a page rather than an accordion or a modal

**No new JavaScript.** Expanding rows or a dialog both need state management that doesn't exist yet.
A page per character is a link and a form post, which is what the rest of `/setup` already is. The
project has kept its JS to two small shared files; this keeps it there.

**Linkable.** You can bookmark a character's editor.

**It leaves room for stages F and G.** Casts and appearance settings both want to live under
`/setup`. Once it's a small hub with sections instead of one long page, they're two more entries
rather than two more scrolls.

### Create and edit should be one path

The current page has a *New character* form separate from the per-character edit form — two forms
with overlapping fields that have to stay in sync. That's exactly the drift that produced the style
dropdown bug, where `/setup` and the control panel disagreed for weeks.

So: **New character** creates a blank entry and redirects into its editor. One form, one code path,
and the id is the only thing the create step needs to ask for.

### Deliberately not building

- **Search or filter.** Doesn't earn its place until roughly twenty characters, and a visual grid
  pushes that a long way out.
- **Drag-and-drop assignment.** Looks impressive, costs a lot, and a dropdown is faster for three
  slots.
- **Inline editing in the grid.** That's the current problem in a smaller box.

---

## Routes

| Route | Purpose |
|---|---|
| `GET /setup` | Slots: what's assigned where, and save-as-default |
| `GET /setup/characters` | The library, as a grid of art |
| `GET /setup/character/<id>` | One character's editor |
| `POST /setup/character` | Create or update a character |
| `POST /setup/upload` | Art upload → `static/characters/` |
| `POST /setup/assign` | Assign a character to a slot |
| `POST /setup/save-default` | Write live voice/style back to the character |
| `POST /setup/cast/apply` | Apply a cast — assign every slot it names |
| `POST /setup/cast/save` | Save the current slot arrangement as a named cast |
| `GET /setup/appearance` | Caption sizes and mouth tuning, applied live |
| `POST /setup/appearance` | Write the appearance block and broadcast it |

`templates/index.html` was not reused — `setup.html` was written fresh. That leaves index.html as
307 lines of superseded markup no route renders, which should now just be deleted.

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
> unstyled, with every symptom pointing at the code. `static_v()` in `chatmob_app.py` now stamps
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

**C. `/setup` read-only — done**, and **D. Assignment and save-as-default — done.** Built together,
because a read-only screen is a page you look at once and a write path with no screen can't be
exercised. `/setup` lists the slots and the library, and the four write endpoints are assign,
create/update, save-as-default and delete.

> **Creating and editing characters landed here rather than at E**, since neither involves a file
> upload — art paths are typed as text for now. That leaves E as purely the upload problem, which is
> the part with validation and overwrite questions attached.
>
> **`Library` preserves top-level keys it doesn't understand.** The file already carries `_comment`,
> and `casts` and `appearance` are specced to live alongside. Rewriting it from only the known keys
> would silently delete the rest, and the first person to notice would be someone whose casts
> vanished when they renamed a character.
>
> **Writes are atomic** — temp file then `os.replace`, the same pattern as `usage.py`. A crash
> mid-write would otherwise take the whole library rather than one edit.
>
> **Assignment resets the slot, editing doesn't.** Assigning is the deliberate reset point from the
> table above, so voice, style and captions all snap to the new character's defaults. Editing a
> character that's already on screen redraws it without touching the live values, since you're
> adjusting the thing already there rather than replacing it.

**E. Art upload — done.** File pickers on `/setup`, writing into `static/characters/`.

> **Overwrite, not versioned filenames** — the question left open below. The doc's worry was that
> overwriting makes the cache-buster load-bearing; it already is, since `art_url()` stamps every art
> URL with the file's mtime and the same mechanism carries the stylesheets. Versioning would
> accumulate `wizard-open-2.png` forever for no benefit.
>
> **Filenames are derived from the character id**, never taken from the upload. A user-supplied
> filename is a path traversal waiting to happen, so ids are constrained to letters, numbers,
> hyphens and underscores — enforced both at upload and when a character is created, since creating
> an id that can never hold art would be a strange kind of valid.
>
> **The pair is validated together before either frame is written.** Mismatched dimensions make the
> character jump every time it speaks, and on stream that reads as a rendering bug rather than as
> mismatched art. Writing one frame and refusing the other would produce exactly that state.

**F. Casts.** Apply and save a named group of slot assignments. Built entirely on D's assign path, so
it's small once D exists and impossible before it. Independent of art upload, so it can land before
or after E.

**G. Appearance settings.** Typeface, caption sizes and mouth tuning moved out of source into an
`appearance` block in `characters.json`, applied live over the socket. Needs a `/setup` page but none
of the library's write paths, so it's independent of D–F — see *Appearance settings* above.

Font selection is the part with a hidden cost: choosing a family is easy, but doing it without
adding a stream-time dependency on Google Fonts means downloading the family locally when it's
picked. Worth splitting if G gets long — sizes and mouth tuning first, typeface second.

**H. Split `/setup` into slots, library and per-character editor — done.** Three pages as described
in *Splitting `/setup` up*. The write endpoints kept their URLs; what changed is that each one now
redirects back to the page it was used from rather than always landing on `/setup`, so editing a
character returns you to that character.

> Create and edit merged as planned: `POST /setup/character/new` takes only an id, creates a blank
> entry and redirects into the editor. The duplicate "new character" form is gone.

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
TWITCH_CHANNEL_NAME = setting('twitch_channel')   # CHATMOB_TWITCH_CHANNEL
```

Keeping the current value as the fallback means existing installs keep working. Setup becomes "set
four environment variables" with no `.py` edit at all, replacing "set three, then edit line 21."
It also keeps the channel name out of a public repo.

All four variables since moved behind `config.py` and gained the `CHATMOB_` prefix, with the
unprefixed names still read as a fallback. See the guided-install design for the resolution order.

### Deleting a character removes the library entry, not the art

`characters.json` loses the entry; the PNGs stay on disk. Re-adding is pointing at the same files
again. A web form that deletes someone's artwork is alarming the one time it's wrong.

**Deletion is refused while the character is assigned to a slot** — "Goblin is in use by player 2."
One guard, and it can't surprise you mid-stream. Unassign first, then delete.

### Slot-level art overrides are removed

`chatmob_app.py` currently allows a slot to override the filename convention:

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

---

## Idea: art that changes with the speaking style

**Not designed, not scheduled.** Came from stream feedback: an angry face when someone types
`(angry)`, a sad one for `(sad)`. Recorded here so the constraints are known when it's picked up,
because two of them would be easy to get wrong.

**The art must follow the *resolved* style, not the requested one.** A chatter types `(whispering)`,
the voice doesn't support it, and `resolve_style()` returns none — so keying off the prefix would put
a whispering face over a completely neutral delivery. Same whenever a style is dropped for any other
reason. The `speak` payload currently carries only the player, the speaker and the audio URL, so
**step one is putting the resolved style in that payload** and driving the art from it.

**Sparse, with a fallback to the default face.** Azure has around thirty styles and nobody is drawing
sixty PNGs; realistically a character gets three or four. So the map should be partial and anything
missing falls back to the existing art — one rule, and it makes the feature useful at any level of
effort.

**Additive rather than a restructure.** Keeping `art_closed` / `art_open` as the default and adding
something like `art_styles: {"angry": {...}}` beside them means every existing character keeps
working untouched, which is the compatibility guarantee that's held since stage A.

**Preloading matters.** Swapping `src` to a frame the browser hasn't cached gives a blank character
for a beat — precisely at the moment they start talking. All frames want loading up front.

**Dimensions must match across the whole set**, not just within a pair. A differently-sized angry
frame makes the character jump whenever they get cross. The pair check from stage E extends
naturally: validate every frame against the character's default art.

**`random` will change the face every message.** A character defaulting to `random` resolves to a
different style per line, so the expression would flick between sets constantly. Either delightful or
exhausting depending on the show, but worth knowing before seeing it live.

### One closed mouth, many open mouths

Mark's idea, and it halves the art — which is the part that would otherwise stop this.

The consequence to weigh: with a shared closed frame, **the emotion is only visible while the mouth
is open**, and during speech that alternates many times a second. So it works when the emotion lives
in the *mouth* — a snarl versus a neutral O — and reads as a flicker when it lives in the *face*,
since raised eyebrows would blink on and off with each mouth swap.

Suggests a middle option: a shared closed frame for most emotions, and a full pair only for the one
or two where the whole face changes. Which the sparse model above already allows without any extra
mechanism.

**The real cost is the upload UI, not the logic.** Two file pickers becomes two per emotion, which is
the clutter problem stage H just solved — so it wants its own section on the character editor, or a
sub-page per style.

**Worth noting it isn't really about emotions.** The mechanism is "art variants keyed by style", and
the same code would serve costumes or scene-specific looks.
