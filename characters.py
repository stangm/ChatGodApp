"""
The character library: who can appear in a slot, and how they look.

A **character** is the persistent thing — art, a display name, a default voice, and
whether its captions show. A **slot** is a numbered position on stream that a
character is assigned to, and that chatters get assigned to in turn. "Henry Potter
the wizard" is the character; whoever is speaking as him changes every few minutes.

Read path only. Nothing here writes `characters.json` — that's the setup screen,
stage D. Hand-write the file to test.

**A missing file is the normal case, not an error.** Without one, every slot gets a
character synthesized from `players.py` and the `characters/player<N>-*.png` naming
convention, which is exactly what the app did before this module existed. A fresh
clone still runs, and nothing about the current install changes until a
`characters.json` appears.

**A malformed file falls back the same way, loudly.** JSON that doesn't parse is a
typo in a file you hand-edited, and the useful response is to say so and keep
running rather than refusing to start ten minutes before a stream.
"""

import json
import os
import re
import struct
import threading

from players import PLAYER_CONFIG, DEFAULT_VOICE_STYLE

CHARACTERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "characters.json")
STATIC_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

DISPLAY_FLAGS = ("show_character_name", "show_chatter_name", "show_message")

# Vertical space each caption adds BELOW the art, including its margin.
#
# Both names are drawn over the bottom of the art rather than under it, so they add
# nothing -- which is the point. Toggling a name can't change how tall the browser
# source needs to be, so there's no resizing in OBS and no arithmetic to redo. The
# message text is still stacked underneath, because it's long enough to bury the
# character if it sits on top.
#
# The zero entries are deliberate rather than missing: every display flag appears
# here, so the height calculation stays a total function over the flags and a future
# caption can't be silently forgotten.
#
# These live here rather than only in overlay.css because two things must agree on
# them: the CSS laying the boxes out, and the arithmetic reporting the OBS source
# height. A stylesheet edit that didn't update the reported size would silently start
# clipping the message box. overlay.html renders them as CSS custom properties, so
# this is the one place they're defined.
BOX_HEIGHTS = {
    "show_character_name": 0,    # drawn over the art
    "show_chatter_name": 0,      # drawn over the art
    "show_message": 79,          # 85px box - 6px overlap, stacked below
}

# ---------------------------------------------------------------------------
# Caption sizing -- THE place to change how the overlay text looks
# ---------------------------------------------------------------------------
#
# "font" is the size the text is drawn at when it fits. "box" is the space the line
# occupies. Both are rendered into the page: the font as a CSS custom property and
# as textfill's maxFontPixels, the box as the element's height.
#
# Sizes have to live in one place because textfill sets an inline font-size that
# beats the stylesheet. Change the CSS alone and nothing happens, which is a
# genuinely baffling ten minutes -- so the stylesheet reads these values too.
#
# **The hierarchy comes from these numbers, not from fitting.** textfill only shrinks
# text below its max when it doesn't fit, so as long as character_name's font is
# larger than chatter_name's, the character name is the larger of the two whenever
# both fit. Sizing purely to fit made whichever name was *shorter* the bigger one.
#
# Rules of thumb when adjusting:
#   - keep box comfortably above font (roughly font + 6) or descenders clip
#   - raising the message box changes the browser source height; the names don't,
#     because they're drawn over the art
#   - a font raised far above its box just gets shrunk straight back by textfill
CAPTIONS = {
    "character_name": {"font": 30, "box": 36},
    "chatter_name":   {"font": 18, "box": 24},
    "message":        {"font": 15, "box": 85},
}

# Kept as its own name because the template and stylesheet want just the heights.
BOX_SIZES = {name: spec["box"] for name, spec in CAPTIONS.items()}
CAPTION_FONTS = {name: spec["font"] for name, spec in CAPTIONS.items()}


class Character:
    """One entry in the library, with everything the overlay needs to draw it."""

    def __init__(self, id, display_name="", art_closed=None, art_open=None,
                 default_voice=None, default_style=DEFAULT_VOICE_STYLE, **flags):
        self.id = id
        self.display_name = (display_name or "").strip()
        self.art_closed = art_closed
        self.art_open = art_open
        self.default_voice = default_voice
        self.default_style = default_style
        for flag in DISPLAY_FLAGS:
            setattr(self, flag, bool(flags.get(flag, True)))

    @property
    def has_name(self):
        """
        Whether the character name can be shown at all.

        A character with no display name and show_character_name on would render an
        empty box that still eats 54px of the browser source -- so the flag alone
        isn't enough to decide, and every caller has to ask this instead.
        """
        return bool(self.display_name)

    def display(self):
        """The three flags as a plain dict, for the socket and the template."""
        return {flag: getattr(self, flag) for flag in DISPLAY_FLAGS}


