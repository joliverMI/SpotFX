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


def test_not_a_member_is_the_216_group_case(monkeypatch):
    """THE EVENING'S FAILURE. The unit declares SupplementaryGroups=video;
    without membership systemd will not start it at all. The refusal must
    name the exit status, the usermod line AND the reboot, and it must say
    why a READABLE device was never evidence of this — or the neighbouring
    question gets asked again."""
    _fake_group_env(monkeypatch, groups="javi sudo docker",
                    manager_pid=1292, manager_groups=[1000])
    r = doctor.Report()
    doctor.check_video_group(r, user="javi")
    f = r.findings[0]
    assert f.verdict == doctor.FAILED
    assert "216/GROUP" in f.detail
    assert "READABLE" in f.detail and "ACL" in f.detail
    assert "usermod -aG video javi" in f.fix and "REBOOT" in f.fix


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
    assert "can start" in r.findings[1].detail


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


def test_exit_216_is_translated_into_the_group(monkeypatch):
    """`status=216/GROUP` in a journal is not a sentence anybody can act on,
    and it is exactly the line that sat in his journal all evening saying
    nothing to anyone."""
    _systemctl(monkeypatch, {"LoadState": "loaded", "UnitFileState": "enabled",
                             "ActiveState": "failed", "SubState": "failed",
                             "Result": "exit-code", "ExecMainStatus": "216"})
    r = doctor.Report()
    doctor.check_service(r)
    status = [f for f in r.findings if f.check == "exit status"][0]
    assert "216/GROUP" in status.detail
    assert "SupplementaryGroups" in status.detail or "group 'video'" in status.detail
    assert "usermod -aG video" in status.fix and "REBOOT" in status.fix


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
                             "Result": "exit-code", "ExecMainStatus": "216"})
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
