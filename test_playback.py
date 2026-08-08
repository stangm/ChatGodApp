"""
Tests for the three playback features that were built but never exercised:
the speech gate, the audio caches behind voice preview, and wav timing.

Run it with the venv active and nothing else running:

    .\.venv\Scripts\Activate.ps1
    python test_playback.py

**It imports the real chatmob_app**, so it needs the same dependencies the app
needs, but it never starts the server, never touches Twitch, and never calls
Azure. `socketio.emit` is replaced with a list so 'what went out to the overlay'
becomes something to assert on rather than something to watch for on stream.

**Timing is the awkward part.** SpeechPacer runs a real thread that really
sleeps for the length of each clip, so a test that submits a four-second clip
and then checks something 50ms later is testing the sleep, not the logic. Every
place that matters waits for the pacer to go idle first -- see `settle()`. A
test that passes only because a thread happened to be busy is worse than no
test, since it fails later for reasons that have nothing to do with the change
that broke it.

What this deliberately does NOT cover, because it needs a browser and Azure:
dimming, mouth animation, autoplay, and whether a preview actually sounds like
the voice you picked. Those are in the live checklist in the README.
"""

import os
import sys
import tempfile
import time
import wave

import chatmob_app as A


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

PASSED, FAILED = [], []
EMITTED = []

A.socketio.emit = lambda event, payload=None, **kw: EMITTED.append((event, payload))


def check(name, got, want):
    if got == want:
        PASSED.append(name)
        print(f"  [PASS] {name}")
    else:
        FAILED.append(name)
        print(f"  [FAIL] {name}\n         got  {got!r}\n         want {want!r}")


def make_wav(seconds=0.5, rate=8000):
    """A real, readable wav of a known length. Silence is fine; only the header matters."""
    handle, path = tempfile.mkstemp(suffix=".wav")
    os.close(handle)
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


def settle(timeout=10.0):
    """
    Wait until the pacer thread is genuinely free, then clear what it emitted.

    **An empty queue is not the same as an idle thread**, which is the mistake
    worth not repeating: after releasing a four-second clip the thread sleeps for
    ~3.65s whether or not anything is queued behind it, and `flush()` empties the
    queue without waking it. A settle that only watched the queue therefore
    returned while the thread was still asleep, and the *next* test then failed
    with a completely unrelated-looking symptom.

    So this probes instead of guessing: it drains the queue, then submits a clip
    of its own and waits for it to come back out. Nothing but a free thread can
    produce that.
    """
    deadline = time.time() + timeout

    was_enabled = A.speech_gate_enabled
    A.speech_gate_enabled = True
    A.speech_pacer.flush()

    # The probe has to go through a slot that's in the show, or the pacer skips it
    # at release time and this waits forever for a clip it deliberately dropped.
    # That's not hypothetical -- the inactive-slot test switches the first slot off
    # and then calls settle().
    number = sorted(A.slot_settings.settings)[0]
    probe_slot = A.slot_settings.get(number)
    was_active, probe_slot.active = probe_slot.active, True

    probe = make_wav(0.01)
    A.speech_pacer.submit(clip("__settle_probe__", number=number), probe)
    while time.time() < deadline:
        if any(u == "__settle_probe__" for u in users()):
            break
        time.sleep(0.05)
    else:
        probe_slot.active = was_active
        raise RuntimeError("pacer never went idle; a previous test left it stuck")

    time.sleep(0.1)
    probe_slot.active = was_active
    A.speech_gate_enabled = was_enabled
    EMITTED.clear()


def users():
    return [payload["current_user"] for _, payload in EMITTED]


def clip(user, number=None):
    if number is None:
        number = sorted(A.slot_settings.settings)[0]
    return {"user_number": number, "current_user": user, "audio_url": "/x.wav"}


# ---------------------------------------------------------------------------
# wav duration -- what the pacer's timing is built on
# ---------------------------------------------------------------------------

