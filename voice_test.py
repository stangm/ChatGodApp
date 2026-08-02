"""
Standalone voice auditioning tool. Not part of the app.

Plays Azure TTS through the same pygame path the app uses, so audio lands on whatever
output device python.exe is routed to (i.e. through CABLE Input -> OBS if you've set
that up). Deliberately imports only azure_text_to_speech + audio_player, NOT
voices_manager -- importing voices_manager would try to connect to OBS and exit if it
can't.

Usage:  python voice_test.py
"""

from azure_text_to_speech import AzureTTSManager, AZURE_VOICES, AZURE_VOICE_STYLES
from audio_player import AudioManager

SAMPLE = "The quick brown fox jumps over the lazy dog. Roll for initiative."

tts = AzureTTSManager()
audio = AudioManager()


def say(text, voice, style):
    """Synthesize and play one line, blocking until it finishes."""
    print(f"  -> {voice} / {style}")
    path = tts.text_to_audio(text, voice, style)
    if path is None:
        print("     (empty message, skipped)")
        return
    audio.play_audio(path, sleep_during_playback=True, delete_file=True)


def numbered(items, label):
    print(f"\n{label}:")
    for i, item in enumerate(items, 1):
        print(f"  {i:2}. {item}")
    return items


def pick(items, prompt):
    """Return a chosen item, or None for 'all'."""
    raw = input(f"{prompt} (number, or Enter for all): ").strip()
    if not raw:
        return None
    try:
        return items[int(raw) - 1]
    except (ValueError, IndexError):
        print("  Not a valid number, using all.")
        return None


def main():
    text = input(f"\nText to speak [Enter for default]: ").strip() or SAMPLE

    numbered(AZURE_VOICES, "Voices")
    voice = pick(AZURE_VOICES, "Which voice?")

    numbered(AZURE_VOICE_STYLES, "Styles")
    style = pick(AZURE_VOICE_STYLES, "Which style?")

    voices = [voice] if voice else AZURE_VOICES
    styles = [style] if style else AZURE_VOICE_STYLES

    total = len(voices) * len(styles)
    print(f"\nPlaying {total} clip(s). Ctrl+C to stop.\n")

    for v in voices:
        for s in styles:
            say(text, v, s)

    print("\nDone.")


if __name__ == "__main__":
    try:
        while True:
            main()
            if input("\nAgain? [y/N]: ").strip().lower() != "y":
                break
    except KeyboardInterrupt:
        print("\nStopped.")
