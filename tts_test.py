"""
Test synthesis and local playback without Twitch or a browser.

Since audio moved to the overlay page, the live app no longer plays anything through
the server's speakers. This script still does, so you can check voices and Azure
credentials on their own.

To test what the stream actually hears, run chat_god_app.py and open an overlay.

Usage:  python tts_test.py
"""

from players import PLAYER_NUMBERS
from voices_manager import TTSManager

tts = TTSManager()


def main():
    print("\nPlayer numbers: " + ", ".join(PLAYER_NUMBERS))
    print("Type 'quit' to exit.\n")

    while True:
        number = input("Player number: ").strip()
        if number.lower() in ("quit", "q", "exit"):
            return
        if number not in PLAYER_NUMBERS:
            print(f"  Not a valid player number (expected one of {', '.join(PLAYER_NUMBERS)}).")
            continue

        text = input("Message: ").strip()
        if not text:
            print("  Empty message, skipped.")
            continue

        path = tts.synthesize(text, number)
        if path is None:
            print("  Nothing to say.\n")
            continue

        print(f"  Rendered to {path}")
        tts.set_filter(number, True)      # no-op unless OBS_WEBSOCKETS_ENABLED
        try:
            tts.play_locally(path, delete_after=True)
        finally:
            tts.set_filter(number, False)
        print("  Done.\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
