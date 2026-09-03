"""THE DOCTOR, BRANCH BY BRANCH — every verdict it can reach, and the two
it must never confuse.

`spectra/capture_client/doctor.py` is the binding statement. What is proven
here is the part a live rig cannot reach on demand: the REBOOT-PENDING case
(a user manager holding stale supplementary groups), a stuck driver, the
three readings of an address, and — the one that matters most — that an
UNKNOWN never counts as a failure.

`scripts/check_capture_client_service.py` covers the other half end to end:
the real installer, the real client, a real server, a real WebSocket. These
two are deliberately different kinds of proof and neither replaces the other.
"""
from __future__ import annotations

import json
import os
import re
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from spectra.capture_client import doctor                        # noqa: E402


# ── the third verdict, which is the whole standard ─────────────────────────

def test_an_unknown_is_never_a_failure():
    """"WE COULD NOT CHECK" IS NOT "WE CHECKED AND IT IS BROKEN" — the
    standing rule `night_exit` (DARK vs UNKNOWN), `witness` (contaminated vs
    witness_unavailable) and `lever_selftest` (unprovable vs no_response)
    each hold, and the reason a doctor needs it most: a blind spot reported
    as a fault sends him to fix a machine that is working."""
    r = doctor.Report()
    r.add("a", doctor.UNKNOWN, "could not look")
    r.add("b", doctor.OK, "fine")
    r.add("c", doctor.WARN, "will bite later")
    assert r.failures == []
    assert len(r.unknowns) == 1
    text = doctor.render(r)
    assert "everything this machine can check passed" in text
    assert "blind spots, not faults" in text


def test_a_failure_names_the_first_thing_to_fix():
    """The check ORDER is the dependency order, so the first failure is the
    one to start on — a doctor that hands over five equal problems has made
    him do the prioritising."""
    r = doctor.Report()
    r.add("venv", doctor.FAILED, "no pip in it", "rm -rf the venv")
    r.add("service", doctor.FAILED, "not running")
    text = doctor.render(r)
    assert "2 problem(s). START HERE: venv" in text
    assert "rm -rf the venv" in text


# ── THE GROUP: membership, and the manager that has to have it ─────────────

def _fake_group_env(monkeypatch, *, groups: str, manager_pid, manager_groups,
                    gid=44):
    monkeypatch.setattr(doctor, "_run",
                        lambda args, **kw: (0, groups)
                        if args[:2] == ["id", "-nG"] else (0, ""))
    monkeypatch.setattr(doctor, "_group_gid", lambda name: gid)
    monkeypatch.setattr(doctor, "_user_manager_pid", lambda: manager_pid)
    monkeypatch.setattr(doctor, "_process_groups", lambda pid: manager_groups)


def test_not_a_member_names_the_real_user_scope_consequence(monkeypatch):
    """THE EVENING'S FAILURE, AND THE HALF OF IT WE GOT WRONG.

    Membership is still the predicate — a readable device was never evidence
    of it, and that has to keep being said or the neighbouring question gets
    asked again. But the CONSEQUENCE in user scope is not `216/GROUP`: a
    user service INHERITS its groups and cannot ask for them, so without
    membership it starts normally and then cannot open the camera. Claiming
    216 here described a unit carrying a directive that must not be in it,
    and sent the owner to fix the wrong thing."""
    _fake_group_env(monkeypatch, groups="javi sudo docker",
                    manager_pid=1292, manager_groups=[1000])
    r = doctor.Report()
    doctor.check_video_group(r, user="javi")
    f = r.findings[0]
    assert f.verdict == doctor.FAILED
    assert "inherits" in f.detail.lower()
    assert "cannot open the camera" in f.detail
    assert "216/GROUP" not in f.detail, \
        "a user unit does not die 216 for want of a membership"
    assert "READABLE" in f.detail and "ACL" in f.detail
    assert "usermod -aG video javi" in f.fix and "REBOOT" in f.fix


