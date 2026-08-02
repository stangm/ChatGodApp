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

    python fetch_voices.py                  # every English locale
    python fetch_voices.py en-US            # one specific locale
    python fetch_voices.py en-GB en-AU      # several
    python fetch_voices.py en fr            # whole languages
    python fetch_voices.py --all            # every locale (hundreds)
    python fetch_voices.py --include-premium # add HD and AOAI voices

An argument with no region ("en") matches every locale in that language, so the
default picks up en-GB, en-AU, en-IE, en-IN and the rest alongside en-US. An
argument with a region ("en-GB") matches only that one.

Premium voices are excluded by default. Azure's free F0 tier covers "prebuilt
non-HD and non-AOAI neural voices" -- so the HD families (DragonHD, and the
Multitalker variants) and the Azure OpenAI voices (the Turbo Multilingual set:
Alloy, Echo, Fable, Nova, Onyx, Shimmer) bill separately, at a higher rate than
standard neural. Listing them in the dropdown is a good way to hand a viewer
your credit card. Pass --include-premium if you are on a paid tier and want
them; the file records which is which either way.
"""

import collections
import json
import os
import sys

import azure.cognitiveservices.speech as speechsdk

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices.json")
DEFAULT_LOCALES = ["en"]          # every English locale, not just en-US

# The SDK's VoiceInfo exposes locale ("en-AU") but not Azure's LocaleName
# ("English (Australia)"), so the readable half is mapped here. Every English
# locale Azure ships is covered; anything else falls back to the raw code, which
# is fine for a dropdown label.
LOCALE_NAMES = {
    "en-AU": "Australia",
    "en-CA": "Canada",
    "en-GB": "United Kingdom",
    "en-HK": "Hong Kong",
    "en-IE": "Ireland",
    "en-IN": "India",
    "en-KE": "Kenya",
    "en-NG": "Nigeria",
    "en-NZ": "New Zealand",
    "en-PH": "Philippines",
    "en-SG": "Singapore",
    "en-TZ": "Tanzania",
    "en-US": "United States",
    "en-ZA": "South Africa",
}


def locale_display(locale):
    """'en-AU' -> 'Australia'. Unknown locales keep their code."""
    return LOCALE_NAMES.get(locale, locale)


def matches(locale, wanted):
    """
    True if this locale is one the user asked for.

    A bare language ("en") matches every region in it; a full locale ("en-GB")
    matches only itself. That's what makes the default pull in all the English
    variants without listing fourteen of them.
    """
    for want in wanted:
        if "-" in want:
            if locale == want:
                return True
        elif locale.split("-")[0].lower() == want.lower():
            return True
    return False


def classify(short_name):
    """
    'standard', 'hd' or 'aoai'. Only 'standard' is covered by the free F0 tier.

    Name-based, because the API doesn't expose a billing tier. The markers are
    stable enough to rely on:
      *:DragonHD...   HD voices, including the Omni and Flash variants
      *:MAI-Voice-*   Microsoft's newer premium voices
      *Multitalker*   multi-speaker HD models
      *Turbo*         Azure OpenAI voices (Alloy, Echo, Fable, Nova, Onyx, Shimmer)

    Check the pricing page if a voice matters to you -- this is a guard against
    surprise bills, not a billing authority.
    """
    if "Turbo" in short_name:
        return "aoai"
    if ":" in short_name or "Multitalker" in short_name:
        return "hd"
    return "standard"


def fetch(locales, keep_all=False, include_premium=False):
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

    voices, skipped = [], {"hd": 0, "aoai": 0}
    for v in result.voices:
        if not keep_all and not matches(v.locale, locales):
            continue

        tier = classify(v.short_name)
        if tier != "standard" and not include_premium:
            skipped[tier] += 1
            continue

        voices.append({
            "short_name": v.short_name,
            "local_name": v.local_name,
            "gender": str(v.gender).rsplit(".", 1)[-1],   # SynthesisVoiceGender.Male -> Male
            "locale": v.locale,
            "locale_name": locale_display(v.locale),
            "tier": tier,
            "voice_type": str(v.voice_type).rsplit(".", 1)[-1],
            # Azure reports a voice with no speaking styles as [''] rather than [],
            # so the empties have to go or the app offers a blank style and builds
            # <mstts:express-as style=''>. An empty list here is meaningful: it
            # means synthesize with no express-as wrapper at all.
            "styles": sorted(s for s in (v.style_list or []) if s and s.strip()),
        })

    # Grouped by locale in the dropdown, so sort that way here and the template
    # can just walk the list. Biggest locale first -- whichever you pulled the
    # most voices for is almost certainly the one you'll pick from.
    counts = collections.Counter(v["locale"] for v in voices)
    voices.sort(key=lambda v: (-counts[v["locale"]], v["locale"], v["short_name"]))
    return voices, skipped


def main():
    flags = {"--all", "--include-premium"}
    args = [a for a in sys.argv[1:] if a not in flags]
    keep_all = "--all" in sys.argv[1:]
    include_premium = "--include-premium" in sys.argv[1:]
    locales = args or DEFAULT_LOCALES

    voices, skipped = fetch(locales, keep_all, include_premium)

    if not voices:
        sys.exit(f"No voices matched {locales}. Check the locale codes, or use --all "
                 "to see everything available.")

    with open(OUTPUT, "w", encoding="utf-8") as fh:
        json.dump({
            "locales": "all" if keep_all else locales,
            "include_premium": include_premium,
            "voices": voices,
        }, fh, indent=2, ensure_ascii=False)

    styled = [v for v in voices if v["styles"]]
    all_styles = sorted({s for v in voices for s in v["styles"]})

    print(f"\nWrote {OUTPUT}")
    print(f"  {len(voices)} voices, {len(styled)} of which support speaking styles")
    print(f"  {len(all_styles)} distinct styles: {', '.join(all_styles) or '(none)'}")

    by_locale = collections.Counter(v["locale"] for v in voices)
    if len(by_locale) > 1:
        print(f"\n  Across {len(by_locale)} locales:")
        for locale, n in by_locale.most_common():
            with_styles = sum(1 for v in voices
                              if v["locale"] == locale and v["styles"])
            note = f", {with_styles} with styles" if with_styles else ""
            print(f"    {locale_display(locale):18} {n:3} voices{note}")

    if len(styled) < len(voices):
        print(f"\n  {len(voices) - len(styled)} voices support no styles at all. Those are "
              "synthesized\n  without an express-as wrapper rather than being sent one that "
              "does nothing.")

    total_skipped = sum(skipped.values())
    if total_skipped:
        print(f"\n  Left out {total_skipped} premium voices ({skipped['hd']} HD, "
              f"{skipped['aoai']} Azure OpenAI).\n  These bill separately from standard "
              "neural and aren't in the free F0 tier.\n  Add --include-premium if you're on "
              "a paid tier and want them.")
    elif include_premium:
        print("\n  Premium voices included. HD and Azure OpenAI voices bill at a higher\n"
              "  rate than standard neural and are not covered by the free F0 tier.")


if __name__ == "__main__":
    main()
