from azure_text_to_speech import NO_STYLE, AzureTTSManager, styles_for
from players import PLAYER_CONFIG, DEFAULT_VOICE_STYLE, OBS_WEBSOCKETS_ENABLED


class TTSManager:
    """
    Turns text into a wav file. Does not play it.

    Playback moved to the browser: the overlay page fetches the wav over HTTP and
    plays it, which means OBS picks the audio up natively from the browser source and
    the bot thread is never blocked waiting for a clip to finish.
    """

    def __init__(self, slots=None):
        self.azuretts_manager = AzureTTSManager()

        # Layer 1 of voice resolution is the character's default, so seed from the
        # library when there is one. Falling back to players.py keeps a fresh clone
        # working: no characters.json means the character library synthesizes an
        # entry per slot carrying exactly this voice anyway, so the two agree.
        if slots:
            self.voices = {
                number: {"name": character.default_voice or PLAYER_CONFIG[number]["voice_name"],
                         "style": character.default_style}
                for number, character in slots.items()
            }
        else:
            self.voices = {
                number: {"name": config["voice_name"], "style": DEFAULT_VOICE_STYLE}
                for number, config in PLAYER_CONFIG.items()
            }

        # Only constructed when explicitly enabled. Off by default, so a closed OBS
        # is no longer able to take the whole app down at startup.
        self.obswebsockets_manager = None
        if OBS_WEBSOCKETS_ENABLED:
            from obs_websockets import OBSWebsocketsManager
            self.obswebsockets_manager = OBSWebsocketsManager()

        self._audio_manager = None  # built on demand; only local playback needs it

    # -- voice settings -------------------------------------------------------

    def update_voice_name(self, user_number, voice_name):
        """
        Change the voice. Returns the style it had to fall back to if the current
        style isn't available on the new voice, otherwise None.

        Styles aren't universal across voices, so switching voice can strand the
        selected style. Silently sending it anyway is what the old code did, and
        Azure's response to an unsupported style is to render the line neutral
        without complaining -- so the operator saw "whispering" selected and
        heard nothing of the sort.
        """
        voice = self.voices.get(user_number)
        if voice is None:
            print(f"Unknown player number {user_number!r}; voice name not changed.")
            return None
        voice["name"] = voice_name
        print(f"Player {user_number}: voice name is now {voice_name}")

        available = styles_for(voice_name)
        # "none" is always valid -- it means no express-as at all. "random" is only
        # valid on a voice that has styles to pick from; on one that doesn't it would
        # claim to be varying something that can't vary.
        if voice["style"] == NO_STYLE:
            return None
        if voice["style"] == "random" and available:
            return None
        if voice["style"] in available:
            return None

        stranded, voice["style"] = voice["style"], NO_STYLE
        print(f"Player {user_number}: '{stranded}' isn't available on "
              f"{voice_name} - changing to none.")
        return NO_STYLE

    def reset_to(self, user_number, character):
        """
        Put a slot's voice back to its character's defaults.

        The counterpart to DisplayManager.reset_to, called when a character is
        assigned. Falls back to players.py when the character names no voice, which
        keeps a half-filled library working rather than leaving a slot mute.
        """
        self.voices[user_number] = {
            "name": character.default_voice or PLAYER_CONFIG[user_number]["voice_name"],
            "style": character.default_style,
        }
        print(f"Player {user_number}: voice reset to "
              f"{self.voices[user_number]['name']} / {self.voices[user_number]['style']}")
        return self.voices[user_number]

    def update_voice_style(self, user_number, voice_style):
        voice = self.voices.get(user_number)
        if voice is None:
            print(f"Unknown player number {user_number!r}; voice style not changed.")
            return
        voice["style"] = voice_style
        print(f"Player {user_number}: voice style is now {voice_style}")

    # -- synthesis ------------------------------------------------------------

    def synthesize(self, text, user_number):
        """
        Render text to a wav file and return its path, or None if there's nothing
        to say. Blocking, so call it from the speech worker rather than the bot.
        """
        voice = self.voices.get(user_number)
        if voice is None:
            print(f"Unknown player number {user_number!r}; skipping TTS.")
            return None
        return self.azuretts_manager.text_to_audio(text, voice["name"], voice["style"])

    # -- local playback (startup chime and tts_test.py only) -------------------

    def play_locally(self, file_path, delete_after=True):
        """
        Play through the server's own speakers. The live message path no longer uses
        this -- it exists so the startup chime and the test scripts still work
        without an overlay page open.
        """
        if not file_path:
            return
        if self._audio_manager is None:
            from audio_player import AudioManager
            self._audio_manager = AudioManager()
        self._audio_manager.play_audio(file_path, True, delete_after, True)

    def play_startup_chime(self):
        try:
            path = self.azuretts_manager.text_to_audio("Chat God App is now running!")
            self.play_locally(path)
        except Exception as exc:
            # A missing audio device shouldn't stop the app from running.
            print(f"Couldn't play the startup chime ({exc}). Continuing.")

    # -- legacy OBS filter toggling -------------------------------------------

    def set_filter(self, user_number, enabled):
        """No-op unless OBS_WEBSOCKETS_ENABLED is turned back on."""
        if self.obswebsockets_manager is None:
            return
        config = PLAYER_CONFIG.get(user_number)
        if config is None:
            return
        self.obswebsockets_manager.set_filter_visibility(
            config["obs_source"], config["obs_filter"], enabled)
