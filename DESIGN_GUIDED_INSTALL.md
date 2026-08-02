# Design: guided install

**Status: design only.** Nothing built. This is a target to aim at and revise as the app settles —
deliberately not implemented yet, because an installer hardens whatever install surface exists at the
time, and that surface is still moving.

**Goal.** A streamer who has never opened a terminal can go from "downloaded a zip" to "character
talking on stream" without editing a file, reading a runbook, or knowing what an environment variable
is.

**The bar.** `SETUP_RUNBOOK.md` is currently 6 stages, ~250 lines, and assumes PowerShell, a Python
install, an Azure portal account and a token generator site. It's a good runbook. It is not something
you hand to someone who wants to stream in an hour.

---

## Who this is for

**One other streamer, non-technical, with the option to open it up later.** That number matters more
than anything else in this document, and it cuts two ways.

At N=1 you can do things that don't scale, and should. You can fill in her config by hand, run the
first install with her over a screen share, and pre-generate anything that needs a key. A wizard that
walks a stranger through creating an Azure resource is weeks of work that one person doesn't justify
— you can just do that part *for* her, once.

What doesn't go away at N=1:

- **She has to start it every stream.** Daily operation, not one-time setup, is where a
  non-technical user actually spends their friction. This is underweighted in most install thinking.
- **When it breaks you're the support desk.** "It's not working" with no further detail, over
  Discord, mid-stream. At N=1 this is the dominant ongoing cost, and almost nothing in the original
  version of this document addressed it.
- **Polish still matters**, both because you want it and because it's what makes opening up later a
  smaller job than starting over.

So the design splits into three, and only the first two are worth building now:

1. **Make it start reliably every day** — launcher, no terminal
2. **Make failures self-describing** — so she can tell you what's wrong, or better, fix it herself
3. **Make setup self-service** — the full wizard. Only pays off at N > 1

The overlay design named the target as "comfortable with OBS but will not edit Python." Still right.
Two consequences hold regardless of N:

- **Anything that can fail silently must be checked**, not left to be noticed on stream.
- **Anything copied from another website** (Twitch token, Azure key) needs a paste box and a "that
  worked" confirmation, not an instruction to set a variable.

---

## Where the friction actually is

Ranked by how many people it would stop, based on what the runbook has to warn about today.

| Step | Why it hurts |
|---|---|
| Install Python, correct version, on PATH | Total blocker. 3.13 breaks a wheel; PATH is invisible when wrong |
| Set 4 environment variables | The reopen-your-terminal trap. Runbook calls this "the single most common failure" |
| Create an Azure Speech resource | Portal is intimidating, F0 tier is easy to miss, region must be the short form |
| Generate a Twitch token | Third-party site, specific scopes, easy to copy the refresh token instead |
| `pip install`, venv, activation policy | PowerShell execution policy, OneDrive sync, wrong-venv confusion |
| Add browser sources in OBS | Mechanical, but three URLs to type correctly |
| Character art | Needs two same-size PNGs per player |

The first two are the ones that decide whether this is a five-minute job or an evening.

**At N=1, most of this table is solvable by you rather than by software.** You set up the Azure
resource, generate the Twitch token, and hand over a machine with `config.json` already written. The
rows that survive are Python, dependencies, OBS sources and art — and the first two collapse into the
launcher.

That reordering is the single biggest consequence of building for one person. It moves the wizard
from "the point of this project" to "the thing you build if you open it up."

---

## The part that isn't install: living with it

She'll launch this before every stream and something will eventually go wrong while you're not
watching. This deserves more design attention than the install does, and it's what the first draft
of this document missed.

**Starting it.** A desktop shortcut that opens the control panel and needs no terminal. If she ever
sees a console window with a traceback, that's a design failure. The launcher should keep its window
minimised or hidden, and put anything worth reading in the browser.

> **Known trap for whoever builds this.** Flask-SocketIO refuses to start the Werkzeug server when
> `sys.stdin` isn't a TTY — it raises "The Werkzeug web server is not designed to run in production."
> Running `python chat_god_app.py` in a terminal is fine, which is why nothing has hit this yet. A
> launcher that hides the console, uses `pythonw`, or runs the app detached will trip it immediately
> and look like a crash on startup. The fix is `socketio.run(app, allow_unsafe_werkzeug=True)`, which
> is fine here: this only ever serves localhost.

**Knowing it's working.** The control panel should show status at a glance, before she goes live:

