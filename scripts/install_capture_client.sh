#!/usr/bin/env bash
#
# TAKE A FRESH LINUX HOST FROM NOTHING TO A RUNNING CAPTURE CLIENT.
#
#     scripts/install_capture_client.sh \
#         --url http://spectra:8000/spectra \
#         --pose-name "the north shelf"
#
#     scripts/install_capture_client.sh --check     # refuse-only, writes nothing
#
# WHAT THIS SCRIPT IS. `docs/UNATTENDED_CAPTURE.md`'s ledger section (b) —
# "needs a human ONCE, per machine" — used to be a list of things somebody
# had to remember: install ffmpeg, install v4l-utils, join the video group,
# check the camera locks, make it a unit. Every one of those is now a NAMED
# CHECK in one script. What it cannot do it REFUSES BY NAME, with the exact
# command that fixes it, and it changes nothing before the refusal.
#
# WHAT IT DELIBERATELY DOES NOT DO:
#
#   * It does not aim the camera. That is the pose, it is a physical act,
#     and nothing here estimates it.
#   * It does not install anything with sudo unless asked (--add-video-group
#     is the only one, and it names the command it will run first).
#   * It does not touch spotfx.service or spectra.service. This unit is a
#     camera process on (usually) a different machine entirely.
#   * It does not decide the camera is good enough. A camera that will not
#     lock its exposure is REPORTED here and refused by every run — that is
#     a camera to replace, not a check to loosen.
#
# RUNNABLE TWICE. Every write is create-or-replace except the configuration
# file, which is created once and thereafter only has the keys you actually
# named on the command line updated in place — so a second run never
# silently reverts a value somebody edited by hand.
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_SRC="$SELF/deploy/spectra-capture-client.service"
REQS="$SELF/requirements-capture-client.txt"

CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/spectra-capture"
ENV_FILE="$CONF_DIR/client.env"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_DST="$UNIT_DIR/spectra-capture-client.service"
LAUNCHER="$HOME/.local/bin/spectra-capture-client"
VENV="${SPECTRA_CAPTURE_VENV:-$HOME/.local/share/spectra-capture/venv}"

URL=""; POSE=""; DEVICE=""; HOSTNAME_ARG=""; SIZE=""; INPUT_FORMAT=""
CHECK_ONLY=0; ADD_GROUP=0; NO_START=0; PYTHON="${SPECTRA_CAPTURE_PYTHON:-python3}"

usage() {
    sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    cat <<'USAGE'

Options:
  --url URL              where SPECTRA is (required on a first install)
  --pose-name WORDS      this camera's placement, in his own words
  --device PATH          the camera (default /dev/video0)
  --host NAME            what to call this machine in refusals
  --capture-size WxH     what to ask the camera for (default 1920x1080)
  --input-format FMT     ffmpeg -input_format, e.g. mjpeg
  --python PATH          the interpreter to build the venv with
  --venv PATH            where to build it
  --add-video-group      run `sudo usermod -aG video $USER` (names it first)
  --no-start             install everything, start nothing
  --check                run every check, write nothing, refuse the same way
  -h, --help
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --url) URL="$2"; shift 2 ;;
        --pose-name) POSE="$2"; shift 2 ;;
        --device) DEVICE="$2"; shift 2 ;;
        --host) HOSTNAME_ARG="$2"; shift 2 ;;
        --capture-size) SIZE="$2"; shift 2 ;;
        --input-format) INPUT_FORMAT="$2"; shift 2 ;;
        --python) PYTHON="$2"; shift 2 ;;
        --venv) VENV="$2"; shift 2 ;;
        --add-video-group) ADD_GROUP=1; shift ;;
        --no-start) NO_START=1; shift ;;
        --check) CHECK_ONLY=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

REFUSALS=0
say()  { printf '  %s\n' "$*"; }
ok()   { printf '  ok   %s\n' "$*"; }
note() { printf '  note %s\n' "$*"; }
# A REFUSAL NAMES THE CONDITION AND THE COMMAND THAT FIXES IT, and every one
# of them is collected before anything is written — a script that installed
# half of itself and then refused would be worse than one that refused.
refuse() {
    REFUSALS=$((REFUSALS + 1))
    printf '  REFUSED  %s\n' "$1"
    [ $# -gt 1 ] && printf '           fix: %s\n' "$2"
    return 0
}

echo "== SPECTRA capture client: checking this host =="

# ── 1. the platform ────────────────────────────────────────────────────────
case "$(uname -s)" in
    Linux) ok "Linux $(uname -m)" ;;
    *) refuse "this is $(uname -s), and the capture client's camera backend \
is V4L2 (Linux only)" "run it on a Linux host with the camera attached" ;;
esac

if command -v systemctl >/dev/null 2>&1; then
    ok "systemd is present ($(systemctl --version | head -1))"