def test_system_scope_says_membership_is_enough_and_a_restart_is_enough(
        monkeypatch):
    """THE OTHER SIDE OF THE BOUNDARY. Under a ROOT manager the directive is
    legitimate and IS the mechanism: root reads the group database at every
    start and applies it before dropping to User=. So membership is enough,
    a RESTART is enough, and the running user manager is not involved — the
    doctor must not send a kiosk host owner to reboot for nothing."""
    _fake_group_env(monkeypatch, groups="camerauser sudo",
                    manager_pid=1292, manager_groups=[1000])
    r = doctor.Report()
    doctor.check_video_group(r, user="camerauser", scope=doctor.SCOPE_SYSTEM)
    f = r.findings[0]
    assert f.verdict == doctor.FAILED
    assert "SupplementaryGroups=video" in f.detail
    assert "legitimate" in f.detail
    assert "systemctl restart" in f.fix and "No reboot" in f.fix

    # And with the membership present it does NOT go on to read /proc: that
    # predicate belongs to the user scope and answering it here would be
    # reporting on a mechanism this unit does not use.
    _fake_group_env(monkeypatch, groups="camerauser video",
                    manager_pid=1292, manager_groups=[1000])   # manager: no 44
    r = doctor.Report()
    doctor.check_video_group(r, user="camerauser", scope=doctor.SCOPE_SYSTEM)
    member, applied = r.findings
    assert member.verdict == doctor.OK
    assert applied.check == "group applied" and applied.verdict == doctor.OK
    assert "root manager applies" in applied.detail


def test_a_member_whose_user_manager_has_not_caught_up_is_its_own_finding(
        monkeypatch):
    """REBOOT, NOT LOGOUT — and this is why it is a MEASUREMENT rather than
    advice. `usermod -aG` changes the group database; it changes no running
    process. `systemd --user` takes its supplementary groups once, at
    manager start, and being unprivileged cannot gain one afterwards — so a
    fresh shell can print `video` while the manager that has to launch the
    unit still cannot, and the service keeps dying 216/GROUP with everything
    a person can see saying it is fine.

    Two findings, because they fail separately: membership passes, applied
    fails."""
    _fake_group_env(monkeypatch, groups="javi sudo video",
                    manager_pid=1292, manager_groups=[4, 24, 1000])   # no 44
    r = doctor.Report()
    doctor.check_video_group(r, user="javi")
    member, applied = r.findings
    assert member.verdict == doctor.OK
    assert applied.check == "group applied"
    assert applied.verdict == doctor.FAILED
    assert "RUNNING user manager (pid 1292)" in applied.detail
    assert "REBOOTED" in applied.detail
    assert "reboot" in applied.fix


def test_a_member_whose_manager_has_it_passes_both(monkeypatch):
    _fake_group_env(monkeypatch, groups="javi video",
                    manager_pid=1292, manager_groups=[44, 1000])
    r = doctor.Report()
    doctor.check_video_group(r, user="javi")
    assert [f.verdict for f in r.findings] == [doctor.OK, doctor.OK]
    assert "inherits the camera" in r.findings[1].detail


def test_an_unreadable_manager_is_unknown_not_broken(monkeypatch):
    """A manager we cannot read is a thing we did not check. Reporting it as
    a stale-group failure would send him to reboot a healthy machine."""
    _fake_group_env(monkeypatch, groups="javi video",
                    manager_pid=1292, manager_groups=None)
    r = doctor.Report()
    doctor.check_video_group(r, user="javi")
    assert r.findings[1].verdict == doctor.UNKNOWN
    assert r.failures == []


def test_the_user_manager_is_matched_on_argv_not_a_substring():
    """MATCHED ON THE EXECUTABLE AND AN EXACT `--user` ARGUMENT. A substring
    search over whole command lines matches any shell that happens to
    mention it — it matched the scouting script that discovered this bug,
    which is why the rule is written down."""
    src = Path(doctor.__file__).read_text()
    body = src[src.index("def _user_manager_pid"):src.index("def _process_groups")]
    assert 'exe != "systemd"' in body, "the executable is checked by name"
    assert 'a == b"--user"' in body, "and --user is an exact argument match"


# ── the address, in three readings ─────────────────────────────────────────

def test_a_name_that_does_not_resolve(monkeypatch):
    def boom(*a, **kw):
        import socket
        raise socket.gaierror(-2, "Name or service not known")
    monkeypatch.setattr("socket.getaddrinfo", boom)
    r = doctor.Report()
    doctor.check_url(r, "http://nope.invalid:8000/spectra")
    assert r.findings[0].check == "address resolves"
    assert r.findings[0].verdict == doctor.FAILED
    assert "tailnet" in r.findings[0].fix


