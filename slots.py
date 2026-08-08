"""
Live per-slot settings -- layer 2 of the three-layer model, all in one place.

The layers, for both voice and display:

1. **Character default** -- `characters.json`, persisted, edited on `/setup`
2. **Live slot value** -- what the control panel changes mid-stream (this module)
3. **Per-message prefix** -- `(angry)`, voice style only; a chatter can't hide
   their own caption

**Why this module exists.** Layer 2 used to live in three places for the same
slot: `TTSManager.voices` held voice and style, `DisplayManager` held the caption
flags, and the `Player` dataclass held `tts_enabled` and `active`. Nothing was
wrong with any one of them; the problem was that "what is slot 3 currently set to"
had three answers in three files, so every feature touching slot state had to know
all three, and persistence had to gather from all three.

The split also wasn't along a real seam. `Player` is *who is talking* -- the
current speaker, the pool of chatters who typed the keyphrase. That genuinely is a
different thing, and it stays there. Everything else is *how the slot behaves*,
which is this.

**Assignment is the reset point.** `reset_to()` puts every field back to the new
character's defaults, because the Wizard should sound and look like the Wizard
whoever was in the slot before. Changing who is *talking* deliberately resets
nothing -- that's a different axis.

Still no persistence here: `slot_state.py` owns the file, and `state.json` was
already written in this shape, so the merge needed no migration.
"""

from dataclasses import dataclass, field

from azure_text_to_speech import NO_STYLE, styles_for
from characters import DISPLAY_FLAGS
from players import PLAYER_CONFIG


@dataclass
class SlotSettings:
    """How one slot behaves right now."""

    voice_name: str
    voice_style: str

    # Silent but still on screen and still pooling. Distinct from `active`.
    tts_enabled: bool = True

    # In the show at all: nothing drawn, nothing spoken, no pool joins, no picking.
    # A six-player OBS scene can be run with four without the app pooling chatters
    # into characters nobody can see or spending Azure quota on them.
    active: bool = True

    # Caption visibility, keyed by DISPLAY_FLAGS. A dict rather than three fields
    # so the flag list stays owned by characters.py -- adding a fourth caption
    # shouldn't mean editing a dataclass here as well.
    display: dict = field(default_factory=dict)


class SlotStore:
    """Every slot's live settings, seeded from the characters assigned to them."""

    def __init__(self, slots):
        self.settings = {number: self._from_character(number, character)
                         for number, character in slots.items()}

    @staticmethod
    def _from_character(number, character):
        # Falling back to players.py keeps a fresh clone working: with no
        # characters.json the library synthesizes an entry per slot carrying
        # exactly this voice, so the two agree rather than merely coexisting.
        fallback = PLAYER_CONFIG.get(number, {}).get("voice_name")
        return SlotSettings(
            voice_name=character.default_voice or fallback,
            voice_style=character.default_style,
            display=character.display(),
        )

    def get(self, number):
        """One slot's settings, or None if the slot doesn't exist."""
        return self.settings.get(number)

    def is_active(self, number):
        """Convenience for the hot paths, which ask this constantly."""
        settings = self.settings.get(number)
        return True if settings is None else settings.active

    def reset_to(self, number, character):
        """Put a slot back to its character's defaults. Called on assignment."""
        self.settings[number] = self._from_character(number, character)
        settings = self.settings[number]
        print(f"Player {number}: reset to {settings.voice_name} / {settings.voice_style}")
        return settings

    # -- voice ----------------------------------------------------------------

    def set_voice_name(self, number, voice_name):
        """
        Change the voice. Returns the style it had to fall back to if the current
        style isn't available on the new voice, otherwise None.

        Styles aren't universal across voices, so switching voice can strand the
        selected style. Sending it anyway is what the original did, and Azure's
        response to an unsupported style is to render the line neutral without
        complaining -- so the operator saw "whispering" selected and heard nothing
        of the sort.
        """
        settings = self.settings.get(number)
        if settings is None:
            print(f"Unknown player number {number!r}; voice name not changed.")
            return None

        settings.voice_name = voice_name
        print(f"Player {number}: voice name is now {voice_name}")

        available = styles_for(voice_name)
        # "none" is always valid -- it means no express-as at all. "random" is only
        # valid on a voice that has styles to pick from; on one that doesn't it
        # would claim to be varying something that can't vary.
        if settings.voice_style == NO_STYLE:
            return None
        if settings.voice_style == "random" and available:
            return None
        if settings.voice_style in available:
            return None

        stranded, settings.voice_style = settings.voice_style, NO_STYLE
        print(f"Player {number}: '{stranded}' isn't available on "
              f"{voice_name} - changing to none.")
        return NO_STYLE

    def set_voice_style(self, number, voice_style):
        settings = self.settings.get(number)
        if settings is None:
            print(f"Unknown player number {number!r}; voice style not changed.")
            return
        settings.voice_style = voice_style
        print(f"Player {number}: voice style is now {voice_style}")

    # -- display --------------------------------------------------------------

    def set_display(self, number, flag, value):
        """
        Toggle one caption. Returns True if it changed anything.

        Rejects unknown flag names rather than storing them: the value arrives from
        the browser, and a typo that silently created a `show_mesage` key would
        leave a checkbox that appears to work and changes nothing.
        """
        if flag not in DISPLAY_FLAGS:
            print(f"Ignoring unknown display flag {flag!r}.")
            return False

        settings = self.settings.get(number)
        if settings is None:
            print(f"Unknown player number {number!r}; display not changed.")
            return False

        settings.display[flag] = bool(value)
        print(f"Player {number}: {flag} is now {settings.display[flag]}")
        return True

    # -- views ----------------------------------------------------------------

    def display_flags(self, number):
        """Caption flags for one slot, or {} -- the shape templates expect."""
        settings = self.settings.get(number)
        return settings.display if settings else {}

    def voice_map(self):
        """
        {number: {"name", "style"}} for the templates that render voice pickers.

        A view rather than the storage: `/setup` wants exactly this shape, and
        changing the template as well as the model in one go would have made a
        refactor that touches nothing visible impossible to verify by eye.
        """
        return {number: {"name": s.voice_name, "style": s.voice_style}
                for number, s in self.settings.items()}
