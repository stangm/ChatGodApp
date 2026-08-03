import json
import os
import random
import tempfile
import uuid
from xml.sax.saxutils import escape as xml_escape
import azure.cognitiveservices.speech as speechsdk
from gtts import gTTS
from pydub import AudioSegment
import pygame

import usage
from config import setting

# Generated clips live outside the repo. The original wrote them to the working
# directory with names built from hash(text), which is randomised per run -- so old
# _Msg*.wav files piled up in the project folder and never matched on a later run.
AUDIO_OUTPUT_DIR = os.path.join(tempfile.gettempdir(), "chatgod_audio")
os.makedirs(AUDIO_OUTPUT_DIR, exist_ok=True)

_HERE = os.path.dirname(os.path.abspath(__file__))

# Your own fetch, gitignored. Takes precedence when present.
VOICES_JSON = os.path.join(_HERE, "voices.json")
# Shipped with the repo: a real fetch_voices.py run covering every English
# locale, free-tier voices only. Means a fresh clone gets accurate voices and
# real style lists before anyone has an Azure key.
VOICES_DEFAULT_JSON = os.path.join(_HERE, "voices.default.json")

# Last resort, if both files are missing or unreadable. Deliberately claims no
# styles: we don't know what these support, and inventing a list is exactly how
# the old hardcoded fallback ended up asserting nine styles worked on every
# voice when most support none.
_EMERGENCY_VOICES = ["en-US-AriaNeural", "en-US-DavisNeural",
                     "en-US-GuyNeural", "en-US-JennyNeural"]