def test_resolves_but_refuses_a_connection():
    """A closed port on loopback — a real refusal from the real stack, not a
    mocked one. Port 1 is reserved and nothing binds it."""
    r = doctor.Report()
    doctor.check_url(r, "http://127.0.0.1:1/spectra")
    verdicts = {f.check: f.verdict for f in r.findings}
    assert verdicts["address resolves"] == doctor.OK
    assert verdicts["address connects"] == doctor.FAILED
    assert "answers" not in " ".join(verdicts)


def test_something_answers_and_it_is_not_spectra(monkeypatch):
    """THE PATH-PREFIX CASE, which is the one he actually hits: SPECTRA
    lives behind `/spectra` and an address missing it answers 404 from a
    server that is otherwise perfectly alive."""
    monkeypatch.setattr(doctor, "_get_json", lambda url, timeout=0: (404, None, ""))
    monkeypatch.setattr("socket.create_connection",
                        lambda *a, **kw: _Closeable())
    r = doctor.Report()
    doctor.check_url(r, "http://127.0.0.1:8000")
    last = r.findings[-1]
    assert last.check == "SPECTRA answers" and last.verdict == doctor.FAILED
    assert "/spectra" in last.fix


def test_json_without_camera_host_is_not_spectra(monkeypatch):
    monkeypatch.setattr(doctor, "_get_json",
                        lambda url, timeout=0: (200, {"hello": "world"}, ""))
    monkeypatch.setattr("socket.create_connection",
                        lambda *a, **kw: _Closeable())
    r = doctor.Report()
    doctor.check_url(r, "http://127.0.0.1:8000")
    assert r.findings[-1].verdict == doctor.FAILED
    assert "camera_host" in r.findings[-1].detail


class _Closeable:
    def __enter__(self): return self
    def __exit__(self, *a): return False


# ── the venv, and the half-made one ────────────────────────────────────────

def test_a_venv_with_no_pip_is_named_as_such(tmp_path, monkeypatch):
    """THE HALF-MADE VENV, two of the eight failures in one: a run that died
    inside pip leaves bin/python behind, and every later run reuses it and
    fails in exactly the same place."""
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "python").write_text("")
    monkeypatch.setattr(doctor, "_run",
                        lambda args, **kw: (0, "") if "ensurepip" in args
                        or args[-1] == "import venv" else (1, "No module named pip"))
    r = doctor.Report()
    doctor.check_python(r, str(tmp_path))
    venv_finding = [f for f in r.findings if f.check == "virtualenv"][0]
    assert venv_finding.verdict == doctor.FAILED
    assert "NO PIP" in venv_finding.detail
    assert "rm -rf" in venv_finding.fix and "python3-venv" in venv_finding.fix


def test_venv_without_ensurepip_is_the_pr241_predicate(monkeypatch):
    """`import venv` working is NOT "a venv built by this will contain pip".
    On Debian-family systems venv is stdlib and ensurepip ships separately
    in python3-venv. PR #241 fixed this in the installer; the doctor asks
    the same right question."""
    def fake(args, **kw):
        if args[-1] == "import venv":
            return 0, ""
        if "ensurepip" in args:
            return 1, "No module named ensurepip"
        return 0, ""
    monkeypatch.setattr(doctor, "_run", fake)
    r = doctor.Report()
    doctor.check_python(r, "")
    venv = [f for f in r.findings if f.check == "venv"][0]
    assert venv.verdict == doctor.FAILED
    assert "cannot put pip in it" in venv.detail
    assert "python3-venv" in venv.fix


# ── the unit ───────────────────────────────────────────────────────────────

def _systemctl(monkeypatch, answers: dict, *, have=True):
    monkeypatch.setattr(doctor.shutil, "which",
                        lambda name: f"/usr/bin/{name}" if have else None)

    def fake(args, **kw):
        if args[:1] == ["journalctl"]:
            # THE TWO JOURNAL READS ARE DIFFERENT QUESTIONS and the fake has
            # to keep them apart: the plain read is "the unit's own words",
            # the monotonic one is "what happened since it last came up".
            if "short-monotonic" in args:
                return 0, answers.get("journal_monotonic", "")
            return 0, answers.get("journal", "")
        if "is-system-running" in args:
            return 0, answers.get("is-system-running", "running")
        if "show" in args:
            prop = args[args.index("-p") + 1]
            return 0, answers.get(prop, "")
        return 0, ""
    monkeypatch.setattr(doctor, "_run", fake)


