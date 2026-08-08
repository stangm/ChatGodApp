"""
One place where every setting is resolved.

Two problems this fixes.

**Collisions.** The app read `AZURE_TTS_KEY`, `AZURE_TTS_REGION`, `TWITCH_ACCESS_TOKEN`
and `TWITCH_CHANNEL_NAME` -- names any other tool talking to Azure Speech or Twitch
would plausibly also pick. Sharing a machine with such a tool means one of them
silently gets the other's credentials, and the failure looks like a bad key rather
than a name clash. Everything is now `CHATMOB_`-prefixed.

**Scatter.** Those reads were spread across three modules, each with its own idea of
whether to strip whitespace or what the default was. Adding `config.json` to the
resolution order (stage A of the guided-install design) would have meant editing all
three and keeping them in agreement. Now it is one function.

Resolution order, first non-empty wins:

    CHATMOB_-prefixed variable  ->  config.json  ->  legacy variables  ->  default

**There are two generations of legacy name**, tried in that order: the `CHATGOD_`
names this app used before it was renamed, then the unprefixed names it read before
that. Both still work. `CHATGOD_` sits above the unprefixed ones for the same reason
`CHATMOB_` sits above `CHATGOD_`: a prefixed name was unambiguously meant for this
app, and an unprefixed one is a guess.

**config.json sits above the legacy names, which reverses what the design doc
originally proposed.** The doc's rule was "environment variables always beat files",
which is the conventional ordering and reads well until you look at what these
particular layers mean:

- a `CHATMOB_`-prefixed variable is unambiguously meant for this app
- `config.json` next to this app is unambiguously meant for this app
- an unprefixed `AZURE_TTS_KEY` is a *guess* that a generic name refers to us

Since `config.json` is how a configured machine gets handed to someone, putting the
ambiguous shim above it means a stale variable from an unrelated tool would silently
beat the file that was deliberately written for them -- and the resulting failure
looks like a bad key, which is the exact confusion the prefix exists to prevent. So
the two deliberate layers go on top and the compatibility shim goes underneath.

**Legacy names still work**, so nothing breaks for a machine configured before the
rename, or for anyone arriving from DougDoug's upstream README. But `legacy_in_use()`
reports them and startup says so out loud, naming the one that actually fired: a
silent fallback would preserve the collision risk while looking like a fix, and after
a rename it would also hide the fact that the machine is still on the old names.

An empty value counts as unset, in the file as well as the environment. Windows makes
it easy to end up with a variable set to the empty string, and treating that as
"configured, with no value" produces a confusing failure much later.

**config.json holds secrets in plain text**, deliberately. Obfuscating them would be
fake security on a file sitting in the user's own directory, and it would make the
one thing you actually want -- reading it to check what's set -- harder. It's
gitignored, and the example file says plainly what it contains.
"""

import json
import os
from dataclasses import dataclass
from typing import Callable, Optional

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


@dataclass(frozen=True)
class Spec:
    env: str                                   # prefixed name; what the docs tell you to set
    legacy: tuple                              # older names, newest first; all still honoured
    default: Optional[str] = None
    normalize: Optional[Callable[[str], str]] = None
    secret: bool = False                       # never print the value
    required: bool = True
    describes: str = ""                        # what breaks without it


SPECS = {
    "twitch_token": Spec(
        env="CHATMOB_TWITCH_TOKEN",
        legacy=("CHATGOD_TWITCH_TOKEN", "TWITCH_ACCESS_TOKEN"),
        secret=True,
        describes="the bot cannot log in to Twitch",
    ),
    "twitch_channel": Spec(
        env="CHATMOB_TWITCH_CHANNEL",
        legacy=("CHATGOD_TWITCH_CHANNEL", "TWITCH_CHANNEL_NAME"),
        default="silverstagvt",
        # twitchio matches channels case-sensitively, and the common mistake is
        # typing the display name rather than the login name.
        normalize=str.lower,
        required=False,
        describes="the bot reads the wrong channel",
    ),
    "azure_key": Spec(
        env="CHATMOB_AZURE_KEY",
        legacy=("CHATGOD_AZURE_KEY", "AZURE_TTS_KEY"),
        secret=True,
        describes="Azure speech fails and playback falls back to gTTS",
    ),
    "azure_region": Spec(
        env="CHATMOB_AZURE_REGION",
        legacy=("CHATGOD_AZURE_REGION", "AZURE_TTS_REGION"),
        describes="Azure speech fails and playback falls back to gTTS",
    ),
}


