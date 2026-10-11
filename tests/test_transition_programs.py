"""THE TRANSITION PROGRAMS (transitions-drop plan phase 3; fx/effects/
transition_program.py is the binding statement, fx/VENDOR.md #70 the two
vendored hooks).

Measured on the real vendored pipeline (fx.headless, frame-stepped under a
fake clock, 72x37 matrix) — never a sketch:

  1. the registry, the anchors and the leads;
  2. INFALL hands its cloud to the real Black Hole with the velocity it
     has — continuous across the hand-off — and the control (the same
     hand-off without a velocity, i.e. the old freeze + wind-up) is not;
  3. the cloud LEAVES on the motion the outgoing particles had;
  4. ERUPTION's pieces arrive ON the incoming effect's live, moving
     formation points WITH their velocity, nothing parked;
  5. set colours only: no cell goes white on a solid-colour set;
  6. the facade honours `"program"` only for a registered pair; without it
     (and for every other pair) the stored crossfade is untouched;
  7. a switch mid-program hands the cloud over first;
  8. the two adoption fixes on ORDINARY switches (no program): Black Hole
     continues an inherited velocity, Fish keeps the inherited heading;
  9. the lead and the fire path ask for a program only where one applies.

Offline throughout: tmp_path dummy hosts, no live storage or network.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless  # noqa: E402
from fx.effects import particle_handoff  # noqa: E402
from fx.effects import transition_program as tp  # noqa: E402
from fx.host import FxHost  # noqa: E402

PIXELS, ROWS, COLS = 72 * 37, 37, 72
WARM = "linear-gradient(90deg, #ff2000 0%, #ffb000 50%, #ff00a0 100%)"
SOLID_RED = "linear-gradient(90deg, #ff0000 0%, #c00000 100%)"


async def _host(tmp_path, sub):
    d = str(tmp_path / sub)
    headless.write_headless_config(d, pixel_count=PIXELS, rows=ROWS)
    headless.silence_audio()
    host = FxHost(d)
    host.audio = headless.SyntheticAudioSource()
    await host.start()
    v = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
    v._config["transition_mode"] = "Add"
    v._config["transition_time"] = 0.5
    return host, v


def _run(coro):
    return asyncio.run(coro)


def _ang(a, b):
    d = np.arctan2(a[:, 1], a[:, 0]) - np.arctan2(b[:, 1], b[:, 0])
    return np.degrees(np.abs(np.angle(np.exp(1j * d))))


# ── 1. registry ────────────────────────────────────────────────────────────

def test_the_registry_anchors_and_leads():
    for src in ("orbits", "fish", "squiggles"):
        assert tp.program_name(src, "blackhole") == tp.INFALL
    for dst in ("orbits", "fish", "squiggles"):
        assert tp.program_name("blackhole", dst) == tp.ERUPTION
    # Fireworks <-> Black Hole is Lensing / Fountain since phase 4
    # (tests/test_transition_programs_phase4.py); unrelated pairs and
    # same-type writes have none
    for out, inc in (("fish", "fireworks"),
                     ("radial", "blackhole"), ("blackhole", "blackhole"),
                     (None, "blackhole")):
        assert tp.program_name(out, inc) is None
    s = tp.ProgramSettings.from_request({})
    assert s.duration_s == pytest.approx(1.4)
    # the infall's payoff is its ignition (the start of FORM); the
    # eruption's its bloom
    assert tp.lead_ms(tp.INFALL, s) == 900
    assert tp.lead_ms(tp.ERUPTION, s) == 420
    on_mark = tp.ProgramSettings.from_request({"on_mark": True})
    assert tp.lead_ms(tp.INFALL, on_mark) == 0
    assert tp.lead_ms(tp.ERUPTION, on_mark) == 0
    # clamped, never trusted
    wild = tp.ProgramSettings.from_request(
        {"duration_ms": 99999, "eruption_count": -5, "infall_spin": "x"})
    assert wild.duration_s == tp.MAX_DURATION_S
    assert wild.eruption_count == 10
    assert wild.infall_spin == tp.DEFAULT_INFALL_SPIN


# ── the shared rig ─────────────────────────────────────────────────────────

async def _program_run(tmp_path, sub, out_type, in_type, *, request=None,
                       gradient=WARM, strip_velocity=False, warm=120):
    host, v = await _host(tmp_path, sub)
    out = {"frames": [], "cloud": [], "targets": []}
    try:
        with headless.fake_clock() as clk:
            headless.attach_effect(host, v, out_type, {"gradient": gradient})
            headless.render_frames(v, warm, clock=clk)
            outgoing = v.active_effect
            out["out_snap"] = outgoing._handoff_snapshot()
            new = host.effects.create(ledfx=host, type=in_type,
                                      config={"gradient": gradient})
            prog = tp.build(out_type, in_type, {"seed": 3, **(request or {})})
            if strip_velocity:
                orig = prog._hand_off

                def strip(eff):
                    adopt = eff._adopt_handoff

                    def no_v(snap, allow_hold):
                        snap = {k: x for k, x in snap.items()
                                if k not in ("vx", "vy")}
                        return adopt(snap=snap, allow_hold=allow_hold)
                    eff._adopt_handoff = no_v
                    orig(eff)
                prog._hand_off = strip
            v.set_effect(new, activate=False, program=prog)
            out["registry_after_begin"] = particle_handoff._store.get(v.id)
            out["transition_live"] = v._transition_effect is not None
            while not prog.done:
                f = headless.render_frames(v, 1, clock=clk)[0]
                out["frames"].append(f)
                if in_type != "blackhole" and getattr(prog, "ejecta", False):
                    out["cloud"].append((prog.ex.copy(), prog.ey.copy(),
                                         prog.evx.copy(), prog.evy.copy(),
                                         prog.form is not None))
                if prog.frames == 1:
                    out["first"] = (getattr(prog, "x", None), getattr(prog, "y", None))
                if len(out["frames"]) > 400:
                    break
            out["prog"] = prog
            out["new"] = new
            if in_type == "blackhole":
                k = prog.x.size
                base = new.n - k
                p0 = np.stack([prog.x, prog.y], 1)
                pv = np.stack([prog.vx, prog.vy], 1)
                headless.render_frames(v, 1, clock=clk)
                p1 = np.stack([
                    new.cx + new.p_r[base:base + k] * np.cos(new.p_theta[base:base + k]) * new.sx,
                    new.cy + new.p_r[base:base + k] * np.sin(new.p_theta[base:base + k]) * new.sy,
                ], 1)
                out["handoff"] = (pv, (p1 - p0) * 60.0)
            out["after"] = headless.render_frames(v, 30, clock=clk)
            out["program_attr_after"] = getattr(new, "_transition_program", None)
    finally:
        await host.shutdown()
    return out


# ── 2. infall: continuous across the hand-off; the control is not ───────────

@pytest.mark.parametrize("src", ["orbits", "fish"])
def test_infall_hands_the_cloud_over_still_moving(tmp_path, src):
    r = _run(_program_run(tmp_path, src, src, "blackhole"))
    ctrl = _run(_program_run(tmp_path, src + "c", src, "blackhole",
                             strip_velocity=True))
    prog = r["prog"]
    assert prog.done and prog.handed_off
    # one picture: no crossfade sibling, and the outgoing's registry
    # snapshot is the program's, not left for the incoming to adopt
    assert r["transition_live"] is False
    assert r["registry_after_begin"] is None
    assert r["program_attr_after"] is None
    pv, after = r["handoff"]
    moving = np.linalg.norm(pv, axis=1) > 2.0
    assert moving.sum() >= 10
    dv = np.linalg.norm(after[moving] - pv[moving], axis=1)
    assert np.median(dv) < 1.0, np.median(dv)
    assert np.median(_ang(after[moving], pv[moving])) < 2.0
    # THE CONTROL: the same hand-off without a velocity is the old freeze
    # and wind-up — the pieces all but stop on the first real frame
    cpv, cafter = ctrl["handoff"]
    cm = np.linalg.norm(cpv, axis=1) > 2.0
    speed_before = np.median(np.linalg.norm(cpv[cm], axis=1))
    speed_after = np.median(np.linalg.norm(cafter[cm], axis=1))
    assert speed_after < 0.2 * speed_before, (speed_before, speed_after)
    # the cloud joined (was appended to) the Black Hole's own population
    assert r["new"].n >= prog.x.size


def test_infall_leaves_on_the_motion_it_had(tmp_path):
    r = _run(_program_run(tmp_path, "start", "orbits", "blackhole"))
    prog = r["prog"]
    x1, y1 = r["first"]
    # the first program frame moves every piece by its own inherited
    # velocity (smoothstep bend has zero slope at t=0)
    dt = 1 / 60
    v_first = np.stack([(x1 - prog.p0x) / dt, (y1 - prog.p0y) / dt], 1)
    v0 = np.stack([prog.v0x, prog.v0y], 1)
    moving = np.linalg.norm(v0, axis=1) > 2.0
    assert moving.sum() >= 10
    err = np.linalg.norm(v_first[moving] - v0[moving], axis=1) \
        / np.linalg.norm(v0[moving], axis=1)
    assert np.median(err) < 0.1, np.median(err)


# ── 4. eruption: implode onto the live, moving targets ────────────────────

@pytest.mark.parametrize("dst", ["orbits", "fish"])
def test_eruption_implodes_onto_the_moving_incoming_form(tmp_path, dst):
    r = _run(_program_run(tmp_path, dst, "blackhole", dst))
    prog = r["prog"]
    assert prog.done
    assert prog.form is not None, "the FORM stage never engaged"
    # the last cloud state sits ON the incoming effect's formation points,
    # moving with them
    ex, ey, evx, evy, _ = r["cloud"][-1]
    q0 = prog._tq                      # the targets as of that same frame
    assert q0 is not None
    j = prog.form["j"] % q0[0].size
    d = np.hypot(ex - q0[0][j], ey - q0[1][j])
    assert np.max(d) < 0.5, np.max(d)
    # the targets really move (the orbits/fish were never parked)...
    u = np.hypot(prog._tu[0], prog._tu[1])
    assert np.median(u) > 1.0, u
    # ...and every piece arrives with its target's velocity
    dv = np.hypot(evx - prog._tu[0][j], evy - prog._tu[1][j])
    assert np.median(dv) < 3.0, np.median(dv)
    # nothing parks: through FORM the pieces keep moving
    speeds = [np.median(np.hypot(c[2], c[3])) for c in r["cloud"] if c[4]]
    assert min(speeds) > 1.0, speeds
    # the incoming effect is whole by the end
    assert prog.last_gain == pytest.approx(1.0, abs=0.05)


def test_eruption_on_the_mark_blooms_on_its_first_frame(tmp_path):
    r = _run(_program_run(tmp_path, "mark", "blackhole", "orbits",
                          request={"on_mark": True}))
    prog = r["prog"]
    assert prog.anchor == 0.0
    assert prog.ejecta
    assert r["cloud"], "ejecta from the first frame"


# ── 5. set colours only ────────────────────────────────────────────────────

@pytest.mark.parametrize("pair", [("orbits", "blackhole"), ("blackhole", "orbits")])
def test_a_solid_colour_set_never_goes_white(tmp_path, pair):
    r = _run(_program_run(tmp_path, "w" + pair[0], pair[0], pair[1],
                          gradient=SOLID_RED))
    for f in r["frames"]:
        assert int(((f > 200).all(axis=1)).sum()) == 0


# ── 6. the facade: a program only where one is registered ─────────────────

async def _facade_switch(tmp_path, sub, out_type, in_type, program):
    from fx import facade
    host, v = await _host(tmp_path, sub)
    try:
        with headless.fake_clock() as clk:
            headless.attach_effect(host, v, out_type, {"gradient": WARM})
            headless.render_frames(v, 60, clock=clk)
            facade.set_host(host)
            body = {"type": in_type, "config": {"gradient": WARM}}
            if program is not None:
                body["program"] = program
            resp = await facade.handle(
                "PUT", f"/api/virtuals/{v.id}/effects", json=body)
            assert resp.status_code == 200, resp.json()
            return {"program": getattr(v, "_program", None),
                    "transition_live": v._transition_effect is not None,
                    "stored": v._config["transition_time"]}
    finally:
        from fx import facade as f2
        f2.set_host(None)
        await host.shutdown()


def test_the_facade_runs_a_program_only_for_a_registered_pair(tmp_path, monkeypatch):
    from fx import facade
    monkeypatch.setattr(facade, "_persist_soon", lambda host: None)
    asked = _run(_facade_switch(tmp_path, "a", "orbits", "blackhole", {"seed": 1}))
    assert asked["program"] is not None and asked["transition_live"] is False
    plain = _run(_facade_switch(tmp_path, "b", "orbits", "blackhole", None))
    assert plain["program"] is None and plain["transition_live"] is True
    unregistered = _run(_facade_switch(tmp_path, "c", "fish", "fireworks", {"seed": 1}))
    assert unregistered["program"] is None and unregistered["transition_live"] is True
    # the stored crossfade was never touched
    assert {asked["stored"], plain["stored"], unregistered["stored"]} == {0.5}


# ── 7. a switch mid-program hands the cloud over first ─────────────────────

def test_a_switch_mid_program_finishes_it(tmp_path):
    async def go():
        host, v = await _host(tmp_path, "mid")
        try:
            with headless.fake_clock() as clk:
                headless.attach_effect(host, v, "orbits", {"gradient": WARM})
                headless.render_frames(v, 60, clock=clk)
                bh = host.effects.create(ledfx=host, type="blackhole",
                                         config={"gradient": WARM})
                prog = tp.build("orbits", "blackhole", {"seed": 1})
                v.set_effect(bh, activate=False, program=prog)
                headless.render_frames(v, 20, clock=clk)
                assert not prog.done
                n_before = bh.n
                other = host.effects.create(ledfx=host, type="orbits",
                                            config={"gradient": WARM})
                v.set_effect(other, activate=False, cut=True)
                return prog, bh, n_before
        finally:
            await host.shutdown()
    prog, bh, n_before = _run(go())
    assert prog.done and prog.handed_off
    assert getattr(bh, "_transition_program", None) is None


# ── 8. the adoption fixes on ordinary switches ─────────────────────────────

async def _cut(tmp_path, sub, out_type, in_type, measure):
    host, v = await _host(tmp_path, sub)
    try:
        with headless.fake_clock() as clk:
            headless.attach_effect(host, v, out_type, {"gradient": WARM})
            headless.render_frames(v, 120, clock=clk)
            snap = v.active_effect._handoff_snapshot()
            new = host.effects.create(ledfx=host, type=in_type,
                                      config={"gradient": WARM})
            v.set_effect(new, activate=False, cut=True)
            headless.render_frames(v, 1, clock=clk)   # adopts
            return measure(snap, new, v, clk)
    finally:
        await host.shutdown()


def test_blackhole_continues_an_inherited_velocity(tmp_path):
    def measure(snap, bh, v, clk):
        k = min(len(snap["px"]), bh.n)

        def p():
            return np.stack([
                bh.cx + bh.p_r[:k] * np.cos(bh.p_theta[:k]) * bh.sx,
                bh.cy + bh.p_r[:k] * np.sin(bh.p_theta[:k]) * bh.sy], 1)
        a = p()
        headless.render_frames(v, 1, clock=clk)
        return (p() - a) * 60.0, np.stack([snap["vx"][:k], snap["vy"][:k]], 1)
    vel, inh = _run(_cut(tmp_path, "bh", "orbits", "blackhole", measure))
    moving = np.linalg.norm(inh, axis=1) > 3.0
    assert moving.sum() >= 5
    # not frozen: the first real frames carry the inherited speed
    ratio = np.linalg.norm(vel[moving], axis=1) / np.linalg.norm(inh[moving], axis=1)
    assert np.median(ratio) > 0.6, np.median(ratio)


def test_fish_keeps_the_inherited_heading(tmp_path):
    def measure(snap, fish, v, clk):
        return snap, fish.p_hd[: fish.n].copy()
    snap, hd = _run(_cut(tmp_path, "f", "orbits", "fish", measure))
    inh = np.stack([snap["vx"], snap["vy"]], 1)
    moving = np.linalg.norm(inh, axis=1) > 1e-3
    inh_hd = np.arctan2(inh[moving, 1], inh[moving, 0])
    # every adopted fish swims on a heading some inherited blob had (one
    # frame of steering allowed for)
    best = [np.min(np.abs(np.angle(np.exp(1j * (h - inh_hd))))) for h in hd[:3]]
    assert max(best) < np.radians(15), np.degrees(best)


# ── 9. the lead and the fire path ──────────────────────────────────────────

def test_program_lead_replaces_the_crossfade_lead_only_where_it_applies():
    from spectra.services import room_controls as rc
    from spectra.services import scene_transition_lead as stl
    room = rc.RoomControlState()
    writes = [{"virtual_id": "m", "effect_type": "blackhole"},
              {"virtual_id": "s", "effect_type": "power"}]
    assert stl.program_lead_ms({"m": "orbits", "s": "power"}, writes, room) == 900
    assert stl.program_lead_ms({"m": "blackhole"}, writes, room) is None
    assert stl.program_lead_ms({"m": "fish"},
                               [{"virtual_id": "m", "effect_type": "fireworks"}],
                               room) is None
    off = room.model_copy(update={"transition_programs_enabled": False})
    assert stl.program_lead_ms({"m": "orbits"}, writes, off) is None
    longer = room.model_copy(update={"transition_program_ms": 2000})
    assert stl.program_lead_ms({"m": "orbits"}, writes, longer) == 1500
    assert rc.transition_program_request(off) is None
    req = rc.transition_program_request(room, on_mark=True)
    assert req["on_mark"] is True and req["duration_ms"] == 1400


def test_fire_scene_asks_for_a_program_only_for_a_registered_switch(monkeypatch):
    from spectra.services import room_controls as rc
    from spectra.services import scene_compiler as sc
    room = rc.RoomControlState()
    w = [{"virtual_id": "m", "effect_type": "blackhole"}]
    assert sc.transition_program_for(w, room, current_types={"m": "orbits"})
    assert sc.transition_program_for(w, room, current_types={"m": "radial"}) is None
    assert sc.transition_program_for(
        w, room.model_copy(update={"transition_programs_enabled": False}),
        current_types={"m": "orbits"}) is None
    assert sc.transition_program_for(
        w, room, on_mark=True, current_types={"m": "orbits"})["on_mark"] is True


def test_drop_switch_names_the_program_rows():
    from spectra.services import drop_switch as ds
    assert ds.handoff_kind("orbits", "blackhole") == ds.HANDOFF_PROGRAM
    assert ds.handoff_kind("blackhole", "fish") == ds.HANDOFF_PROGRAM
    assert ds.handoff_kind("fireworks", "blackhole") == ds.HANDOFF_SWALLOWED
    # phase 4: the Black Hole fountains into Fireworks on the mark
    assert ds.handoff_kind("blackhole", "fireworks") == ds.HANDOFF_PROGRAM
