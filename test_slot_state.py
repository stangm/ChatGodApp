"""
Tests for persisting live slot settings across a restart.

    .\.venv\Scripts\Activate.ps1
    python test_slot_state.py

Two halves. The first exercises `slot_state.py` alone -- file format, debounce,
and every way the file can be wrong. The second imports the real `chatmob_app`
and simulates a restart: snapshot the live state, throw the managers away, build
fresh ones, restore, and check the values came back.

**It writes to a temporary state.json path, not the real one**, so running this
can't overwrite settings you're actually using.

The cases that matter most are the refusals. Restoring a saved value blindly is
easy; the failure worth preventing is restoring a voice Azure no longer offers, or
one character's overrides onto another character who has since been assigned to
that slot -- both of which look like the app inventing settings on its own.
"""

import json
import os
import sys
import tempfile
import time

import slot_state

PASSED, FAILED = [], []


def check(name, got, want):
    if got == want:
        PASSED.append(name)
        print(f"  [PASS] {name}")
    else:
        FAILED.append(name)
        print(f"  [FAIL] {name}\n         got  {got!r}\n         want {want!r}")


# Redirect the module at a scratch file before anything touches the real one.
_handle, TEST_FILE = tempfile.mkstemp(suffix="-state.json")
os.close(_handle)
os.remove(TEST_FILE)
slot_state.STATE_FILE = TEST_FILE


def clean():
    if os.path.exists(TEST_FILE):
        os.remove(TEST_FILE)


# ---------------------------------------------------------------------------
# The file itself
# ---------------------------------------------------------------------------

def test_round_trip():
    print("\nfile round trip")
    clean()
    snapshot = {
        "_app": {"speech_gate": True},
        "1": {"character": "wizard", "voice": "en-US-DavisNeural", "style": "angry",
              "tts": True, "active": False, "show_character_name": True,
              "show_chatter_name": False, "show_message": True},
    }
    slot_state.save_soon(snapshot)
    slot_state.flush()
    check("file is written", os.path.exists(TEST_FILE), True)
    check("loads back identically", slot_state.load(), snapshot)
    check("no .tmp left behind", os.path.exists(TEST_FILE + ".tmp"), False)


def test_debounce():
    print("\ndebounce")
    clean()
    writes = []
    real_write = slot_state._write
    slot_state._write = lambda snap: (writes.append(snap), real_write(snap))
    try:
        # A streamer dragging through the caption toggles, which is the case this
        # exists for: ten changes should cost one write, not ten.
        for i in range(10):
            slot_state.save_soon({"1": {"tts": i % 2 == 0}})
        check("nothing written while changes are still arriving", len(writes), 0)

        time.sleep(slot_state.DEBOUNCE_SECONDS + 0.4)
        check("one write for ten changes", len(writes), 1)
        # Snapshots replace rather than queue, so the file describes the end state.
        check("and it holds the last value, not the first", writes[0]["1"]["tts"], False)
    finally:
        slot_state._write = real_write


def test_bad_files():
    print("\nevery way the file can be wrong")
    with open(TEST_FILE, "w", encoding="utf-8") as out:
        out.write("{ not json at all")
    # Refusing to start over a settings file would be indefensible ten minutes
    # before a stream, when every value in it is recoverable by clicking things.
    check("corrupt file loads as empty", slot_state.load(), {})

    with open(TEST_FILE, "w", encoding="utf-8") as out:
        json.dump(["a", "list"], out)
    check("a JSON array loads as empty", slot_state.load(), {})

    with open(TEST_FILE, "w", encoding="utf-8") as out:
        json.dump({"1": "garbage", "2": {"tts": False}}, out)
    check("a bad entry is skipped, siblings survive",
          slot_state.load(), {"2": {"tts": False}})

    with open(TEST_FILE, "w", encoding="utf-8") as out:
        json.dump({"1": {"tts": True, "unexpected": "value"},
                   "_app": {"speech_gate": False, "unexpected": 1}}, out)
    loaded = slot_state.load()
    check("unknown slot keys dropped", sorted(loaded["1"]), ["tts"])
    check("unknown app keys dropped", sorted(loaded["_app"]), ["speech_gate"])

    clean()
    check("a missing file is the normal first run", slot_state.load(), {})


# ---------------------------------------------------------------------------
# A simulated restart
# ---------------------------------------------------------------------------

def test_restart():
    print("\nsimulated restart")
    import chatmob_app as app

    voice_name = next((v for v in app.AZURE_VOICES if app.styles_for(v)), None)
    if voice_name is None:
        print("  [SKIP] no voice with styles in the catalogue")
        return
    style = app.styles_for(voice_name)[0]

    def restart():
        """
        Throw the live state away the way a crash does.

        Since the layer-2 merge that's one object, not three -- which is most of
        the argument for having done the merge.
        """
        app.slot_settings = app.SlotStore(app.CHARACTERS)

    number = sorted(app.PLAYER_CONFIG)[0]

    restart()
    live = app.slot_settings.get(number)
    live.voice_name = voice_name
    live.voice_style = style
    live.tts_enabled = False
    live.active = False
    live.display["show_message"] = False
    app.speech_gate_enabled = True

    app.save_slot_state()
    slot_state.flush()

    restart()
    app.speech_gate_enabled = False
    app.restore_slot_state()

    live = app.slot_settings.get(number)
    check("voice restored", live.voice_name, voice_name)
    check("style restored", live.voice_style, style)
    check("tts toggle restored", live.tts_enabled, False)
    check("in-the-show switch restored", live.active, False)
    check("caption toggle restored", live.display["show_message"], False)
    check("speech gate restored", app.speech_gate_enabled, True)

    print("\n  refusals")

    def rewrite(**changes):
        saved = json.load(open(TEST_FILE, encoding="utf-8"))
        saved[number].update(changes)
        with open(TEST_FILE, "w", encoding="utf-8") as out:
            json.dump(saved, out)

    # Someone assigned a different character while the app was down. These
    # overrides describe a character who isn't in this slot any more, and putting
    # The Narrator's voice on Henry Potter is worse than restoring nothing.
    rewrite(character="a-different-character")
    restart()
    default_voice = app.slot_settings.get(number).voice_name
    app.restore_slot_state()
    check("a swapped character drops its predecessor's voice",
          app.slot_settings.get(number).voice_name, default_voice)
    check("and its toggles too", app.slot_settings.get(number).tts_enabled, True)

    # Azure retires voices. Restoring one silently fails at synthesis time, which
    # reads as "TTS is broken" from the one place the cause isn't visible.
    rewrite(character=app.library.slots.get(number),
            voice="en-XX-NotARealNeural", style="cheerful")
    restart()
    default_voice = app.slot_settings.get(number).voice_name
    app.restore_slot_state()
    check("a retired voice is refused",
          app.slot_settings.get(number).voice_name, default_voice)
    # Rejecting one field must not throw away the rest of the slot.
    check("but the rest of the slot still restores",
          app.slot_settings.get(number).tts_enabled, False)

    saved = json.load(open(TEST_FILE, encoding="utf-8"))
    saved["99"] = {"character": None, "tts": False}
    with open(TEST_FILE, "w", encoding="utf-8") as out:
        json.dump(saved, out)
    restart()
    try:
        app.restore_slot_state()
        check("a slot that no longer exists is skipped", True, True)
    except Exception as exc:
        check("a slot that no longer exists is skipped", f"raised {exc!r}", True)


def main():
    try:
        test_round_trip()
        test_debounce()
        test_bad_files()
        test_restart()
    finally:
        clean()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("failed: " + ", ".join(FAILED))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