def _conventional(number, config):
    """
    The character a slot gets when no library entry claims it.

    This is the pre-library behaviour preserved exactly: art by filename convention,
    voice from players.py, every caption on, and no character name -- because there
    was nowhere to have put one.
    """
    return Character(
        id=f"player{number}",
        display_name="",
        art_closed=f"characters/player{number}-closed.png",
        art_open=f"characters/player{number}-open.png",
        default_voice=config.get("voice_name"),
        default_style=DEFAULT_VOICE_STYLE,
    )


def _read_file():
    """Parsed characters.json, or None if it's absent or unreadable."""
    if not os.path.exists(CHARACTERS_FILE):
        return None
    try:
        with open(CHARACTERS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"characters.json could not be read ({exc}); using defaults from players.py.")
        return None
    if not isinstance(data, dict):
        print("characters.json isn't a JSON object; using defaults from players.py.")
        return None
    return data


class Library:
    """
    The character library, as an editable thing rather than a one-shot read.

    Stage A only ever read `characters.json` at startup, so a module function that
    returned resolved slots was enough. Assignment needs more: the raw entries (to
    list and edit them), the slot map (to change it), and a way to write the file
    back. This holds all three and derives the resolved view on demand.

    **Unknown top-level keys are preserved on write.** The file already carries
    `_comment` from the example, and the design has `casts` and `appearance` blocks
    arriving later. Rewriting the file from only the keys this class understands
    would silently delete whatever it didn't -- and the first person to notice would
    be someone whose casts vanished when they renamed a character.
    """

    def __init__(self):
        self.characters = {}    # id -> raw dict, as stored
        self.slots = {}         # number -> char_id, or None for deliberately empty.
                                # A missing key means "not mentioned", which is a
                                # third state: fall back to the naming convention.
        self.extra = {}         # top-level keys this class doesn't interpret
        self.source = "defaults"
        self._lock = threading.Lock()

    # -- reading --------------------------------------------------------------

    def load(self):
        """Read the file. Safe to call again; a bad file leaves defaults in place."""
        data = _read_file()
        if data is None:
            self.characters, self.slots, self.extra = {}, {}, {}
            self.source = "defaults"
            return self

        self.characters = dict(data.get("characters") or {})
        self.extra = {k: v for k, v in data.items() if k not in ("characters", "slots")}

        self.slots = {}
        for number, assigned in (data.get("slots") or {}).items():
            self.slots[number] = (assigned.get("character")
                                  if isinstance(assigned, dict) else assigned)

        self.source = "file"
        return self

    def resolved(self):
        """
        {number: Character} covering exactly the slots in PLAYER_CONFIG.

        An empty slot is a Character with no art, which the overlay renders as
        nothing. An unknown character id is a typo, so it warns and falls back to the
        convention: a mistyped name silently blanking a slot mid-stream is worse than
        a visible fallback.
        """
        return {number: self._resolve_one(number, config)
                for number, config in PLAYER_CONFIG.items()}

    def _resolve_one(self, number, config):
        if number not in self.slots:
            return _conventional(number, config)

        char_id = self.slots[number]
        if char_id is None:
            # Deliberately empty. Every caption off as well as no art: an empty slot
            # that still reserved space for two blank boxes would push the browser
            # source taller than the nothing it draws.
            return Character(id="", display_name="",
                             **dict.fromkeys(DISPLAY_FLAGS, False))

        entry = self.characters.get(char_id)
        if entry is None:
            print(f"Slot {number} is assigned to unknown character {char_id!r}; "
                  "using the default art for that slot.")
            return _conventional(number, config)

        return Character(
            id=char_id,
            display_name=entry.get("display_name", ""),
            art_closed=entry.get("art_closed"),
            art_open=entry.get("art_open"),
            default_voice=entry.get("default_voice") or config.get("voice_name"),
            default_style=entry.get("default_style", DEFAULT_VOICE_STYLE),
            **{flag: entry.get(flag, True) for flag in DISPLAY_FLAGS},
        )

    # -- writing --------------------------------------------------------------

    def save(self):
        """
        Write the file atomically. Returns (ok, message).

        Same pattern as usage.py: write a temp file then os.replace, so a crash
        mid-write can't leave a truncated characters.json -- which would take the
        whole library with it rather than one edit.

        Writing makes this file the app's own, which is why `extra` exists: anything
        the class didn't parse goes back untouched.
        """
        payload = dict(self.extra)
        payload["characters"] = self.characters
        payload["slots"] = {n: {"character": c} for n, c in self.slots.items()}

        tmp = CHARACTERS_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=False)
                fh.write("\n")
            os.replace(tmp, CHARACTERS_FILE)
        except (OSError, TypeError, ValueError) as exc:
            return False, f"Couldn't write characters.json: {exc}"

        self.source = "file"
        return True, "Saved."

    def assign(self, number, char_id):
        """
        Put a character in a slot. char_id of None empties it deliberately.

        Returns (ok, message). The caller is responsible for resetting the slot's
        live voice and display state -- that's a deliberate reset point and it lives
        with the managers that own that state, not here.
        """
        if number not in PLAYER_CONFIG:
            return False, f"There's no player {number}."
        if char_id is not None and char_id not in self.characters:
            return False, f"There's no character called {char_id!r}."

        with self._lock:
            self.slots[number] = char_id
            return self.save()

    def upsert(self, char_id, fields):
        """
        Create or update a character. Returns (ok, message).

        Merges rather than replaces, so a form that only sends the fields it edits
        can't blank the ones it didn't. Unknown keys are kept for the same reason
        `extra` exists at the top level.
        """
        char_id = (char_id or "").strip()
        if not char_id:
            return False, "A character needs an id."
        # Enforced here as well as at upload, because the id is what uploaded
        # filenames are derived from -- letting an unusable one into the library
        # would mean creating a character that can never have art.
        if not valid_id(char_id):
            return False, ("Ids can only use letters, numbers, hyphens and "
                           "underscores, and must start with a letter or number.")

        with self._lock:
            entry = dict(self.characters.get(char_id) or {})
            for key, value in fields.items():
                if key in DISPLAY_FLAGS:
                    entry[key] = bool(value)
                elif value is None or value == "":
                    # Empty means "no opinion" rather than "set to empty": clearing
                    # default_voice should fall back to players.py, not store "".
                    entry.pop(key, None)
                else:
                    entry[key] = str(value).strip()
            self.characters[char_id] = entry
            return self.save()

    def delete(self, char_id):
        """
        Remove a library entry. The art files on disk are left alone.

        **Refused while the character is assigned to a slot.** One guard, and it
        can't surprise anyone mid-stream. A web form that silently blanks a slot on
        stream is alarming the one time it's wrong.
        """
        if char_id not in self.characters:
            return False, f"There's no character called {char_id!r}."

        in_use = [n for n, c in self.slots.items() if c == char_id]
        if in_use:
            where = ", ".join(sorted(in_use))
            return False, (f"{char_id} is assigned to player {where}. "
                           "Unassign it first, then delete.")

        with self._lock:
            self.characters.pop(char_id, None)
            ok, message = self.save()
            return ok, "Deleted. The art files are still on disk." if ok else message