def test_no_session_bus_is_unknown_not_a_missing_unit(monkeypatch):
    """THE SHELL, NOT THE SERVICE. `systemctl --user` with no session bus
    fails with "Failed to connect to bus", which reads exactly like "no such
    service" — and would send him to reinstall a service that is running."""
    _systemctl(monkeypatch, {"is-system-running": "Failed to connect to bus: "
                                                 "No medium found"})
    r = doctor.Report()
    doctor.check_service(r)
    assert r.findings[0].verdict == doctor.UNKNOWN
    assert "property of THIS SHELL" in r.findings[0].detail
    assert r.failures == []


def test_a_crash_looping_unit_is_not_uptime(monkeypatch):
    """`Restart=always` means a service failing five times a minute reads as
    "active" if only the current state is looked at."""
    _systemctl(monkeypatch, {"LoadState": "loaded", "UnitFileState": "enabled",
                             "ActiveState": "activating",
                             "SubState": "auto-restart", "NRestarts": "37"})
    r = doctor.Report()
    doctor.check_service(r)
    running = [f for f in r.findings if f.check == "service running"][0]
    assert running.verdict == doctor.FAILED
    assert "37 restarts" in running.detail and "loop" in running.detail


#: The journal a user manager actually writes when a unit asks for a group
#: it cannot be given. Captured verbatim from `systemd-run --user
#: --property=SupplementaryGroups=...` on 2026-09-03, both in-group and
#: out-of-group — they are IDENTICAL, which is the whole point.
EPERM_JOURNAL = (
    "Started spectra-capture-client.service - SPECTRA capture client.\n"
    "(python3)[3154419]: spectra-capture-client.service: Changing group "
    "credentials failed: Operation not permitted\n"
    "spectra-capture-client.service: Main process exited, code=exited, "
    "status=216/GROUP\n"
    "spectra-capture-client.service: Failed with result 'exit-code'.\n")

#: A 216 that is NOT the privilege case: systemd could make the call and
#: could not resolve the group.
MEMBERSHIP_JOURNAL = (
    "spectra-capture-client.service: Changing group credentials failed: "
    "No such process\n"
    "spectra-capture-client.service: Main process exited, code=exited, "
    "status=216/GROUP\n")


def _failed_216(monkeypatch, journal):
    _systemctl(monkeypatch, {"LoadState": "loaded", "UnitFileState": "enabled",
                             "ActiveState": "failed", "SubState": "failed",
                             "Result": "exit-code", "ExecMainStatus": "216",
                             "journal": journal})
    r = doctor.Report()
    doctor.check_service(r)
    return [f for f in r.findings if f.check == "exit status"][0]


def test_216_eperm_is_the_privilege_cause_not_the_membership_one(monkeypatch):
    """THE SECOND EVENING (2026-09-03). `216/GROUP` has TWO causes and the
    status code cannot tell them apart. When the journal says 'Operation not
    permitted' the MANAGER was refused the call outright — an unprivileged
    `systemd --user` cannot change group credentials at all, so MEMBERSHIP
    IS IRRELEVANT and a member fails identically.

    The old reading collapsed this into "you are not in the group", which is
    how the owner was sent to `usermod` and a REBOOT, twice, for a fault
    neither could touch: he was already a member and had already rebooted."""
    f = _failed_216(monkeypatch, EPERM_JOURNAL)
    assert f.verdict == doctor.FAILED
    assert "Operation not permitted" in f.detail
    assert "NOT about membership" in f.detail
    assert "SupplementaryGroups" in f.fix and "daemon-reload" in f.fix
    assert "NO REBOOT" in f.fix.upper()
    assert "usermod" not in f.fix, \
        "the advice that cost two reboots must not be reachable from here"


def test_216_without_eperm_is_still_the_membership_reading(monkeypatch):
    """The other cause keeps the verdict it always had. Naming one of them
    is only worth anything if the other stays distinguishable."""
    f = _failed_216(monkeypatch, MEMBERSHIP_JOURNAL)
    assert f.verdict == doctor.FAILED
    assert "216/GROUP" in f.detail
    assert "not the manager's privilege" in f.detail
    assert "usermod -aG video" in f.fix and "REBOOT" in f.fix


def test_216_with_no_readable_journal_names_neither_cause(monkeypatch):
    """"We could not check" is never "we checked". With no reason line the
    doctor says WHICH question is unanswered and how to answer it, rather
    than picking the cause that happens to be more common."""
    f = _failed_216(monkeypatch, "")
    assert f.verdict == doctor.FAILED
    assert "could not be read" in f.detail
    assert "WHICH of the two causes" in f.detail
    assert "grep -n SupplementaryGroups" in f.fix


