from azure_text_to_speech import AzureTTSManager
from players import PLAYER_CONFIG, OBS_WEBSOCKETS_ENABLED
from slots import SlotSettings


class TTSManager:
    """
    Turns text into a wav file. Does not play it.

    Playback moved to the browser: the overlay page fetches the wav over HTTP and
    plays it, which means OBS picks the audio up natively from the browser source and
    the bot thread is never blocked waiting for a clip to finish.
    """

    def __init__(self, slot_store):
        self.azuretts_manager = AzureTTSManager()

        # Which voice a slot is currently using is slot state, not synthesis state,
        # so it lives in SlotStore with the rest of layer 2 and this only reads it.
        # Holding a second copy here is what made "what is slot 3 set to" a question
        # with three answers.
        self.slots = slot_store

        # Only constructed when explicitly enabled. Off by default, so a closed OBS
        # is no longer able to take the whole app down at startup.
        self.obswebsockets_manager = None
        if OBS_WEBSOCKETS_ENABLED:
            from obs_websockets import OBSWebsocketsManager
            self.obswebsockets_manager = OBSWebsocketsManager()

        self._audio_manager = None  # built on demand; only local playback needs it

    # -- synthesis ------------------------------------------------------------

    def synthesize(self, text, user_number):
        """
        Render text to a wav file and return its path, or None if there's nothing
        to say. Blocking, so call it from the speech worker rather than the bot.
        """
        settings = self.slots.get(user_number)
        # isinstance, not `is None`. The store and the character map are both
        # keyed by slot number, so handing over the wrong one returns a perfectly
        # truthy Character and the None check passes -- then every message dies on
        # an AttributeError inside the speech worker, which swallows it. A guard
        # that only catches None cannot catch the right container holding the
        # wrong contents, which is exactly how this shipped once.
        if not isinstance(settings, SlotSettings):
            print(f"No live settings for player {user_number!r} "
                  f"(got {type(settings).__name__}); skipping TTS.")
            return None
        return self.azuretts_manager.text_to_audio(
            text, settings.voice_name, settings.voice_style)

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
            path = self.azuretts_manager.text_to_audio("ChatMob is now running!")
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
