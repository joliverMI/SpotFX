"""THE DOCTOR — one command, every branch, so a broken camera host can say
what is wrong with it WITHOUT a person being the messenger.

THE EVENING THIS EXISTS FOR (2026-09-02). Eight successive failures on one
laptop, in one evening, every one of them ours and every one INVISIBLE from
here until he pasted something into a chat window: a cached browser tab
running old capture code; a `python3 -m venv` with no ensurepip; the pipless
venv that failed run left behind; a browser tab holding the lens the client
needed; an install line not re-run after the unblock; a unit that could not
start at all (`216/GROUP`); user services that were login-gated; and then,
after a reboot, a service that still never said hello — cause unknown,
BECAUSE NOTHING REPORTED.

**The defect was never any one of the eight. It was that we had no way to
know.** So this module is not a troubleshooting guide; it is an instrument.
It answers every branch of that evening in one run, in his own terms, and it
is meant to be run and pasted whole.

    spectra-capture-client --doctor

WHAT IT MAY NOT DO, and these are the same boundaries the rest of this
package lives inside:

  * **It fixes nothing.** Every failure names the command that fixes it and
    stops there. A doctor that repaired things would be a second, unwatched
    installer, and the one thing this evening proved is that unwatched
    machinery is how you get a confident wrong answer.
  * **It gates nothing.** A run's refusals are `mapping_session`'s and the
    server's, unchanged. Nothing here is consulted before a light is driven.
  * **It takes no room, opens no camera stream and drives no light.** It
    reads: files, `id`, `/proc`, DNS, one HTTP GET, and `systemctl --user`.
    The one thing it starts is nothing.

THREE VERDICTS, AND THE THIRD IS THE POINT. `ok`, `failed` and `unknown` —
"we could not check" is never reported as "we checked and it is broken",
which is the standing standard `night_exit` (DARK vs UNKNOWN), `witness`
(contaminated vs witness_unavailable) and `lever_selftest` (unprovable vs
no_response) each already hold. An UNKNOWN never counts toward the exit
status: inventing a fault is worse than admitting a blind spot. `warn` is
the fourth word and it means "this works now and will bite later" (no
linger, most of all) — it does not fail the run either.

THE TWO PREDICATES THIS EVENING TAUGHT US TO CHECK, both of which the
INSTALLER was getting wrong by asking a neighbouring question instead:

  * **GROUP MEMBERSHIP, not readability.** `[ -r /dev/video0 ]` passes on a
    desktop through the seat's ACL — `logind` grants the *logged-in* user
    read access to the seat's devices with no group anywhere in it — so the
    old check said yes on a machine whose user was not in `video`, and the
    service could not open the camera. Two different questions that agree on
    most machines and disagree on his. Exactly the shape of the
    `venv`/`ensurepip` bug fixed in PR #241, one subsystem over.
  * **AND WHETHER THE USER MANAGER HAS IT YET.** `usermod -aG video` changes
    the group DATABASE. It does not change the supplementary groups of any
    process already running — including `systemd --user`, which inherits
    them once, at manager start, and cannot gain a group afterwards because
    it is unprivileged. A user service INHERITS the manager's groups, so
    `id -nG` in a fresh terminal can say `video` while the service that
    actually holds the camera has none. That is the "reboot, not a logout"
    requirement, and this reads it as a FACT out of `/proc/<manager>/status`
    rather than telling him to reboot on principle.

THE THIRD PREDICATE, AND IT COST A SECOND REBOOT (2026-09-03). `216/GROUP`
HAS TWO CAUSES AND THE STATUS CODE CANNOT TELL THEM APART — only the
journal's own reason line can:

  * `Changing group credentials failed: **Operation not permitted**` — the
    unit is carrying a `SupplementaryGroups=` line and an UNPRIVILEGED
    manager cannot apply one AT ALL. `setgroups(2)` is refused outright, so
    MEMBERSHIP IS IRRELEVANT: a user who IS in the group fails identically.
    The fix is to remove the directive, `daemon-reload`, restart — no
    reboot, no `usermod`.
  * anything else — the membership-shaped failure, which is the reading this
    module always gave.

Until this was written the doctor collapsed both into the second, which is
how the owner was sent to `usermod` and a REBOOT for a fault neither could
touch: he was already a member, he had already rebooted, and the shipped
USER unit was carrying `SupplementaryGroups=video`. `read_216_cause()` now
reads the journal and names which one it is. The shipped user unit no longer
carries the directive at all — see `deploy/spectra-capture-client.service`'s
own header for the boundary, and note the SYSTEM unit (the installer's
`--system` mode, for a root-manager host) legitimately does.

WHY /proc AND NOT A TEST UNIT. Asking systemd to actually try
(`systemd-run --user --property=SupplementaryGroups=video`) is the most
direct possible answer — but it is a WRITE: a transient unit in his live
user manager, every time he runs the doctor. The manager's own supplementary
group set is the same predicate as a pure read, because a user service
inherits exactly the groups its manager holds and can never ask for more.
(That transient-unit probe is still how the CLAIM is proven, once, offline:
`scripts/check_capture_client_fresh_host.py` rig A drives real systemd to
both shapes of `216/GROUP` and cross-checks this module's translation
against each real journal line.)

THE SEVENTH CHECK IS THE ONE THAT CLOSES THE LOOP. When everything local
passes, it asks THE SERVER whether it can see this machine — the same
`camera_host` surface `spectra/services/capture_health.py` publishes. That
is the difference between "my service is running" and "SPECTRA has my
camera", which are not the same sentence and were not the same sentence on
the evening this was written.

STDLIB ONLY, AND THAT IS A REQUIREMENT RATHER THAN A PREFERENCE. Every
other file in this package may import `httpx` and `websockets`, because a
running client has a virtualenv that contains them. THIS one is the file
you reach for when the virtualenv is the broken thing — a venv with no pip
in it was two of the eight failures — so it must run under a bare system
`python3` with nothing installed, and it must run WITHOUT importing the
rest of the package (`__init__` pulls in `websockets`). Hence `urllib`
rather than `httpx`, and hence it works three ways:

    spectra-capture-client --doctor              # the installed launcher
    python3 -m spectra.capture_client --doctor   # a checkout with a venv
    python3 spectra/capture_client/doctor.py     # NOTHING installed at all

The installer runs the third form BEFORE it writes anything, which is how
"does this address even answer from this machine" became a pre-install
check instead of a thing nobody had ever tested.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlsplit

#: The verdicts. `UNKNOWN` never counts as a failure and never as a pass —
#: see the module docstring for why that third word is load-bearing.
OK = "ok"
FAILED = "failed"
WARN = "warn"
UNKNOWN = "unknown"

#: The group the shipped unit demands (`SupplementaryGroups=video`). Named
#: once, here, so the check and the fix line cannot drift apart.
VIDEO_GROUP = "video"

#: The unit the installer writes. Same reason.
UNIT_NAME = "spectra-capture-client"

#: WHICH SERVICE MANAGER OWNS THE UNIT — and this is not cosmetic. The two
#: scopes have DIFFERENT correct answers to the same questions:
#:
#:   USER   an unprivileged `systemd --user`. It cannot change group
#:          credentials at all, so a `SupplementaryGroups=` line can never
#:          work there; group access is INHERITED from the login session,
#:          which is why the running manager's own `/proc` group set is the
#:          predicate and why applying a new membership needs a REBOOT.
#:          Boot-start needs LINGER.
#:   SYSTEM a root manager that drops privileges into `User=`. There
#:          `SupplementaryGroups=` is legitimate and is the mechanism, the
#:          group DATABASE is the predicate (root applies it at each start,
#:          so a plain restart is enough), and boot-start needs no login and
#:          no linger.
#:
#: Getting this wrong is how a correct machine gets diagnosed as broken.
SCOPE_USER = "user"
SCOPE_SYSTEM = "system"


def _scope_args(scope: str) -> list:
    """The one place `--user` is decided, so no call site can quietly ask
    the wrong manager and report on a unit that is not the one running."""
    return ["--user"] if scope == SCOPE_USER else []


def detect_scope(unit: str = UNIT_NAME) -> str:
    """WHICH MANAGER ACTUALLY HAS THIS UNIT, read rather than assumed.

    A SYSTEM unit file present on disk wins, because the installer's
    `--system` mode is a deliberate choice for a host with no login session
    (the kiosk Pi), and on such a host the user manager may not exist at
    all. Otherwise the user scope, which is the default install."""
    for path in (f"/etc/systemd/system/{unit}.service",
                 f"/usr/lib/systemd/system/{unit}.service",
                 f"/lib/systemd/system/{unit}.service"):
        if os.path.exists(path):
            return SCOPE_SYSTEM
    return SCOPE_USER

#: How long any single external probe may take. A doctor that hangs is a
#: doctor nobody runs twice.
PROBE_TIMEOUT_S = 6.0

#: How long to wait for the SERVER's answer specifically. Longer, because it
#: may be across a house network and a slow answer is still an answer.
SERVER_TIMEOUT_S = 10.0

#: The one read this doctor makes of SPECTRA — `mapping_session.status()`,
#: which carries `camera_host`. Named once so the address check and the
#: does-it-see-us check cannot end up probing two different things.
STATUS_PATH = "/api/rooms/map/status"


@dataclass
class Finding:
    """One branch, its verdict, and — when it failed — the command that
    fixes it. `fix` is never prose: it is a line he can paste."""
    check: str
    verdict: str
    detail: str
    fix: str = ""

    @property
    def failed(self) -> bool:
        return self.verdict == FAILED

    def as_dict(self) -> dict:
        row = {"check": self.check, "verdict": self.verdict,
               "detail": self.detail}
        if self.fix:
            row["fix"] = self.fix
        return row


@dataclass
class Report:
    host: str = ""
    findings: list = field(default_factory=list)

    def add(self, check: str, verdict: str, detail: str,
            fix: str = "") -> Finding:
        f = Finding(check, verdict, detail, fix)
        self.findings.append(f)
        return f

    @property
    def failures(self) -> list:
        return [f for f in self.findings if f.failed]

    @property
    def unknowns(self) -> list:
        return [f for f in self.findings if f.verdict == UNKNOWN]

    def as_dict(self) -> dict:
        return {"host": self.host,
                "findings": [f.as_dict() for f in self.findings],
                "failures": len(self.failures),
                "unknowns": len(self.unknowns)}


# ── small helpers ──────────────────────────────────────────────────────────

def _run(args: list[str], timeout: float = PROBE_TIMEOUT_S,
         env: Optional[dict] = None) -> tuple[int, str]:
    """Exit code and combined output, and never an exception: every caller
    here treats "the tool would not run" as an answer, not a crash."""
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout, env=env)
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)


def _user_bus_env() -> dict:
    """The environment `systemctl --user` needs, filled in when the caller's
    shell did not have it.

    A non-login shell (a cron line, an ssh command, a terminal opened by
    something odd) often has no `XDG_RUNTIME_DIR` and no
    `DBUS_SESSION_BUS_ADDRESS`, and `systemctl --user` then fails with
    "Failed to connect to bus", which reads exactly like "there is no such
    service". Those are different facts and this doctor must never confuse
    them, so the standard paths are filled in when they are absent and the
    socket is actually there — and when it is not, the finding says the bus
    is missing rather than blaming the unit."""
    env = dict(os.environ)
    uid = os.getuid()
    runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    env.setdefault("XDG_RUNTIME_DIR", runtime)
    if not env.get("DBUS_SESSION_BUS_ADDRESS"):
        bus = os.path.join(runtime, "bus")
        if os.path.exists(bus):
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"
    return env


def _get_json(url: str, timeout: float = SERVER_TIMEOUT_S
              ) -> tuple[int, Optional[dict], str]:
    """(http status, decoded body or None, error words).

    `urllib` rather than `httpx` — see the module docstring: this file has
    to work on a machine whose virtualenv is the broken thing, and a
    dependency here would make the doctor unavailable in exactly the case it
    was written for. An HTTP error status is an ANSWER (status returned,
    empty error), not an exception: "something is listening and it said 404"
    is a completely different finding from "nothing answered"."""
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            raw = r.read()
            status = int(getattr(r, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        return int(exc.code), None, ""
    except Exception as exc:                           # noqa: BLE001
        return 0, None, f"{type(exc).__name__}: {exc}"
    try:
        return status, json.loads(raw.decode("utf-8", "replace")), ""
    except ValueError:
        return status, None, ""


def _group_gid(name: str) -> Optional[int]:
    try:
        import grp
        return int(grp.getgrnam(name).gr_gid)
    except Exception:                                  # noqa: BLE001
        return None


def _user_manager_pid() -> Optional[int]:
    """The PID of THIS user's `systemd --user`, or None.

    Matched on the executable being systemd AND `--user` being one of its
    arguments — never a substring search over the whole command line, which
    matches any shell that happens to be talking about it (it matched this
    doctor's own scouting script, which is how the rule got written down)."""
    try:
        uid = os.getuid()
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                if os.stat(f"/proc/{entry}").st_uid != uid:
                    continue
                with open(f"/proc/{entry}/cmdline", "rb") as fh:
                    argv = fh.read().split(b"\0")
            except OSError:
                continue
            if not argv or not argv[0]:
                continue
            exe = os.path.basename(argv[0].decode("utf-8", "replace"))
            if exe != "systemd":
                continue
            if any(a == b"--user" for a in argv[1:]):
                return int(entry)
    except OSError:
        return None
    return None


def _process_groups(pid: int) -> Optional[list]:
    """The supplementary groups a running process actually holds, read out
    of `/proc/<pid>/status`. None means we could not read it — which is an
    UNKNOWN, never a failure."""
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("Groups:"):
                    return [int(x) for x in line.split()[1:] if x.isdigit()]
    except (OSError, ValueError):
        return None
    return None


# ── 1. python, venv, pip ───────────────────────────────────────────────────

def check_python(report: Report, venv: str = "") -> None:
    """THE INTERPRETER, AND THE TWO THINGS THAT ARE NOT THE SAME QUESTION.

    `import venv` working does not mean a venv built by it will contain pip:
    on Debian-family systems `venv` is in the standard library and
    `ensurepip` — the part that seeds pip — ships separately in
    python3-venv. Asking the first and reporting on the second is PR #241's
    bug, and it is checked here as two findings so a paste says which."""
    report.add("python", OK,
               f"python {platform.python_version()} at {sys.executable}")

    have_venv = _run([sys.executable, "-c", "import venv"])[0] == 0
    have_ensurepip = _run([sys.executable, "-m", "ensurepip",
                           "--version"])[0] == 0
    if not have_venv:
        report.add("venv", FAILED,
                   "this python cannot build a virtualenv at all (no venv "
                   "module)",
                   "sudo apt install -y python3-venv python3-pip")
    elif not have_ensurepip:
        report.add("venv", FAILED,
                   "this python can build a virtualenv but cannot put pip "
                   "in it (no ensurepip), so an install fails with "
                   "'No module named pip' INSIDE the new environment",
                   "sudo apt install -y python3-venv python3-pip")
    else:
        report.add("venv", OK,
                   "this python can build a virtualenv WITH pip in it "
                   "(venv and ensurepip are both present)")

    if not venv:
        report.add("virtualenv", UNKNOWN,
                   "no virtualenv path was given, so the installed "
                   "environment was not inspected")
        return
    python = os.path.join(venv, "bin", "python")
    if not os.path.exists(python):
        report.add("virtualenv", FAILED,
                   f"there is no virtualenv at {venv}",
                   "scripts/install_capture_client.sh --url <SPECTRA's address>")
        return
    if _run([python, "-m", "pip", "--version"])[0] != 0:
        # THE HALF-MADE VENV. A run that died inside pip leaves bin/python
        # behind, and every later run reuses it and fails in the same place.
        report.add("virtualenv", FAILED,
                   f"the virtualenv at {venv} has NO PIP in it — a previous "
                   f"install built it with a python that could not seed pip, "
                   f"and reusing it fails the same way every time",
                   f"sudo apt install -y python3-venv python3-pip && "
                   f"rm -rf {venv}, then run the installer again")
        return
    code, out = _run([python, "-c",
                      "import httpx, websockets; "
                      "print(httpx.__version__, websockets.__version__)"])
    if code != 0:
        report.add("virtualenv", FAILED,
                   f"the virtualenv at {venv} is missing the client's "
                   f"dependencies ({out.splitlines()[-1] if out else 'import failed'})",
                   "scripts/install_capture_client.sh --url <SPECTRA's address>")
        return
    report.add("virtualenv", OK,
               f"{venv} has pip and both dependencies (httpx "
               f"{out.split()[0]}, websockets {out.split()[-1]})")


# ── 2. the two external tools ──────────────────────────────────────────────

def check_tools(report: Report) -> None:
    for tool, package, why in (
            ("ffmpeg", "ffmpeg",
             "the client reads the camera through it"),
            ("v4l2-ctl", "v4l-utils",
             "it is the ONLY thing that can read this camera's exposure "
             "lock back out of the driver")):
        found = shutil.which(tool)
        if found:
            report.add(tool, OK, f"{tool} at {found}")
        else:
            report.add(tool, FAILED,
                       f"{tool} is not installed, and {why}",
                       f"sudo apt install {package}")


# ── 3. the camera device ───────────────────────────────────────────────────

def check_device(report: Report, device: str) -> None:
    """WHETHER THE DEVICE IS THERE. Deliberately NOT whether it is readable
    — that question is the next check's, and asking it here is exactly the
    conflation that cost the evening."""
    if os.path.exists(device):
        report.add("camera device", OK, f"{device} exists")
        return
    others = sorted(p for p in ("/dev/video0", "/dev/video1", "/dev/video2",
                                "/dev/video3") if os.path.exists(p))
    hint = (f" (this machine does have {', '.join(others)} — pass "
            f"--device, or set SPECTRA_CAPTURE_DEVICE)" if others else "")
    report.add("camera device", FAILED,
               f"{device} does not exist{hint}",
               "plug the camera in, then: v4l2-ctl --list-devices")


# ── 4. THE GROUP, AND THE MANAGER THAT HAS TO HAVE IT ──────────────────────

def check_video_group(report: Report, *, user: Optional[str] = None,
                      scope: str = SCOPE_USER) -> None:
    """MEMBERSHIP, then WHETHER THE THING THAT LAUNCHES THE UNIT HAS IT —
    two findings, because they fail separately and the fix is different for
    each, and different again per scope.

    Membership is read from `id -nG`, which is the real predicate. Device
    READABILITY is NOT asked anywhere here: a desktop seat's ACL grants it
    without membership, so a check that passed on a machine whose service
    cannot open the camera is worse than no check at all.

    WHAT MEMBERSHIP BUYS, and it is scope-dependent:

      USER scope — the service INHERITS the supplementary groups of
      `systemd --user`, which takes them once, at manager start, and (being
      unprivileged) cannot acquire one afterwards. So a fresh shell saying
      `video` proves nothing about the manager that has to launch the unit,
      and applying a new membership takes a REBOOT. That second finding is
      what makes "reboot, not logout" a MEASURED fact rather than advice.

      SYSTEM scope — the root manager reads the group DATABASE at each
      start and applies `SupplementaryGroups=` itself before dropping to
      `User=`. Membership is enough, a restart is enough, and the running
      user manager is not part of the mechanism at all.

    NOTE WHAT THIS NO LONGER CLAIMS. Until 2026-09-03 both findings said a
    missing group meant the unit would die `216/GROUP`. That was true of a
    USER unit carrying `SupplementaryGroups=` — and that unit could never
    have started anyway, member or not. The honest consequence in user
    scope is a service that starts fine and cannot open the camera."""
    user = user or _current_user()
    code, out = _run(["id", "-nG"] + ([user] if user else []))
    if code != 0:
        report.add("video group", UNKNOWN,
                   f"could not read this user's groups ({out.strip()[:120]})")
        return
    groups = out.split()
    member = VIDEO_GROUP in groups
    if scope == SCOPE_SYSTEM:
        fix = (f"sudo usermod -aG {VIDEO_GROUP} {user}, then: sudo "
               f"systemctl restart {UNIT_NAME}. (No reboot: a system unit's "
               f"groups are applied by root at every start.)")
        consequence = (f"The system unit declares "
                       f"SupplementaryGroups={VIDEO_GROUP} — which is "
                       f"legitimate there, root applies it before dropping "
                       f"to User= — so systemd refuses to start it at all "
                       f"until the group resolves for that user.")
    else:
        fix = (f"sudo usermod -aG {VIDEO_GROUP} {user} — then REBOOT. A "
               f"logout is not enough: the user manager keeps the groups it "
               f"started with, and the service inherits ITS groups, not "
               f"this shell's.")
        consequence = (f"A user service inherits its groups from "
                       f"`systemd --user`; it cannot ask for them (a "
                       f"`SupplementaryGroups=` line in a user unit is "
                       f"refused outright — see the unit's own header). So "
                       f"without membership the service STARTS NORMALLY and "
                       f"then cannot open the camera, and SPECTRA sees a "
                       f"host that is present and impaired.")
    if not member:
        report.add("video group", FAILED,
                   f"{user} is NOT in group '{VIDEO_GROUP}'. {consequence} "
                   f"Note the camera can still be READABLE without this — a "
                   f"desktop seat grants that through an ACL — so a "
                   f"readable /dev/video0 is not evidence this is fine.",
                   fix)
        return
    report.add("video group", OK,
               f"{user} is in group '{VIDEO_GROUP}'")

    if scope == SCOPE_SYSTEM:
        # THE RUNNING USER MANAGER IS NOT THE MECHANISM HERE, and saying so
        # is better than silently skipping a check somebody expects to see.
        report.add("group applied", OK,
                   f"and this is a SYSTEM unit, so the root manager applies "
                   f"SupplementaryGroups={VIDEO_GROUP} from the group "
                   f"database at every start — the login session's own "
                   f"groups are not involved and no reboot is needed")
        return

    gid = _group_gid(VIDEO_GROUP)
    pid = _user_manager_pid()
    if gid is None:
        report.add("group applied", UNKNOWN,
                   f"group '{VIDEO_GROUP}' is not in this machine's group "
                   f"database, so whether the user manager holds it could "
                   f"not be checked")
        return
    if pid is None:
        report.add("group applied", UNKNOWN,
                   "no 'systemd --user' manager was found for this user, so "
                   "whether it holds the group could not be checked — the "
                   "service check below says whether a manager is reachable "
                   "at all")
        return
    held = _process_groups(pid)
    if held is None:
        report.add("group applied", UNKNOWN,
                   f"could not read /proc/{pid}/status, so whether the user "
                   f"manager holds group '{VIDEO_GROUP}' is not known")
        return
    if gid in held:
        report.add("group applied", OK,
                   f"and the running user manager (pid {pid}) holds it too, "
                   f"so a service it starts inherits the camera")
        return
    report.add("group applied", FAILED,
               f"but the RUNNING user manager (pid {pid}) does not hold "
               f"group '{VIDEO_GROUP}' yet — it keeps the groups it started "
               f"with. The membership is real and this shell can see it; the "
               f"manager that has to launch the unit cannot, so the service "
               f"it starts inherits no camera access and the client will "
               f"report a device it cannot open until this machine is "
               f"REBOOTED.",
               "sudo reboot   (a logout does not reliably restart the user "
               "manager, especially with linger enabled)")


def _current_user() -> str:
    for var in ("LOGNAME", "USER"):
        if os.environ.get(var):
            return os.environ[var]
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_name
    except Exception:                                  # noqa: BLE001
        return str(os.getuid())


# ── 5. THE URL: resolves, connects, answers ────────────────────────────────

def check_url(report: Report, url: str) -> None:
    """THREE READINGS OF ONE ADDRESS, because they have three different
    fixes and a single "cannot reach SPECTRA" hides which one it is.

    RESOLVE — the name does not turn into an address on THIS machine
    (a Tailscale name on a laptop that is not on the tailnet).
    CONNECT — it resolves and nothing accepts a TCP connection there
    (the server is down, or a firewall, or the wrong port).
    ANSWER  — something is listening and it is not SPECTRA, or SPECTRA is
    there but the path is wrong (the `/spectra` prefix is easy to lose).

    This was never checked at install time before, and the evening's URL
    branch was therefore never tested at all."""
    if not url:
        report.add("SPECTRA's address", FAILED,
                   "no address is configured, so this client does not know "
                   "where SPECTRA is",
                   "set SPECTRA_CAPTURE_URL in the client's env file, or "
                   "re-run the installer with --url")
        return
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if not host:
        report.add("SPECTRA's address", FAILED,
                   f"{url!r} is not an address this client can use",
                   "it should look like http://spectra:8000/spectra")
        return

    # RESOLVE
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        addrs = sorted({i[4][0] for i in infos})
    except socket.gaierror as exc:
        report.add("address resolves", FAILED,
                   f"this machine cannot resolve {host!r} ({exc.strerror or exc})",
                   f"check the name, or use the server's IP address in "
                   f"SPECTRA_CAPTURE_URL; if it is a Tailscale name, check "
                   f"this machine is on the tailnet")
        return
    report.add("address resolves", OK,
               f"{host} resolves to {', '.join(addrs)}")

    # CONNECT
    try:
        with socket.create_connection((host, port), timeout=PROBE_TIMEOUT_S):
            pass
    except OSError as exc:
        report.add("address connects", FAILED,
                   f"{host}:{port} resolves but will not accept a "
                   f"connection ({exc})",
                   f"check SPECTRA is running on that machine and that "
                   f"nothing is blocking port {port}")
        return
    report.add("address connects", OK, f"{host}:{port} accepts a connection")

    # ANSWER
    probe = url.rstrip("/") + STATUS_PATH
    status, body, err = _get_json(probe)
    if err:
        report.add("SPECTRA answers", FAILED,
                   f"{host}:{port} accepted a connection but the request to "
                   f"{probe} failed ({err})",
                   "check the address includes SPECTRA's path prefix, e.g. "
                   "http://spectra:8000/spectra")
        return
    if status >= 400:
        report.add("SPECTRA answers", FAILED,
                   f"something is listening at {host}:{port} but "
                   f"{probe} answered HTTP {status} — this address is "
                   f"probably missing SPECTRA's path prefix, or it is a "
                   f"different server",
                   "the address usually looks like "
                   "http://<host>:8000/spectra (note the /spectra)")
        return
    if body is None:
        report.add("SPECTRA answers", FAILED,
                   f"{probe} answered HTTP {status} but not JSON, so "
                   f"whatever is at this address is not SPECTRA",
                   "check SPECTRA's address and its /spectra path prefix")
        return
    if "camera_host" not in body:
        report.add("SPECTRA answers", FAILED,
                   f"{probe} answered JSON without a 'camera_host' key, so "
                   f"this is not the SPECTRA capture surface (or it is much "
                   f"older than this client)",
                   "check the address, and that SPECTRA is up to date")
        return
    report.add("SPECTRA answers", OK,
               f"SPECTRA answered at {probe}")


# ── 6. the unit ────────────────────────────────────────────────────────────

def check_service(report: Report, unit: str = UNIT_NAME,
                  scope: str = SCOPE_USER) -> None:
    """THE UNIT AND ITS LAST REAL ERROR LINE. Every state it can be in gets
    its own sentence, because "not running" covers a unit that was never
    installed, one that is disabled, one that is crash-looping five times a
    minute, and one that is up — and those have four different fixes.

    A UNIT MANAGER THAT CANNOT BE REACHED IS AN UNKNOWN, not a missing unit.
    `systemctl --user` in a shell with no session bus fails with "Failed to
    connect to bus", which reads exactly like "no such service"; saying so
    plainly is the difference between looking at the right machine and the
    wrong one.

    `scope` says WHICH manager to ask (see SCOPE_USER/SCOPE_SYSTEM). Asking
    the user manager about a unit the system manager owns reports "there is
    no unit installed for this user" about a service that is running fine,
    which is the same class of confident wrong answer as everything else
    this module exists to end."""
    if not shutil.which("systemctl"):
        report.add("service", UNKNOWN,
                   "systemctl is not installed, so there is no unit to ask "
                   "about (the client can still be run by hand)")
        return
    env = _user_bus_env() if scope == SCOPE_USER else None
    sc = _scope_args(scope)
    code, out = _run(["systemctl"] + sc + ["is-system-running"], env=env)
    if "Failed to connect to bus" in out or "No medium found" in out:
        report.add("service", UNKNOWN,
                   f"this shell cannot reach the user service manager "
                   f"({out.splitlines()[0][:100] if out else 'no bus'}), so "
                   f"the unit's state is not known from here. That is a "
                   f"property of THIS SHELL, not of the service.",
                   "run this from a normal login session on that machine, "
                   "or: export XDG_RUNTIME_DIR=/run/user/$(id -u) "
                   "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus")
        return

    load = _run(["systemctl"] + sc + ["show", unit, "-p", "LoadState",
                 "--value"], env=env)[1].strip()
    if load in ("not-found", ""):
        where = ("for this user" if scope == SCOPE_USER
                 else "on this machine (system scope)")
        report.add("service", FAILED,
                   f"there is no {unit} unit installed {where}",
                   "scripts/install_capture_client.sh --url <SPECTRA's address>"
                   + ("" if scope == SCOPE_USER else " --system"))
        return
    props = {}
    for name in ("ActiveState", "SubState", "UnitFileState", "Result",
                 "ExecMainStatus", "NRestarts",
                 # WHEN THE SERVICE LAST CAME UP. Without this the journal's
                 # oldest failure and its newest success are the same to a
                 # reader, which is how a FIXED machine kept being told it
                 # was broken — see `_add_last_error`.
                 "ActiveEnterTimestamp", "ActiveEnterTimestampMonotonic"):
        props[name] = _run(["systemctl"] + sc + ["show", unit, "-p", name,
                            "--value"], env=env)[1].strip()

    if props["UnitFileState"] not in ("enabled", "enabled-runtime",
                                      "linked", "static"):
        report.add("service enabled", FAILED,
                   f"{unit} is installed but {props['UnitFileState'] or 'not enabled'}, "
                   f"so it will not start on its own",
                   _systemctl_hint(scope, "enable", "--now", unit))
    else:
        report.add("service enabled", OK,
                   f"{unit} is {props['UnitFileState']}")

    active, sub = props["ActiveState"], props["SubState"]
    restarts = props["NRestarts"] or "0"
    if active == "active" and sub == "running":
        detail = f"{unit} is running"
        if restarts not in ("0", ""):
            # A RUNNING SERVICE THAT KEEPS COMING BACK IS NOT A HEALTHY ONE.
            # `Restart=always` means a crash loop looks exactly like uptime
            # if only the current state is read.
            detail += (f", but it has restarted {restarts} times — it is "
                       f"crash-looping, not settled")
            report.add("service running", WARN, detail)
        else:
            report.add("service running", OK, detail)
    elif active in ("activating", "deactivating") or sub == "auto-restart":
        report.add("service running", FAILED,
                   f"{unit} is {active}/{sub} after {restarts} restarts — it "
                   f"is failing and being restarted in a loop, so it never "
                   f"stays up long enough to hold a session",
                   _journal_hint(unit, scope))
    else:
        report.add("service running", FAILED,
                   f"{unit} is {active or 'unknown'}/{sub or 'unknown'} "
                   f"(result={props['Result'] or 'none'}, "
                   f"exit={props['ExecMainStatus'] or 'none'})",
                   _systemctl_hint(scope, "start", unit) + " && "
                   + _journal_hint(unit, scope))

    journal = _read_journal(unit, env, scope)
    _add_216_reading(report, props, unit=unit, env=env,
                     scope=scope, journal_text=journal)
    _add_last_error(report, unit, env, journal_text=journal,
                    scope=scope, props=props)


#: systemd's own exit statuses for the failures that are otherwise
#: unreadable in a log. `216` is NOT here: it has two causes with two
#: different fixes, only one of which is a group membership problem, and the
#: journal is the only thing that can tell them apart — see
#: `read_216_cause` and `_add_216_reading`.
_EXIT_READINGS = {
    "217": ("217/USER — systemd could not switch to the configured user.",
            "check the unit's User= directive"),
    "203": ("203/EXEC — systemd could not execute the program at all: the "
            "launcher is missing, not executable, or its interpreter is "
            "gone.",
            "scripts/install_capture_client.sh --url <SPECTRA's address>"),
    "200": ("200/CHDIR — the working directory in the unit does not exist.",
            "re-run the installer to rewrite the launcher"),
}

#: THE TWO CAUSES OF ONE STATUS. Named, because a single "216 = you are not
#: in the group" reading is what sent the owner to `usermod` and a REBOOT
#: for a fault that neither of those could ever fix.
CAUSE_PRIVILEGE = "privilege"     # the manager could not make the call
CAUSE_MEMBERSHIP = "membership"   # systemd could not resolve/apply the group

#: The kernel's own word, carried verbatim into systemd's journal line. This
#: is EPERM on `setgroups(2)` itself, which an unprivileged manager gets
#: whether or not the user is a member of anything.
_EPERM_WORDS = "operation not permitted"

#: systemd's line for the whole family, whichever cause produced it.
_GROUP_CRED_WORDS = "changing group credentials failed"


def read_216_cause(journal_text: str) -> Optional[str]:
    """WHICH 216 THIS IS, read out of the unit's OWN journal text.

    A status code cannot answer this and never could. `216/GROUP` means only
    "systemd could not apply the group directives", and there are two very
    different ways to get there:

      * `Operation not permitted` — the *manager* was refused the
        `setgroups(2)` call outright. Under `systemd --user` that is
        UNCONDITIONAL: an unprivileged manager cannot change group
        credentials at all, and MEMBERSHIP IS IRRELEVANT — a user who is in
        the group fails identically. The unit is simply carrying a directive
        that cannot work where it is. No amount of `usermod` or rebooting
        touches it.

      * anything else — the membership-shaped failure: systemd could resolve
        the call but not the group (it does not exist, or the manager may
        not grant it). That is the reading this doctor has always given.

    Returns None when the journal could not be read or says nothing about
    group credentials — an UNKNOWN, never a guess. Inventing the privilege
    reading from a bare status code would be the same class of confident
    wrong answer this whole module exists to end."""
    text = (journal_text or "").lower()
    if _GROUP_CRED_WORDS not in text and "216" not in text:
        return None
    # Only judge the line that actually names the failure, so an unrelated
    # "operation not permitted" elsewhere in 60 lines of journal cannot
    # promote a membership fault into a privilege one.
    for line in text.splitlines():
        if _GROUP_CRED_WORDS in line:
            return (CAUSE_PRIVILEGE if _EPERM_WORDS in line
                    else CAUSE_MEMBERSHIP)
    return None


def _add_216_reading(report: Report, props: dict, *,
                     unit: str = UNIT_NAME,
                     env: Optional[dict] = None,
                     scope: str = SCOPE_USER,
                     journal_text: Optional[str] = None) -> None:
    """THE EXIT STATUS, TRANSLATED — and translated from the JOURNAL'S OWN
    REASON, not from the number alone.

    `status=216/GROUP` in a journal is not a sentence anybody can act on,
    and it is precisely the line that sat in his journal all evening saying
    nothing to anyone. Worse, the reading it used to get here ("you are not
    in group video, run usermod and REBOOT") was RIGHT about the class and
    WRONG about his machine: he was already a member, he had already
    rebooted, and the unit still died — because a user unit carrying
    `SupplementaryGroups=` can never start, member or not.

    `journal_text` may be supplied by a caller that already has the unit's
    real journal in hand (the fresh-host rig does exactly this, so the
    translation is cross-checked against a live journal line rather than a
    constant somebody typed into a test)."""
    status = (props.get("ExecMainStatus") or "").strip()
    if status != "216":
        reading = _EXIT_READINGS.get(status)
        if reading is not None:
            report.add("exit status", FAILED, reading[0], reading[1])
        return

    if journal_text is None:
        journal_text = _read_journal(unit, env, scope)
    cause = read_216_cause(journal_text or "")

    if cause == CAUSE_PRIVILEGE:
        report.add(
            "exit status", FAILED,
            f"216/GROUP, and the journal says why: 'Changing group "
            f"credentials failed: Operation not permitted'. THE UNIT IS "
            f"CARRYING A GROUP DIRECTIVE AN UNPRIVILEGED MANAGER CANNOT "
            f"APPLY. `systemd --user` is not root, so `setgroups(2)` is "
            f"refused outright — this is NOT about membership and a user "
            f"who IS in '{VIDEO_GROUP}' fails exactly the same way. "
            f"`usermod` will not fix it and neither will a reboot. The "
            f"shipped user unit has no SupplementaryGroups= line for this "
            f"reason; a hand-edited or pre-2026-09-03 one does. (Under a "
            f"SYSTEM unit — the installer's --system mode — the same "
            f"directive is legitimate, because root applies it before "
            f"dropping to User=.)",
            f"remove the SupplementaryGroups= line from "
            f"~/.config/systemd/user/{unit}.service — or just re-run "
            f"scripts/install_capture_client.sh, which regenerates the unit "
            f"without it — then: systemctl --user daemon-reload && "
            f"systemctl --user restart {unit}   (NO REBOOT NEEDED)")
        return

    if cause == CAUSE_MEMBERSHIP:
        report.add(
            "exit status", FAILED,
            f"216/GROUP — systemd could not give the service its "
            f"supplementary groups, and the journal does NOT say "
            f"'Operation not permitted', so this is the group itself, not "
            f"the manager's privilege: see the group check above.",
            f"sudo usermod -aG {VIDEO_GROUP} $(id -un), then "
            + ("REBOOT" if scope == SCOPE_USER else
               f"systemctl restart {unit}"))
        return

    report.add(
        "exit status", FAILED,
        f"216/GROUP — systemd could not apply the unit's group directives. "
        f"The journal's own reason line could not be read from here, so "
        f"WHICH of the two causes this is was not determined: a "
        f"SupplementaryGroups= line in a USER unit (which can never work, "
        f"whatever the membership), or the group itself. Read the reason "
        f"and the answer is in it — 'Operation not permitted' means the "
        f"first.",
        f"grep -n SupplementaryGroups "
        f"~/.config/systemd/user/{unit}.service ; journalctl --user -u "
        f"{unit} -n 50 --no-pager")


def _read_journal(unit: str, env: Optional[dict],
                  scope: str = SCOPE_USER) -> Optional[str]:
    """The unit's recent journal. None means it COULD NOT BE READ (no
    journalctl, or the read failed); "" means it was read and was empty —
    a distinction that matters, because "we could not check" and "there was
    nothing" get different verdicts. Shared by the 216 reading and the
    last-error line so there is one idea of what "the unit's own words"
    means, and so the doctor reads the journal once."""
    if not shutil.which("journalctl"):
        return None
    code, out = _run(["journalctl"] + _scope_args(scope) + ["-u", unit, "-n",
                      "60", "--no-pager", "-o", "cat"],
                     timeout=PROBE_TIMEOUT_S, env=env)
    return out if code == 0 else None


def _systemctl_hint(scope: str, *words) -> str:
    """A systemctl command HE can actually run in this scope. A system unit
    needs root, and printing a line that comes back "Access denied" is one
    more thing for him to be the messenger about."""
    prefix = ["systemctl"] if scope == SCOPE_USER else ["sudo", "systemctl"]
    return " ".join(prefix + _scope_args(scope) + list(words))


def _journal_hint(unit: str, scope: str = SCOPE_USER) -> str:
    """The command HE should run, in the scope his unit actually lives in.
    Handing someone `journalctl --user` for a system unit is handing them a
    command that answers about nothing."""
    prefix = ["journalctl"] if scope == SCOPE_USER else ["sudo", "journalctl"]
    return " ".join(prefix + _scope_args(scope)
                    + ["-u", unit, "-n", "50", "--no-pager"])


def _add_last_error(report: Report, unit: str, env: Optional[dict],
                    journal_text: Optional[str] = None,
                    scope: str = SCOPE_USER,
                    props: Optional[dict] = None) -> None:
    """THE LAST REAL ERROR LINE from the journal — the thing a person would
    scroll for. Not a summary and not our paraphrase: the unit's own words,
    which is what makes it worth pasting.

    AND WHEN IT HAPPENED, WHICH IS THE HALF THIS SHIPPED WITHOUT (fixed
    2026-09-03). The owner fixed his host, the service came up, SPECTRA saw
    it — and the doctor still headlined `last error` as a PROBLEM, quoting a
    failure from BEFORE the fix, because a journal read with no clock cannot
    tell a scar from a wound. A tool whose whole purpose is to stop him
    being the messenger had him pasting a message about a machine that was
    working.

    So a last-error finding now carries WHEN, measured against the unit's
    own `ActiveEnterTimestamp` — the moment it last came up — and the two
    cases get DIFFERENT VERDICTS:

      IS FAILING      the newest error line is at or after the last
                      successful start, or the service is not running at
                      all. FAILED, and it counts as a problem.
      FAILED EARLIER  every error line predates the start that is still
                      running. That is HISTORY on a healthy service, so it
                      is reported as UNKNOWN — visible, never counted, and
                      explicitly labelled as such.

    An unreadable or absent timestamp is NOT resolved by guessing: with no
    clock the line is reported as-is and said to be undated."""
    out = (journal_text if journal_text is not None
           else _read_journal(unit, env, scope))
    if out is None:
        report.add("last error", UNKNOWN,
                   "the unit's own words could not be read (journalctl is "
                   "not installed, or the journal refused this read)")
        return
    if not out.strip():
        report.add("last error", UNKNOWN,
                   "the journal had nothing for this unit (it may never "
                   "have been started on this machine)")
        return
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    interesting = [ln for ln in lines if _INTERESTING.search(ln)]
    chosen = (interesting or lines)[-1]
    if not interesting:
        report.add("last error", UNKNOWN,
                   f"the unit's own last line: {chosen[:300]}")
        return

    healthy, started_at, started_mono = _running_since(props)
    stale = (_errors_predate_start(unit, env, scope, started_mono)
             if healthy else False)
    if healthy and stale:
        # FAILED EARLIER — history, not a fault. UNKNOWN so it appears in
        # the paste and is never counted as a problem, which is the whole
        # difference between "your machine is broken" and "here is what it
        # went through before it came up".
        report.add("last error", UNKNOWN,
                   f"FAILED EARLIER, not now: the service has been up since "
                   f"{started_at or 'its last start'} and every error in its "
                   f"journal predates that. Kept because it says what this "
                   f"machine went through, not because anything is wrong "
                   f"now. Newest of them: {chosen[:250]}")
        return
    when = (f" (the service has been up since {started_at}, so this is at or "
            f"after that start)" if healthy and started_at else "")
    report.add("last error", FAILED,
               f"IS FAILING — the unit's own last line: {chosen[:300]}{when}",
               _journal_hint(unit, scope))


def _running_since(props: Optional[dict]) -> tuple:
    """(is the service up right now, when it came up in words, when it came
    up on the monotonic clock). All three out of systemd's own properties —
    never inferred from the journal we are about to judge against them."""
    if not props:
        return False, "", None
    healthy = (props.get("ActiveState") == "active"
               and props.get("SubState") == "running")
    mono = (props.get("ActiveEnterTimestampMonotonic") or "").strip()
    try:
        mono_s = float(mono) / 1e6 if mono and mono != "0" else None
    except ValueError:
        mono_s = None
    return healthy, (props.get("ActiveEnterTimestamp") or "").strip(), mono_s


#: `journalctl -o short-monotonic` puts seconds-since-boot in brackets at
#: the head of every line: `[830866.798367] host systemd[1]: ...`
_MONOTONIC_LINE = re.compile(r"^\[\s*(\d+(?:\.\d+)?)\]\s*(.*)$")


def _errors_predate_start(unit: str, env: Optional[dict], scope: str,
                          started_monotonic_s: Optional[float]) -> bool:
    """DID EVERY ERROR LINE HAPPEN BEFORE THE START THAT IS STILL RUNNING?

    WHY THE MONOTONIC CLOCK AND NOT `--since`. `ActiveEnterTimestamp` is a
    wall-clock string with SECOND granularity, so a unit that failed and
    came back inside the same second — which is exactly what a `Restart=`
    loop does, and what the rig reproduces — lands its old failure inside
    the window and reads as current. `ActiveEnterTimestampMonotonic` and
    `journalctl -o short-monotonic` are THE SAME CLOCK, boot-relative, at
    microsecond precision: one origin, no timezone, no locale, and nothing
    to parse but a number systemd printed.

    `-b` bounds it to the CURRENT BOOT, which the monotonic clock requires:
    across a reboot those seconds start again, and without it a failure from
    a previous boot could carry a larger number than this boot's start and
    read as newer than it.

    Anything that cannot be read gives False — history, if we cannot prove
    it, is treated as a live problem. A doctor that downgraded a REAL,
    CURRENT failure to a scar because its own clock query failed would be
    worse than one that never had a clock at all."""
    if started_monotonic_s is None or not shutil.which("journalctl"):
        return False
    code, out = _run(["journalctl"] + _scope_args(scope) + ["-u", unit, "-b",
                      "--no-pager", "-o", "short-monotonic"],
                     timeout=PROBE_TIMEOUT_S, env=env)
    if code != 0 or not out.strip():
        return False
    saw_boundary = False
    for line in out.splitlines():
        m = _MONOTONIC_LINE.match(line.strip())
        if not m:
            # A LINE WE CANNOT DATE IS NOT A LINE WE MAY DISMISS.
            return False
        when, text = float(m.group(1)), m.group(2)
        if when < started_monotonic_s:
            continue
        saw_boundary = True
        if _INTERESTING.search(text):
            return False
    # Nothing at or after the start at all means the journal and systemd
    # disagree about when this unit came up; say so by refusing the claim
    # rather than declaring every failure historical.
    return saw_boundary


#: What counts as an error line. One definition, used to pick the line worth
#: quoting AND to decide whether anything since the start is a problem — two
#: different answers from one regex is a bug this file cannot afford.
_INTERESTING = re.compile(
    r"error|fail|refus|traceback|cannot|could not|no such|permission"
    r"|denied|216|Exception", re.I)


# ── 7. DOES THE SERVER SEE THIS MACHINE ────────────────────────────────────

def check_server_sees_us(report: Report, url: str, host: str) -> None:
    """THE ONE QUESTION THE OTHER SIX CANNOT ANSWER: not "is my service
    running" but "has SPECTRA got my camera". Those came apart on the
    evening this was written and a doctor that only looked at this machine
    would have said everything was fine.

    It reads the SERVER's own `camera_host` surface
    (`spectra/services/capture_health.py`) and reports its sentence, never
    one composed here."""
    if not url:
        report.add("SPECTRA sees this machine", UNKNOWN,
                   "no address configured, so the server was not asked")
        return
    _status, body, err = _get_json(url.rstrip("/") + STATUS_PATH)
    if err or body is None:
        report.add("SPECTRA sees this machine", UNKNOWN,
                   f"the server could not be asked ({err or 'not JSON'}) — "
                   f"the address checks above say why")
        return
    camera_host = body.get("camera_host") or {}
    state = str(camera_host.get("state") or "")
    sentence = str(camera_host.get("sentence") or "")
    client = camera_host.get("client") or {}
    seen = str(client.get("host") or "")

    if state == "never":
        report.add("SPECTRA sees this machine", FAILED,
                   f"SPECTRA has NEVER seen a capture client. {sentence}",
                   f"start the service and watch it: systemctl --user "
                   f"restart {UNIT_NAME} && journalctl --user -u "
                   f"{UNIT_NAME} -f")
        return
    if seen and host and seen != host:
        # A DIFFERENT MACHINE IS THE ONE IT KNOWS. Silent otherwise, and
        # exactly the shape of "the browser tab held the lens".
        report.add("SPECTRA sees this machine", FAILED,
                   f"SPECTRA's camera host is {seen!r}, not this machine "
                   f"({host!r}). {sentence}",
                   f"if this machine should be the camera, stop the other "
                   f"client (a browser tab on the Rooms page counts) and "
                   f"restart: systemctl --user restart {UNIT_NAME}")
        return
    if state in ("present", "impaired"):
        report.add("SPECTRA sees this machine",
                   OK if state == "present" else FAILED,
                   sentence or f"SPECTRA reports this machine {state}",
                   "" if state == "present" else
                   "the sentence above is the client's own reason; fix that "
                   "and it clears on its own")
        return
    report.add("SPECTRA sees this machine", FAILED,
               f"SPECTRA knows this machine but it is NOT connected right "
               f"now. {sentence}",
               f"systemctl --user restart {UNIT_NAME} && journalctl --user "
               f"-u {UNIT_NAME} -n 50 --no-pager")


# ── the whole thing ────────────────────────────────────────────────────────

def run(*, url: str = "", device: str = "/dev/video0", host: str = "",
        venv: str = "", unit: str = UNIT_NAME,
        skip_server: bool = False, scope: str = "") -> Report:
    """Every branch, in the order a person would work through them: this
    machine's own tools first, then the thing between it and SPECTRA, then
    SPECTRA's own answer. Nothing here writes, fixes or starts anything."""
    report = Report(host=host or platform.node())
    scope = scope or detect_scope(unit)
    check_python(report, venv)
    check_tools(report)
    check_device(report, device)
    check_video_group(report, scope=scope)
    check_url(report, url)
    check_service(report, unit, scope)
    if not skip_server:
        check_server_sees_us(report, url, report.host)
    return report


_GLYPH = {OK: "ok  ", FAILED: "FAIL", WARN: "warn", UNKNOWN: "?   "}


def render(report: Report, *, venv: str = "", url: str = "",
           device: str = "") -> str:
    """ONE PASTE. Wide enough to read, narrow enough to survive a chat
    window, and it ends with the ONE thing to do next rather than a list he
    has to prioritise himself."""
    out = ["== SPECTRA capture client: doctor ==",
           f"  machine   {report.host}",
           f"  platform  {platform.system()} {platform.release()} "
           f"{platform.machine()}"]
    if url:
        out.append(f"  server    {url}")
    if device:
        out.append(f"  camera    {device}")
    if venv:
        out.append(f"  venv      {venv}")
    out.append("")
    for f in report.findings:
        out.append(f"  {_GLYPH.get(f.verdict, '?   ')}  {f.check}: {f.detail}")
        if f.fix:
            out.append(f"        fix: {f.fix}")
    out.append("")
    failures = report.failures
    if not failures:
        unknowns = report.unknowns
        tail = (f" ({len(unknowns)} thing(s) could not be checked from here "
                f"— those are blind spots, not faults)" if unknowns else "")
        out.append(f"== everything this machine can check passed{tail}. ==")
        return "\n".join(out)
    # THE FIRST FAILURE IN THIS ORDER IS THE ONE TO FIX FIRST, because the
    # order the checks run in IS the dependency order — a venv with no pip
    # makes every later answer meaningless.
    first = failures[0]
    out.append(f"== {len(failures)} problem(s). START HERE: {first.check} ==")
    out.append(f"   {first.detail}")
    if first.fix:
        out.append(f"   fix: {first.fix}")
    return "\n".join(out)


def main(*, url: str = "", device: str = "/dev/video0", host: str = "",
         venv: str = "", unit: str = UNIT_NAME, as_json: bool = False,
         skip_server: bool = False, scope: str = "") -> int:
    """Exit 0 when nothing FAILED. An UNKNOWN never fails the run: a doctor
    that reported a blind spot as a fault would send him to fix a machine
    that is working."""
    report = run(url=url, device=device, host=host, venv=venv, unit=unit,
                 skip_server=skip_server, scope=scope)
    if as_json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(render(report, venv=venv, url=url, device=device))
    return 1 if report.failures else 0


# ── THE INSTALLER'S BOUNDED WAIT FOR A REAL HELLO ──────────────────────────

def await_hello(url: str, host: str, *, timeout_s: float = 45.0,
                unit: str = UNIT_NAME, poll_s: float = 2.0,
                clock=None, sleep=None) -> tuple[int, str]:
    """DID THE THING WE JUST INSTALLED ACTUALLY ARRIVE? Poll SPECTRA's own
    `camera_host` surface until this machine appears, then say what really
    happened — and when it never appears, say THAT, with the distinguishing
    detail rather than a shrug.

    THE FOUR OUTCOMES, and they are four because they have four different
    next steps:

      connected           SPECTRA names this machine. The only outcome that
                          may be reported as success, and it carries the
                          lever self-test verdict, because "connected" and
                          "trustworthy as an instrument" are two claims.
      present but unable  the client IS there and is saying why it cannot
                          do the job (`capture_health`'s `impaired`).
      the unit failed     the service is not running or is crash-looping,
                          and its OWN last journal line is the answer.
      never arrived       the service is up, and SPECTRA has not heard from
                          it — the cannot-reach-the-server case, which is
                          structurally invisible from the server side and is
                          exactly what the address probe and `--doctor`
                          cover.

    Returns (exit code, text). Non-zero for every outcome but the first: an
    install that ends in any of the other three has not finished, and saying
    so is the whole point of this function existing."""
    import time as _time
    clock = clock or _time.monotonic
    sleep = sleep or _time.sleep
    if not url:
        return 1, ("  no SPECTRA address, so there is nothing to wait for. "
                   "Set SPECTRA_CAPTURE_URL and run the installer again.")
    probe = url.rstrip("/") + STATUS_PATH
    deadline = clock() + float(timeout_s)
    last_err = ""
    while True:
        _status, body, err = _get_json(probe, timeout=PROBE_TIMEOUT_S)
        if err:
            last_err = err
        elif body is not None:
            ch = body.get("camera_host") or {}
            client = ch.get("client") or {}
            seen = str(client.get("host") or "")
            state = str(ch.get("state") or "")
            if state in ("present", "impaired") and (not host or seen == host):
                return _hello_landed(ch, client, state, unit)
        if clock() >= deadline:
            break
        sleep(poll_s)
    # NOTHING ARRIVED. Say which of the two silences it is.
    return 1, _hello_never_arrived(unit, last_err, timeout_s, probe)


def _hello_landed(ch: dict, client: dict, state: str,
                  unit: str) -> tuple[int, str]:
    who = (f"{client.get('host')}"
           f"{' (' + client.get('pose_name') + ')' if client.get('pose_name') else ''}")
    build = client.get("version") or "?"
    lever = dict(client.get("lever") or {})
    if state == "impaired":
        return 1, "\n".join([
            f"  SPECTRA SEES {who}, running {build} — and it says it CANNOT "
            f"do the job:",
            f"    {ch.get('unable') or ch.get('sentence') or 'no reason given'}",
            "",
            "  The connection is fine. Fix what it names above and it clears",
            "  on its own; nothing needs reinstalling."])
    lines = [f"  CONNECTED. SPECTRA sees {who}, running {build}.",
             f"    camera: {(client.get('camera') or {}).get('device') or 'reported'}",
             f"    locked: {'yes' if client.get('locked') else 'not yet'}"]
    # THE SELF-TEST VERDICT, NAMED — because a connected camera and a camera
    # whose exposure lever was measured to work are two different claims,
    # and this script has no business collapsing them.
    if lever.get("verdict"):
        lines.append(f"    lever self-test: {lever['verdict']}"
                     f"{' — ' + lever['reason'] if lever.get('reason') else ''}")
    else:
        lines.append("    lever self-test: not run yet (it runs inside the "
                     "first calibration-grade run, on the held room)")
    return 0, "\n".join(lines)


def _hello_never_arrived(unit: str, last_err: str, timeout_s: float,
                         probe: str) -> str:
    """THE SERVICE'S OWN WORDS FIRST, then the honest unknown. A unit that
    could not start has an answer in its journal and there is no reason to
    make anybody go and find it."""
    out = [f"  SPECTRA never saw this machine within {timeout_s:.0f}s."]
    report = Report()
    check_service(report, unit, detect_scope(unit))
    failed = [f for f in report.findings if f.failed]
    if failed:
        out.append("")
        out.append("  THE SERVICE IS THE PROBLEM, in its own words:")
        for f in failed:
            out.append(f"    {f.check}: {f.detail}")
            if f.fix:
                out.append(f"      fix: {f.fix}")
        return "\n".join(out)
    if last_err:
        out.append(f"  ...and SPECTRA could not be reached either "
                   f"({last_err} at {probe}).")
        out.append("  The service is running; it is the address or the "
                   "network between them.")
        return "\n".join(out)
    out.append("")
    out.append("  The service is RUNNING and SPECTRA is ANSWERING, and the "
               "client has still")
    out.append("  not appeared there. That is the one case neither side can "
               "explain alone:")
    out.append(f"    {_journal_hint(unit, detect_scope(unit))}")
    return "\n".join(out)


# ── the address check, on its own, for the installer ───────────────────────

def check_address_only(url: str) -> tuple[int, str]:
    """JUST THE THREE READINGS OF THE ADDRESS — the installer's pre-install
    probe, which has to happen before there is a virtualenv to run the whole
    doctor from. Same functions, same wording; there is no second copy of
    the resolve/connect/answer logic anywhere."""
    report = Report()
    check_url(report, url)
    lines = []
    for f in report.findings:
        lines.append(f"{_GLYPH.get(f.verdict, '?   ').strip()} {f.check}: "
                     f"{f.detail}")
        if f.fix:
            lines.append(f"    fix: {f.fix}")
    return (1 if report.failures else 0), "\n".join(lines)


if __name__ == "__main__":                             # pragma: no cover
    # RUNNABLE AS A PLAIN FILE, with no package import and no dependencies:
    # `python3 spectra/capture_client/doctor.py`. That is the form the
    # installer uses before it has built anything, and the form that still
    # works on a machine where the install went wrong.
    import argparse
    _p = argparse.ArgumentParser(
        prog="doctor.py",
        description="Check every link in the chain from this machine to "
                    "SPECTRA. Fixes nothing, starts nothing, opens no "
                    "camera.")
    _p.add_argument("--url", default=os.environ.get("SPECTRA_CAPTURE_URL", ""))
    _p.add_argument("--device",
                    default=os.environ.get("SPECTRA_CAPTURE_DEVICE",
                                           "/dev/video0"))
    _p.add_argument("--host", default=os.environ.get("SPECTRA_CAPTURE_HOST", ""))
    _p.add_argument("--venv", default=os.environ.get("SPECTRA_CAPTURE_VENV", ""))
    _p.add_argument("--json", action="store_true")
    # WHICH MANAGER OWNS THE UNIT. Detected from disk by default (a system
    # unit file present wins), overridable because a half-migrated host can
    # have both and only a person knows which one is meant to be running.
    _p.add_argument("--scope", choices=(SCOPE_USER, SCOPE_SYSTEM),
                    default="",
                    help="ask the user or the system service manager "
                         "(default: whichever has the unit installed)")
    _p.add_argument("--offline", action="store_true",
                    help="do not ask the server anything")
    _p.add_argument("--address-only", action="store_true",
                    help="just the three readings of the address")
    _p.add_argument("--await-hello", type=float, default=None,
                    metavar="SECONDS",
                    help="wait up to SECONDS for this machine to appear on "
                         "SPECTRA's camera_host surface, then report what "
                         "actually happened (the installer's own check)")
    _a = _p.parse_args()
    if _a.address_only:
        _code, _text = check_address_only(_a.url)
        print(_text)
        raise SystemExit(_code)
    if _a.await_hello is not None:
        _code, _text = await_hello(_a.url, _a.host or platform.node(),
                                   timeout_s=_a.await_hello)
        print(_text)
        raise SystemExit(_code)
    raise SystemExit(main(url=_a.url, device=_a.device, host=_a.host,
                          venv=_a.venv, as_json=_a.json,
                          skip_server=_a.offline, scope=_a.scope))
