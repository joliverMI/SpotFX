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
# Set only when THIS RUN added the user to 'video'. The membership is real
# from that moment but the running user manager does not have it, so the
# service is installed and deliberately NOT started — see section 4.
ADDED_GROUP=0
# How long to wait, after starting the service, for the client to actually
# appear on SPECTRA's own camera_host surface. Generous: a camera settles
# before it can honestly report anything (the client's own
# SETTLE_BEFORE_LOCK_S), and a slow answer is still an answer.
HELLO_WAIT_S="${SPECTRA_CAPTURE_HELLO_WAIT_S:-45}"

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
# THE PREDICATE IS "will a venv built by this python CONTAIN PIP", not "does
# `import venv` work". On Debian-family systems `venv` is in the standard
# library and imports fine while `ensurepip` — the part that seeds pip into a
# new environment — ships separately in python3-venv. Checking the wrong one
# passed here and then failed as a raw `No module named pip` traceback INSIDE
# the freshly built venv, which is precisely the shape this script exists to
# replace with a named refusal, before anything is written.
if ! "$PYTHON" -c 'import venv' >/dev/null 2>&1; then
    refuse "this python cannot make a virtualenv (no venv module)" \
           "sudo apt install -y python3-venv python3-pip"
elif ! "$PYTHON" -m ensurepip --version >/dev/null 2>&1; then
    refuse "this python can make a virtualenv but cannot put pip in it (no \
ensurepip), so the install would fail with 'No module named pip' inside the \
new venv" \
           "sudo apt install -y python3-venv python3-pip"
fi

# A HALF-MADE VENV FROM A FAILED RUN IS NOT A VENV TO REUSE. The run that
# died inside pip leaves $VENV/bin/python behind, and the reuse branch below
# would take it as finished and fail in exactly the same place again. This
# NAMES it and leaves it alone — removing somebody's directory uncommanded is
# not this script's to do.
if [ -x "$VENV/bin/python" ] && ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
    refuse "the virtualenv at $VENV has no pip in it — a previous run built \
it with a python that could not seed pip, and reusing it would fail the same \
way" \
           "sudo apt install -y python3-venv python3-pip, then remove the \
half-made environment: rm -rf $VENV"
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

# ── 4. the camera, and GROUP MEMBERSHIP (not readability) ──────────────────
# `|| true` because `pipefail` is on and grep exits 1 on no match — which
# is the ordinary case (no configuration yet), not a failure.
DEV_FROM_ENV="$( { grep -E '^SPECTRA_CAPTURE_DEVICE=' "$ENV_FILE" 2>/dev/null || true; } | tail -1 | cut -d= -f2- )"
DEV="${DEVICE:-$DEV_FROM_ENV}"
DEV="${DEV:-/dev/video0}"
#
# THE PREDICATE IS MEMBERSHIP, AND ASKING THE NEIGHBOURING QUESTION COST AN
# EVENING (2026-09-02). This used to test `[ -r $DEV ]` and call that the
# video-group check. On a desktop those are not the same question: logind
# grants the LOGGED-IN user read access to the seat's devices through an
# ACL, with no group anywhere in it, so `-r` said yes on a machine whose
# user was not in `video` — and then the unit, which declares
# `SupplementaryGroups=video`, could not start AT ALL: `status=216/GROUP`,
# "Changing group credentials failed". The install reported success while
# installing a service that could never run. This is the same shape as the
# `venv` vs `ensurepip` bug one section up: a check that passes on most
# machines and is not the thing that has to be true.
#
# AND MEMBERSHIP ALONE IS NOT ENOUGH EITHER, so the refusal says REBOOT
# rather than "log out and back in": `systemd --user` takes its
# supplementary groups once, when the manager starts, and being
# unprivileged it cannot gain one afterwards. With linger enabled the
# manager may not even stop at logout. `--doctor` reads the running
# manager's own groups out of /proc and says which of the two is missing.
VIDEO_FIX="sudo usermod -aG video $(id -un)  — then REBOOT (a logout does \
not reliably restart the user manager, and the unit fails 216/GROUP until \
it does)"
if id -nG | tr ' ' '\n' | grep -qx video; then
    ok "$(id -un) is in group 'video' (which is what the unit's \
SupplementaryGroups=video actually requires)"
elif [ "$ADD_GROUP" = "1" ]; then
    say "running: sudo usermod -aG video $(id -un)"
    if sudo usermod -aG video "$(id -un)"; then
        ADDED_GROUP=1
        note "added $(id -un) to group 'video'. NEITHER THIS SHELL NOR THE \
RUNNING USER MANAGER HAS IT YET. Everything below is installed, and the \
service is NOT started, because it would only fail 216/GROUP. REBOOT and it \
starts by itself."
    else
        refuse "could not add $(id -un) to group 'video'" \
               "run it as a user with sudo: $VIDEO_FIX"
    fi
else
    refuse "$(id -un) is NOT in group 'video'. The unit declares \
SupplementaryGroups=video, so systemd would refuse to start it at all \
(status=216/GROUP). Note this is NOT the same as whether the camera is \
readable: a desktop seat grants that through an ACL without any group, \
which is exactly why the old check here passed on a machine whose service \
could never start." \
           "$VIDEO_FIX — or re-run this script with --add-video-group"
fi
if [ -e "$DEV" ]; then
    ok "$DEV exists"
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