```
Twitch     connected as silverstagbot, reading #herchannel
Azure      key valid, 412,000 of 500,000 characters left this month
Voices     119 loaded, 21 with styles
Overlay    2 browser sources connected
```

Every one of those is a thing that can be silently wrong today. Bot logged out, key expired, quota
exhausted mid-stream, OBS source not actually pointed at the right URL. A green/red panel she checks
before going live turns most support conversations into her reading one line to you.

Azure quota is worth calling out: the F0 tier is 500,000 characters a month, and hitting the ceiling
mid-stream would look exactly like "TTS randomly stopped working." Whether the API exposes remaining
quota needs checking; if not, counting characters locally is a decent approximation.

**Telling you what broke.** A rolling log file, and a "copy diagnostics" button that puts version,
config state with secrets redacted, and the last errors on the clipboard. Being able to say "click
that button and paste it to me" is worth more than any number of wizard pages.

**Not breaking on update.** If you hand her a new zip, her config, art and voice list must survive.
That argues for keeping user data out of the app folder, or at minimum being certain about which
files are hers and which are yours.

---

## Shape

Two pieces, because they solve different problems and fail differently.

### 1. A launcher that handles the machine

A single `.bat` (or small signed `.exe`) the user double-clicks. It:

1. Finds a usable Python 3.9–3.12, or offers to download and install one
2. Creates `.venv` next to the app if absent
3. `pip install -r requirements.txt` on first run, skips it after
4. Starts the app and opens the browser at the wizard or the control panel

Everything here is unattended and idempotent. Double-clicking it a second time should just start the
app.

### 2. A browser wizard that handles the credentials

Once the app is running it can serve its own setup UI, which is where the copy-paste steps belong.
The browser is the right surface: it can validate a key the moment it's pasted, it can play a test
sound, and it can show a live preview of the overlay.

```
/setup/welcome     what this is, what you'll need, ~10 minutes
/setup/twitch      token + channel, validated by connecting
/setup/azure       key + region, validated by synthesizing a test phrase
/setup/voices      runs fetch_voices.py, shows what it found
/setup/characters  art upload and voice assignment (the character library)
/setup/obs         the browser source URLs, with a copy button and a live preview
/setup/done        smoke test checklist
```

Resumable — each step writes as it completes, so closing the browser doesn't lose progress. And
reachable afterwards, since "change my Azure key" and "set this up" are the same screens.

---

## The big change: credentials stop being environment variables

Environment variables are the worst part of the current install. They're invisible, they don't reach
open terminals, they have a User/Machine distinction nobody wants to learn, and setting one wrong
produces a failure that looks like something else entirely.

A wizard can't set them usefully either — it would have to spawn a shell and tell the user to restart
everything.

**Proposal:** the wizard writes a gitignored `config.json` next to the app. Environment variables are
still read and still win, so existing installs and anyone who prefers them are unaffected.

```
resolution order:  environment variable  →  config.json  →  built-in default
```

That keeps the current behaviour as a superset and makes the wizard possible. `config.json` holds the
Twitch token and channel, Azure key and region — so it's secret, gitignored, and worth saying so in
the file itself.

Open question worth deciding before building: whether to obfuscate the stored token at all. Plain
JSON is honest and debuggable; anything else is fake security on a file sitting in the user's own
directory. Leaning plain, with a comment saying what it contains.

---

## Validation is the whole point

A wizard that collects four values and says "done" is worth very little. The value is that each step
proves itself before you move on, so failures surface next to the thing that caused them.

| Step | Check | On failure |
|---|---|---|
| Python | version in range, wheels available | offer the 3.12 installer link |
| Dependencies | import each top-level package | show the pip error, not a traceback |
| Twitch | connect, report the bot username | distinguish bad token from expired token |
| Channel | channel exists | catch display-name-instead-of-login |
| Azure | synthesize "testing" and play it in the page | separate wrong-key from wrong-region |
| Voices | count fetched, how many have styles | fall back to `voices.default.json` |
| Art | both PNGs present, same dimensions | name the mismatch, since it causes a visible jump |
| OBS | live overlay preview in the page | can't verify OBS itself; ask the user to confirm |

The Azure step is the one to get right. Today a wrong key and a wrong region produce the same
message — "Azure failed, using gTTS instead" — and the real error is swallowed. The wizard should
report which of the two it was, which means fixing the error handling in
`azure_text_to_speech.py` regardless of whether the wizard ever ships.

