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

  A. THE HOST'S OWN systemd USER MANAGER, AND BOTH SHAPES OF 216/GROUP.
     Transient units (`systemd-run --user`) driven to a REAL `216/GROUP` —
     the exact status that sat in his journal — and the doctor's translation
     cross-checked against each REAL JOURNAL LINE rather than a string
     somebody typed into a test.

     THE CONTROL THIS RIG WAS MISSING, AND WHAT IT COST. Until 2026-09-03
     this rig ran exactly ONE case: a `SupplementaryGroups=video` unit on a
     user who is NOT in that group. It went red, it proved 216, and it
     PASSED FOR THE WRONG REASON — it never ran the IN-GROUP control, so
     nothing here ever noticed that MEMBERSHIP IS IRRELEVANT under a user
     manager: `setgroups(2)` is refused outright, and a member fails
     identically. The doctor therefore told the owner to `usermod` and
     REBOOT for a fault neither could touch, and he did both, twice, before
     anyone read the journal's own reason line.

     So there are now THREE live cases on one manager, and the middle one is
     the whole point:

       A1  a group the user IS a member of, with the directive  -> 216
       A2  a group the user is NOT a member of, same directive  -> 216
       A3  no directive at all, same user, same manager         -> starts

     A1 and A2 give the SAME status for the SAME reason ("Operation not
     permitted"), which is the confound; A3 is what proves the fix is the
     absence of the directive and not anything about groups. Each journal is
     fed VERBATIM to `doctor.read_216_cause()` / `_add_216_reading()`.

     WHAT IT DOES NOT COVER: it never installs, enables or starts the real
     unit, and it touches nothing of his. The transient units run /bin/true,
     and every one is reset. They drive no light, open no camera and reach
     no room. Nor can it prove the SYSTEM half — a root manager applying
     `SupplementaryGroups=` legitimately is out of offline reach here, and
     is named as unproven in `docs/CAPTURE_CLIENT_HOST.md`'s ledger rather
     than simulated.

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


def _transient(unit, env, props):
    """Run /bin/true as a transient user unit with `props`, wait for it to
    settle, and hand back (ExecMainStatus, journal text). The journal is the
    point: a status code cannot say WHICH 216 this is."""
    args = ["systemd-run", "--user", f"--unit={unit}"]
    for prop in props:
        args += [f"--property={prop}"]
    rc, out = run(args + ["/bin/true"], env=env)
    if rc != 0:
        return None, out
    status = ""
    for _ in range(40):
        time.sleep(0.25)
        _rc, status = run(["systemctl", "--user", "show", unit,
                           "-p", "ExecMainStatus", "--value"], env=env)
        if status.strip():
            break
    _rc, journal = run(["journalctl", "--user", "-u", unit, "-n", "40",
                        "--no-pager", "-o", "cat"], env=env)
    return status.strip(), journal


def _reset(unit, env):
    run(["systemctl", "--user", "reset-failed", unit], env=env)
    _rc, left = run(["systemctl", "--user", "list-units", "--all",
                     f"{unit}*", "--no-legend"], env=env)
    return unit not in left


def _pick_groups(groups):
    """A group this user IS in, and one it is NOT — read off the machine, so
    the in-group control is a real membership rather than a claim.

    `video` is preferred for the NOT case because it is the one the unit
    actually cares about; any other real group does when the user happens to
    be a member of it."""
    held = [g for g in groups.split() if g]
    _rc, all_groups = run(["getent", "group"])
    known = [ln.split(":")[0] for ln in all_groups.splitlines() if ":" in ln]
    outsider = None
    for candidate in ["video"] + known:
        if candidate and candidate not in held:
            outsider = candidate
            break
    return (held[0] if held else None), outsider


def rig_a() -> None:
    print("== A. the host's own systemd user manager: BOTH shapes of a REAL "
          "216/GROUP, and the fix ==")
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

    rc, groups = run(["id", "-nG"])
    in_group, out_group = _pick_groups(groups)
    print(f"   (this user's groups: {groups.strip()})")
    if in_group is None or out_group is None:
        SKIPPED.append("rig A: could not find both a group this user IS in "
                       "and one it is NOT, so the confound control could not "
                       "be run")
        print("SKIPPED: no in/out group pair available on this machine")
        return
    print(f"   IN '{in_group}'  /  NOT IN '{out_group}'  — the pair that "
          f"makes the confound visible")

    sys.path.insert(0, str(ROOT))
    from spectra.capture_client import doctor

    base = f"{UNIT_PREFIX}-{os.getpid()}"
    cases = [
        ("A1", "IN the group", in_group,
         [f"SupplementaryGroups={in_group}"]),
        ("A2", "NOT in the group", out_group,
         [f"SupplementaryGroups={out_group}"]),
    ]
    journals = {}
    for tag, what, group, props in cases:
        unit = f"{base}-{tag.lower()}"
        try:
            print(f"\n   -- {tag}: a user unit demanding "
                  f"SupplementaryGroups={group} ({what}) --")
            status, journal = _transient(unit, env, props)
            journals[tag] = journal
            check(status == "216",
                  f"{tag}: it FAILED with the real thing — "
                  f"ExecMainStatus={status!r} (216 = EXIT_GROUP), and the "
                  f"user IS {'' if tag == 'A1' else 'NOT '}a member")
            check("Changing group credentials failed" in journal,
                  f"{tag}: systemd's own words are in the journal")
            check("Operation not permitted" in journal,
                  f"{tag}: and the REASON is EPERM — the manager could not "
                  f"make the call at all, which is why membership changes "
                  f"nothing")

            # THE DOCTOR'S TRANSLATION, AGAINST THIS REAL JOURNAL TEXT.
            # Never a constant: the string fed in here came out of systemd
            # seconds ago.
            check(doctor.read_216_cause(journal) == doctor.CAUSE_PRIVILEGE,
                  f"{tag}: the doctor reads that journal and names the "
                  f"PRIVILEGE cause, not the membership one")
            r = doctor.Report()
            doctor._add_216_reading(r, {"ExecMainStatus": status},
                                    journal_text=journal)
            check(len(r.findings) == 1
                  and r.findings[0].verdict == doctor.FAILED,
                  f"{tag}: as a single FAILED finding")
            detail, fix = r.findings[0].detail, r.findings[0].fix
            check("Operation not permitted" in detail
                  and "NOT about membership" in detail,
                  f"{tag}: whose words say it is not about membership")
            check("SupplementaryGroups" in fix and "daemon-reload" in fix
                  and "NO REBOOT" in fix.upper(),
                  f"{tag}: and whose FIX is remove-the-directive, reload, "
                  f"restart — explicitly NOT a reboot: {fix[:70]}...")
            check("usermod" not in fix,
                  f"{tag}: and does NOT send him to usermod, which is the "
                  f"advice that cost the owner two reboots")
        finally:
            check(_reset(unit, env), f"{tag}: the transient unit is gone")

    # THE CONFOUND, STATED AS A MEASUREMENT. Two units, opposite memberships,
    # ONE outcome — which is the whole reason last night's single red case
    # proved nothing about the cause it claimed.
    if "A1" in journals and "A2" in journals:
        check(doctor.read_216_cause(journals["A1"])
              == doctor.read_216_cause(journals["A2"])
              == doctor.CAUSE_PRIVILEGE,
              "THE CONFOUND, MEASURED: in-group and out-of-group produce the "
              "SAME 216 for the SAME reason on this manager — membership was "
              "never the variable")

    # A3: THE FIX ITSELF. Same user, same manager, same everything except the
    # directive. If this did not start, "remove the line" would be advice
    # nobody had checked.
    unit = f"{base}-a3"
    try:
        print("\n   -- A3: the SAME user unit with NO group directive --")
        status, journal = _transient(unit, env, [])
        check(status == "0",
              f"A3: it STARTS — ExecMainStatus={status!r}. The fix is the "
              f"absence of the directive, proven on the same manager that "
              f"just refused it twice")
        check("Changing group credentials failed" not in journal,
              "A3: and nothing in its journal is about group credentials")
        check(doctor.read_216_cause(journal) is None,
              "A3: so the doctor reads no 216 cause at all — it does not "
              "invent one from a clean journal")
    finally:
        check(_reset(unit, env), "A3: the transient unit is gone")

    # ── A4: THE STALE LAST-ERROR GHOST, reproduced and then not believed ──
    #
    # THE FAILURE THIS IS FOR (2026-09-03): after the owner fixed his host,
    # the doctor STILL headlined `last error` as a problem — quoting a
    # failure from before the fix — while the service was up and SPECTRA
    # could see it. A journal read with no clock cannot tell a scar from a
    # wound, so a working machine kept being reported broken and he kept
    # being the messenger about it.
    #
    # Built here out of real systemd rather than described: ONE unit name
    # that fails 216/GROUP, is reset, and then comes up healthy — so its own
    # journal genuinely carries an old failure underneath a current success,
    # which is exactly his machine's shape.
    unit = f"{base}-a4"
    try:
        print("\n   -- A4: a HEALTHY unit whose journal still holds the "
              "old 216 --")
        _status, _j = _transient(unit, env, [f"SupplementaryGroups={out_group}"])
        _reset(unit, env)
        rc, _out = run(["systemd-run", "--user", f"--unit={unit}",
                        "/bin/sh", "-c", "sleep 45"], env=env)
        check(rc == 0, "A4: the same unit name is started again, healthy")
        time.sleep(1.5)
        _rc, journal = run(["journalctl", "--user", "-u", unit, "--no-pager",
                            "-o", "cat"], env=env)
        check("216/GROUP" in journal,
              "A4: and its journal really does still carry the old "
              "216/GROUP — the ghost is present, not assumed")

        r = doctor.Report()
        doctor.check_service(r, unit)
        by_check = {f.check: f for f in r.findings}
        running = by_check.get("service running")
        check(running is not None and running.verdict == doctor.OK,
              f"A4: the doctor reports the service RUNNING "
              f"({running.verdict if running else 'no finding'})")
        last = by_check.get("last error")
        check(last is not None and last.verdict != doctor.FAILED,
              f"A4: and its `last error` is NOT a failure "
              f"({last.verdict if last else 'no finding'}) — the whole "
              f"defect was reporting this one as a current problem")
        check(last is not None and "FAILED EARLIER" in last.detail,
              "A4: it is headlined FAILED EARLIER, and says the service has "
              "been up since after it")
        # QUOTED VERBATIM, and checked against the journal's OWN newest
        # error line rather than a word we expect to see in it.
        errs = [ln.strip() for ln in journal.splitlines()
                if ln.strip() and doctor._INTERESTING.search(ln)]
        check(bool(errs) and last is not None
              and errs[-1][:120] in last.detail,
              f"A4: while still QUOTING that journal's own newest error "
              f"line verbatim — kept as history, never hidden: "
              f"{(errs[-1][:70] if errs else 'no error lines')!r}")

        # THE BAR, STATED HONESTLY. A transient unit is genuinely not
        # enabled and the doctor correctly says so, so that one finding is
        # named here rather than filtered silently: apart from it, a healthy
        # service with an old failure in its journal produces NO problems.
        failed = [f.check for f in r.findings if f.verdict == doctor.FAILED]
        check(failed in ([], ["service enabled"]),
              f"A4: and apart from 'service enabled' (true of any transient "
              f"unit — it will not start on its own), the healthy service "
              f"reports NO problems: {failed}")
    finally:
        run(["systemctl", "--user", "stop", unit], env=env)
        check(_reset(unit, env), "A4: the transient unit is gone")

    # AND THE SHIPPED USER UNIT CARRIES NO SUCH LINE. The proof above is
    # about a directive; this is the assertion that we do not ship one.
    unit_text = (ROOT / "deploy" / "spectra-capture-client.service").read_text()
    body = "\n".join(l for l in unit_text.splitlines()
                     if not l.lstrip().startswith("#"))
    check("SupplementaryGroups" not in body,
          "and the SHIPPED USER UNIT carries no SupplementaryGroups= line, "
          "so this failure cannot be installed by the script")

    # THE PURE-READ PREDICATE STILL AGREES WITH THE LIVE OUTCOME. This is
    # why the doctor reads /proc instead of running a test unit every time.
    gid = doctor._group_gid(out_group)
    pid = doctor._user_manager_pid()
    if pid is None or gid is None:
        SKIPPED.append("rig A: could not find this user's systemd --user "
                       "manager, so the /proc predicate was not "
                       "cross-checked against the live failure")
        print("SKIPPED (part): no user manager found to cross-check")
    else:
        held = doctor._process_groups(pid)
        check(held is not None and gid not in held,
              f"and the doctor's PURE READ of the running manager (pid "
              f"{pid}) agrees about the group this user is NOT in: it does "
              f"not hold gid {gid} for '{out_group}'")


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

echo "### THE SYSTEM SCOPE, ON THE SAME FRESH HOST ###"
su camerauser -c 'cd /home/camerauser/work/SpotFX && \
  ./scripts/install_capture_client.sh --check --system \
  --url http://127.0.0.1:1/spectra --device /dev/null 2>&1; \
  echo "SYSTEM_RC=$?"'

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
          "naming the group membership the client actually requires")
    check("inherits" in installer.lower() and "cannot open the camera" in installer,
          "and the real consequence in USER scope — a service that starts "
          "and cannot open the camera — rather than the 216/GROUP it used "
          "to claim, which was only ever true of a unit carrying a "
          "directive it must not carry")
    check("REBOOT" in installer,
          "and that a reboot — not a logout — is what applies it")
    check("cannot put pip in it" in installer or "ensurepip" in installer,
          "AND the ensurepip trap on the same run, so a fresh host learns "
          "both in one pass instead of one failure at a time")
    check("NOTHING WAS INSTALLED" in installer,
          "with nothing written")

    # THE SYSTEM SCOPE'S OWN REFUSALS, on a host that has neither root nor
    # sudo — which is exactly the shape of somebody trying `--system` on a
    # laptop, and must be a sentence rather than a permission-denied traceback.
    system = out.split("### THE SYSTEM SCOPE, ON THE SAME FRESH HOST ###")[1] \
                .split("###")[0]
    check("system scope" in system,
          "the installer says which scope it is checking, so a --system run "
          "cannot be mistaken for the default one")
    check("SYSTEM_RC=1" in system,
          "and it REFUSES on this host too, writing nothing")
    check("sudo is not installed" in system,
          "naming the one thing --system needs that the default does not: "
          "somewhere to write /etc/systemd/system from")
    check("no login session and no linger" in system,
          "while confirming the thing --system is FOR — boot-start with "
          "nobody logged in — rather than asking about linger, which a "
          "system unit does not use")
    check("legitimate THERE" in system and "root applies it" in system,
          "and its group refusal names the SYSTEM-scope mechanism (root "
          "applies SupplementaryGroups= before dropping to User=), not the "
          "user-scope one")
    check("REBOOT" not in system,
          "and does NOT tell a kiosk-host owner to reboot: root reads the "
          "group database at every start, so a restart is enough")

    written = out.split("### ANYTHING WRITTEN? ###")[1].split("###")[0]
    check("NO_CONFIG_DIR" in written or "spectra-capture" not in written,
          "and the fresh home really is untouched")

    doc = out.split("### THE DOCTOR, STANDALONE, NOTHING INSTALLED ###")[1]
    check("SPECTRA capture client: doctor" in doc,
          "the doctor RUNS on that host with nothing installed at all — "
          "bare system python3, no virtualenv, no httpx, no websockets")
    check("video group" in doc and "NOT in group 'video'" in doc,
          "and it names the group problem there too")
    check("cannot open the camera" in doc,
          "with the consequence a USER-scope host actually gets — the "
          "service starts and has no camera — and not the 216/GROUP that "
          "only ever came from a directive a user unit must not carry")
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