# ── 5b. AND WHETHER THAT ADDRESS ANSWERS FROM THIS MACHINE ─────────────────
# NEVER CHECKED UNTIL 2026-09-02, so the whole URL branch of an install was
# untested: a name that does not resolve here, a port nothing is listening
# on, and a server that answers but is not SPECTRA (usually the `/spectra`
# path prefix, which is easy to lose) all produced the same silent outcome —
# an installed service quietly failing to connect to nothing.
#
# THREE READINGS, and they have three different fixes, which is the whole
# reason not to collapse them into "cannot reach SPECTRA". The logic is the
# DOCTOR'S OWN (`spectra/capture_client/doctor.py --address-only`), run
# straight from the checkout with the system interpreter because there is no
# virtualenv yet — that file is stdlib-only precisely so this can happen
# before anything is built. There is no second copy of it here.
URL_TO_CHECK="$URL"
if [ -z "$URL_TO_CHECK" ] && [ -f "$ENV_FILE" ]; then
    URL_TO_CHECK="$( { grep -E '^SPECTRA_CAPTURE_URL=' "$ENV_FILE" 2>/dev/null || true; } | tail -1 | cut -d= -f2- )"
fi
DOCTOR="$SELF/spectra/capture_client/doctor.py"
if [ -z "$URL_TO_CHECK" ]; then
    :   # already refused above; no address to probe
elif [ ! -f "$DOCTOR" ]; then
    note "the doctor is missing from this checkout ($DOCTOR), so SPECTRA's \
address could not be probed from here"
elif ! command -v "$PYTHON" >/dev/null 2>&1; then
    :   # already refused above; nothing to run it with
else
    ADDR_OUT="$("$PYTHON" "$DOCTOR" --address-only --url "$URL_TO_CHECK" 2>&1)" \
        && ADDR_RC=0 || ADDR_RC=$?
    printf '%s\n' "$ADDR_OUT" | sed 's/^/  /'
    if [ "${ADDR_RC:-0}" != "0" ]; then
        refuse "SPECTRA does not answer at $URL_TO_CHECK from this machine \
(the three readings above say which of resolve / connect / answer failed)" \
               "fix the address or the server, then run this again. \
Everything else on this host is fine and nothing has been written."
    fi
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

cat <<INSTALLED_MSG

== installed ==
  configuration   $ENV_FILE
  launcher        $LAUNCHER
  unit            $UNIT_DST
  virtualenv      $VENV
INSTALLED_MSG

# ── THE PART THAT USED TO BE A CLAIM ───────────────────────────────────────
#
# This script used to end by announcing that "SPECTRA can now SEE this
# machine". It printed that sentence unconditionally — including, on
# 2026-09-02, while installing a service that could not start at all
# (216/GROUP). A closing message that asserts something nobody checked is
# worse than no closing message: it sends the reader to look somewhere else.
#
# So nothing is claimed now. The install STARTS the service and then WAITS,
# bounded, for the client to actually appear on SPECTRA's own camera_host
# surface, and prints what really happened — one of:
#
#   connected            with the machine SPECTRA named and its self-test
#                        verdict, because that is the thing being claimed
#   present but unable   the client is there and says why it cannot work
#   the unit's own words when the service failed or is crash-looping
#   never arrived        the service is up and SPECTRA never heard from it,
#                        which is the cannot-reach-the-server case and the
#                        one the address probe above and `--doctor` exist for
#
# `--doctor` is named in every outcome, because the next question after any
# of them is the same one.
if [ "$ADDED_GROUP" = "1" ]; then
    cat <<GROUP_MSG

== NOT STARTED, AND THAT IS THE HONEST ANSWER ==
  $(id -un) was added to group 'video' by this run. The membership is real,
  but the RUNNING user manager still has the groups it started with, so
  starting the service now would only fail 216/GROUP.

  REBOOT. The unit is enabled, so it starts by itself when the machine comes
  back, and it will have the group.

    sudo reboot
    # then, on that machine:
    $LAUNCHER --doctor
GROUP_MSG
    systemctl --user enable spectra-capture-client >/dev/null 2>&1 || true
    ok "unit enabled (it will start at boot)"
    exit 0
fi

if [ "$NO_START" = "1" ]; then
    cat <<NOSTART_MSG

  --no-start given: nothing was started and nothing is claimed about what
  SPECTRA can see. Start it, then check:

    systemctl --user enable --now spectra-capture-client
    $LAUNCHER --doctor
NOSTART_MSG
    exit 0
fi

systemctl --user enable --now spectra-capture-client
ok "spectra-capture-client is enabled and started"

echo
echo "== waiting up to ${HELLO_WAIT_S}s for SPECTRA to actually see this machine =="
VERIFY_HOST="${HOSTNAME_ARG:-$(uname -n)}"
if "$VENV/bin/python" "$DOCTOR" --await-hello "$HELLO_WAIT_S" \
        --url "$URL_TO_CHECK" --host "$VERIFY_HOST" \
        --device "$DEV" --venv "$VENV"; then
    echo
    echo "  Run this any time that changes: $LAUNCHER --doctor"
    exit 0
fi
echo
echo "  The install itself is complete — the configuration, launcher, unit"
echo "  and virtualenv above are all in place. What is NOT working is above,"
echo "  in its own words. Full detail, every branch at once:"
echo
echo "    $LAUNCHER --doctor"
exit 1