else
    refuse "systemd is not installed, so there is nothing to install a unit into" \
           "run the client by hand: $PYTHON -m spectra.capture_client --url ..."
fi

# ── 2. the interpreter ─────────────────────────────────────────────────────
if command -v "$PYTHON" >/dev/null 2>&1; then
    PYV="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "")"
    if [ -z "$PYV" ]; then
        refuse "$PYTHON is on PATH but will not report its version" \
               "check the interpreter, or pass --python /usr/bin/python3"
    elif "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
        ok "python $PYV at $(command -v "$PYTHON")"
    else
        refuse "python $PYV is too old; this client needs 3.9 or newer" \
               "apt install python3, or pass --python to a newer one"
    fi
else
    refuse "$PYTHON is not on PATH" "apt install python3 python3-venv"
fi
if ! "$PYTHON" -c 'import venv' >/dev/null 2>&1; then
    refuse "this python cannot make a virtualenv (no venv module)" \
           "apt install python3-venv"
fi

# ── 3. THE TWO EXTERNAL TOOLS, each by name ────────────────────────────────
# The client checks for both at run time too and refuses by name there; this
# is the same refusal moved to install time, where somebody is watching.
if command -v ffmpeg >/dev/null 2>&1; then
    ok "ffmpeg at $(command -v ffmpeg)"
else
    refuse "ffmpeg is not installed, and the client reads the camera through it" \
           "sudo apt install ffmpeg"
fi
if command -v v4l2-ctl >/dev/null 2>&1; then
    ok "v4l2-ctl at $(command -v v4l2-ctl)"
else
    refuse "v4l2-ctl is not installed, and it is the ONLY thing that can \
read this camera's exposure lock back out of the driver" \
           "sudo apt install v4l-utils"
fi

# ── 4. the camera, and the video group ─────────────────────────────────────
# `|| true` because `pipefail` is on and grep exits 1 on no match — which
# is the ordinary case (no configuration yet), not a failure.
DEV_FROM_ENV="$( { grep -E '^SPECTRA_CAPTURE_DEVICE=' "$ENV_FILE" 2>/dev/null || true; } | tail -1 | cut -d= -f2- )"
DEV="${DEVICE:-$DEV_FROM_ENV}"
DEV="${DEV:-/dev/video0}"
if [ -e "$DEV" ]; then
    ok "$DEV exists"
    if [ -r "$DEV" ]; then
        ok "$DEV is readable by $(id -un)"
    elif [ "$ADD_GROUP" = "1" ]; then
        say "running: sudo usermod -aG video $(id -un)"
        if sudo usermod -aG video "$(id -un)"; then
            note "added to group 'video' — THIS SHELL still is not in it. \
Log out and back in (or reboot) before the service can read the camera."
        else
            refuse "could not add $(id -un) to group 'video'" \
                   "run it as a user with sudo: sudo usermod -aG video $(id -un)"
        fi
    else
        refuse "$DEV is not readable by $(id -un) — the user must be in \
group 'video'" \
               "sudo usermod -aG video $(id -un) (then log out and back in), \
or re-run this script with --add-video-group"
    fi
else
    # NOT A REFUSAL. A camera host is often provisioned before the camera is
    # plugged in, and the client itself connects and REPORTS a missing camera
    # rather than dying — which is the behaviour that makes this safe to
    # install early.
    note "$DEV does not exist yet. Installing anyway: the client connects \
without a camera and reports the reason, so SPECTRA will say what is wrong \
instead of going quiet."
fi

# ── 5. the configuration ───────────────────────────────────────────────────
if [ -f "$ENV_FILE" ]; then
    ok "configuration exists at $ENV_FILE (it will be kept; only keys you \
named are updated)"
elif [ -n "$URL" ]; then
    ok "configuration will be created at $ENV_FILE"
else
    refuse "there is no configuration at $ENV_FILE and no --url was given, \
so this client would not know where SPECTRA is" \
           "re-run with --url http://spectra:8000/spectra"
fi

# ── 6. boot-start actually starting at boot ────────────────────────────────
# A user unit runs when that user has a session. LINGER is what makes it run
# from boot on a headless camera host — without it the whole point of the
# unit is lost on a machine nobody logs into.
if command -v loginctl >/dev/null 2>&1; then
    if [ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null || echo no)" = "yes" ]; then
        ok "linger is enabled, so this user unit starts at boot"
    else
        note "linger is NOT enabled for $(id -un): this unit will start when \
that user logs in, not at boot. On a headless camera host run: \
sudo loginctl enable-linger $(id -un)"
    fi
else
    note "loginctl is not available; check that a user unit starts at boot \
on this system before relying on it"
fi

# ── 7. the shipped unit, verified by systemd itself ────────────────────────
[ -f "$UNIT_SRC" ] || refuse "the unit is missing from this checkout ($UNIT_SRC)" \
                             "run this script from a complete SpotFX checkout"
