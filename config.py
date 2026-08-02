"""
One place where every setting is resolved.

Two problems this fixes.

**Collisions.** The app read `AZURE_TTS_KEY`, `AZURE_TTS_REGION`, `TWITCH_ACCESS_TOKEN`
and `TWITCH_CHANNEL_NAME` -- names any other tool talking to Azure Speech or Twitch
would plausibly also pick. Sharing a machine with such a tool means one of them
silently gets the other's credentials, and the failure looks like a bad key rather
than a name clash. Everything is now `CHATGOD_`-prefixed.

**Scatter.** Those reads were spread across three modules, each with its own idea of
whether to strip whitespace or what the default was. Adding `config.json` to the
resolution order (stage A of the guided-install design) would have meant editing all
three and keeping them in agreement. Now it is one function.

Resolution order, first non-empty wins:

    CHATGOD_-prefixed variable  ->  legacy variable  ->  built-in default

`config.json` slots in between the legacy variable and the default when it lands.

**Legacy names are kept, and still win over anything but the prefixed name.** Nothing
breaks for an install that already has them set, or for anyone arriving from
DougDoug's upstream README. But a legacy name is exactly the collision this module
exists to prevent, so `legacy_in_use()` reports them and startup says so out loud --
a silent fallback would preserve the bug while looking like a fix.

An empty variable counts as unset. Windows makes it easy to end up with one set to
the empty string, and treating that as "configured, with no value" produces a
confusing failure much later.
"""

import os
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class Spec:
    env: str                                   # prefixed name; what the docs tell you to set
    legacy: str                                # unprefixed name this app used to read
    default: Optional[str] = None
    normalize: Optional[Callable[[str], str]] = None
    secret: bool = False                       # never print the value
    required: bool = True
    describes: str = ""                        # what breaks without it


SPECS = {
    "twitch_token": Spec(
        env="CHATGOD_TWITCH_TOKEN",
        legacy="TWITCH_ACCESS_TOKEN",
        secret=True,
        describes="the bot cannot log in to Twitch",
    ),
    "twitch_channel": Spec(
        env="CHATGOD_TWITCH_CHANNEL",
        legacy="TWITCH_CHANNEL_NAME",
        default="silverstagvt",
        # twitchio matches channels case-sensitively, and the common mistake is
        # typing the display name rather than the login name.
        normalize=str.lower,
        required=False,
        describes="the bot reads the wrong channel",
    ),
    "azure_key": Spec(
        env="CHATGOD_AZURE_KEY",
        legacy="AZURE_TTS_KEY",
        secret=True,
        describes="Azure speech fails and playback falls back to gTTS",
    ),
    "azure_region": Spec(
        env="CHATGOD_AZURE_REGION",
        legacy="AZURE_TTS_REGION",
        describes="Azure speech fails and playback falls back to gTTS",
    ),
}


def resolve(key):
    """
    Return (value, source, name) for one setting.

    source is 'env', 'legacy' or 'default'; name is the variable the value actually
    came from, or None for a default. Callers that only want the value use setting().
    """
    spec = SPECS[key]
    for name, source in ((spec.env, "env"), (spec.legacy, "legacy")):
        value = (os.getenv(name) or "").strip()
        if value:
            return (spec.normalize(value) if spec.normalize else value), source, name

    value = spec.default
    if value is not None and spec.normalize:
        value = spec.normalize(value)
    return value, "default", None


def setting(key):
    """The resolved value, or None if it isn't set and has no default."""
    return resolve(key)[0]


def legacy_in_use():
    """
    (prefixed_name, legacy_name) for every setting still coming from an unprefixed
    variable. These work, but they're the collision risk -- so they're worth naming
    at startup rather than quietly accepting.
    """
    return [(SPECS[key].env, SPECS[key].legacy)
            for key in SPECS if resolve(key)[1] == "legacy"]


def missing_required():
    """Prefixed names of required settings with no value from any source."""
    return [SPECS[key].env for key in SPECS
            if SPECS[key].required and not setting(key)]


def startup_report():
    """
    Lines describing the configuration, for printing at startup.

    Values are shown only for settings that aren't secret -- knowing which channel
    is being read is the single most useful line at startup, and knowing that a key
    is present matters, but the key itself has no business in a terminal someone
    might be screen-sharing while streaming.
    """
    lines = []
    for key, spec in SPECS.items():
        value, source, name = resolve(key)
        if not value:
            lines.append(f"  {spec.env}: NOT SET -- {spec.describes}")
        elif spec.secret:
            lines.append(f"  {spec.env}: set (from {name or 'default'})")
        else:
            suffix = "" if source == "env" else f" (from {name or 'built-in default'})"
            lines.append(f"  {spec.env}: {value}{suffix}")
    return lines


def set_command(name, value="yourvalue"):
    """The PowerShell line that sets one variable, for error messages."""
    return f'[Environment]::SetEnvironmentVariable("{name}", "{value}", "User")'