def test_the_216_translation_reads_the_journal_and_not_the_number(monkeypatch):
    """THE PROPERTY, PINNED. Same status, opposite journals, different
    verdicts — so nothing here can go back to deciding from the code alone.

    This is also the RED PROOF for the fix: the pre-2026-09-03 translation
    was a dict lookup on `ExecMainStatus` with no journal argument at all,
    and would answer these two identically."""
    eperm = _failed_216(monkeypatch, EPERM_JOURNAL)
    member = _failed_216(monkeypatch, MEMBERSHIP_JOURNAL)
    assert eperm.detail != member.detail and eperm.fix != member.fix
    assert doctor.read_216_cause(EPERM_JOURNAL) == doctor.CAUSE_PRIVILEGE
    assert doctor.read_216_cause(MEMBERSHIP_JOURNAL) == doctor.CAUSE_MEMBERSHIP
    assert doctor.read_216_cause("") is None


def test_an_unrelated_eperm_elsewhere_does_not_promote_the_cause():
    """ONLY THE LINE THAT NAMES THE FAILURE IS JUDGED. Sixty lines of
    journal will contain "permission denied" for all sorts of reasons, and
    letting any of them decide would turn a real membership fault into
    advice to delete a directive that is not there."""
    noisy = ("some-helper: open /dev/thing: Operation not permitted\n"
             + MEMBERSHIP_JOURNAL)
    assert doctor.read_216_cause(noisy) == doctor.CAUSE_MEMBERSHIP


# ── THE STALE LAST-ERROR GHOST ─────────────────────────────────────────────
#
# Found live 2026-09-03: after the owner fixed his host and the service came
# up and SPECTRA could see it, the doctor STILL headlined `last error` as a
# problem, quoting a failure from BEFORE the fix. A journal read with no
# clock cannot tell a scar from a wound, and the one tool whose whole point
# is that he stops being the messenger had him pasting a message about a
# machine that was working.

_HEALTHY = {"LoadState": "loaded", "UnitFileState": "enabled",
            "ActiveState": "active", "SubState": "running", "NRestarts": "0",
            "ActiveEnterTimestamp": "Thu 2026-09-03 09:00:00 EDT",
            "ActiveEnterTimestampMonotonic": "900000000"}     # 900.0 s


def _last_error(monkeypatch, answers):
    merged = dict(_HEALTHY)
    merged.update(answers)
    _systemctl(monkeypatch, merged)
    r = doctor.Report()
    doctor.check_service(r)
    return r, [f for f in r.findings if f.check == "last error"][0]


def test_a_healthy_service_with_only_OLD_failures_reports_zero_problems(
        monkeypatch):
    """THE RED CASE, AND THE BAR. A unit that is up right now, whose journal
    still carries everything it went through on the way there, must report
    NO problems at all. It reported one, for hours, on a machine that was
    working."""
    r, last = _last_error(monkeypatch, {
        "journal": EPERM_JOURNAL,
        # `-o short-monotonic`: everything at 800s, the start at 900s.
        "journal_monotonic":
            "[  800.100000] host systemd[1]: Changing group credentials "
            "failed: Operation not permitted\n"
            "[  800.200000] host systemd[1]: Main process exited, "
            "status=216/GROUP\n"
            "[  900.000100] host systemd[1]: Started SPECTRA capture "
            "client.\n"})
    assert last.verdict == doctor.UNKNOWN
    assert "FAILED EARLIER" in last.detail
    # STILL QUOTED. History is kept, never hidden — it says what this
    # machine went through, it just is not a fault now.
    assert "216/GROUP" in last.detail or "exit-code" in last.detail
    assert r.failures == [], \
        f"a healthy service must report zero problems, got {r.failures}"


def test_a_failure_since_the_last_start_is_still_IS_FAILING(monkeypatch):
    """THE OTHER DIRECTION, AND IT MATTERS MORE. Downgrading a live failure
    to history would be a doctor that tells him everything is fine while his
    camera is not working — strictly worse than the ghost it replaced."""
    r, last = _last_error(monkeypatch, {
        "journal": "the client cannot open /dev/video0\n",
        "journal_monotonic":
            "[  900.000100] host systemd[1]: Started SPECTRA capture "
            "client.\n"
            "[  905.000000] host python3[9]: the client cannot open "
            "/dev/video0\n"})
    assert last.verdict == doctor.FAILED
    assert "IS FAILING" in last.detail
    assert last in r.failures


