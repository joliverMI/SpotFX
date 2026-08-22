"""The AV-sync session end to end against the simulated room that
scripts/check_av_sync.py defines (ONE simulator, shared), plus the
pattern driver's room-safety contract, the clock map, the frame seam and
the privacy property (nothing on disk but the measurement record).

Everything runs on a fake clock through the REAL Session / PatternDriver
/ AudioReference / correlator code with fake seams — no hardware, no
live storage, no network."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_av_sync.py"
_spec = importlib.util.spec_from_file_location("check_av_sync", _SCRIPT)
sim = importlib.util.module_from_spec(_spec)
sys.modules["check_av_sync"] = sim      # dataclasses + future annotations need it registered
_spec.loader.exec_module(sim)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import av_sync_session as sessions
    from spectra.services import preview_pause
    monkeypatch.setattr(scfg, "AV_SYNC_MEASUREMENTS_FILE", tmp_path / "av_sync_measurements.json")
    monkeypatch.setattr(scfg, "AV_SYNC_PATTERN_FILE", tmp_path / "av_sync_pattern.json")
    sessions.current = None
    preview_pause.clear()
    yield tmp_path
    preview_pause.clear()
    sessions.current = None


# ── 1. THE NUMBER — the whole point ───────────────────────────────────────

def test_simulated_room_measures_the_av_offset_with_a_statement(tmp_path):
    room = sim.SimRoom()
    result = asyncio.run(sim.run_room(room, storage_dir=tmp_path, verbose=False))
    est = result["estimate"]
    assert est["ok"], est
    # truth −320 ms; the three NAMED systematics (+½ frame, +½ rise, +hub
    # input latency) put the expected reading at −273.3 — within its own
    # stated statistical tolerance plus a small modelling margin
    sim.check(result, room)
    assert est["av_offset_ms"] < 0 and "AHEAD" in est["statement"]
    # the correlator keeps the strongest detection: here the whole-frame
    # mean and grid region 5 (the one that IS the light) both see it
    assert est["light_region"] in ("mean", "region5")
    assert est["clock"]["rtt_ms"] == pytest.approx(12.0, abs=0.5)
    assert est["systematic_later_ms"] > 0 and est["systematic_earlier_ms"] > 0
    assert any("exposure" in t["term"] for t in est["systematics"])
    # the exposure bound follows the phone's reported fps (30 → 16.7)
    exp = [t for t in est["systematics"] if "exposure" in t["term"]][0]
    assert exp["bound_ms"] == pytest.approx(16.7, abs=0.1)


def test_lights_behind_reads_positive_and_says_behind(tmp_path):
    room = sim.SimRoom(light_latency_s=0.150, audio_path_s=0.040, fps=60, seed=11)
    result = asyncio.run(sim.run_room(room, storage_dir=tmp_path, verbose=False))
    sim.check(result, room)
    assert result["estimate"]["av_offset_ms"] > 0
    assert "BEHIND" in result["estimate"]["statement"]


def test_large_phone_clock_offset_cancels_in_the_difference(tmp_path):
    room = sim.SimRoom(phone_clock_offset_s=-86400.5, rtt_s=0.040, seed=9)
    result = asyncio.run(sim.run_room(room, storage_dir=tmp_path, verbose=False))
    sim.check(result, room)
    assert result["estimate"]["clock"]["phone_minus_server_ms"] == pytest.approx(-86400500.0, abs=25)


# ── 2. PRIVACY — the only thing on disk is the record, and it has no media ──

def test_only_the_measurement_record_is_written_and_it_carries_no_media(tmp_path):
    room = sim.SimRoom()
    result = asyncio.run(sim.run_room(room, storage_dir=tmp_path, verbose=False))
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["av_sync_measurements.json"], files
    recs = json.loads((tmp_path / "av_sync_measurements.json").read_text())["measurements"]
    assert len(recs) == 1
    rec = recs[0]
    assert rec["final"] is True and rec["ok"] is True
    assert rec["av_offset_ms"] == result["estimate"]["av_offset_ms"]
    flat = json.dumps(rec)
    for forbidden in ('"v":', '"lum":', '"data":', '"grid":', '"t_ms":'):
        assert forbidden not in flat, f"media/stream key {forbidden} leaked into the record"
    assert rec["phone"]["user_agent"] == "sim-phone"
    assert "statement" in rec and "systematic_bound_ms" in rec


def test_measurements_file_is_bounded():
    from spectra.services import av_sync_session as s
    for i in range(s.MEASUREMENTS_KEEP + 7):
        s.append_measurement({"id": i})
    recs = s.load_measurements()
    assert len(recs) == s.MEASUREMENTS_KEEP and recs[0]["id"] == 7


# ── 3. The pattern driver's room-safety contract ──────────────────────────

def test_pattern_driver_snapshots_flashes_and_reverts_exactly(tmp_path):
    from spectra import config as scfg
    from spectra.services import preview_pause
    from spectra.services.av_sync_pattern import (PATTERN_EFFECT_TYPE, PatternDriver,
                                                  REVERT_TRANSITION_MS)

    async def main():
        ft = sim.FakeTime()
        seam = sim.FakeSeam(ft, {
            "a": {"active": True, "effect": {"type": "blackhole", "config": {"brightness": 0.4, "x": 1}}},
            "b": {"active": True, "effect": {"type": "orbits1d", "config": {}}},
            "off": {"active": False, "effect": {"type": "power", "config": {}}},
            "bare": {"active": True, "effect": {}},
        })
        drv = PatternDriver(get_virtuals=seam.get_virtuals, apply_writes=seam.apply_writes,
                            clock=ft.now, sleep=ft.sleep)
        edges_seen = []
        run = await drv.start(duration_s=4.0, seed=5, on_edge=lambda t, s: edges_seen.append((t, s)))
        assert drv.active and preview_pause.active()
        assert scfg.AV_SYNC_PATTERN_FILE.exists()
        snap = json.loads(scfg.AV_SYNC_PATTERN_FILE.read_text())["snapshot"]
        assert set(snap) == {"a", "b"}           # inactive / effect-less virtuals untouched
        for _ in range(5000):
            if run.done:
                break
            await asyncio.sleep(0)
        assert run.done and not run.aborted
        # first write: the one type switch; then brightness-only edges; last: the revert
        first = seam.writes[0][1]
        assert all(w["effect_type"] == PATTERN_EFFECT_TYPE for w in first)
        assert {w["virtual_id"] for w in first} == {"a", "b"}
        assert len(run.edges) == len(edges_seen) >= 8
        for t, s in run.edges:
            assert s in (0, 1)
        assert all(1 <= w[2] for w in seam.writes[1:-1])      # edges land as 1 ms jumps
        last_t, last_writes, last_tr = seam.writes[-1]
        assert last_tr == REVERT_TRANSITION_MS
        assert {(w["virtual_id"], w["effect_type"], json.dumps(w["config"], sort_keys=True))
                for w in last_writes} == {
            ("a", "blackhole", json.dumps({"brightness": 0.4, "x": 1}, sort_keys=True)),
            ("b", "orbits1d", "{}")}
        assert seam.virtuals["off"]["effect"]["type"] == "power"   # never written
        assert not drv.active and not preview_pause.active()
        assert not scfg.AV_SYNC_PATTERN_FILE.exists()
        # hold durations are random within bounds
        holds = np.diff([t for t, _ in run.edges])
        assert holds.min() > 0.14 and holds.max() < 0.46

    asyncio.run(main())


def test_pattern_stop_mid_run_reverts_and_clears(tmp_path):
    from spectra.services import preview_pause
    from spectra.services.av_sync_pattern import PatternDriver

    async def main():
        ft = sim.FakeTime()
        seam = sim.FakeSeam(ft, {"a": {"active": True, "effect": {"type": "radial", "config": {"spin": 0.5}}}})
        drv = PatternDriver(get_virtuals=seam.get_virtuals, apply_writes=seam.apply_writes,
                            clock=ft.now, sleep=ft.sleep)
        run = await drv.start(duration_s=30.0, seed=1)
        for _ in range(6):
            await asyncio.sleep(0)
        assert not run.done
        await drv.stop()
        assert run.aborted and run.done
        assert seam.virtuals["a"]["effect"] == {"type": "radial", "config": {"spin": 0.5}}
        assert not preview_pause.active() and not drv.active

    asyncio.run(main())


def test_recover_stale_pattern_lands_a_leftover_snapshot(tmp_path):
    from spectra import config as scfg
    from spectra.services import av_sync_pattern as p
    scfg.AV_SYNC_PATTERN_FILE.write_text(json.dumps({"snapshot": {
        "a": {"type": "blackhole", "config": {"brightness": 0.3}}}}))
    landed = []

    async def fake_apply(writes, *, transition_ms):
        landed.append((writes, transition_ms))

    assert asyncio.run(p.recover_stale_pattern(apply_writes=fake_apply)) is True
    assert landed == [([{"virtual_id": "a", "effect_type": "blackhole",
                         "config": {"brightness": 0.3}}], p.REVERT_TRANSITION_MS)]
    assert not scfg.AV_SYNC_PATTERN_FILE.exists()
    assert asyncio.run(p.recover_stale_pattern(apply_writes=fake_apply)) is False


# ── 4. Clock map + frame seam ─────────────────────────────────────────────

def test_clock_map_picks_min_rtt_sample():
    from spectra.services.av_sync_session import ClockMap
    cm = ClockMap()
    assert not cm.ready
    cm.add(100.0, (100.0 + 0.050 + 7.0) * 1000, 100.100)     # rtt 100 ms
    cm.add(200.0, (200.0 + 0.005 + 7.0) * 1000, 200.010)     # rtt 10 ms  ← best
    assert cm.ready and cm.rtt_s == pytest.approx(0.010)
    assert cm.offset_s == pytest.approx(7.0, abs=1e-6)
    assert cm.to_server((250.0 + 7.0) * 1000) == pytest.approx(250.0, abs=1e-6)


def test_frame_ring_is_bounded_subscribable_and_off_by_default():
    from spectra.services.av_sync_session import Frame, FrameRing
    ring = FrameRing(maxlen=3)
    assert ring.enabled is False
    seen = []
    unsub = ring.subscribe(seen.append)
    for i in range(5):
        ring.push(Frame(float(i), float(i) / 1000, 0.0, 4, 4, "image/jpeg", bytes([i])))
    assert len(seen) == 5 and ring.latest().data == b"\x04"
    assert ring.status()["held"] == 3 and ring.status()["received"] == 5
    unsub()
    ring.push(Frame(9.0, None, 0.0, 4, 4, "image/jpeg", b"\x09"))
    assert len(seen) == 5
    ring.configure(enabled=False)
    assert ring.latest() is None
    cfg = ring.configure(enabled=True, fps=50, width=9999)
    assert cfg == {"enabled": True, "fps": 10.0, "width": 1280}   # clamped


def test_session_refuses_by_name_before_data_and_a_show_reference_works_on_synthetic_writes():
    from spectra.services import av_sync_session as s
    from spectra.services.av_sync_audio_ref import AudioReference

    async def main():
        ft = sim.FakeTime()
        hub = sim.FakeHub()
        sent = []

        async def send(m):
            sent.append(m)
        writes: list[dict] = []
        sess = s.Session(send, audio_ref=AudioReference(hub_getter=lambda: hub, clock=ft.now),
                         pattern=None, show_writes=lambda: writes, clock=ft.now)
        assert sess.estimate().reason == "clock"
        sess.clockmap.add(ft.now(), ft.now() * 1000, ft.now() + 0.01)
        assert sess.estimate().reason == "no_data"
        # show mode: the engine's own jump writes are the light reference
        await sess.start_measure(mode="show")
        assert sent[-1]["type"] == "measure_started" and sent[-1]["mode"] == "show"
        room = sim.SimRoom(seed=21)
        sess._audio_ref_started = sess.audio_ref.start()
        await asyncio.sleep(0)
        t0 = ft.now()
        t_true, env = room.make_song_env(t0 - 2.0, t0 + 20.0)
        hub.subs[0].queue.extend(room.hub_blocks(t_true, env))
        await asyncio.sleep(0.03)
        for m in room.phone_audio_messages(t_true, env):
            await sess.handle(m)
        # a random train of engine "jumps" is the show reference …
        rng = np.random.default_rng(21)
        edge_times = np.sort(rng.uniform(t0 + 1.0, t0 + 13.0, 26))
        edges = []
        state = 1
        for et in edge_times:
            writes.append({"seq": len(writes), "at": float(et), "kind": "jump", "virtual_id": "a",
                           "effect_type": "x", "params": {}, "duration_ms": 1})
            edges.append((float(et), state))
            state ^= 1
        # … and the phone's camera sees the resulting luminance edges
        for m in room.phone_video_messages(edges, t0, t0 + 14.0):
            await sess.handle(m)
        ft.t = t0 + 14.0
        est = sess.estimate()
        assert est.light_ref["kind"] == "show" and est.light_ref["event_count"] == 26
        # the passive reference is weaker by nature; what matters is that it
        # reads the right lag when it DOES detect, and names itself when not
        if est.ok:
            assert abs(est.light.lag_s - (room.light_latency_s + 0.5 / room.fps + room.rise_s / 2)) < 0.030
        else:
            assert est.reason in ("light", "audio") and "No measurement yet" in est.statement
        await sess.stop_measure()
        assert sent[-1]["type"] == "measure_done" and sent[-1]["mode"] == "show"
        await sess.close()

    asyncio.run(main())
