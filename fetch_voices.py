"""
Build voices.json from your Azure subscription.

Azure knows which voices exist and which speaking styles each one supports. That
second part matters: styles are not universal, and asking for an unsupported one
does not raise -- Azure just renders the line neutral and says nothing. Reading
the real list lets the control panel offer only styles that will actually do
something.

Run this once after setting AZURE_TTS_KEY and AZURE_TTS_REGION, and again
whenever you want to pick up new voices. The app reads the cached file at
startup and never calls Azure just to draw a dropdown.

    python fetch_voices.py                  # en-US only
    python fetch_voices.py en-US en-GB      # several locales
    python fetch_voices.py --all            # everything (hundreds)
"""

import json
import os
import sys

import azure.cognitiveservices.speech as speechsdk

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices.json")
DEFAULT_LOCALES = ["en-US"]


def fetch(locales, keep_all=False):
    key, region = os.getenv("AZURE_TTS_KEY"), os.getenv("AZURE_TTS_REGION")
    if not key or not region:
        sys.exit("AZURE_TTS_KEY and AZURE_TTS_REGION must be set. "
                 "Reopen your terminal if you only just set them.")

    config = speechsdk.SpeechConfig(subscription=key, region=region)
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=None)

    print(f"Asking Azure for the voice list ({region})...")
    result = synthesizer.get_voices_async().get()

    if result.reason != speechsdk.ResultReason.VoicesListRetrieved:
        sys.exit(f"Could not retrieve voices: {result.error_details or result.reason}\n"
                 "A wrong key or region is the usual cause. The region must be the short "
                 "form, like 'eastus', not 'East US'.")

    voices = []
    for v in result.voices:
        if not keep_all and v.locale not in locales:
            continue
        voices.append({
            "short_name": v.short_name,
            "local_name": v.local_name,
            "gender": str(v.gender).rsplit(".", 1)[-1],   # SynthesisVoiceGender.Male -> Male
            "locale": v.locale,
            # Voices with no styles support no express-as at all. An empty list is
            # meaningful, not missing data -- the app skips the SSML wrapper for these.
            "styles": sorted(v.style_list or []),
        })

    voices.sort(key=lambda v: v["short_name"])
    return voices


def main():
    args = [a for a in sys.argv[1:] if a != "--all"]
    keep_all = "--all" in sys.argv[1:]
    locales = args or DEFAULT_LOCALES

    voices = fetch(locales, keep_all)

    if not voices:
        sys.exit(f"No voices matched {locales}. Check the locale codes, or use --all "
                 "to see everything available.")

    with open(OUTPUT, "w", encoding="utf-8") as fh:
        json.dump({
            "locales": "all" if keep_all else locales,
            "voices": voices,
        }, fh, indent=2, ensure_ascii=False)

    styled = [v for v in voices if v["styles"]]
    all_styles = sorted({s for v in voices for s in v["styles"]})

    print(f"\nWrote {OUTPUT}")
    print(f"  {len(voices)} voices, {len(styled)} of which support speaking styles")
    print(f"  {len(all_styles)} distinct styles: {', '.join(all_styles) or '(none)'}")
    if len(styled) < len(voices):
        print(f"\n  {len(voices) - len(styled)} voices support no styles at all. Those are "
              "synthesized\n  without an express-as wrapper rather than silently ignoring it.")


if __name__ == "__main__":
    main()
