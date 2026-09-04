"""A SELF-TAKEN NIGHT ORPHANED BY A CRASH — found at the cold start, given
back before anything re-lights.

THE GAP THIS CLOSES, and Captain DJ owed River the name of it (the seam's
addendum 11): the night's state lives in memory with a durable record
written at every transition, so a crash mid-night leaves the DISK record
stuck at "running", the restarted process has no idea a night was ever in
flight, and NO terminal state is re-posted for the house's own re-dark to
catch. Since the self-taking build there is a fourth thing wrong with it and
it is the worst: the ownership record still says SPECTRA holds a room nobody
asked for, and `handover.resume_own_room()` — which runs on every start —
would re-activate the stack and RESUME HIS SHOW. His house coming on at 2am,
through a door the quiet take itself never opens.

SO THE ORDER IS THE PROOF. `night_run.recover_orphaned_night()` runs in
`spectra/app.py`'s lifespan BEFORE the resume, and section 1 enters the REAL
lifespan (tests/test_process_split.py's own harness: headless dummy device,
silenced audio, temp ownership record) rather than re-enacting it. Section 2
is the CONTROL — the same rig in the wrong order, proving the instrument can
see the defect. Section 3 is a genuinely FRESH INTERPRETER, per the house
cold-start discipline: nothing about a cold start is honestly provable in a
process that already has every module imported.

Nothing here touches his room, reaches a network, or runs systemctl: the
release is a fake that moves the record and does nothing else (the real
release path's own ordering is proven in tests/test_night_self_take.py).
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _run(coro):
    return asyncio.run(coro)


def _plant_orphan(tmp_path, monkeypatch, *, run_id="crashednight"):
    """The exact state a crash leaves behind: the record saying SPECTRA
    owns, the night's own record stuck at `running`, and the pre-take
    snapshot still on disk — which is the proof, since this process cannot
    be the one that wrote it."""
    from fx import light_ownership as lo
    from spectra.services import night_run, night_take

    handover = lo.begin_handover(lo.SPECTRA)
    lo.mark_quiesced(handover.token)
    lo.commit(handover.token)

    night_take.save_snapshot(run_id=run_id, owner_before=lo.RELEASED)
    # AGED, so "held for" is a real span rather than the microseconds
    # between planting and reading. His crashed night had been holding the
    # room for over an hour; the sentence he reads says so.
    snapshot = night_take.load_snapshot()
    snapshot["taken_at"] = time.time() - 4200
    night_take._atomic_write(night_take._snapshot_path(), snapshot)
    run = night_run.NightRun(
        id=run_id, state=night_run.STATE_RUNNING,
        trigger={"event": "sleep-window-start"}, started=time.time() - 4200,
        label="nightly",
        take={"self_taken": True, "owner_before": lo.RELEASED,
              "taken_at": time.time() - 4200, "quiet": True,
              "announce": [{"event": night_take.EVENT_TAKEN,
                            "at": time.time() - 4200}]})
    night_run.save_night(run)
    # The crash: this process has no live night in memory, only what is on
    # disk. That asymmetry IS the defect.
    night_run.current = None
    night_run._task = None
    return run_id


def _offline_release(monkeypatch, calls):
    """`release_room` with the record moved and nothing else — no Hue
    bridge, no external LedFX, no systemctl. The real one's behaviour is
    proven in tests/test_night_self_take.py; what this file is about is
    WHEN it happens."""
    from fx import light_ownership as lo

    async def release(reason="release"):
        calls.append(reason)
        lo.release(reason)

        class _Result:
            record = lo.load()
            from_world = lo.SPECTRA
            verified = True
            problems: list = []
        return _Result()

    monkeypatch.setattr("spectra.services.release.release_room", release)
    return calls


# ── 1. THE REAL LIFESPAN: the room goes back and the show never starts ─────

def test_the_cold_start_gives_the_room_back_before_anything_relights(
        tmp_path, monkeypatch):
    """THE HEADLINE. Enters the REAL `_standalone_lifespan` with an orphaned
    self-taken night on disk and proves the end state: released, dark, the
    engine never switched live, the night stamped and re-posted, the
    snapshot gone."""
    import functools

    from fx import headless, light_ownership as lo
    import spectra.app as spectra_app
    from spectra.services import engine, handover, night_run, night_take
    from spectra.services.live_host import live

    monkeypatch.setattr(lo, "OWNERSHIP_FILE", tmp_path / "ownership.json")
    headless.silence_audio()
    config_dir = tmp_path / "fx-live"
    headless.write_headless_config(
        str(config_dir),
        initial_effect={"type": "singleColor", "config": {"color": "#ffffff"}})
    dead = _free_port()
    monkeypatch.setattr(engine.bridge, "ws_url", f"ws://127.0.0.1:{dead}/ws")
    monkeypatch.setattr(engine.bridge, "http_url", f"http://127.0.0.1:{dead}")
    monkeypatch.setattr(handover, "SpectraSide", functools.partial(
        handover.SpectraSide, config_dir=str(config_dir), open_audio=False))
    calls: list = []
    _offline_release(monkeypatch, calls)

    run_id = _plant_orphan(tmp_path, monkeypatch)

    async def scenario():
        async with spectra_app._standalone_lifespan(None):
            # THE ROOM IS HIS AGAIN, and the resume that runs moments later
            # sees a released room and takes its own unchanged early return.
            assert lo.load().owner == lo.RELEASED, (
                "the cold start kept a room a crashed night had taken")
            assert not live.active, (
                "the crashed night's room was re-activated — this is his "
                "house coming on at 2am")
            assert engine.executor.mode == "recording", (
                "the show was resumed over a crashed night's room")
            assert calls, "the room was never released"

    _run(scenario())

    # THE PAPERWORK, re-posted so River's own re-dark fires normally.
    night = [n for n in night_run.load_nights() if n["run_id"] == run_id][0]
    assert night["state"] == night_run.STATE_FAILED
    assert night["refusal"] == "crashed"
    assert "SPECTRA restarted while it was still running" in night["detail"]
    assert night["ended"] > 0
    # BOTH ENDS OF ORDER 22 SURVIVED THE CRASH: the take was announced
    # before it, the give-back is announced now.
    events = [a["event"] for a in night["take"]["announce"]]
    assert events == [night_take.EVENT_TAKEN, night_take.EVENT_GIVEN_BACK]
    assert night["take"]["why"] == night_take.WHY_CRASH
    assert night["take"]["given_back"] is True
    # AND THE STATE IS OVER, on the one boolean River branches on.
    brief = night_run.status_brief()
    assert brief["active"] is False
    assert brief["state"] == night_run.STATE_FAILED
    assert brief["take"]["holding"] is False
    assert night_take.load_snapshot() is None


# ── 2. THE CONTROL: in the wrong order, his room comes on ──────────────────

def test_the_resume_would_relight_the_room_if_recovery_ran_after_it(
        tmp_path, monkeypatch):
    """RED-FIRST, kept in the file. Without this, section 1 could be passing
    because nothing was ever going to re-light the room. Here the resume
    runs FIRST, exactly as it would if `recover_orphaned_night()` were moved
    below it in the lifespan — and the stack comes up driving his show."""
    from fx import headless, light_ownership as lo
    from spectra.services import engine, handover
    from spectra.services.live_host import live

    monkeypatch.setattr(lo, "OWNERSHIP_FILE", tmp_path / "ownership.json")
    headless.silence_audio()
    config_dir = tmp_path / "fx-live"
    headless.write_headless_config(
        str(config_dir),
        initial_effect={"type": "singleColor", "config": {"color": "#ffffff"}})
    _plant_orphan(tmp_path, monkeypatch)

    async def scenario():
        side = handover.SpectraSide(config_dir=str(config_dir),
                                    open_audio=False)
        try:
            resumed = await handover.resume_own_room(side)
            assert resumed is True, (
                "the resume declined to re-light — this control proves "
                "nothing unless it actually would have")
            assert live.active
            assert engine.executor.mode == "facade", (
                "the resume did not switch the engine live, so section 1's "
                "assertion that it stayed dark proves nothing")
        finally:
            engine.go_dark()
            await live.deactivate()

    _run(scenario())


# ── 3. A GENUINELY FRESH INTERPRETER ───────────────────────────────────────

_COLD = r'''
import asyncio, json, os, sys, time
sys.path.insert(0, os.getcwd())
os.environ["SPECTRA_STORAGE_DIR"] = %(storage)r

import pathlib
from fx import light_ownership as lo
lo.OWNERSHIP_FILE = pathlib.Path(%(ownership)r)

from spectra.services import night_run, night_take

async def fake_release(reason="x"):
    lo.release(reason)
    class _R:
        record = lo.load(); from_world = lo.SPECTRA
        verified = True; problems = []
    return _R()

import spectra.services.release as release_mod
release_mod.release_room = fake_release

async def main():
    before = {"owner": lo.load().owner,
              "holding": night_take.holding(),
              "state": night_run.status_brief()["state"],
              "active": night_run.status_brief()["active"]}
    result = await night_run.recover_orphaned_night()
    after = {"owner": lo.load().owner,
             "holding": night_take.holding(),
             "state": night_run.status_brief()["state"],
             "active": night_run.status_brief()["active"],
             "detail": night_run.status_brief().get("detail", "")}
    return {"before": before, "after": after, "result": result,
            "nights": night_run.load_nights()}

out = asyncio.run(main())
sys.stdout.write("RESULT " + json.dumps(out) + "\n")
sys.stdout.flush(); sys.stderr.flush()
os._exit(0)
'''


def test_a_fresh_interpreter_finds_the_orphan_and_lands_it(tmp_path,
                                                           monkeypatch):
    """THE COLD-START DISCIPLINE. A warm pytest process has already imported
    every module involved and has module globals from other tests; a fresh
    interpreter has neither, which is the only honest way to say "the
    process that comes back after the crash does the right thing".

    It also proves the import itself is clean in this order —
    `night_run` imports `night_take` at module scope and `night_take`
    reaches `night_run` only lazily, inside the recovery, precisely so this
    cannot become a circular-import failure at startup."""
    from fx import light_ownership as lo
    from spectra import config as scfg
    from spectra.services import night_run, night_take

    storage = tmp_path / "storage"
    (storage).mkdir(parents=True, exist_ok=True)
    ownership = tmp_path / "ownership.json"
    monkeypatch.setattr(lo, "OWNERSHIP_FILE", ownership)
    monkeypatch.setattr(scfg, "NIGHT_RUNS_FILE", storage / "night_runs.json")
    monkeypatch.setattr(scfg, "NIGHT_TAKE_FILE", storage / "night_take.json")
    monkeypatch.setattr(scfg, "NIGHT_QUEUE_FILE", storage / "night_queue.json")
    run_id = _plant_orphan(tmp_path, monkeypatch)

    script = _COLD % {"storage": str(storage), "ownership": str(ownership)}
    proc = subprocess.run([sys.executable, "-c", script], cwd=REPO,
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(next(ln for ln in proc.stdout.splitlines()
                          if ln.startswith("RESULT "))[len("RESULT "):])

    # The state the crashed process left behind, seen by a process that was
    # not there for any of it.
    assert out["before"] == {"owner": lo.SPECTRA, "holding": True,
                             "state": night_run.STATE_RUNNING,
                             "active": True}
    # And what it did about it.
    assert out["after"]["owner"] == lo.RELEASED
    assert out["after"]["holding"] is False
    assert out["after"]["state"] == night_run.STATE_FAILED
    assert out["after"]["active"] is False, (
        "the terminal state was not re-posted — River's re-dark rides this "
        "boolean and would never fire")
    assert out["result"]["recovered"] is True
    assert out["result"]["run_id"] == run_id
    assert out["result"]["held_for_s"] > 4000
    assert out["result"]["give_back"]["given_back"] is True
    night = [n for n in out["nights"] if n["run_id"] == run_id][0]
    assert night["refusal"] == "crashed"


# ── 4. THE THINGS RECOVERY MUST *NOT* DO ───────────────────────────────────

def test_an_ordinary_start_with_nothing_on_disk_is_a_no_op(monkeypatch):
    """Every ordinary start reaches this, so it has to be free and it has to
    be silent."""
    from spectra.services import night_run, night_take

    assert night_take.load_snapshot() is None
    result = _run(night_run.recover_orphaned_night())
    assert result == {"recovered": False, "run_id": "", "held_for_s": 0.0,
                      "detail": "", "give_back": {}, "night": {}}


def test_a_night_that_ended_properly_is_never_restamped_as_crashed(
        tmp_path, monkeypatch):
    """A night that was ended properly and then crashed something else has
    already said what it was. Overwriting a true ending with "crashed" would
    replace a fact with a guess."""
    from fx import light_ownership as lo
    from spectra.services import night_run, night_take

    monkeypatch.setattr(lo, "OWNERSHIP_FILE", tmp_path / "ownership.json")
    _offline_release(monkeypatch, [])
    _plant_orphan(tmp_path, monkeypatch, run_id="endednight")
    # ... but the record was already stamped by his morning routine.
    nights = night_run.load_nights()
    nights[-1]["state"] = night_run.STATE_ENDED_BY_MORNING
    nights[-1]["detail"] = "The night run ended with his morning routine."
    night_run._atomic_write(night_run._runs_path(), {"nights": nights})
    night_run._disk_cache.update({"key": None, "night": None})

    _run(night_run.recover_orphaned_night())

    night = night_run.load_nights()[-1]
    assert night["state"] == night_run.STATE_ENDED_BY_MORNING
    assert night["refusal"] != "crashed"
    # The ROOM still went back — that half is unconditional.
    assert lo.load().owner == lo.RELEASED
    assert night_take.load_snapshot() is None


def test_a_snapshot_naming_a_night_nobody_recorded_still_gives_the_room_back(
        tmp_path, monkeypatch):
    """The crash landed between the snapshot write and the night's own first
    save. There is no record to stamp and inventing one would be inventing a
    night — but the room is the load-bearing half and it goes back anyway."""
    from fx import light_ownership as lo
    from spectra.services import night_run, night_take

    monkeypatch.setattr(lo, "OWNERSHIP_FILE", tmp_path / "ownership.json")
    calls: list = []
    _offline_release(monkeypatch, calls)
    handover = lo.begin_handover(lo.SPECTRA)
    lo.mark_quiesced(handover.token)
    lo.commit(handover.token)
    night_take.save_snapshot(run_id="never-recorded", owner_before=lo.RELEASED)

    result = _run(night_run.recover_orphaned_night())

    assert result["recovered"] is True
    assert result["night"] == {}
    assert calls, "the room was kept because there was no paperwork for it"
    assert lo.load().owner == lo.RELEASED
    assert night_take.load_snapshot() is None


def test_a_snapshot_that_will_not_parse_still_gives_the_room_back(
        tmp_path, monkeypatch):
    """THE ROOM OUTRANKS THE PAPERWORK. A snapshot that will not parse — a
    truncated disk, a hand-edited file — is still proof that a night took
    his room. Refusing to hand it back over a JSON error would keep his room
    held for exactly the reason nobody would ever guess."""
    from fx import light_ownership as lo
    from spectra import config as scfg
    from spectra.services import night_run, night_take

    monkeypatch.setattr(lo, "OWNERSHIP_FILE", tmp_path / "ownership.json")
    calls: list = []
    _offline_release(monkeypatch, calls)
    handover = lo.begin_handover(lo.SPECTRA)
    lo.mark_quiesced(handover.token)
    lo.commit(handover.token)
    Path(scfg.NIGHT_TAKE_FILE).write_text("{this is not json")

    assert night_take.holding() is True
    assert night_take.load_snapshot() is None, "the fixture is not corrupt"

    result = _run(night_run.recover_orphaned_night())

    assert result["recovered"] is True
    assert result["run_id"] == ""
    assert calls, "an unreadable snapshot kept his room"
    assert lo.load().owner == lo.RELEASED
    assert night_take.load_snapshot() is None
    assert night_take.holding() is False


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