---

## What we can't do for them

Honest list, because a wizard that pretends otherwise is worse than a runbook.

- **Creating the Azure account.** Card details, a Microsoft account, a portal we don't control. Best
  case is a walkthrough with screenshots and a paste box at the end. Deep-linking to the resource
  creation blade with the tier preselected is possible and worth investigating.
- **Generating the Twitch token.** Third-party site. We can link with the right scopes pre-filled and
  validate the paste.
- **Configuring OBS.** No API unless obs-websocket is enabled, which is exactly the setup we removed.
  Show the URLs, make them copyable, preview the overlay so they can compare.
- **Making the art.** Two same-size PNGs is a real ask. Shipping a placeholder set so the app works
  before the user has any art would help a lot.

---

## Packaging

Three options, roughly increasing in effort and in how much they help.

**Option 1 — zip + launcher script.** Ship the repo with a `.bat`. Needs Python, or the script installs it.
Cheapest, no signing, no antivirus problems. Still asks the user to trust a batch file.

**Option 2 — PyInstaller one-folder build.** No Python needed at all. Removes the single biggest blocker.
Costs: the build is fiddly with native dependencies — `azure-cognitiveservices-speech` ships binaries
and `pygame` has its own — and an unsigned executable trips SmartScreen, which for a streamer looks
exactly like malware. Code signing certificates are a real recurring cost.

**Option 3 — installer proper (MSI/Inno).** Start menu entry, uninstaller, upgrade path. Only worth it if option 2
already works.

**At N=1, do option 1 and stop.** You can install Python on her machine once, in person or over a screen
share. That's an hour that buys you everything option 2 would, without a build pipeline that breaks whenever
a dependency shifts, and without SmartScreen flagging an unsigned executable on a streamer's machine.

Option 2 becomes worth it the moment there's a third user, and not really before. Option 3 only if 2
already works.

The important thing is that **option 1 isn't wasted work if you later do option 2** — a launcher script
that finds Python, builds a venv and starts the app is the same logic a packaged build needs, just
with the Python bundled instead of located.

---

## Staging

Ordered for one non-technical user, with the split marked. Everything before the line is worth
building now; everything after waits for a reason to exist.

**A. `config.json` with env-var precedence.** No UI. Lets you hand over a pre-configured install and
removes environment variables from her life entirely. Foundation for everything else.

**B. Launcher script.** Finds Python, builds the venv, installs deps, starts the app, opens the
browser. No terminal, no activation policy, no wrong-venv confusion. Best return per hour of anything
here, and it's what she touches every single stream.

**C. Status panel.** The green/red block above, at the top of the control panel. Turns "it's not
working" into a line she can read out.

**D. Fix Azure error reporting.** Bad key, bad region and network failure are currently one message
with the real error swallowed. Needed by C, and useful in the runbook world regardless.

**E. Logging and a copy-diagnostics button.** Rolling log, one-click redacted summary to clipboard.
The remote-support workhorse.

— *below this line, only if you open it up* —

**F. Wizard pages.** Twitch, Azure, voices, OBS, each self-validating. Shares the character library's
setup screen rather than duplicating it.

**G. First-run detection.** No `config.json` redirects to `/setup/welcome`.

**H. Packaging.** PyInstaller, then possibly an installer. Redone on every dependency change, so
last.

A through E are roughly the work of the character library stages, and none of it is wasted if you
later open up — F and G build directly on A, and H wraps B.

---

## Open questions

- **Whose Azure subscription?** If she uses your key, you carry the cost and you share one F0 quota —
  500,000 characters a month across both of you, and a quota exhausted by your stream breaks hers.
  Separate resources are cleaner and free, but that's one more thing for her to create. Leaning
  separate, set up by you during install.
- **Where does user data live?** Config, art and voice list must survive you handing her a new
  version. Either keep them outside the app folder, or be strict about which files are hers.
- **Does Azure expose remaining quota?** Needed for the status panel's character count. If not,
  counting locally gets close enough to warn before the ceiling.
- **Ship placeholder art?** Would let her reach a working overlay before drawing anything, and makes
  the first run demonstrable. Needs art that's ours to distribute.
- **Windows only?** Everything here assumes it. Fine for one user; worth revisiting only if opening
  up.
- **Does the wizard replace the runbook?** If F ever happens, the runbook should become the
  "something went wrong" reference rather than the primary path, or the two will drift.
