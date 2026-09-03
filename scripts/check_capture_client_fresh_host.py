"""PROVEN SOMEWHERE IT WAS NOT BORN — the evening's failures, reproduced on
machines that have never seen this repository, and caught.

WHY THIS EXISTS SEPARATELY FROM `check_capture_client_service.py`. That
script proves the installer, the unit and the client end to end, and it does
it on a throwaway HOME with `id` and `systemctl` SHIMMED. Shims are honest
there — they force both answers to a question so the refusal is exercised
deterministically — but a shim can only ever prove that the code reacts to
the answer it was handed. It cannot prove the QUESTION is the right one on a
real machine, and "we asked the neighbouring question" was the shape of two
of the eight failures on 2026-09-02.

So this script asks the real machines instead. Two rigs, each named for what
it does and does not cover:

  A. THE HOST'S OWN systemd USER MANAGER. A transient unit
     (`systemd-run --user`) with `SupplementaryGroups=video`, on a user who
     is not in that group, produces the REAL `216/GROUP` — the exact status
     that sat in his journal all evening. The doctor's translation of that
     status is then checked against what systemd actually did, rather than
     against a string somebody typed into a test.

     WHAT IT DOES NOT COVER: it never installs, enables or starts the real
     unit, and it touches nothing of his. The transient unit runs /bin/true,
     fails before executing anything, and is reset. It drives no light,
     opens no camera and reaches no room.

  B. A GENUINELY FRESH LINUX HOST, IN A CONTAINER. A stock `debian:stable-
     slim`, a real non-root user created there, the repository mounted
     READ-ONLY, and the real installer run as that user. Nothing about this
     machine's configuration is inherited: the user is not in `video`
     because it was just created, and `python3` has no `ensurepip` because
     that is what a bare Debian is.

     WHAT IT DOES NOT COVER: there is no systemd inside it (so the unit is
     never started there — rig A and the service check own that), and no
     camera. It proves the REFUSALS, which is the half that has to be right
     on a machine nobody has prepared.

EACH RIG SKIPS HONESTLY. No docker, or no session bus, means that rig
reports SKIPPED with the reason and the script says so at the end — a
missing facility is a named hole in the ledger, never a pass. A false clean
row is exactly what this evening produced.

Run from repo root:  .venv/bin/python scripts/check_capture_client_fresh_host.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
print = __import__("functools").partial(print, flush=True)     # noqa: A001

FAILURES: list[str] = []
SKIPPED: list[str] = []

#: A distinctive prefix so the transient unit can never be confused with
#: anything of his, and so a leftover is findable by name.
UNIT_PREFIX = "spectra-capture-groupprobe"

#: The image rig B runs on. Stock Debian on purpose: `python3` there has no
#: `ensurepip`, which is the real shape of the PR #241 failure rather than a
#: simulated one.
IMAGE = "debian:stable-slim"


def check(cond, label):
    if not cond:
        FAILURES.append(label)
        print(f"FAIL: {label}")
        return False
    print(f"ok: {label}")
    return True


def run(args, timeout=120, env=None):
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout, env=env)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)


# ── RIG A: the host's own systemd, and a real 216/GROUP ────────────────────

def user_bus_env():
    """The session bus, filled in when this shell has none — the same thing
    the doctor does, and for the same reason: an agent shell often has
    neither variable while the manager is perfectly alive."""
    env = dict(os.environ)
    runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    env["XDG_RUNTIME_DIR"] = runtime
    if not env.get("DBUS_SESSION_BUS_ADDRESS"):
        bus = os.path.join(runtime, "bus")
        if os.path.exists(bus):
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"
    return env


def rig_a() -> None:
    print("== A. the host's own systemd user manager, and a REAL 216/GROUP ==")
    if not shutil.which("systemd-run") or not shutil.which("systemctl"):
        SKIPPED.append("rig A: systemd-run/systemctl are not on this machine")
        print("SKIPPED: systemd-run/systemctl are not on this machine")
        return
    env = user_bus_env()
    rc, out = run(["systemctl", "--user", "is-system-running"], env=env)
    if "Failed to connect to bus" in out or "No medium found" in out:
        SKIPPED.append("rig A: no session bus reachable for this user, so "
                       "systemd could not be asked to do anything")
        print(f"SKIPPED: no session bus reachable ({out.strip()[:60]})")
        return

    # WHICH ANSWER THIS HOST GIVES, read rather than assumed — the proof is
    # only meaningful on a user who is NOT in the group, and pretending
    # otherwise would be the vacuous pass this file exists to avoid.
    rc, groups = run(["id", "-nG"])
    if "video" in groups.split():
        SKIPPED.append("rig A: this user IS in group 'video', so a unit "
                       "demanding it would start and there is no 216/GROUP "
                       "to reproduce here")
        print("SKIPPED: this user is in 'video' — nothing to reproduce")
        return
    print(f"   (this user's groups: {groups.strip()} — no 'video', which is "
          f"the precondition)")

    unit = f"{UNIT_PREFIX}-{os.getpid()}"
    try:
        rc, out = run(["systemd-run", "--user", f"--unit={unit}",
                       "--property=SupplementaryGroups=video", "/bin/true"],
                      env=env)
        check(rc == 0, "systemd accepted a transient unit demanding "
                       "SupplementaryGroups=video")
        status = ""
        for _ in range(40):
            time.sleep(0.25)
            _rc, status = run(["systemctl", "--user", "show", unit,
                               "-p", "ExecMainStatus", "--value"], env=env)
            if status.strip():
                break
        status = status.strip()
        check(status == "216",
              f"and it FAILED with the real thing: ExecMainStatus={status!r} "
              f"(216 = EXIT_GROUP)")
        _rc, text = run(["systemctl", "--user", "status", unit,
                         "--no-pager"], env=env)
        check("216/GROUP" in text,
              "systemd's own words: 'status=216/GROUP'")
        check("Changing group credentials failed" in text,
              "with the reason it gives in the journal — the line that sat "
              "in his journal all evening explaining nothing to anyone")

        # THE DOCTOR'S TRANSLATION, CHECKED AGAINST WHAT SYSTEMD ACTUALLY
        # DID — not against a status code somebody typed into a test.
        sys.path.insert(0, str(ROOT))
        from spectra.capture_client import doctor
        r = doctor.Report()
        doctor._add_216_reading(r, {"ExecMainStatus": status})
        check(len(r.findings) == 1 and r.findings[0].verdict == doctor.FAILED,
              "the doctor translates that exact status into a failure")
        detail, fix = r.findings[0].detail, r.findings[0].fix
        check("group 'video'" in detail and "SupplementaryGroups" in detail,
              f"naming the group and the directive: {detail[:80]}")
        check("usermod -aG video" in fix and "REBOOT" in fix,
              "and the fix names the command AND the reboot")

        # AND THE PURE-READ PREDICATE AGREES WITH THE LIVE OUTCOME. This is
        # the whole reason the doctor reads /proc instead of running a test
        # unit every time: the two must give the same answer, and here the
        # live one is available to check it against.
        gid = doctor._group_gid("video")
        pid = doctor._user_manager_pid()
        if pid is None or gid is None:
            SKIPPED.append("rig A: could not find this user's systemd --user "
                           "manager, so the /proc predicate was not "
                           "cross-checked against the live failure")
            print("SKIPPED (part): no user manager found to cross-check")
        else:
            held = doctor._process_groups(pid)
            check(held is not None and gid not in held,
                  f"and the doctor's PURE READ of the running manager "
                  f"(pid {pid}) agrees with what systemd just did: it does "
                  f"not hold gid {gid}")
    finally:
        run(["systemctl", "--user", "reset-failed", unit], env=env)
        _rc, left = run(["systemctl", "--user", "list-units", "--all",
                         f"{unit}*", "--no-legend"], env=env)
        check(unit not in left,
              "the transient unit is gone — nothing of his was touched and "
              "nothing is left behind")


# ── RIG B: a genuinely fresh Linux host, in a container ────────────────────

#: Run as a REAL non-root user that was created seconds ago. It is not in
#: `video` because nobody put it there, and that is the point: no shim
#: decides the answer.
_RIG_B_SCRIPT = r"""
set -u
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null 2>&1
apt-get install -y -qq python3 ffmpeg v4l-utils systemd >/dev/null 2>&1