def test_wav_seconds():
    print("\nwav duration")
    check("reads a real wav", round(A._wav_seconds(make_wav(1.25)), 3), 1.25)
    check("missing file guesses 3.0", A._wav_seconds("/nope/nope.wav"), 3.0)

    handle, bad = tempfile.mkstemp(suffix=".wav")
    os.close(handle)
    with open(bad, "wb") as out:
        out.write(b"this is not a wav")
    # A wrong guess is a small timing error; an exception here would kill the
    # submitting thread, so the fallback matters more than its accuracy.
    check("unreadable file guesses 3.0", A._wav_seconds(bad), 3.0)


# ---------------------------------------------------------------------------
# The two caches -- the reason preview got its own
# ---------------------------------------------------------------------------

def test_caches():
    print("\naudio caches")
    A._audio_cache.clear()
    A._preview_cache.clear()

    speech = [make_wav(0.1) for _ in range(3)]
    speech_tokens = [A.register_audio(p) for p in speech]

    # The scenario the split cache exists for: stepping through a voice's styles
    # is a burst big enough to evict a queued message from a shared cache.
    previews = [make_wav(0.1) for _ in range(6)]
    preview_tokens = [A.register_audio(p, A._preview_cache, A.PREVIEW_CACHE_SIZE)
                      for p in previews]

    check("preview cache honours its own limit",
          len(A._preview_cache), A.PREVIEW_CACHE_SIZE)
    check("a burst of previews leaves queued speech alone",
          len(A._audio_cache), 3)
    check("every speech token still resolves",
          all(A._audio_cache.get(t) for t in speech_tokens), True)
    check("evicted preview files are deleted from disk",
          [os.path.exists(p) for p in previews[:2]], [False, False])
    check("surviving preview files are still on disk",
          all(os.path.exists(p) for p in previews[2:]), True)

    client = A.app.test_client()
    check("a speech token is served",
          client.get(f"/audio/{speech_tokens[0]}.wav").status_code, 200)
    check("a preview token is served from the other cache",
          client.get(f"/audio/{preview_tokens[-1]}.wav").status_code, 200)
    check("an unknown token 404s",
          client.get("/audio/deadbeef.wav").status_code, 404)
    # This 404 is the one the overlay hits when a clip waited too long.
    check("an evicted token 404s",
          client.get(f"/audio/{preview_tokens[0]}.wav").status_code, 404)


# ---------------------------------------------------------------------------
# The speech gate
# ---------------------------------------------------------------------------

def test_gate_off():
    print("\nspeech gate: off (how the app has always behaved)")
    A.speech_gate_enabled = False
    settle()
    A.speech_pacer.submit(clip("straight-through"), make_wav(0.1))
    time.sleep(0.2)
    check("emits immediately", len(EMITTED), 1)
    check("queues nothing", len(A.speech_pacer._queue), 0)


def test_gate_on_and_backlog():
    print("\nspeech gate: on")
    A.speech_gate_enabled = True
    settle()

    long_clip = make_wav(4.0)
    for i in range(12):
        A.speech_pacer.submit(clip(f"u{i}"), long_clip)
    time.sleep(0.3)

    check("queue is capped at SPEECH_QUEUE_MAX",
          len(A.speech_pacer._queue) <= A.SPEECH_QUEUE_MAX, True)
    check("one clip is playing, the rest wait", len(EMITTED), 1)

    # Which clip is playing is deliberately NOT asserted as "u0". Whether the
    # thread pops before or during the submitting loop is a real race, and with 12
    # submitted against a cap of 8 the earliest few are *supposed* to be dropped.
    # Asserting u0 would be asserting the race. What must hold regardless is that
    # order is preserved and drops come off the old end -- so the survivors are a
    # contiguous run ending at the newest clip.
    surviving = [p["current_user"] for p, _ in A.speech_pacer._queue]
    expected_tail = [f"u{i}" for i in range(12 - len(surviving), 12)]
    check("the newest clips are the ones kept, in order", surviving, expected_tail)
    playing = users()[0]
    check("the clip playing is older than everything still queued",
          int(playing[1:]) < int(surviving[0][1:]), True)

    print("\nswitching the gate off releases the backlog rather than stranding it")
    backlog = len(A.speech_pacer._queue)
    EMITTED.clear()
    A.speech_pacer.flush()
    check("flush emits the whole backlog", len(EMITTED), backlog)
    check("flush empties the queue", len(A.speech_pacer._queue), 0)

    A.speech_gate_enabled = False


