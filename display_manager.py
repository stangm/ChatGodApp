"""
Live display settings per slot -- layer 2 of the three-layer model.

The layers, same as voice:

1. **Character default** -- `show_*` in `characters.json`, persisted
2. **Live slot value** -- what the control panel toggles, in memory (this module)
3. *(no per-message layer; a chatter can't hide their own caption)*

Deliberately shaped like `TTSManager.voices`: a per-slot dict, mutated by socket
handlers, rebuilt from character defaults on assignment. Two managers holding layer-2
state for one slot is one more than ideal -- when characters can be assigned at
runtime (stage D) they should probably merge into a single slot-state object. Adding
display state to TTSManager now would have meant either a misleading name or
refactoring voice handling that had just been smoke-tested, so it waits.

Nothing here persists. A restart rebuilds from the character defaults, which is the
same thing that happens to voice, and is on the list to fix properly rather than
twice in two places.
"""

from characters import DISPLAY_FLAGS


class DisplayManager:
    """Per-slot caption visibility, seeded from each slot's character."""

    def __init__(self, slots):
        self.settings = {number: character.display()
                         for number, character in slots.items()}

    def get(self, user_number):
        """The flags for one slot, or None if the slot doesn't exist."""
        return self.settings.get(user_number)

    def update(self, user_number, flag, value):
        """
        Toggle one flag. Returns True if it changed anything.

        Rejects unknown flag names rather than storing them: the value arrives from
        the browser, and a typo that silently created a `show_mesage` key would
        leave a checkbox that appears to work and changes nothing.
        """
        if flag not in DISPLAY_FLAGS:
            print(f"Ignoring unknown display flag {flag!r}.")
            return False

        current = self.settings.get(user_number)
        if current is None:
            print(f"Unknown player number {user_number!r}; display not changed.")
            return False

        current[flag] = bool(value)
        print(f"Player {user_number}: {flag} is now {current[flag]}")
        return True

    def reset_to(self, user_number, character):
        """
        Put a slot back to its character's defaults.

        Assigning a character is a deliberate reset point -- the Wizard brings his
        display settings with him the same way he brings his voice. Unused until
        assignment exists (stage D), but it's the counterpart to update() and
        belongs with it.
        """
        self.settings[user_number] = character.display()
        return self.settings[user_number]