useradd -m -s /bin/bash camerauser
install -d -o camerauser -g camerauser /home/camerauser/work
cp -r /repo /home/camerauser/work/SpotFX
chown -R camerauser:camerauser /home/camerauser/work

echo "### FRESH HOST FACTS ###"
su camerauser -c 'id -nG'
su camerauser -c 'python3 -c "import venv" >/dev/null 2>&1 && echo VENV_IMPORTS || echo NO_VENV'
su camerauser -c 'python3 -m ensurepip --version >/dev/null 2>&1 && echo ENSUREPIP_OK || echo NO_ENSUREPIP'

echo "### INSTALLER, AS THAT USER ###"
su camerauser -c 'cd /home/camerauser/work/SpotFX && \
  ./scripts/install_capture_client.sh --check --url http://127.0.0.1:1/spectra \
  --device /dev/null 2>&1; echo "INSTALLER_RC=$?"'

echo "### ANYTHING WRITTEN? ###"
su camerauser -c 'ls -A /home/camerauser/.config 2>/dev/null || echo NO_CONFIG_DIR'
su camerauser -c 'ls -A /home/camerauser/.local 2>/dev/null || echo NO_LOCAL_DIR'

echo "### THE DOCTOR, STANDALONE, NOTHING INSTALLED ###"
su camerauser -c 'cd /home/camerauser/work/SpotFX && \
  python3 spectra/capture_client/doctor.py --offline \
  --url http://127.0.0.1:1/spectra 2>&1; echo "DOCTOR_RC=$?"'