def test_inactive_slot_skipped():
    print("\na slot switched out of the show while its clip waited")

    # Since the layer-2 merge the pacer asks SlotStore directly rather than
    # reaching into a Player, so this is now just two settings objects.
    numbers = sorted(A.slot_settings.settings)
    off, on = numbers[0], numbers[1]
    A.slot_settings.get(off).active = False
    A.slot_settings.get(on).active = True

    A.speech_gate_enabled = False
    settle()
    A.speech_gate_enabled = True

    short = make_wav(0.05)
    A.speech_pacer.submit(clip("inactive", number=off), short)
    A.speech_pacer.submit(clip("active", number=on), short)
    time.sleep(1.5)

    check("the inactive slot's clip is never emitted", "inactive" in users(), False)
    check("the active slot's clip still goes out", "active" in users(), True)

    # Skipping must not cost a sleep, or a disabled slot's backlog would hold up
    # the whole show for the length of clips nobody will ever hear.
    EMITTED.clear()
    started = time.time()
    for i in range(4):
        A.speech_pacer.submit(clip(f"skipped{i}", number=off), make_wav(3.0))
    A.speech_pacer.submit(clip("after", number=on), short)
    while "after" not in users() and time.time() - started < 8:
        time.sleep(0.05)
    elapsed = time.time() - started
    check("four skipped clips cost no sleep (would be ~10.6s each slept)",
          elapsed < 2.0, True)
    print(f"         drained in {elapsed:.2f}s")

    A.slot_settings.get(off).active = True
    A.speech_gate_enabled = False


def test_synthesis_wiring():
    """
    The one path the whole app exists for, asserted without Azure or a network.

    This exists because it was missing. `TTSManager` was changed to read its voice
    from `SlotStore`, and the app's own entry point kept passing `CHARACTERS` --
    also a {number: something-with-a-voice} map, also truthy, so the `is None`
    guard passed and every message died on an AttributeError inside SpeechWorker,
    which swallows exceptions to a console nobody watches. Both suites stayed
    green because neither ever called synthesize().

    So this asserts the wiring rather than the synthesis: that whatever the manager
    is holding actually answers to `.voice_name`, and that the voice it reaches for
    is the *live* one rather than the character default.
    """
    print("\nsynthesis wiring")

    class FakeAzure:
        def __init__(self):
            self.seen = None

        def text_to_audio(self, text, voice=None, style=None):
            self.seen = (text, voice, style)
            return make_wav(0.1)

    number = sorted(A.slot_settings.settings)[0]
    live = A.slot_settings.get(number)
    live.voice_name = "en-US-TestOnlyNeural"
    live.voice_style = "cheerful"

    manager = A.TTSManager.__new__(A.TTSManager)     # no Azure SDK, no device
    manager.azuretts_manager = FakeAzure()
    manager.slots = A.slot_settings

    check("synthesize returns a clip", bool(manager.synthesize("hello", number)), True)
    check("and it used the live voice, not the character default",
          manager.azuretts_manager.seen, ("hello", "en-US-TestOnlyNeural", "cheerful"))

    # The guard that turns "wrong container, right shape" into a skip and a message
    # instead of an exception nobody sees.
    manager.slots = A.CHARACTERS
    check("handed the character map instead, it refuses rather than raising",
          manager.synthesize("hello", number), None)

    manager.slots = A.slot_settings
    check("an unknown slot still refuses", manager.synthesize("hello", "999"), None)


