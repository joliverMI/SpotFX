"""THE CAPTURE CLIENT AS A BOOT SERVICE — proven as far as this machine can
prove it, and no further.

WHAT IS REAL HERE: the shipped systemd unit, verified by SYSTEMD'S OWN
PARSER (`systemd-analyze verify`, which is what rejected two real mistakes
while this was being written); the real provisioning script, run twice, on a
throwaway HOME; the real virtualenv it builds from
`requirements-capture-client.txt`; the real launcher it writes; the real
`EnvironmentFile` it writes; a real uvicorn server running the real SPECTRA
app; and the REAL capture client started EXACTLY the way the unit starts it
— the unit's own `ExecStart`, with the unit's own `EnvironmentFile` as its
whole configuration and not one command-line argument.

WHAT IS NOT REAL, and it is named rather than implied:

  * **systemd itself never runs the unit here.** This sandbox has no D-Bus
    session bus, and a private `systemd --user` refuses to start without
    cgroup delegation, so `systemctl --user start` cannot be executed on
    this machine at all. The unit's TEXT is verified by systemd; its
    RESTART BEHAVIOUR is exercised by a supervisor in this script that
    reads `Restart=`/`RestartSec=` out of the installed unit and does what
    they say. That is a proof of what the unit tells systemd to do. It is
    not a proof that systemd did it, and it is not reported as one.
  * **The camera is synthetic** (`SPECTRA_CAPTURE_SYNTHETIC=1`), which by
    construction reports NO lock — a proof that could only declare "locked"
    could not show the gate. No map is produced here and none could be.
  * **`systemctl` and `v4l2-ctl` are shims on PATH**, so the provisioning
    script's own calls can be asserted without a bus and without a webcam.
    `systemd-analyze` is the REAL one.
  * **No ARM board has run any of this.** See
    `scripts/check_capture_client_deps.py` and the ledger in
    `docs/CAPTURE_CLIENT_HOST.md`.

THE SEVEN THINGS IT PROVES:

  1. The shipped unit is valid systemd, and an invalid one is refused.
  2. Provisioning refuses BY NAME at each missing prerequisite and writes
     NOTHING when it does.
  3. Provisioning a fresh host works, and running it a SECOND time changes
     nothing it should not — including a value edited by hand in between.
  4. The unit's ExecStart, with the unit's EnvironmentFile as its whole
     configuration, establishes a real session on a real server with no
     arguments at all.
  5. SPECTRA can SEE that host: name, build, declared placement, camera —
     on the session status surface.
  6. A client that DIES is a READ, not a silence: the record names the
     machine, its build, its placement and how long it has been gone.
  7. `Restart=always` brings it back and it re-establishes the session —
     and the new session is honestly a NEW POSE, because the camera was
     opened again.

Run from repo root: .venv/bin/python scripts/check_capture_client_service.py
Isolated: a throwaway HOME and XDG dirs, temp SPECTRA storage, a spare
loopback port. It never touches ~/.config/systemd/user, never touches
spotfx.service or spectra.service, and never reaches his room.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
print = __import__("functools").partial(print, flush=True)     # noqa: A001

FAILURES: list[str] = []


def check(cond, label):
    if not cond:
        FAILURES.append(label)
        print(f"FAIL: {label}")
        return False
    print(f"ok: {label}")
    return True


td = Path(tempfile.mkdtemp(prefix="spectra-capture-service-"))
os.environ["SPECTRA_STORAGE_DIR"] = str(td / "spectra")

from fx import device_model                                    # noqa: E402
device_model.CATEGORIES_FILE = td / "device_categories.json"
device_model.CATEGORIES_FILE.write_text(json.dumps({}))

from fx import light_ownership                                 # noqa: E402
light_ownership.OWNERSHIP_FILE = td / "ownership.json"
light_ownership.OWNERSHIP_FILE.write_text(json.dumps({"owner": "spectra"}))

from spectra import config as scfg                             # noqa: E402
scfg.SPECTRA_STORAGE = td / "spectra"
for name in ("SCENES_FILE", "SEQUENCER_FILE", "DRIFT_PROFILES_FILE",
             "ROOM_COLOR_FILE", "ROOM_CONTROLS_FILE", "GRADIENT2D_FILE",
             "FIRE_HISTORY_FILE", "SHOW_LOG_FILE", "FLARE_PREVIEW_HOLD_FILE",
             "ROOM_MAPS_FILE", "ROOM_EFFECTS_FILE", "COMMISSIONING_FILE",
             "CAPTURE_QUEUE_FILE", "CAPTURE_HEALTH_FILE"):
    setattr(scfg, name, scfg.SPECTRA_STORAGE / f"{name.lower()}.json")
scfg.COLOR_SETS_FILE = td / "color_sets.json"

import httpx                                                   # noqa: E402
import uvicorn                                                 # noqa: E402

UNIT_SRC = ROOT / "deploy" / "spectra-capture-client.service"
INSTALLER = ROOT / "scripts" / "install_capture_client.sh"

# ── the throwaway host ─────────────────────────────────────────────────────
HOME = td / "home"
SHIMS = td / "shims"
for d in (HOME, SHIMS):
    d.mkdir(parents=True, exist_ok=True)
SYSTEMCTL_LOG = td / "systemctl-calls.log"

(SHIMS / "systemctl").write_text(
    "#!/bin/sh\n"
    f'printf "%s\\n" "$*" >> "{SYSTEMCTL_LOG}"\n'
    'case "$1" in --version) echo "systemd 255 (shim)";; esac\n'
    "exit 0\n")
# v4l2-ctl exists on the provisioned host but is never called by the
# installer — its presence IS the check, which is the point.
(SHIMS / "v4l2-ctl").write_text("#!/bin/sh\nexit 0\n")
for name in ("systemctl", "v4l2-ctl"):
    os.chmod(SHIMS / name, 0o755)

# ── THE GROUP, BOTH WAYS, AND WHY IT IS A SHIM AT ALL ──────────────────────
#
# The installer's real predicate is now `id -nG | grep -qx video` — actual
# membership, because a user service INHERITS its groups from
# `systemd --user` and a readable /dev/video0 does NOT imply membership (a
# desktop seat's ACL grants read access with no group in sight, which is how
# a machine whose service could never open the camera passed the old check).
#
# Both answers therefore have to be forced here rather than inherited from
# whoever happens to run this: a machine whose user IS in video would make
# the refusal proof pass vacuously, and one whose user is NOT (this build
# host, as it happens) could not provision at all. So there are two PATHs,
# each with an `id` that answers one way and delegates everything else to
# the real binary. What is NOT shimmed is the refusal's own logic, which is
# the thing under test.
_REAL_ID = shutil.which("id") or "/usr/bin/id"
for _dirname, _extra in (("id-in-video", "video"), ("id-not-in-video", "")):
    _d = td / _dirname
    _d.mkdir(exist_ok=True)
    (_d / "id").write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-nG" ] && [ $# -eq 1 ]; then\n'
        f'  printf "%s\\n" "$({_REAL_ID} -nG) {_extra}"\n'
        "  exit 0\n"
        "fi\n"
        f'exec {_REAL_ID} "$@"\n')
    os.chmod(_d / "id", 0o755)
ID_IN_VIDEO = td / "id-in-video"
ID_NOT_IN_VIDEO = td / "id-not-in-video"

#: A PATH holding every tool the installer genuinely uses EXCEPT the one
#: under test — built by symlink so the refusal is exercised against a host
#: that really is missing that binary, rather than against a crippled PATH
#: that would refuse for some other reason first.
INSTALLER_TOOLS = ("uname", "id", "grep", "tail", "cut", "awk", "sed", "mv",
                   "cp", "mkdir", "chmod", "loginctl", "systemd-analyze",
                   "python3", "ffmpeg", "v4l2-ctl", "systemctl", "env",
                   "sh", "bash")


def path_without(missing: str) -> str:
    d = td / f"path-without-{missing}"
    d.mkdir(exist_ok=True)
    for tool in INSTALLER_TOOLS:
        if tool == missing:
            continue
        target = (SHIMS / tool) if (SHIMS / tool).exists() else None
        target = target or (Path(shutil.which(tool)) if shutil.which(tool) else None)
        if target is None:
            continue
        link = d / tool
        if not link.exists():
            link.symlink_to(target)
    # Every "missing tool" refusal must fail for THAT tool, not for the
    # group — so these hosts are always in video.
    return f"{ID_IN_VIDEO}:{d}"

BASE_ENV = dict(os.environ)
BASE_ENV.pop("SPECTRA_STORAGE_DIR", None)
BASE_ENV.update({
    "HOME": str(HOME),
    "XDG_CONFIG_HOME": str(HOME / ".config"),
    "XDG_RUNTIME_DIR": str(HOME / "run"),
    # Provisioning runs as a host whose user IS in video; the refusal
    # section below explicitly runs with the other one.
    "PATH": f"{ID_IN_VIDEO}:{SHIMS}:{BASE_ENV.get('PATH', '')}",
})
(HOME / "run").mkdir(parents=True, exist_ok=True)

ENV_FILE = HOME / ".config" / "spectra-capture" / "client.env"
UNIT_DST = HOME / ".config" / "systemd" / "user" / "spectra-capture-client.service"
LAUNCHER = HOME / ".local" / "bin" / "spectra-capture-client"
VENV = HOME / ".local" / "share" / "spectra-capture" / "venv"


def run_installer(*args, env_extra=None, path=None):
    env = dict(BASE_ENV)
    if env_extra:
        env.update(env_extra)
    if path is not None:
        env["PATH"] = path
    return subprocess.run([str(INSTALLER), *args], capture_output=True,
                          text=True, env=env, timeout=600)


async def run_installer_async(*args, **kw):
    """The same call, off the event loop — LOAD-BEARING once the installer
    talks to SPECTRA.

    The test server runs inside THIS process's loop, and the installer now
    probes the address before writing and waits for a real hello after
    starting. A blocking `subprocess.run` here would stall the very server
    it is trying to reach, and every one of those checks would fail for a
    reason that has nothing to do with what it is testing."""
    return await asyncio.to_thread(run_installer, *args, **kw)


# ── the unit, read the way systemd reads it ────────────────────────────────

def unit_values(path: Path) -> dict:
    """Every directive of the INSTALLED unit, with systemd's specifiers
    resolved the way the manager would resolve them for this user."""
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = (value.strip()
                            .replace("%h", str(HOME))
                            .replace("%t", str(HOME / "run")))
    return out


def env_file_vars(path: Path) -> dict:
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


# ── the server ─────────────────────────────────────────────────────────────

def _index_reachable() -> bool:
    try:
        socket.create_connection(("pypi.org", 443), timeout=4).close()
        return True
    except OSError:
        return False


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.asynccontextmanager
async def _no_lifespan(app):
    yield


class Server:
    def __init__(self, port: int) -> None:
        from spectra.app import create_app
        app = create_app()
        app.router.lifespan_context = _no_lifespan
        self.server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="warning",
            lifespan="on", ws_ping_interval=None))
        self.task = None

    async def start(self):
        self.task = asyncio.create_task(self.server.serve())
        for _ in range(300):
            if self.server.started:
                return
            await asyncio.sleep(0.05)
        raise RuntimeError("server did not start")

    async def stop(self):
        self.server.should_exit = True
        if self.task is not None:
            await asyncio.wait_for(self.task, timeout=10.0)


async def wait_for(predicate, timeout=30.0, poll=0.2):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        got = predicate()
        if asyncio.iscoroutine(got):
            got = await got
        if got:
            return got
        await asyncio.sleep(poll)
    return None


# ── the supervisor that does what Restart= says ────────────────────────────

class UnitSupervisor:
    """`ExecStart`, `EnvironmentFile`, `Restart` and `RestartSec` read out of
    the INSTALLED unit and obeyed.

    THIS IS NOT SYSTEMD, and the docstring at the top says so plainly. It is
    the honest half that can be executed on a machine with no session bus:
    the exact command, the exact environment, and the exact restart policy
    the unit declares."""

    def __init__(self, unit: Path) -> None:
        self.values = unit_values(unit)
        self.exec_start = self.values["ExecStart"]
        self.env_path = Path(self.values["EnvironmentFile"])
        self.restart = self.values.get("Restart", "no")
        self.restart_sec = float(self.values.get("RestartSec", "0") or 0)
        self.proc: subprocess.Popen | None = None
        self.starts = 0
        self._task: asyncio.Task | None = None
        self._stop = False

    def _env(self) -> dict:
        env = dict(BASE_ENV)
        env.update(env_file_vars(self.env_path))
        return env

    def _spawn(self) -> None:
        self.starts += 1
        self.proc = subprocess.Popen(
            self.exec_start.split(), env=self._env(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    async def start(self) -> None:
        self._spawn()
        self._task = asyncio.create_task(self._watch())

    async def _watch(self) -> None:
        while not self._stop:
            await asyncio.sleep(0.2)
            if self.proc is None or self.proc.poll() is None:
                continue
            if self.restart != "always":
                return
            await asyncio.sleep(self.restart_sec)
            if not self._stop:
                self._spawn()

    async def stop(self) -> None:
        self._stop = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self.kill()

    def kill(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGKILL)
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.proc.wait(timeout=5)


async def main():
    # ── 1. the shipped unit is valid systemd ──────────────────────────────
    print("== 1. the SHIPPED unit, checked by systemd's own parser ==")
    analyze = shutil.which("systemd-analyze")
    if not analyze:
        check(False, "systemd-analyze is not on this machine, so the unit "
                     "could not be verified at all")
    else:
        # The launcher does not exist until provisioning, so verify against
        # a copy whose ExecStart is a real file — everything else is the
        # shipped bytes.
        probe = td / "shipped-probe.service"
        stub = td / "stub-launcher"
        stub.write_text("#!/bin/sh\nexit 0\n")
        os.chmod(stub, 0o755)
        probe.write_text(UNIT_SRC.read_text().replace(
            "%h/.local/bin/spectra-capture-client", str(stub)))
        r = subprocess.run([analyze, "verify", str(probe)],
                           capture_output=True, text=True, timeout=60)
        check(r.returncode == 0 and not (r.stdout + r.stderr).strip(),
              f"deploy/spectra-capture-client.service verifies clean: "
              f"rc={r.returncode} {(r.stdout + r.stderr).strip()[:120]!r}")
        # THE NEGATIVE CONTROL: a proof that cannot fail is decoration.
        broken = td / "broken.service"
        broken.write_text(UNIT_SRC.read_text().replace(
            "%h/.local/bin/spectra-capture-client",
            "/nonexistent/capture-client"))
        r = subprocess.run([analyze, "verify", str(broken)],
                           capture_output=True, text=True, timeout=60)
        check(r.returncode != 0,
              "and a unit pointing at a launcher that is not there is REFUSED "
              "by the same check")

    values = unit_values(UNIT_SRC)
    check(values.get("Restart") == "always",
          "the unit restarts always — a camera host that dies must come back")
    check(values.get("WantedBy") == "default.target",
          "and is wanted by default.target, so it starts at boot (with linger)")
    check(not values.get("EnvironmentFile", "").startswith("-"),
          "its EnvironmentFile has no '-' prefix: a missing configuration "
          "stops the unit and names itself, rather than guessing")

    # ── 1b. THE BOUNDARY: one directive, legal in exactly one unit ───────
    #
    # `SupplementaryGroups=` is legitimate ONLY under a ROOT manager that
    # drops privileges. An unprivileged `systemd --user` is refused
    # `setgroups(2)` outright — `216/GROUP`, "Operation not permitted" — and
    # MEMBERSHIP IS IRRELEVANT to that: proven on the owner's own laptop
    # AFTER correct membership and a reboot, and reproduced on real systemd,
    # both shapes, by `scripts/check_capture_client_fresh_host.py` rig A.
    #
    # BOTH DIRECTIONS ARE CHECKED. "The user unit lost the line" and "the
    # system unit still has it" are two different regressions, and deleting
    # a string only catches one of them.
    print("\n== 1b. the user/system boundary, on the shipped bytes ==")
    check("SupplementaryGroups" not in values,
          "the USER unit carries NO SupplementaryGroups= directive — it "
          "could never have been applied there, member or not")
    header = UNIT_SRC.read_text()
    check("SupplementaryGroups" in header
          and "Operation not permitted" in header
          and "USER unit must not" in header,
          "and its header NAMES the excluded directive, the kernel's own "
          "reason and the boundary — a removed line leaves no trace, and "
          "the next person adding DeviceAllow= would put it back")

    sys_src = ROOT / "deploy" / "spectra-capture-client-system.service.in"
    check(sys_src.exists(),
          "and there IS a system unit template, so the boundary is two "
          "files rather than one conditional line")
    if sys_src.exists():
        # GENERATED, THEN VERIFIED — which is where the verification
        # property lives for this half: under a root manager `%h` is ROOT's
        # home, so a system unit cannot ship verbatim and what has to be
        # valid is the bytes the installer actually writes.
        gen = td / "system-probe.service"
        gen.write_text(sys_src.read_text()
                       .replace("@USER@", "camerauser")
                       .replace("@GROUP@", "camerauser")
                       .replace("@HOME@", str(td))
                       .replace("@LAUNCHER@", str(stub) if analyze else "/bin/true"))
        check("@" not in gen.read_text().split("[Unit]")[1],
              "every placeholder is filled in the generated body — an "
              "unfilled one would land in /etc as a literal @HOME@")
        sys_values = unit_values(gen)
        check(sys_values.get("SupplementaryGroups") == "video",
              "the SYSTEM unit DOES carry it — there is no login session on "
              "a kiosk host to inherit a group from, so root applying it "
              "before the drop to User= is the whole mechanism")
        check(sys_values.get("User") == "camerauser"
              and sys_values.get("Group") == "camerauser",
              "naming the account it drops into")
        check(sys_values.get("WantedBy") == "multi-user.target",
              "and wanted by multi-user.target, not default.target: it "
              "needs no login session and therefore no linger")
        check(sys_values.get("NoNewPrivileges") == "yes"
              and sys_values.get("ProtectSystem") == "strict",
              "with hardening no weaker than the user unit's — running "
              "under a root manager does not widen what the client may do")
        if analyze:
            r = subprocess.run([analyze, "verify", str(gen)],
                               capture_output=True, text=True, timeout=60)
            check(r.returncode == 0 and not (r.stdout + r.stderr).strip(),
                  f"and systemd's own parser accepts the GENERATED bytes: "
                  f"rc={r.returncode} "
                  f"{(r.stdout + r.stderr).strip()[:120]!r}")
    # WHAT THIS CANNOT PROVE, and it is not implied anywhere above: a REAL
    # ROOT MANAGER STARTING THAT UNIT. It needs a machine we may install
    # into /etc on and reboot, which is out of offline reach here — named as
    # unproven in docs/CAPTURE_CLIENT_HOST.md's ledger rather than
    # simulated. What IS proven is the text, both ways.

    # ── 2. every prerequisite refuses BY NAME, and writes nothing ─────────
    print("\n== 2. refusals by name, with nothing written ==")
    r = run_installer("--check", "--url", "http://x/y", "--device", "/dev/null",
                      path=path_without("ffmpeg"))
    check("ffmpeg is not installed" in r.stdout and
          "apt install ffmpeg" in r.stdout,
          "a host without ffmpeg is refused, naming the package")
    check(r.returncode == 1 and "NOTHING WAS INSTALLED" in r.stdout,
          "and it exits 1 having written nothing")

    r = run_installer("--check", "--url", "http://x/y", "--device", "/dev/null",
                      path=path_without("v4l2-ctl"))
    check("v4l2-ctl is not installed" in r.stdout and "v4l-utils" in r.stdout,
          "a host without v4l2-ctl is refused, naming what it is for")
    check(r.returncode == 1, "and that one exits 1 too")

    r = run_installer("--check", "--url", "http://x/y", "--device", "/dev/null",
                      path=path_without("python3"))
    check("python3 is not on PATH" in r.stdout,
          "a host with no python3 is refused, naming it")

    r = run_installer("--check")
    check("no --url was given" in r.stdout and r.returncode == 1,
          "a host with no configuration and no --url is refused, naming both")
    check(not ENV_FILE.exists() and not UNIT_DST.exists(),
          "after three refusals the throwaway host is still untouched")

    # ── 2b. THE GROUP RED CASE — the one that cost the evening ────────────
    # A host whose user is NOT in group 'video'. A user service inherits the
    # groups of `systemd --user`, so without membership it starts and cannot
    # open the camera — and the old check here asked whether /dev/video0 was
    # READABLE, which a desktop seat's ACL grants without any group. It said
    # yes, the install said success, and the service could never work.
    #
    # (The unit itself no longer declares SupplementaryGroups=video: a USER
    # unit carrying that can never start, member or not. See
    # `deploy/spectra-capture-client.service`'s header and
    # `check_capture_client_fresh_host.py` rig A, which proves both shapes
    # of 216/GROUP on real systemd.)
    #
    # Note the device passed here is /dev/null, which IS readable: that is
    # the point. A check that conflated the two would pass this test.
    print("\n== 2b. NOT in group 'video' — refused, and for the right "
          "reason ==")
    r = run_installer("--check", "--url", "http://x/y", "--device", "/dev/null",
                      path=f"{ID_NOT_IN_VIDEO}:{SHIMS}:{os.environ.get('PATH','')}")
    check(r.returncode == 1 and "NOT in group 'video'" in r.stdout,
          "a user who is not in 'video' is REFUSED, by name")
    check("inherits" in r.stdout.lower() and "cannot open the camera" in r.stdout,
          "and the refusal says the REAL user-scope consequence — a service "
          "that starts and cannot open the camera — not the 216/GROUP it "
          "used to claim, which was only ever true of a unit carrying a "
          "directive a user unit must not carry")
    check("usermod -aG video" in r.stdout and "REBOOT" in r.stdout,
          "naming the command AND the reboot — a logout does not restart "
          "the user manager, which is what has to gain the group")
    check("readable" in r.stdout.lower() and "ACL" in r.stdout,
          "and it says WHY a readable /dev/video0 was never evidence of "
          "this, so nobody re-introduces the old check")
    check(not ENV_FILE.exists() and not UNIT_DST.exists(),
          "nothing was written for it")

    # ── 2c. AN ADDRESS THAT DOES NOT ANSWER, also refused before writing ──
    # The URL branch had never been checked at install time at all, so a
    # name that does not resolve here, a port nothing listens on, and a
    # server that is not SPECTRA were all the same silent non-event.
    print("\n== 2c. an address that does not answer, refused before "
          "anything is written ==")
    dead = free_port()
    r = run_installer("--check", "--url", f"http://127.0.0.1:{dead}/spectra",
                      "--device", "/dev/null")
    check(r.returncode == 1 and "does not answer" in r.stdout,
          "an address nothing is listening on is refused before installing")
    check("will not accept a connection" in r.stdout,
          "naming WHICH of resolve/connect/answer failed")
    r = run_installer("--check", "--url", "http://no-such-host.invalid/spectra",
                      "--device", "/dev/null")
    check("cannot resolve" in r.stdout and r.returncode == 1,
          "and a name this machine cannot resolve is its own reading, not "
          "the same one")
    check(not ENV_FILE.exists(), "still nothing written")

    # ── 3. provisioning, and then provisioning again ──────────────────────
    print("\n== 3. a fresh host, provisioned — then provisioned again ==")
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    # THE SERVER COMES UP FIRST NOW, because the installer verifies the
    # address before it writes anything and then waits for a real hello
    # after it starts the service. Provisioning against a server that is not
    # there is itself one of the cases under test — section 2c above.
    server = Server(port)
    await server.start()
    print(f"   (the real SPECTRA app is up on 127.0.0.1:{port})")

    r = await run_installer_async("--check", "--url", url, "--device", "/dev/null")
    check(r.returncode == 0 and "nothing was written" in r.stdout,
          "--check with every prerequisite met passes and still writes nothing")
    check("SPECTRA answered at" in r.stdout,
          "and it got a real answer from SPECTRA before saying so")
    check(not ENV_FILE.exists(), "and really wrote nothing")
    # THE ONE THING HERE THAT NEEDS THE OUTSIDE WORLD is pip building the
    # client's virtualenv. On a machine with no index reachable, pre-build
    # it with system site packages and SAY SO, rather than failing a proof
    # about systemd units on a network condition that has nothing to do
    # with it. The installer's pip step then reports "already satisfied",
    # which is the same idempotent path a second run takes.
    if not _index_reachable():
        print("note: no package index reachable, so the virtualenv is "
              "pre-built with system site packages — the installer's pip "
              "step is then the same no-op a second run makes")
        subprocess.run([sys.executable, "-m", "venv", "--system-site-packages",
                        str(VENV)], check=True, timeout=300)
    r = await run_installer_async("--url", url, "--pose-name", "the north shelf",
                      "--device", "/dev/null", "--host", "camera-probe",
                      "--venv", str(VENV), "--no-start")
    check(r.returncode == 0, f"the installer succeeded: {r.stdout[-300:]}"
                             f"{r.stderr[-300:]}")
    check(ENV_FILE.exists(), f"configuration written to {ENV_FILE.name}")
    check(LAUNCHER.exists() and os.access(LAUNCHER, os.X_OK),
          "an executable launcher was written")
    check(UNIT_DST.exists() and UNIT_DST.read_text() == UNIT_SRC.read_text(),
          "the unit was installed VERBATIM — the bytes verified above are "
          "the bytes installed")
    check((VENV / "bin" / "python").exists(),
          "a virtualenv was built from requirements-capture-client.txt")
    r2 = subprocess.run([str(VENV / "bin" / "python"), "-c",
                         "import httpx, websockets; print('ok')"],
                        capture_output=True, text=True, timeout=60)
    check(r2.returncode == 0,
          "and it holds the client's two dependencies and nothing else was "
          "needed")
    calls = SYSTEMCTL_LOG.read_text() if SYSTEMCTL_LOG.exists() else ""
    check("daemon-reload" in calls, "systemctl --user daemon-reload was called")
    check("enable --now" not in calls,
          "and --no-start really started nothing")
    got = env_file_vars(ENV_FILE)
    check(got.get("SPECTRA_CAPTURE_URL") == url and
          got.get("SPECTRA_CAPTURE_POSE") == "the north shelf" and
          got.get("SPECTRA_CAPTURE_HOST") == "camera-probe",
          "the configuration says what was asked for")

    # A HAND EDIT MUST SURVIVE A SECOND RUN. A provisioner that rewrote the
    # config every time would silently undo whatever somebody fixed at 2am.
    with open(ENV_FILE, "a") as fh:
        fh.write("\nSPECTRA_CAPTURE_FPS=3\n")
    before_unit = UNIT_DST.read_text()
    r = await run_installer_async("--url", url, "--device", "/dev/null",
                      "--venv", str(VENV), "--no-start")
    check(r.returncode == 0, "running it a second time succeeds")
    again = env_file_vars(ENV_FILE)
    check(again.get("SPECTRA_CAPTURE_FPS") == "3",
          "a value edited by hand between runs is still there")
    check(again.get("SPECTRA_CAPTURE_POSE") == "the north shelf",
          "and a value it was not asked about again is unchanged")
    check(UNIT_DST.read_text() == before_unit,
          "the unit is byte-identical after the second run")

    # A HAND-EDITED UNIT MUST CONVERGE, and this is the opposite rule to the
    # configuration one immediately above — deliberately. The config is HIS
    # (a value fixed at 2am survives); the UNIT is ours (a line added at 2am
    # does not). The owner's own emergency fix was to delete
    # `SupplementaryGroups=video` from his installed unit by hand, so a
    # reinstall that patched only the lines it recognised would silently put
    # back the directive that stopped his service starting at all.
    with open(UNIT_DST, "a") as fh:
        fh.write("SupplementaryGroups=video\n")
    # THE DIRECTIVE, NOT THE WORD. The shipped header deliberately NAMES
    # `SupplementaryGroups=` so nobody re-adds it helpfully, so a substring
    # test over the file would pass on the shipped bytes and prove nothing.
    check("SupplementaryGroups" in unit_values(UNIT_DST),
          "with the broken directive hand-added back to the installed unit")
    r = await run_installer_async("--url", url, "--device", "/dev/null",
                                  "--venv", str(VENV), "--no-start")
    check(r.returncode == 0, "a reinstall over it succeeds")
    check("SupplementaryGroups" not in unit_values(UNIT_DST),
          "and the directive is GONE — the unit is regenerated whole, never "
          "patched, so his hand-fix converges instead of being undone")
    check(UNIT_DST.read_text() == UNIT_SRC.read_text(),
          "back to exactly the shipped bytes")

    # ── 4-7. the unit's own ExecStart, against a real server ──────────────
    print("\n== 4. the unit's ExecStart, configured ONLY by its "
          "EnvironmentFile ==")
    with open(ENV_FILE, "a") as fh:
        # The synthetic camera reports NO lock, by construction. Nothing
        # here can produce a map and nothing tries to.
        fh.write("SPECTRA_CAPTURE_SYNTHETIC=1\n")

    sup = UnitSupervisor(UNIT_DST)
    check(sup.exec_start == str(LAUNCHER),
          "ExecStart resolves to the launcher provisioning wrote")
    check("--" not in sup.exec_start,
          "and it carries NO arguments: the environment file is the whole "
          "configuration, which is what a boot service needs")

    async with httpx.AsyncClient(base_url=url, timeout=30.0) as http:
        async def host_view():
            body = (await http.get("/api/rooms/map/status")).json()
            return body.get("camera_host") or {}

        first = await host_view()
        check(first.get("state") == "never",
              f"before anything connects, SPECTRA says NEVER, not 'absent': "
              f"{first.get('sentence', '')[:70]}")

        await sup.start()
        live = await wait_for(lambda: _present(http), timeout=60.0)
        check(bool(live), "the client started by the unit's own ExecStart "
                          "established a session with no arguments at all")

        print("\n== 5. SPECTRA can SEE that host ==")
        view = await host_view()
        client = view.get("client") or {}
        # PRESENT AND UNABLE, AND THIS RIG IS THE PROOF OF IT. The client
        # here runs the SYNTHETIC camera, which by construction reports NOT
        # LOCKED — so it is a real reachable-but-broken client, and until
        # `impaired` existed this surface called it "present", the same word
        # it uses for a camera doing its job perfectly. The socket is still
        # a fact (`present` stays True); what changed is that the answer no
        # longer stops there.
        check(view.get("present") is True and view.get("state") == "impaired",
              f"the camera host reads present-but-UNABLE, not simply "
              f"present: state={view.get('state')!r}")
        check(bool(view.get("unable")),
              f"carrying the client's OWN reason: "
              f"{str(view.get('unable'))[:90]}")
        check("connected but cannot do the job" in (view.get("sentence") or ""),
              "and the sentence says connected AND unable in one line, so "
              "neither half can be read without the other")
        check(client.get("host") == "camera-probe",
              f"named: {client.get('host')!r}")
        check(client.get("client") == "spectra-capture-client" and
              client.get("version"),
              f"with its build: {client.get('client')} {client.get('version')}")
        check(client.get("pose_name") == "the north shelf",
              f"and its declared placement: {client.get('pose_name')!r}")
        check((client.get("platform") or {}).get("machine"),
              f"and the board it is running on: "
              f"{(client.get('platform') or {}).get('machine')!r}")
        check(client.get("locked") is False,
              "the synthetic camera reports NOT LOCKED — the gate is intact "
              "and no map could come from this")
        qv = (await http.get("/api/rooms/capture-queue")).json()
        check(((qv.get("session") or {}).get("host") or {}).get("present") is True,
              "and the same read reaches the capture queue's own session view")
        first_session = client.get("session_id")
        first_pose = client.get("pose_id")

        print("\n== 6. a client that DIES is a read, not a silence ==")
        sup._stop = True                 # hold the restart while we look
        if sup._task is not None:
            sup._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sup._task
        sup.kill()
        gone = await wait_for(lambda: _absent(http), timeout=30.0)
        check(bool(gone), "SPECTRA notices the client is gone")
        view = await host_view()
        check(view.get("state") == "absent" and view.get("present") is False,
              "and reports ABSENT rather than the same silence as 'never'")
        sentence = view.get("sentence", "")
        check("camera-probe" in sentence and "the north shelf" in sentence,
              f"naming the machine and its placement: {sentence[:100]}")
        check("ago" in sentence and view.get("absent_for_s") is not None,
              f"and how long it has been gone: absent_for_s="
              f"{view.get('absent_for_s')}")
        check((view.get("client") or {}).get("version"),
              "with the build it was running when it went")
        sv = (await http.get("/api/rooms/capture-queue")).json().get("session") or {}
        check(sv.get("present") is False and "no phone connected" in
              (sv.get("refusal") or ""),
              "the RUN's refusal is unchanged — this reports, it does not gate")

        print("\n== 7. Restart=always brings it back ==")
        started_before = sup.starts
        sup._stop = False
        await sup.start()
        back = await wait_for(lambda: _present(http), timeout=60.0)
        check(bool(back), "the restarted client re-established the session")
        check(sup.starts == started_before + 1,
              f"the supervisor obeyed Restart={sup.restart} / "
              f"RestartSec={sup.restart_sec:g} from the installed unit")
        view = await host_view()
        client = view.get("client") or {}
        check(client.get("session_id") and client.get("session_id") != first_session,
              "it is a NEW session")
        check(client.get("pose_id") and client.get("pose_id") != first_pose,
              "and honestly a NEW POSE — the camera was opened again, so the "
              "byte scale starts over and footprints either side are not "
              "comparable")
        check((view.get("known") or []) and
              len(view["known"]) == 1 and
              view["known"][0]["host"] == "camera-probe",
              "and the record still holds ONE row for this machine, not one "
              "per connection")

        # ── 8. THE INSTALLER NO LONGER CLAIMS WHAT IT DID NOT CHECK ──────
        # It used to END by announcing "SPECTRA can now SEE this machine",
        # unconditionally — including while installing a service that could
        # not start at all. It now STARTS the service and WAITS, bounded,
        # for this machine to appear on SPECTRA's own camera_host surface,
        # and prints what really happened.
        print("\n== 8. the installer verifies the whole chain, and says "
              "what it found ==")
        text = INSTALLER.read_text()
        check("SPECTRA can now SEE this machine" not in text,
              "the old unconditional claim is GONE from the script")

        # (a) NOTHING RUNNING. The systemctl shim logs `enable --now` and
        #     starts nothing, so this is a service that did not come up —
        #     the exact evening-shaped case.
        await sup.stop()
        await wait_for(lambda: _absent(http), timeout=30.0)
        r = await run_installer_async(
            "--url", url, "--device", "/dev/null", "--host", "camera-probe",
            "--venv", str(VENV), env_extra={"SPECTRA_CAPTURE_HELLO_WAIT_S": "4"})
        check(r.returncode != 0,
              "when the client never arrives, the install EXITS NON-ZERO "
              "rather than reporting success")
        check("never saw this machine" in r.stdout,
              f"and says so plainly: "
              f"{[ln for ln in r.stdout.splitlines() if 'never saw' in ln][:1]}")
        check("== installed ==" in r.stdout,
              "while still reporting that the FILES were installed — those "
              "two facts are separate and both are true")
        check("--doctor" in r.stdout,
              "and it names the one command that answers every branch")

        # (b) RUNNING, AND UNABLE. The client comes back with its synthetic
        #     camera, which reports NO lock — present, and saying why it
        #     cannot work. An install that called that "connected" would be
        #     the same lie in a new place.
        await sup.start()
        await wait_for(lambda: _present(http), timeout=60.0)
        r = await run_installer_async(
            "--url", url, "--device", "/dev/null", "--host", "camera-probe",
            "--venv", str(VENV), env_extra={"SPECTRA_CAPTURE_HELLO_WAIT_S": "20"})
        check("SPECTRA SEES camera-probe" in r.stdout,
              "with the client actually there, the install SEES it — by "
              "asking the server, not by asserting it")
        check("CANNOT" in r.stdout and r.returncode != 0,
              "and reports that it cannot do its job, non-zero, rather "
              "than calling a broken camera a finished install")
        await sup.stop()
    await server.stop()

    print()
    if FAILURES:
        raise SystemExit(f"FAILED {len(FAILURES)} check(s):\n  " +
                         "\n  ".join(FAILURES))
    print("NOT PROVEN HERE: systemd itself starting this unit (no session "
          "bus on this machine), and ARM execution. Both are named in "
          "docs/CAPTURE_CLIENT_HOST.md's ledger.")
    print("ALL CAPTURE CLIENT SERVICE CHECKS PASSED")


async def _present(http) -> bool:
    try:
        body = (await http.get("/api/rooms/map/status")).json()
    except httpx.HTTPError:
        return False
    return bool((body.get("camera_host") or {}).get("present"))


async def _absent(http) -> bool:
    try:
        body = (await http.get("/api/rooms/map/status")).json()
    except httpx.HTTPError:
        return False
    return (body.get("camera_host") or {}).get("state") == "absent"


if __name__ == "__main__":
    status_code = 0
    try:
        asyncio.run(main())
    except SystemExit as exc:
        print(exc)
        status_code = 1
    except BaseException:
        import traceback
        traceback.print_exc()
        status_code = 1
    finally:
        shutil.rmtree(td, ignore_errors=True)
    os._exit(status_code)
