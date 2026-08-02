"""
Single source of truth for player configuration.

Adding a player is one entry here. Nothing else needs to change: both templates
iterate this dict, so the control panel and the overlay grow a slot on their own.
You will also want static/characters/player<N>-closed.png and -open.png, and a
browser source pointing at /overlay?player=<N>.

The "obs_source" and "obs_filter" keys below are only read when
OBS_WEBSOCKETS_ENABLED is True, and new entries can leave them out entirely.
When they are used, the names must match OBS exactly, including case and spacing:
a mismatch fails silently, because OBS returns an error response that the code
never inspects.
"""

# Style applied to a player's voice until the operator picks one in the web UI.
# "random" makes each message pick a different style.
DEFAULT_VOICE_STYLE = "random"

# Since audio now plays in the browser, OBS no longer hears anything on "Line In" and
# the app has nothing useful to toggle. The mouth animation happens inside the overlay
# page instead: it analyses the clip it is playing with WebAudio and swaps between the
# open and closed PNGs. No OBS plugin or filter is involved.
#
# Set this back to True only if you are still driving Move filters the old way. When
# False the app never connects to OBS, so OBS does not have to be running at all.
OBS_WEBSOCKETS_ENABLED = False

PLAYER_CONFIG = {
    "1": {
        "keyphrase": "!player1",
        "voice_name": "en-US-DavisNeural",
        "obs_source": "Line In",
        "obs_filter": "Audio Move - DnD Player 1",
    },
    "2": {
        "keyphrase": "!player2",
        "voice_name": "en-US-TonyNeural",
        "obs_source": "Line In",
        "obs_filter": "Audio Move - DnD Player 2",
    },
    "3": {
        "keyphrase": "!player3",
        "voice_name": "en-US-JaneNeural",
        "obs_source": "Line In",
        "obs_filter": "Audio Move - DnD Player 3",
    },
}

# Keys are strings because that is what the browser sends over the socket.
# Keeping them strings end-to-end avoids int/str coercion bugs in the handlers.
PLAYER_NUMBERS = tuple(PLAYER_CONFIG)