def test_a_stopped_service_never_gets_the_historical_reading(monkeypatch):
    """FAILED EARLIER is a claim about a service that is UP. A unit that is
    down has no "since it came up" to measure against, so its journal is
    read exactly as it always was."""
    r, last = _last_error(monkeypatch, {
        "ActiveState": "failed", "SubState": "failed",
        "journal": EPERM_JOURNAL,
        "journal_monotonic": "[  800.100000] host systemd[1]: boom failed\n"})
    assert last.verdict == doctor.FAILED
    assert "IS FAILING" in last.detail


def test_an_unreadable_clock_keeps_the_failure_rather_than_excusing_it(
        monkeypatch):
    """A DOCTOR MAY NOT EXCUSE A FAILURE WITH A CHECK IT COULD NOT MAKE. If
    the monotonic window comes back empty or unparseable, the error stands —
    the safe direction is over-reporting, and it is the only direction that
    cannot leave him with a dark room and a clean bill of health."""
    for mono in ("", "no timestamps here at all\n"):
        r, last = _last_error(monkeypatch, {"journal": EPERM_JOURNAL,
                                            "journal_monotonic": mono})
        assert last.verdict == doctor.FAILED, mono
        assert "IS FAILING" in last.detail


def test_the_boundary_is_microseconds_not_seconds(monkeypatch):
    """WHY THE MONOTONIC CLOCK AND NOT `--since`. `ActiveEnterTimestamp` is
    a wall-clock string with SECOND granularity, so a unit that failed and
    restarted inside the same second — which is what `Restart=` does — puts
    its old failure inside the window and reads as current. Here the failure
    is 200us before the start, and it is still history."""
    r, last = _last_error(monkeypatch, {
        "journal": EPERM_JOURNAL,
        "journal_monotonic":
            "[  899.999800] host systemd[1]: Failed with result "
            "'exit-code'.\n"
            "[  900.000000] host systemd[1]: Started SPECTRA capture "
            "client.\n"})
    assert last.verdict == doctor.UNKNOWN
    assert "FAILED EARLIER" in last.detail
    assert r.failures == []


def test_the_ghost_harness_goes_RED_on_the_defect_it_was_written_for(
        monkeypatch):
    """A PROOF BAR THAT CANNOT FAIL ON ITS OWN DEFECT IS DECORATION.

    The pre-fix `_add_last_error` had no clock at all: any error line
    anywhere in the journal was a current failure. That is exactly
    `_errors_predate_start` never returning True, so pinning it there
    reproduces the shipped behaviour — and the bar above must go red."""
    monkeypatch.setattr(doctor, "_errors_predate_start",
                        lambda *a, **kw: False)
    r, last = _last_error(monkeypatch, {
        "journal": EPERM_JOURNAL,
        "journal_monotonic":
            "[  800.100000] host systemd[1]: Changing group credentials "
            "failed: Operation not permitted\n"
            "[  900.000100] host systemd[1]: Started SPECTRA capture "
            "client.\n"})
    assert last.verdict == doctor.FAILED
    assert r.failures != [], \
        "with the pre-fix behaviour restored, a healthy machine reports a " \
        "problem — which is the defect, and which the bar above catches"


def test_the_216_harness_goes_RED_on_the_defect_it_was_written_for():
    """THE SAME BAR FOR THE OTHER FIX. The pre-2026-09-03 translation was a
    dict lookup on the exit status with no journal in it at all. Reproduced
    here, it answers the two opposite journals IDENTICALLY — which is what
    made a directive fault indistinguishable from a membership one, and what
    sent the owner to `usermod` and a reboot for neither."""
    old_reading = ("216/GROUP — the unit asks for group 'video' and the user "
                   "manager does not hold it.",
                   "sudo usermod -aG video $(id -un), then REBOOT")

    def old_translate(_journal_text):
        return old_reading          # the number was the whole input

    assert old_translate(EPERM_JOURNAL) == old_translate(MEMBERSHIP_JOURNAL)
    assert "usermod" in old_translate(EPERM_JOURNAL)[1] and \
        "REBOOT" in old_translate(EPERM_JOURNAL)[1], \
        "and its advice for the privilege case was the reboot that could " \
        "never work"
    # The shipped one does not.
    assert doctor.read_216_cause(EPERM_JOURNAL) != \
        doctor.read_216_cause(MEMBERSHIP_JOURNAL)


