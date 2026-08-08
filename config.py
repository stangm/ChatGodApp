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

    CHATMOB_-prefixed variable  ->  config.json  ->  default

Both layers are unambiguous: a `CHATMOB_`-prefixed variable and a `config.json` next
to this app are each unmistakably meant for this app and nothing else. The variable
wins because it's the more specific of the two and the easier to override for one
run.

**There used to be a third layer and it is gone on purpose (7 Aug 2026).** The app
originally read `AZURE_TTS_KEY`, `AZURE_TTS_REGION`, `TWITCH_ACCESS_TOKEN` and
`TWITCH_CHANNEL_NAME`, and those were kept as a silent-but-announced fallback,
briefly joined by a `CHATGOD_` generation from before the rename.

Removing them is worth explaining, because "keep the fallback, it costs nothing" is
the obvious call and it was the wrong one:

- **The `CHATGOD_` generation was never set on any machine.** It existed in code for
  five days and protected a population of zero.
- **The warning did not work.** The unprefixed names were quietly powering the only
  real install for months. Startup announced it at every single launch, in a block
  written specifically to be noticed -- and it was scrolled past every time. A
  fallback that has to be *read about* to be noticed is a fallback that hides
  misconfiguration in plain sight.
- **A loud failure is cheaper than a quiet success on the wrong value.** With the
  layer gone, an old-only machine gets `Not set: CHATMOB_AZURE_KEY` and instructions,
  which takes a minute to act on. The alternative was an app that worked until the
  day another Azure tool claimed the same generic name.

So there is nothing to migrate from any more. If a machine turns up configured the
old way, set the four `CHATMOB_` names or write a `config.json`; both are a two-minute
job and the startup report will say exactly which one it read.

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
    default: Optional[str] = None
    normalize: Optional[Callable[[str], str]] = None
    secret: bool = False                       # never print the value
    required: bool = True
    describes: str = ""                        # what breaks without it


SPECS = {
    "twitch_token": Spec(
        env="CHATMOB_TWITCH_TOKEN",
        secret=True,
        describes="the bot cannot log in to Twitch",
    ),
    "twitch_channel": Spec(
        env="CHATMOB_TWITCH_CHANNEL",
        # **No default, deliberately.** This used to fall back to one specific
        # streamer's channel, which is the one value that is wrong for every
        # install except the machine it was written on. Forgetting it there
        # produced a bot that connected *successfully* to someone else's chat,
        # with a green status row naming a plausible channel, and no keyphrase
        # ever matching -- a green lie, which is the exact failure mode the
        # legacy-variable fallback was removed for.
        #
        # It's a per-install value set once at setup, so there is no universal
        # default that could be right. Absent means absent.
        default=None,
        # twitchio matches channels case-sensitively, and the common mistake is
        # typing the display name rather than the login name.
        normalize=str.lower,
        required=True,
        describes="the bot has no channel to read",
    ),
    "azure_key": Spec(
        env="CHATMOB_AZURE_KEY",
        secret=True,
        describes="Azure speech fails and playback falls back to gTTS",
    ),
    "azure_region": Spec(
        env="CHATMOB_AZURE_REGION",
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

    source is 'env', 'config' or 'default'; name is where the value actually came
    from, for the startup report. Callers that only want the value use setting().
    """
    spec = SPECS[key]

    value = (os.getenv(spec.env) or "").strip()
    if value:
        return (spec.normalize(value) if spec.normalize else value), "env", spec.env

    value = _from_config(key)
    if value:
        return (spec.normalize(value) if spec.normalize else value), "config", "config.json"

    value = spec.default
    if value is not None and spec.normalize:
        value = spec.normalize(value)
    return value, "default", None


def setting(key):
    """The resolved value, or None if it isn't set and has no default."""
    return resolve(key)[0]


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