# Parsed config.json, cached. None until first read; {} means "nothing usable".
_config = None
_config_state = "unread"   # unread | missing | ok | broken


def _load_config():
    """
    Read config.json once and remember the outcome.

    Three outcomes, kept apart because they mean different things to the operator:
    the file isn't there (normal -- environment variables are still fully supported),
    it's there and readable, or it's there and broken. The last one is the only one
    worth shouting about, and it must not stop the app: a typo in a JSON file ten
    minutes before a stream should cost you the file's contents, not the stream.
    """
    global _config, _config_state
    if not os.path.exists(CONFIG_FILE):
        _config, _config_state = {}, "missing"
        return _config
    try:
        with open(CONFIG_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"config.json could not be read ({exc}); ignoring it and using "
              "environment variables instead.")
        _config, _config_state = {}, "broken"
        return _config
    if not isinstance(data, dict):
        print("config.json isn't a JSON object; ignoring it.")
        _config, _config_state = {}, "broken"
        return _config
    _config, _config_state = data, "ok"
    return _config


def reload():
    """
    Forget the cached config.json and read it again.

    Nothing calls this yet. It exists because the setup wizard will write the file
    while the app is running, and a module-level cache with no way to refresh it is
    the kind of decision that's invisible until it's expensive.
    """
    global _config, _config_state
    _config, _config_state = None, "unread"
    return _load_config()


def config_state():
    """'missing', 'ok' or 'broken' -- for the startup report and diagnostics."""
    if _config is None:
        _load_config()
    return _config_state


def _from_config(key):
    """This setting's value from config.json, or '' if absent or unusable."""
    data = _config if _config is not None else _load_config()
    value = data.get(key)
    # Coerced rather than rejected: someone hand-editing JSON may well write a
    # region as a bare word or a number, and refusing an otherwise fine value on a
    # type technicality helps nobody.
    if value is None or isinstance(value, (dict, list, bool)):
        return ""
    return str(value).strip()


def resolve(key):
    """
    Return (value, source, name) for one setting.

    source is 'env', 'config', 'legacy' or 'default'; name is where the value
    actually came from, for the startup report. Callers that only want the value use
    setting().
    """
    spec = SPECS[key]

    value = (os.getenv(spec.env) or "").strip()
    if value:
        return (spec.normalize(value) if spec.normalize else value), "env", spec.env

    value = _from_config(key)
    if value:
        return (spec.normalize(value) if spec.normalize else value), "config", "config.json"

    # Oldest names last, so a machine that sets both the CHATGOD_ name and the
    # unprefixed one gets the more deliberate of the two.
    for old in spec.legacy:
        value = (os.getenv(old) or "").strip()
        if value:
            return (spec.normalize(value) if spec.normalize else value), "legacy", old

    value = spec.default
    if value is not None and spec.normalize:
        value = spec.normalize(value)
    return value, "default", None


def setting(key):
    """The resolved value, or None if it isn't set and has no default."""
    return resolve(key)[0]


def legacy_in_use():
    """
    (current_name, old_name_actually_used) for every setting still coming from an
    older variable. These work, but they're the collision risk -- and after a rename
    they're also the thing that will quietly stop being maintained -- so they're
    worth naming at startup rather than quietly accepting.

    The second element is the name that actually supplied the value, not the whole
    list of candidates: telling someone to migrate away from a variable they never
    set is worse than saying nothing.
    """
    out = []
    for key in SPECS:
        _, source, name = resolve(key)
        if source == "legacy":
            out.append((SPECS[key].env, name))
    return out


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
    state = config_state()
    lines = []
    if state == "ok":
        lines.append("  config.json: found")
    elif state == "broken":
        lines.append("  config.json: UNREADABLE -- ignored, see the error above")

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