def test_the_units_own_last_error_line_is_carried(monkeypatch):
    _systemctl(monkeypatch, {
        "LoadState": "loaded", "UnitFileState": "enabled",
        "ActiveState": "active", "SubState": "running", "NRestarts": "0",
        "journal": "starting up\nsomething ordinary\n"
                   "ERROR camera: /dev/video0 does not exist\n"})
    r = doctor.Report()
    doctor.check_service(r)
    last = [f for f in r.findings if f.check == "last error"][0]
    assert "/dev/video0 does not exist" in last.detail


# ── does the server see this machine ───────────────────────────────────────

def _server(monkeypatch, camera_host):
    monkeypatch.setattr(doctor, "_get_json",
                        lambda url, timeout=0: (200, {"camera_host": camera_host}, ""))


def test_the_server_seeing_a_different_machine_is_named(monkeypatch):
    """THE BROWSER-TAB SHAPE. Another client holds the session and this one
    silently never gets it — one of the eight, and invisible from either
    side alone."""
    _server(monkeypatch, {"state": "present", "client": {"host": "his-phone"},
                          "sentence": "A browser session on his-phone is connected."})
    r = doctor.Report()
    doctor.check_server_sees_us(r, "http://s/spectra", "camera-pi")
    f = r.findings[0]
    assert f.verdict == doctor.FAILED
    assert "'his-phone', not this machine" in f.detail
    assert "browser tab" in f.fix


def test_impaired_reaches_the_doctor_as_a_failure(monkeypatch):
    _server(monkeypatch, {"state": "impaired", "client": {"host": "camera-pi"},
                          "unable": "no camera",
                          "sentence": "connected but cannot do the job: no camera"})
    r = doctor.Report()
    doctor.check_server_sees_us(r, "http://s/spectra", "camera-pi")
    assert r.findings[0].verdict == doctor.FAILED
    assert "cannot do the job" in r.findings[0].detail


def test_never_seen_is_distinct_from_gone(monkeypatch):
    _server(monkeypatch, {"state": "never", "client": None,
                          "sentence": "No capture client has ever connected."})
    r = doctor.Report()
    doctor.check_server_sees_us(r, "http://s/spectra", "camera-pi")
    assert "NEVER seen" in r.findings[0].detail


def test_a_server_that_cannot_be_asked_is_unknown(monkeypatch):
    monkeypatch.setattr(doctor, "_get_json",
                        lambda url, timeout=0: (0, None, "ConnectError: refused"))
    r = doctor.Report()
    doctor.check_server_sees_us(r, "http://s/spectra", "camera-pi")
    assert r.findings[0].verdict == doctor.UNKNOWN
    assert r.failures == []


# ── the installer's bounded wait ───────────────────────────────────────────

def test_await_hello_reports_a_real_connection_with_its_lever_verdict(monkeypatch):
    """CONNECTED IS THE ONLY SUCCESS, and it still separates two claims: the
    machine is there, and its exposure lever was measured to actually work.
    An install that collapsed those would be the same class of overclaim it
    was written to remove."""
    _server(monkeypatch, {"state": "present",
                          "client": {"host": "camera-pi", "version": "1.0",
                                     "pose_name": "the north shelf",
                                     "locked": True, "camera": {"device": "/dev/video0"},
                                     "lever": {"verdict": "ok", "reason": "light moved"}}})
    code, text = doctor.await_hello("http://s/spectra", "camera-pi",
                                    timeout_s=1, sleep=lambda s: None)
    assert code == 0
    assert "CONNECTED" in text and "camera-pi (the north shelf)" in text
    assert "lever self-test: ok" in text


def test_await_hello_never_claims_a_connection_it_did_not_see(monkeypatch):
    """THE DEFECT, PINNED. The installer used to print "SPECTRA can now SEE
    this machine" while installing a service that could not start."""
    _server(monkeypatch, {"state": "never", "client": None, "sentence": "none"})
    _systemctl(monkeypatch, {"LoadState": "loaded", "UnitFileState": "enabled",
                             "ActiveState": "failed", "SubState": "failed",
                             "Result": "exit-code", "ExecMainStatus": "216",
                             "journal": EPERM_JOURNAL})
    code, text = doctor.await_hello("http://s/spectra", "camera-pi",
                                    timeout_s=0, sleep=lambda s: None)
    assert code == 1
    assert "never saw this machine" in text
    assert "216/GROUP" in text, "and the unit's own reason is carried up"