[ -f "$REQS" ] || refuse "the client requirements are missing ($REQS)" \
                         "run this script from a complete SpotFX checkout"

echo
if [ "$REFUSALS" -gt 0 ]; then
    echo "== $REFUSALS refusal(s). NOTHING WAS INSTALLED. =="
    exit 1
fi
if [ "$CHECK_ONLY" = "1" ]; then
    echo "== every check passed. --check was given, so nothing was written. =="
    exit 0
fi

# ── installing ─────────────────────────────────────────────────────────────
echo "== installing =="
mkdir -p "$CONF_DIR" "$UNIT_DIR" "$(dirname "$LAUNCHER")" "$(dirname "$VENV")"

# The virtualenv: created once, dependencies re-checked every run (pip is
# idempotent and says "already satisfied").
if [ ! -x "$VENV/bin/python" ]; then
    say "creating the virtualenv at $VENV"
    "$PYTHON" -m venv "$VENV"
else
    ok "virtualenv already at $VENV"
fi
say "installing the client's two dependencies (NOT the server's — see $REQS)"
"$VENV/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
"$VENV/bin/python" -m pip install --quiet -r "$REQS"
ok "$("$VENV/bin/python" -c 'import httpx, websockets; print("httpx %s, websockets %s" % (httpx.__version__, websockets.__version__))')"

# THE LAUNCHER carries the one thing that differs between machines, so the
# unit can ship verbatim and be verified as the exact bytes installed.
cat > "$LAUNCHER" <<LAUNCH
#!/bin/sh
# Generated by scripts/install_capture_client.sh — regenerate rather than
# edit; the CONFIGURATION lives in $ENV_FILE.
cd "$SELF" || exit 2
exec "$VENV/bin/python" -m spectra.capture_client "\$@"
LAUNCH
chmod +x "$LAUNCHER"
ok "launcher at $LAUNCHER (checkout $SELF)"

# THE CONFIGURATION: created from the shipped example on a first install,
# and thereafter only the keys named on this command line are updated. A
# provisioning script that rewrote a config file every run would silently
# undo whatever somebody fixed by hand at 2am.
set_key() {
    key="$1"; value="$2"
    [ -n "$value" ] || return 0
    if grep -qE "^#?$key=" "$ENV_FILE"; then
        tmp="$ENV_FILE.tmp.$$"
        awk -v k="$key" -v v="$value" '
            $0 ~ "^#?" k "=" && !done { print k "=" v; done=1; next }
            { print }
        ' "$ENV_FILE" > "$tmp" && mv "$tmp" "$ENV_FILE"
    else
        printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
    fi
    ok "$key=$value"
}
if [ ! -f "$ENV_FILE" ]; then
    cp "$SELF/deploy/spectra-capture-client.env.example" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    ok "configuration created at $ENV_FILE from the shipped example"
fi
set_key SPECTRA_CAPTURE_URL "$URL"
set_key SPECTRA_CAPTURE_POSE "$POSE"
set_key SPECTRA_CAPTURE_DEVICE "$DEVICE"
set_key SPECTRA_CAPTURE_HOST "$HOSTNAME_ARG"
set_key SPECTRA_CAPTURE_SIZE "$SIZE"
set_key SPECTRA_CAPTURE_INPUT_FORMAT "$INPUT_FORMAT"

# THE UNIT, verbatim, then VERIFIED BY SYSTEMD'S OWN PARSER. A unit that
# does not verify is not installed: an unattended camera host whose service
# file has a typo is a machine that looks provisioned and is not.
cp "$UNIT_SRC" "$UNIT_DST"
ok "unit at $UNIT_DST"
if command -v systemd-analyze >/dev/null 2>&1; then
    if systemd-analyze verify "$UNIT_DST"; then
        ok "systemd-analyze verify: the installed unit is valid"
    else
        echo "  REFUSED  systemd will not accept the installed unit (above)." >&2
        exit 1
    fi
else
    note "systemd-analyze is not installed, so the unit could not be verified here"
fi

systemctl --user daemon-reload
if [ "$NO_START" = "1" ]; then
    note "--no-start given: enabled nothing. Start it with: \
systemctl --user enable --now spectra-capture-client"
else
    systemctl --user enable --now spectra-capture-client
    ok "spectra-capture-client is enabled and started"
fi

cat <<DONE_MSG

== installed ==
  configuration   $ENV_FILE
  launcher        $LAUNCHER
  unit            $UNIT_DST
  virtualenv      $VENV

  systemctl --user status spectra-capture-client
  journalctl --user -u spectra-capture-client -f

SPECTRA can now SEE this machine: GET /spectra/api/rooms/map/status carries
'camera_host', which names this host, its build, its declared placement and
its camera's self-test verdict — and, when this client is not connected,
says so with the machine named rather than a bare "no session".
DONE_MSG
