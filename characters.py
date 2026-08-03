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
import struct

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


def load():
    """
    Resolve every slot to a Character.

    Returns (slots, source) where slots is {number: Character} covering exactly the
    slots in PLAYER_CONFIG, and source is 'file' or 'defaults' -- the app says which
    at startup, because "my edits aren't taking effect" is otherwise a silent
    failure.

    An empty slot is a Character with no art, which the overlay renders as nothing.
    An unknown character id is a typo, so it warns and falls back to the convention:
    a mistyped name silently blanking a slot mid-stream is the worse outcome.
    """
    data = _read_file()
    if data is None:
        return {n: _conventional(n, c) for n, c in PLAYER_CONFIG.items()}, "defaults"

    library = data.get("characters") or {}
    assignments = data.get("slots") or {}
    slots = {}

    for number, config in PLAYER_CONFIG.items():
        if number not in assignments:
            slots[number] = _conventional(number, config)
            continue

        assigned = assignments[number]
        char_id = assigned.get("character") if isinstance(assigned, dict) else assigned

        if char_id is None:
            # Deliberately empty. Every caption off as well as no art: an empty slot
            # that still reserved space for two blank boxes would push the browser
            # source taller than the nothing it draws.
            slots[number] = Character(id="", display_name="",
                                      **dict.fromkeys(DISPLAY_FLAGS, False))
            continue

        entry = library.get(char_id)
        if entry is None:
            print(f"Slot {number} is assigned to unknown character {char_id!r}; "
                  "using the default art for that slot.")
            slots[number] = _conventional(number, config)
            continue

        slots[number] = Character(
            id=char_id,
            display_name=entry.get("display_name", ""),
            art_closed=entry.get("art_closed"),
            art_open=entry.get("art_open"),
            default_voice=entry.get("default_voice") or config.get("voice_name"),
            default_style=entry.get("default_style", DEFAULT_VOICE_STYLE),
            **{flag: entry.get(flag, True) for flag in DISPLAY_FLAGS},
        )

    return slots, "file"


# ---------------------------------------------------------------------------
# Art dimensions, so the app can report the OBS browser source size
# ---------------------------------------------------------------------------


def art_size(relative_path):
    """
    (width, height) of a PNG under static/, or None if it can't be determined.

    Reads the IHDR header directly rather than pulling in Pillow for eight bytes.
    None is a real answer -- a missing file, or art that isn't a PNG -- and callers
    report the size as unknown rather than guessing, since a wrong number here means
    a clipped message box that's baffling to diagnose.
    """
    if not relative_path:
        return None
    path = os.path.join(STATIC_ROOT, relative_path.replace("/", os.sep))
    try:
        with open(path, "rb") as fh:
            header = fh.read(24)
    except OSError:
        return None
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    try:
        width, height = struct.unpack(">II", header[16:24])
    except struct.error:
        return None
    return (width, height) if width and height else None


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