def load():
    """
    Backwards-compatible shim: (slots, source), as stage A returned.

    Kept because the resolved view is what most of the app wants, and it reads
    better than constructing a Library at every call site that only needs slots.
    """
    library = Library().load()
    return library.resolved(), library.source


# ---------------------------------------------------------------------------
# Art dimensions, so the app can report the OBS browser source size
# ---------------------------------------------------------------------------


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# Per file. Large enough for any sensible character, small enough that a browser
# source doesn't choke -- a 40MB PNG loads fine and then makes OBS miserable.
MAX_ART_BYTES = 8 * 1024 * 1024

# Character ids become filenames, so they have to be safe to put in a path. A
# user-supplied id containing a slash or ".." would otherwise let an upload write
# outside static/characters/, which is the classic way a file upload becomes a
# remote write primitive.
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def png_size(header):
    """
    (width, height) from the first 24 bytes of a PNG, or None if it isn't one.

    Takes bytes rather than a path so the same check works on an upload still in
    memory and on a file already on disk. Reads the IHDR header directly rather than
    pulling in Pillow for eight bytes.
    """
    if len(header) < 24 or header[:8] != PNG_MAGIC:
        return None
    try:
        width, height = struct.unpack(">II", header[16:24])
    except struct.error:
        return None
    return (width, height) if width and height else None