def _read_catalog(path):
    """Parse one catalog file into the internal shape, or None if unusable."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        catalog = {
            v["short_name"]: {
                "local_name": v.get("local_name") or v["short_name"],
                "gender": v.get("gender", ""),
                "locale": v.get("locale", ""),
                "locale_name": v.get("locale_name") or v.get("locale", ""),
                "tier": v.get("tier", "standard"),
                # Azure reports "no styles" as [''], not []. fetch_voices.py strips
                # those, but a file written by an older version still has them, and
                # a blank style means a blank dropdown entry and style='' in the
                # SSML. Cheap to guard here too.
                "styles": [s for s in v.get("styles", []) if s and s.strip()],
            }
            for v in data["voices"]
        }
        return catalog or None
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"Could not read {os.path.basename(path)} ({exc}); skipping it.")
        return None


def _load_catalog():
    """
    Returns (catalog, source) where source is "fetched", "default" or "builtin".

    Tried in order: your voices.json, the shipped voices.default.json, then a
    tiny built-in list. The app should always start -- on a fresh clone, with no
    Azure account, with the catalog files deleted.
    """
    catalog = _read_catalog(VOICES_JSON)
    if catalog:
        return catalog, "fetched"

    catalog = _read_catalog(VOICES_DEFAULT_JSON)
    if catalog:
        print(f"Using the shipped voice list ({len(catalog)} voices). Run "
              "'python fetch_voices.py' for the current catalog and your own "
              "choice of locales.")
        return catalog, "default"

    print("No voice catalog found. Falling back to a handful of voices with no "
          "styles.\nRun 'python fetch_voices.py' to fix this.")
    return ({name: {"local_name": name.split("-")[-1].removesuffix("Neural"),
                    "gender": "", "locale": "en-US",
                    "locale_name": "United States", "tier": "standard",
                    "styles": []}
             for name in _EMERGENCY_VOICES}, "builtin")


VOICE_CATALOG, VOICES_SOURCE = _load_catalog()

AZURE_VOICES = list(VOICE_CATALOG)

# Every style any known voice supports. The control panel narrows this per voice;
# this union is only for building the full option list.
AZURE_VOICE_STYLES = sorted({s for v in VOICE_CATALOG.values() for s in v["styles"]})


def styles_for(voice_name):
    """
    Styles this voice actually supports. Empty list is a real answer -- plenty of
    voices support no express-as at all, and those are synthesized without the
    wrapper instead of pretending the style applied.
    """
    entry = VOICE_CATALOG.get(voice_name)
    return list(entry["styles"]) if entry else []


def resolve_style(voice_name, voice_style):
    """
    Pick a style that will actually do something on this voice.

    "random" picks from what the voice supports. A style the voice doesn't
    support -- from a stale dropdown or a chat prefix -- degrades to random
    rather than being sent and silently ignored. Returns None when the voice
    supports no styles, meaning "synthesize without express-as".
    """
    available = styles_for(voice_name)
    if not available:
        return None
    if voice_style in available:
        return voice_style
    return random.choice(available)

AZURE_PREFIXES = {
    "(angry)" : "angry",
    "(cheerful)" : "cheerful",
    "(excited)" : "excited",
    "(hopeful)" : "hopeful",
    "(sad)" : "sad",
    "(shouting)" : "shouting",
    "(shout)" : "shouting",
    "(terrified)" : "terrified",
    "(unfriendly)" : "unfriendly",
    "(whispering)" : "whispering",
    "(whisper)" : "whispering",
    "(random)" : "random"
}

def _failure_reason(result):
    """
    A short, readable reason a synthesis failed.

    Azure's cancellation details carry the useful part -- a 401 for a bad key, a 403
    for the wrong region or an exhausted quota -- but they arrive as a wall of text
    with an error code buried in it. The status panel wants one line, and the common
    causes are worth naming outright because they're indistinguishable on stream:
    every one of them just sounds like the robotic fallback voice.
    """
    try:
        details = speechsdk.CancellationDetails(result)
        raw = (details.error_details or "").strip()
    except Exception:
        raw = ""

    lowered = raw.lower()
    if "401" in lowered or "unauthorized" in lowered or "authentication" in lowered:
        return "key rejected -- check CHATGOD_AZURE_KEY"
    if "403" in lowered or "forbidden" in lowered:
        return "refused -- wrong region, or the monthly quota is used up"
    if "quota" in lowered or "exceeded" in lowered:
        return "quota exceeded for this month"
    if "connection" in lowered or "timeout" in lowered or "unreachable" in lowered:
        return "couldn't reach Azure -- network or firewall"
    return raw[:120] if raw else "no reason given"


class AzureTTSManager:
    azure_speechconfig = None
    azure_synthesizer = None

    # Outcome of the most recent synthesis, for the control panel's status row:
    # None (nothing tried yet), 'ok', or a short reason it fell back to gTTS.
    #
    # This is a health signal rather than a log. The app already synthesizes a
    # startup chime, so by the time the panel is first opened this has been set by a
    # real Azure round trip -- an active credential check for free, with no extra
    # call and no artificial test phrase.
    last_result = None
    last_error = None

    def __init__(self):
        pygame.init()
        # Creates an instance of a speech config with specified subscription key and service region.
        # Replace with your own subscription key and service region (e.g., "westus").
        self.azure_speechconfig = speechsdk.SpeechConfig(subscription=setting('azure_key'), region=setting('azure_region'))
        # Set the voice name, refer to https://aka.ms/speech/voices/neural for full list.
        self.azure_speechconfig.speech_synthesis_voice_name = "en-US-AriaNeural"
        # Creates a speech synthesizer. Setting audio_config to None means it wont play the synthesized text out loud.
        self.azure_synthesizer = speechsdk.SpeechSynthesizer(speech_config=self.azure_speechconfig, audio_config=None)        

    # Returns the path to the new .wav file
    def text_to_audio(self, text: str, voice_name="random", voice_style="random"):
        if voice_name == "random":
            voice_name = random.choice(AZURE_VOICES)

        # Change the voice style if the message includes a prefix
        text = text.lower()
        if text.startswith("(") and ")" in text:
            prefix = text[0:(text.find(")")+1)]
            if prefix in AZURE_PREFIXES:
                voice_style = AZURE_PREFIXES[prefix]
                text = text.removeprefix(prefix)
        if len(text) == 0:
            print("This message was empty")
            return

        # Resolved once, after the prefix has had its say. Handles "random",
        # coerces styles this voice can't do, and returns None for voices that
        # support no styles at all.
        voice_style = resolve_style(voice_name, voice_style)

        # Chat is untrusted XML input: an unescaped & or < makes the SSML
        # malformed, Azure rejects the whole request, and the gTTS fallback
        # fires. "Tom & Jerry" was enough to trigger it.
        body = xml_escape(text)
        if voice_style:
            body = f"<mstts:express-as style='{voice_style}'>{body}</mstts:express-as>"

        ssml_text = (
            "<speak version='1.0' "
            "xmlns='http://www.w3.org/2001/10/synthesis' "
            "xmlns:mstts='http://www.w3.org/2001/mstts' "
            "xmlns:emo='http://www.w3.org/2009/10/emotionml' "
            f"xml:lang='en-US'><voice name='{voice_name}'>{body}</voice></speak>"
        )
        result = self.azure_synthesizer.speak_ssml_async(ssml_text).get()

        output = os.path.join(AUDIO_OUTPUT_DIR, f"_Msg{uuid.uuid4().hex}.wav")
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            stream = speechsdk.AudioDataStream(result)
            stream.save_to_wav_file(output)
            AzureTTSManager.last_result = "ok"
            AzureTTSManager.last_error = None
            # Counted only on success, since a failed call isn't billed. Counting on
            # entry would inflate the total every time the key was wrong.
            usage.record(text)
        else:
            # If Azure fails, use gTTS instead. gTTS saves as an mp3 by default, so convert it to a wav file after
            AzureTTSManager.last_result = "fallback"
            AzureTTSManager.last_error = _failure_reason(result)
            print(f"\n   Azure failed ({AzureTTSManager.last_error}), using gTTS instead   \n")
            output_mp3 = output.replace(".wav", ".mp3")
            msgAudio = gTTS(text=text, lang='en', slow=False)
            msgAudio.save(output_mp3)
            audiosegment = AudioSegment.from_mp3(output_mp3)
            audiosegment.export(output, format="wav")
            try:
                os.remove(output_mp3)   # the original left the intermediate mp3 behind
            except OSError:
                pass

        return output


# Tests here
if __name__ == '__main__':
    tts_manager = AzureTTSManager()
    pygame.mixer.init()

    file_path = tts_manager.text_to_audio("Here's my test audio!!", "en-US-DavisNeural")
    pygame.mixer.music.load(file_path)
    pygame.mixer.music.play()

    while True:
        stuff_to_say = input("\nNext question? \n\n")
        if len(stuff_to_say) == 0:
            continue
        file_path = tts_manager.text_to_audio(stuff_to_say)
        pygame.mixer.music.load(file_path)
        pygame.mixer.music.play()
        