def test_await_hello_distinguishes_a_running_service_from_an_unreachable_one(
        monkeypatch):
    """THE ONE STRUCTURALLY SILENT CASE. A client that cannot reach the
    server is invisible from the server side by construction — so when the
    service IS up and SPECTRA IS answering and nothing arrived, that has to
    be said as its own thing rather than blamed on either end."""
    _server(monkeypatch, {"state": "never", "client": None, "sentence": "none"})
    _systemctl(monkeypatch, {"LoadState": "loaded", "UnitFileState": "enabled",
                             "ActiveState": "active", "SubState": "running",
                             "NRestarts": "0", "journal": "started"})
    code, text = doctor.await_hello("http://s/spectra", "camera-pi",
                                    timeout_s=0, sleep=lambda s: None)
    assert code == 1
    assert "RUNNING" in text and "ANSWERING" in text
    assert "journalctl" in text


# ── boundaries ─────────────────────────────────────────────────────────────

def test_the_doctor_is_stdlib_only(monkeypatch):
    """IT HAS TO WORK WHEN THE VIRTUALENV IS THE BROKEN THING — a venv with
    no pip in it was two of the eight failures, and a doctor that needed
    `httpx` would have been unavailable in exactly that case. Proven by
    IMPORTING it with the client's own two dependencies blocked."""
    import importlib
    blocked = {"httpx", "websockets"}

    class Blocker:
        def find_module(self, name, path=None): return self.find_spec(name, path)

        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in blocked:
                raise ImportError(f"{name} is blocked by this test")
            return None

    for mod in [m for m in sys.modules if m.startswith("spectra.capture_client")]:
        del sys.modules[mod]
    blocker = Blocker()
    sys.meta_path.insert(0, blocker)
    try:
        spec = importlib.util.spec_from_file_location(
            "_doctor_isolated", REPO / "spectra" / "capture_client" / "doctor.py")
        mod = importlib.util.module_from_spec(spec)
        # `@dataclass` resolves annotations through `sys.modules[__module__]`
        # while the module body runs, so it has to be registered first.
        sys.modules["_doctor_isolated"] = mod
        spec.loader.exec_module(mod)
        # And it must WORK, not merely import: the address reading is the
        # part the installer runs before anything is built.
        r = mod.Report()
        mod.check_url(r, "http://127.0.0.1:1/spectra")
        assert any(f.verdict == mod.FAILED for f in r.findings)
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.pop("_doctor_isolated", None)


def test_the_doctor_fixes_nothing_and_starts_nothing():
    """IT IS AN INSTRUMENT, NOT A SECOND INSTALLER. Every failure names a
    command and stops. A doctor that repaired things would be unwatched
    machinery, which is how this evening produced confident wrong answers in
    the first place."""
    src = (REPO / "spectra" / "capture_client" / "doctor.py").read_text()
    body = re.sub(r'"""(?:.|\n)*?"""', "", src)          # docstrings out
    for verb in ("usermod", "apt install", "rm -rf", "systemctl --user start",
                 "systemctl --user restart", "enable --now"):
        for line in body.splitlines():
            if verb in line and "_run(" in line:
                raise AssertionError(f"the doctor would run {verb!r}: {line}")
    # The only subprocesses it may spawn are READS.
    calls = re.findall(r"_run\(\[([^\]]*)\]", body)
    allowed = {'"id"', '"systemctl"', '"journalctl"', 'sys.executable',
               'python', '"-m"', '"-c"'}
    for call in calls:
        head = call.split(",")[0].strip()
        assert head in allowed, f"the doctor spawns {head}"


def test_the_doctor_takes_no_room_authority():
    """The same structural boundary every other file in this package holds:
    a camera host's diagnostic may not reach a light, an ownership record or
    a handover."""
    src = (REPO / "spectra" / "capture_client" / "doctor.py").read_text()
    for name in ("fx_seam", "light_ownership", "handover", "fx.devices",
                 "flare_preview_hold", "room_effects", "scene_compiler",
                 "drift_conductor", "ledfx"):
        assert name not in src, f"doctor.py mentions {name}"
    for m in re.finditer(r"^\s*(?:from|import)\s+(spectra[\w.]*)", src, re.M):
        assert m.group(1).startswith("spectra.capture_client"), m.group(1)