def test_overlay_can_receive_art():
    """
    An overlay page must render the elements `art_changed` writes into, even for a
    slot that currently has no art.

    The block used to be wrapped in `{% if images[n].closed %}`, so an empty slot
    had no <img> tags, `slot.find('img.mouth-closed')` matched nothing, and
    assigning a character into that slot drew nothing until the browser source was
    reloaded -- which reads as an OBS caching problem rather than a bug. Unassigning
    worked, because the elements existed; that asymmetry was the tell.

    Asserted on the rendered HTML rather than through a browser, because the failure
    is a missing element, and that is visible in the markup.
    """
    print("\noverlay renders art targets for empty slots")

    number = sorted(A.PLAYER_CONFIG)[0]
    original = A.CHARACTERS.get(number)

    class Empty:
        """A slot with no character at all -- the state the bug needed."""
        id = ""
        display_name = ""
        has_name = False
        art_closed = None
        art_open = None

        def display(self):
            return {flag: True for flag in A.DISPLAY_FLAGS}

    A.CHARACTERS[number] = Empty()
    try:
        html = A.app.test_client().get(f"/overlay?player={number}").get_data(as_text=True)
        check("the mouth-closed img exists", 'class="character-art mouth-closed"' in html, True)
        check("the mouth-open img exists", 'class="character-art mouth-open"' in html, True)
        check("both are hidden rather than omitted", html.count('style="display:none"') >= 2, True)
        check("the character name box exists",
              f'id="character-name-{number}"' in html, True)
    finally:
        if original is not None:
            A.CHARACTERS[number] = original


def test_overlay_resync_on_connect():
    """
    `overlay_here` must reply to the page that announced itself.

    A browser source doesn't reload when the app restarts -- socket.io reconnects
    the existing page -- so without a reply the overlay keeps drawing pre-restart
    state forever, with nothing to correct it.
    """
    print("\noverlay resyncs when it announces itself")

    number = sorted(A.PLAYER_CONFIG)[0]
    replies = []
    real_emit, real_push = A.emit, A.push_status
    A.emit = lambda event, payload=None, **kw: replies.append((event, payload))
    A.push_status = lambda: None

    class FakeRequest:
        sid = "test-sid"

    real_request = A.request
    A.request = FakeRequest()
    try:
        # An app context is required, not optional: slot_payload() -> art_url() ->
        # url_for('static', ...) needs one. The real handler has it because
        # Flask-SocketIO runs every event inside a request context -- which is also
        # why `request.sid` works there. Calling it bare here is the test being
        # unrealistic, not the handler being wrong.
        with A.app.test_request_context():
            A.overlay_here({"players": [number]})
    finally:
        A.emit, A.push_status, A.request = real_emit, real_push, real_request

    events = [event for event, _ in replies]
    check("it replies with art for the slot", "art_changed" in events, True)
    check("and with whether the slot is in the show", "slot_active" in events, True)

    art = next(p for e, p in replies if e == "art_changed")
    check("the art payload names the right slot", art["user_number"], number)
    # A payload missing these is one the page can't act on.
    check("and carries what the page needs",
          all(k in art for k in ("art_closed", "art_open", "character_name",
                                 "show_message", "size_parts")), True)

    A.overlay_clients.pop("test-sid", None)


def test_invariant():
    print("\nthe invariant the pacer's comments depend on")
    # register_audio() deletes the oldest wav past AUDIO_CACHE_SIZE, so a backlog
    # approaching that number would have its files removed before playing and the
    # overlay would 404 and skip them with nothing on screen to explain why.
    check("SPEECH_QUEUE_MAX stays well under AUDIO_CACHE_SIZE",
          A.SPEECH_QUEUE_MAX * 2 < A.AUDIO_CACHE_SIZE, True)


# ---------------------------------------------------------------------------

def main():
    test_wav_seconds()
    test_caches()
    test_gate_off()
    test_gate_on_and_backlog()
    test_inactive_slot_skipped()
    test_synthesis_wiring()
    test_overlay_can_receive_art()
    test_overlay_resync_on_connect()
    test_invariant()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("failed: " + ", ".join(FAILED))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