def art_size(relative_path):
    """
    (width, height) of a PNG under static/, or None if it can't be determined.

    None is a real answer -- a missing file, or art that isn't a PNG -- and callers
    report the size as unknown rather than guessing, since a wrong number here means
    a clipped message box that's baffling to diagnose.
    """
    if not relative_path:
        return None
    path = os.path.join(STATIC_ROOT, relative_path.replace("/", os.sep))
    try:
        with open(path, "rb") as fh:
            return png_size(fh.read(24))
    except OSError:
        return None


def valid_id(char_id):
    """Whether a character id is safe to use as part of a filename."""
    return bool(ID_PATTERN.match(char_id or ""))


def art_path(char_id, which):
    """Where a character's uploaded art lives. Derived, never user-supplied."""
    return f"characters/{char_id}-{which}.png"


def save_art(char_id, which, data, other_size=None):
    """
    Write one uploaded PNG. Returns (ok, message, relative_path_or_None).

    Validation, in the order that gives the most useful message first:

    1. **Actually a PNG**, by magic bytes rather than by filename. An extension is a
       claim; the header is evidence.
    2. **Within the size cap.**
    3. **Matching its counterpart's dimensions.** This is the one that matters. Art
       whose open and closed frames differ in size makes the character visibly jump
       every time it speaks -- and on stream that reads as a rendering bug rather
       than as a mismatched pair, so it's worth refusing outright rather than
       accepting and letting someone discover it live.
    """
    if not valid_id(char_id):
        return False, "That character id can't be used as a filename.", None
    if which not in ("closed", "open"):
        return False, f"Unknown art slot {which!r}.", None

    if len(data) > MAX_ART_BYTES:
        mb = MAX_ART_BYTES // (1024 * 1024)
        return False, f"That file is over {mb}MB. Resize it and try again.", None

    size = png_size(data[:24])
    if size is None:
        return False, "That isn't a PNG. Save it as a PNG and try again.", None

    if other_size and size != other_size:
        return False, (f"The two images are different sizes -- {size[0]}x{size[1]} "
                       f"and {other_size[0]}x{other_size[1]}. They must match, or the "
                       "character jumps every time its mouth moves."), None

    relative = art_path(char_id, which)
    full = os.path.join(STATIC_ROOT, relative.replace("/", os.sep))
    try:
        os.makedirs(os.path.dirname(full), exist_ok=True)
        tmp = full + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, full)
    except OSError as exc:
        return False, f"Couldn't save the image: {exc}", None

    return True, f"Uploaded {size[0]}x{size[1]}.", relative


def size_parts(character, flags):
    """
    The pieces the browser source height is built from, or None if art size is
    unknown: {"art_w", "art_h", "boxes"}.

    height = round(width * art_h / art_w) + boxes

    Split this way because the control panel lets you pick a width and shows the
    height live. Sending the finished number would mean recomputing it in
    JavaScript on every keystroke, which puts the formula in two languages -- and
    the fiddly half of it is deciding *which* boxes count, not the multiplication.

    So the policy stays here: which captions are visible, and the rule that a
    character with no display name never counts the character-name box however the
    flag is set. The browser is left with one multiply and one add.
    """
    if character is None or not character.art_closed:
        return None
    size = art_size(character.art_closed)
    if size is None:
        return None

    boxes = 0
    for flag, height in BOX_HEIGHTS.items():
        if not flags.get(flag):
            continue
        if flag == "show_character_name" and not character.has_name:
            continue
        boxes += height

    return {"art_w": size[0], "art_h": size[1], "boxes": boxes}


def source_size(character, flags, width=500):
    """
    Finished browser source dimensions: (width, height), or None if unknown.

    Too short clips the message box; too tall only leaves transparent space, which
    is harmless. So an unknown art size reports as unknown rather than as a guess
    that might crop.
    """
    parts = size_parts(character, flags)
    if parts is None:
        return None
    return width, round(width * parts["art_h"] / parts["art_w"]) + parts["boxes"]