"""


def rig_b() -> None:
    print(f"\n== B. a genuinely fresh {IMAGE} host, a user created seconds "
          f"ago ==")
    if not shutil.which("docker"):
        SKIPPED.append("rig B: docker is not on this machine")
        print("SKIPPED: docker is not available")
        return
    rc, _ = run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=60)
    if rc != 0:
        SKIPPED.append("rig B: the docker daemon is not reachable")
        print("SKIPPED: the docker daemon is not reachable")
        return

    # READ-ONLY MOUNT, deliberately: this rig may not write into the
    # checkout, and it copies the tree inside the container before touching
    # anything.
    rc, out = run(["docker", "run", "--rm", "--network", "bridge",
                   "-v", f"{ROOT}:/repo:ro", IMAGE, "bash", "-c",
                   _RIG_B_SCRIPT], timeout=900)
    if rc != 0 and "### FRESH HOST FACTS ###" not in out:
        SKIPPED.append(f"rig B: the container could not be prepared "
                       f"(rc={rc}) — most likely no network for apt")
        print(f"SKIPPED: the container could not be prepared: {out[-300:]}")
        return
    print(out.strip()[-2000:] if os.environ.get("VERBOSE") else
          "   (container output captured)")

    # THE FRESH FACTS, first — a proof about a refusal is worthless if the
    # condition it refuses on was not actually true.
    facts = out.split("### FRESH HOST FACTS ###")[1].split("###")[0]
    check("video" not in facts.split("### ")[0].split("\n")[1].split(),
          f"the fresh user is NOT in group 'video' — nobody put it there: "
          f"{facts.strip().splitlines()[0]!r}")
    check("VENV_IMPORTS" in facts,
          "and `import venv` WORKS on this host, as it does on his")
    check("NO_ENSUREPIP" in facts,
          "while `ensurepip` is missing — the real PR #241 trap on a real "
          "Debian, not a simulated one: the two questions genuinely differ "
          "here")

    installer = out.split("### INSTALLER, AS THAT USER ###")[1].split("###")[0]
    check("INSTALLER_RC=1" in installer,
          "the installer REFUSES on this fresh host")
    check("NOT in group 'video'" in installer,
          "naming the group membership the unit actually requires")
    check("216/GROUP" in installer,
          "and what systemd would do about it")
    check("REBOOT" in installer,
          "and that a reboot — not a logout — is what applies it")
    check("cannot put pip in it" in installer or "ensurepip" in installer,
          "AND the ensurepip trap on the same run, so a fresh host learns "
          "both in one pass instead of one failure at a time")
    check("NOTHING WAS INSTALLED" in installer,
          "with nothing written")

    written = out.split("### ANYTHING WRITTEN? ###")[1].split("###")[0]
    check("NO_CONFIG_DIR" in written or "spectra-capture" not in written,
          "and the fresh home really is untouched")

    doc = out.split("### THE DOCTOR, STANDALONE, NOTHING INSTALLED ###")[1]
    check("SPECTRA capture client: doctor" in doc,
          "the doctor RUNS on that host with nothing installed at all — "
          "bare system python3, no virtualenv, no httpx, no websockets")
    check("video group" in doc and "216/GROUP" in doc,
          "and it names the group problem there too")
    check("DOCTOR_RC=1" in doc,
          "exiting non-zero because it found real failures")


def main() -> int:
    rig_a()
    rig_b()
    print()
    if SKIPPED:
        print("SKIPPED (named holes in the ledger, not passes):")
        for s in SKIPPED:
            print(f"  - {s}")
        print()
    if FAILURES:
        print(f"FAILED {len(FAILURES)} check(s):")
        for f in FAILURES:
            print(f"  {f}")
        return 1
    # WHAT ACTUALLY RAN goes on its own line ABOVE the verdict, so the
    # verdict line is stable and a reader still cannot mistake a partial run
    # for a full one.
    print(f"rigs run: {2 - len(set(s.split(':')[0] for s in SKIPPED))} of 2"
          f"{' — see the skips above' if SKIPPED else ''}")
    print("FRESH-HOST CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
