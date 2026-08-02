"""
Single source of truth for player configuration.

Adding a player is one entry here. Nothing else in the Python needs to change.
(The web UI still hardcodes three panels -- that comes out in the template pass.)

Names under "obs_source" and "obs_filter" must match OBS exactly, including case and
spacing. A mismatch fails silently: OBS returns an error response that the code never
inspects, so the animation simply doesn't happen.
"""

# Style applied to a player's voice until the operator picks one in the web UI.
# "random" makes each message pick a different style.
DEFAULT_VOICE_STYLE = "random"

# Since audio now plays in the browser, OBS no longer hears anything on "Line In" and
# the app has nothing useful to toggle. Animation comes from an Audio Move filter
# attached directly to each overlay browser source, always enabled.
#
# Set this back to True only if you are still driving filters the old way. When False
# the app never connects to OBS, so OBS no longer has to be running at all.
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
