"""THE FIREWORKS MELDS (drop-scene-variety plan phase 3, option C —
spectra/services/drop_switch.py's THE FIREWORKS MELDS is the binding
statement; fx/VENDOR.md #64 the effect side). His ask: "fish and orbits
could have 3 'particles' remain instead of just 1 and then they could
explode into fireworks on the drop, but going from fireworks to others might
need to have the standard effect followed by a transition into the other
effects after the initial burst, but the other effect needs to come in loud
to maintain the energy. So example could be the fireworks drops, then
immediately those big fireworks get swallowed by the black hole, or they
explode and then on the next big bass hit they implode into the fish, orbit
particle, squiggle, etc."

Three halves:

  1. THE DECISION, pure: the hand-off rows, the late moments (a cut a
     second after the drop; a cut on the next big analysed flare, or its
     deadline), the next-big-hit definition, what the lull is told.
  2. THE EFFECTS, on the real vendored pipeline (fx.headless, frame-stepped):
     fish and orbits flag the keepers only when told another effect is
     coming; a hard cut to Fireworks with its drop arm explodes each keeper
     where it stands; held keepers never hang; an unflagged snapshot and an
     untold orbits lull are BYTE-IDENTICAL to the pinned pre-change modules;
     the Black Hole swallows the burst cloud and Fish / Orbits / Squiggles
     take it as their own pieces.
  3. THE TRIGGER CLOCK on his real FINA (the phase-2 sweep harness): into
     Fireworks cuts on the drop with the lull told keep 3; out of it the
     cut lands after Fireworks' own drop — the swallow delay, or the hit
     flare's own tick with that flare landing on the new scene, or the
     deadline with the new scene's flare fired for it.

Offline throughout: tmp_path dummy hosts, no live storage or network.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fx import headless  # noqa: E402
from fx.effects import fireworks as fw_mod  # noqa: E402
from fx.effects import lull_handoff as lh  # noqa: E402
from spectra import config as scfg  # noqa: E402
from spectra.services import drop_sequences, drop_switch as ds  # noqa: E402
from spectra.services.scene_response import LullContext  # noqa: E402
from spectra.services.trigger_engine import TriggerEngine  # noqa: E402
from tests.test_drop_switch import (SCENES, STEP, Room, _load,  # noqa: E402
                                    showing)

# the commit before the melds: orbits had no lull hand-off keys and
# fireworks no keepers path
PRE_REF = "903214dfe1698de3a4cae3b742622ee89b6b674a"
DT = 1.0 / 60.0
ROWS, COLS = 37, 72


# ═══ 1. the decision ════════════════════════════════════════════════════

MEMBERS = {"charge": 10_000, "lull": 14_000, "drop": 16_000}
STALE = ds.StintRecord(drops_carried=1, carried_previous_drop=True,
                       arrived_on_previous_drop=False)


def _to(sid):
    return lambda showing_id, rng: SCENES[sid]


def _decide(frm, to, **kw):
    args = dict(key="drop:16000", uri="u", members=MEMBERS,
                showing=showing(frm), record=STALE,
                settings=ds.SwitchSettings(), pick_target=_to(to))
    args.update(kw)
    return ds.decide(**args)


def test_into_fireworks_from_a_keeping_lull_cuts_on_the_drop_with_keepers():
    for frm in ("fish", "orbits"):
        p = _decide(frm, "fw")
        assert p.switch and p.moment == ds.MOMENT_DROP
        assert p.handoff == ds.HANDOFF_KEEPERS and p.cut_ms() == 16_000
        assert "three keepers that burst on the drop" in p.sentence
    # a lull that cannot keep pieces cuts into Fireworks generically
    assert _decide("bh", "fw").handoff == ds.HANDOFF_GENERIC


def test_the_lull_is_told_keep_three_and_fireworks(monkeypatch):
    from fx import device_model as dm
    monkeypatch.setattr(dm, "get_virtuals_for_category",
                        lambda c: {"Matrix": ["crystal"], "Strips": ["strip"]}.get(c, []))
    target = NS(devices=[NS(target_kind="category", target="Matrix", effect_type="fireworks"),
                         NS(target_kind="category", target="Strips", effect_type="fireworks1d")])
    ctx = LullContext(scene=None, intensity=0.8, gap_ms=4000, lull_s=4.0,
                      virtuals={"crystal": "fish", "strip": "orbits1d"})
    ans = ds.handoff_for(_decide("fish", "fw"), ctx, target_scene=target)
    assert ans.keep == ds.FIREWORKS_KEEP == 3
    assert dict(ans.next_effect) == {"crystal": "fireworks", "strip": "fireworks1d"}
    # a late plan's lull runs on the showing Fireworks: told nothing new
    late = _decide("fw", "bh")
    assert ds.handoff_for(late, ctx, target_scene=target).keep == lh.DEFAULT_KEEP


def test_out_of_fireworks_into_the_black_hole_is_a_cut_after_its_own_drop():
    p = _decide("fw", "bh")
    assert p.handoff == ds.HANDOFF_SWALLOWED and p.moment == ds.MOMENT_AFTER_DROP
    assert (p.release_by, p.release_ms, p.cut_ms()) == ("delay", 17_000, 17_000)
    assert p.late and not p.early
    assert "swallows the burst" in p.sentence
    slow = _decide("fw", "bh", settings=ds.SwitchSettings(swallow_delay_s=2.5))
    assert slow.cut_ms() == 18_500


def test_out_of_fireworks_into_the_others_waits_for_the_next_big_hit():
    beat = 500.0
    deadline = ds.hit_deadline_ms(16_000, beat)
    assert deadline == 16_000 + (8 + 4) * 500        # tail + one bar
    flares = [("at_drop", 16_600, 0.95),   # inside the drop's own reach
              ("weak", 17_500, 0.3),        # under the threshold
              ("hit", 18_200, 0.8),
              ("later", 19_000, 0.9),
              ("too_late", deadline + 1, 0.99)]
    for to in ("fish", "orbits", "sq", "star"):
        p = _decide("fw", to, flares=flares, beat_ms=beat)
        assert p.handoff == ds.HANDOFF_IMPLODE_ON_HIT
        assert p.moment == ds.MOMENT_NEXT_HIT
        assert (p.release_by, p.hit_trigger_id, p.cut_ms()) == ("hit", "hit", 18_200)
        assert p.deadline_ms == deadline
    # nothing big enough before the deadline: the deadline
    p = _decide("fw", "fish", flares=flares[:2] + flares[-1:], beat_ms=beat)
    assert (p.release_by, p.hit_trigger_id, p.cut_ms()) == ("deadline", None, deadline)
    # the threshold is his
    p = _decide("fw", "fish", flares=flares, beat_ms=beat,
                settings=ds.SwitchSettings(hit_threshold=0.25))
    assert p.hit_trigger_id == "weak"


def test_an_overstayed_fireworks_still_switches_early_at_the_charge():
    p = _decide("fw", "bh", showing=showing("fw", shown_s=60.0))
    assert p.moment == ds.MOMENT_CHARGE_START and not p.late


def test_with_no_drop_member_a_late_plan_falls_back_to_the_drop_moment():
    p = _decide("fw", "bh", members={"charge": 10_000, "lull": 14_000})
    assert p.moment == ds.MOMENT_DROP


# ═══ 2. the effects, on the real pipeline ═══════════════════════════════

class Rig:
    def __init__(self, host, virtual, clock, effect, cm):
        self.host, self.virtual, self.clock = host, virtual, clock
        self.effect, self._cm = effect, cm

    def step(self, frames=1):
        out = None
        for _ in range(frames):
            self.clock.advance(DT)
            out = self.virtual.assemble_frame()
            if out is not None:
                self.virtual.flush(out)
        return out

    def phase(self, phase, seconds, told=None):
        eff = self.effect
        arm = {"phase": phase, "phase_progress": 0.0}
        arm.update(told or {})
        eff.update_config(arm)
        frames = int(seconds / DT)
        ramp = max(1, int(0.9 * frames)) if phase == "lull" else frames
        for i in range(1, frames + 1):
            if i <= ramp:
                eff.update_config({"phase_progress": i / ramp})
            self.step(1)

    def cut(self, effect_type, config, seed=3):
        new = self.host.effects.create(ledfx=self.host, type=effect_type,
                                       config=dict(config))
        self.virtual.set_effect(new, activate=False, cut=True)
        new._rng = np.random.default_rng(seed)
        self.effect = new
        return new


_TAGS = [0]


async def _rig(tmp_path, effect_type, config, seed=5):
    _TAGS[0] += 1
    tag = f"meld{_TAGS[0]}"
    host = await headless.start_headless_host(
        str(tmp_path / tag), pixel_count=ROWS * COLS, rows=ROWS, device_id=tag)
    virtual = host.virtuals.get(tag)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    eff = headless.attach_effect(host, virtual, effect_type, dict(config))
    eff._rng = np.random.default_rng(seed)
    return Rig(host, virtual, clock, eff, cm)


async def _close(r):
    r._cm.__exit__(None, None, None)
    await r.host.shutdown()


def _run(coro):
    return asyncio.run(coro)


def _lit(frame):
    return int((np.asarray(frame).reshape(-1, 3).max(axis=1) > 20).sum())


SOURCES = {"fish": {"gradient": "#ff8000"}, "orbits": {"gradient": "#ff0000"}}


async def _to_the_lull(tmp_path, src, told, seed=5):
    r = await _rig(tmp_path, src, SOURCES[src], seed=seed)
    r.step(180)
    r.phase("charge", 3.0)
    r.phase("lull", 4.0, told=told)
    return r


@pytest.mark.parametrize("src", ["fish", "orbits"])
def test_a_lull_flags_its_keepers_only_when_told_another_effect_comes(tmp_path, src):
    async def main():
        out = {}
        for label, told in (("fireworks", lh.keys_for(3, "fireworks", 4.0)),
                            ("same", lh.keys_for(3, "", 4.0)),
                            ("own", lh.keys_for(3, src, 4.0)),
                            ("untold", None)):
            r = await _to_the_lull(tmp_path, src, told)
            snap = r.effect._handoff_snapshot()
            out[label] = snap.get("keepers")
            await _close(r)
        return out
    out = _run(main())
    assert out["fireworks"] is not None and int(out["fireworks"].sum()) == 3
    assert out["same"] is None and out["own"] is None and out["untold"] is None


def test_orbits_told_keep_three_holds_a_spaced_ring(tmp_path):
    async def main():
        r = await _to_the_lull(tmp_path, "orbits", lh.keys_for(3, "fireworks", 4.0))
        eff = r.effect
        snap = eff._handoff_snapshot()
        k = snap["keepers"]
        pts = np.stack([snap["px"][k], snap["py"][k]], 1)
        await _close(r)
        return pts
    pts = _run(main())
    assert len(pts) == 3
    d = [np.hypot(*(pts[i] - pts[j])) for i in range(3) for j in range(i + 1, 3)]
    assert min(d) >= 8.0, d          # three distinct origins, not a clump


@pytest.mark.parametrize("src", ["fish", "orbits"])
def test_the_cut_to_fireworks_explodes_each_keeper_where_it_stands(tmp_path, src):
    """THE KEEPERS MELD: the drop-led cut lands Fireworks with its drop arm
    on the same frame; every one of the three keepers becomes a giant
    firework at its own position, and nothing else does."""
    async def main():
        r = await _to_the_lull(tmp_path, src, lh.keys_for(3, "fireworks", 4.0))
        snap = r.effect._handoff_snapshot()
        k = snap["keepers"]
        keepers = np.stack([snap["px"][k], snap["py"][k]], 1)
        before = _lit(r.step(1))
        fw = r.cut("fireworks", {"gradient": "#00ff00"})
        fw.update_config({"phase": "drop", "phase_progress": 0.0})
        after = _lit(r.step(1))
        ox = fw.cx + fw.p_x[:fw.n] * fw.sx
        oy = fw.cy + fw.p_y[:fw.n] * fw.sy
        near = [int((np.hypot(ox - x, oy - y) < 3.0).sum()) for x, y in keepers]
        rockets = int((fw.p_rocket[:fw.n] > 0).sum())
        n = fw.n
        await _close(r)
        return keepers, near, rockets, n, before, after
    keepers, near, rockets, n, before, after = _run(main())
    payoff = max(int(round(fw_mod.Fireworks2d.CONFIG_SCHEMA({})["burst_size"] * 2.5)), 24)
    assert len(keepers) == 3
    assert all(c >= payoff for c in near), near     # a giant burst at each
    assert sum(near) >= n and n == 3 * payoff       # and nothing anywhere else
    assert rockets == 0                             # the keepers died into them
    assert after > before                           # loud, on the mark


def test_held_keepers_with_no_drop_arm_burst_on_their_own(tmp_path):
    async def main():
        r = await _to_the_lull(tmp_path, "fish", lh.keys_for(3, "fireworks", 4.0))
        fw = r.cut("fireworks", {"gradient": "#00ff00"})
        r.step(1)
        held = int((fw.p_rocket[:fw.n] > 0).sum())
        r.step(int(fw_mod.KEEPER_HOLD_S / DT) + 2)
        left = int((fw.p_rocket[:fw.n] > 0).sum())
        n = fw.n
        await _close(r)
        return held, left, n
    held, left, n = _run(main())
    assert held == 3            # held as rockets, waiting for the drop
    assert left == 0 and n > 0  # then burst as ordinary fireworks, never hung


def _load_pinned(module, name, must_lack):
    if name in sys.modules:
        return name
    try:
        src = subprocess.run(["git", "show", f"{PRE_REF}:fx/effects/{module}.py"],
                             cwd=REPO, capture_output=True, text=True,
                             check=True, timeout=60).stdout
    except Exception as exc:                             # noqa: BLE001
        pytest.skip(f"cannot read {PRE_REF} out of git: {exc}")
    assert must_lack not in src, f"the pinned {module}.py is not pre-change"
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return name


def test_an_untold_orbits_lull_is_byte_identical_to_before(tmp_path):
    pinned = _load_pinned("orbits", "orbits_premeld", "lull_handoff")

    async def arc(effect_type):
        r = await _rig(tmp_path, effect_type, SOURCES["orbits"], seed=11)
        frames = []
        r.step(120)
        for ph, s in (("charge", 2.0), ("lull", 3.0), ("drop", 2.0)):
            arm = {"phase": ph, "phase_progress": 0.0}
            r.effect.update_config(arm)
            n = int(s / DT)
            for i in range(1, n + 1):
                r.effect.update_config({"phase_progress": min(1.0, i / (0.9 * n))})
                frames.append(np.asarray(r.step(1)).copy())
        await _close(r)
        return frames
    now, then = _run(arc("orbits")), _run(arc(pinned))
    assert len(now) == len(then)
    assert all(np.array_equal(a, b) for a, b in zip(now, then))


def test_a_snapshot_without_keepers_adopts_exactly_as_before(tmp_path):
    pinned = _load_pinned("fireworks", "fireworks_premeld", "KEEPER")

    async def main():
        r = await _rig(tmp_path, "orbits", SOURCES["orbits"])
        r.step(120)
        snap = r.effect._handoff_snapshot()
        await _close(r)
        assert "keepers" not in snap
        out = []
        for t in ("fireworks", pinned):
            f = await _rig(tmp_path, t, {"gradient": "#00ff00"}, seed=9)
            f.step(1)
            f.effect.n = 0
            f.effect._adopt_handoff(snap=snap, allow_hold=False)
            e = f.effect
            out.append({k: getattr(e, k)[:e.n].copy() for k in fw_mod._SOA_NAMES})
            await _close(f)
        return out
    now, then = _run(main())
    assert len(now["p_x"]) > 0
    for k in fw_mod._SOA_NAMES:
        assert np.array_equal(now[k], then[k]), k


async def _fireworks_drop(tmp_path, seconds_after):
    r = await _rig(tmp_path, "fireworks", {"gradient": "#ffff00"})
    r.step(120)
    r.phase("charge", 2.0)
    r.phase("lull", 2.5)
    r.effect.update_config({"phase": "drop", "phase_progress": 0.0})
    r.step(int(seconds_after / DT))
    return r


def test_the_black_hole_swallows_the_burst_cloud(tmp_path):
    async def main():
        r = await _fireworks_drop(tmp_path, 1.0)
        before = _lit(r.step(1))
        bh = r.cut("blackhole", {"gradient": "#ff00ff"})
        after = _lit(r.step(1))
        adopted = bh.n
        await _close(r)
        return before, after, adopted
    before, after, adopted = _run(main())
    assert before > 100
    assert adopted > 0                 # the cloud joined the infall
    assert after >= 0.5 * before, (before, after)   # no seam at the cut


@pytest.mark.parametrize("effect_type", ["fish", "orbits", "squiggles"])
def test_the_burst_implodes_into_the_next_scene_as_its_own_pieces(tmp_path, effect_type):
    async def main():
        r = await _fireworks_drop(tmp_path, 1.5)
        snap_n = r.effect.n
        r.step(1)
        new = r.cut(effect_type, {"gradient": "#00ffff"})
        lit = _lit(r.step(1))
        pieces = len(new.chains) if effect_type == "squiggles" else new.n
        await _close(r)
        return snap_n, pieces, lit
    snap_n, pieces, lit = _run(main())
    assert snap_n > 0 and pieces > 0
    # the adopted pieces are on the panel on the cut frame itself — a cut
    # leaves no outgoing frames to hide a fade-in behind (squiggles used to
    # go dark for ~80 ms here while its adopted chains faded up)
    assert lit > 0


# ═══ 3. the trigger clock on FINA ═══════════════════════════════════════

class MeldRoom(Room):
    """Phase 2's modelled room with a fixed route through the melds:
    Fish -> Fireworks (keepers), Fireworks -> `out`, `out` -> Fish."""

    def __init__(self, start, out, **kw):
        super().__init__(start, **kw)
        self.out = out
        self.told = []

    def pick(self, intensity):
        route = {"fish": "fw", "fw": self.out}

        def p(showing_id, rng):
            return SCENES[route.get(showing_id, "fish")]
        return p

    async def fire_sequence(self, cls, intensity, gap=None):
        if cls == "lull":
            # the resolver the hook asks, as production installs it
            self.told.append((self.position, ds.lull_handoff_resolver(LullContext(
                scene=None, intensity=intensity, gap_ms=gap,
                lull_s=(gap or 0) / 1000.0, virtuals={"crystal": SCENES[self.scene].effect},
                uri=None, position_ms=self.position))))
        await super().fire_sequence(cls, intensity, gap)


def _meld_sweep(monkeypatch, out, settings=None, extra_flares=()):
    from fx import device_model as dm
    monkeypatch.setattr(dm, "get_virtuals_for_category",
                        lambda c: {"Matrix": ["crystal"]}.get(c, []))
    monkeypatch.setattr(ds, "_scene_by_id", lambda sid: NS(devices=[
        NS(target_kind="category", target="Matrix",
           effect_type=SCENES[sid].effect)]) if sid in SCENES else None)
    fix, his, plan = _load("fina_planned_scene_changes.json")
    if extra_flares:
        from spectra.services import analysed_flares
        plan = analysed_flares.SongPlan(
            plan.scene_cues, list(plan.flares) + [
                analysed_flares.FlareMoment(ms, inten, f"section:test{ms}")
                for ms, inten in extra_flares], plan.rank_of)
    uri = fix["uri"]
    scfg.DROP_SEQUENCES_FILE.write_text(
        json.dumps({uri: fix["drop_sequences_store"]}), encoding="utf-8")
    drop_sequences.reset()
    room = MeldRoom("fish", out)
    eng = TriggerEngine(
        list_triggers=lambda u: list(his),
        scene_change_mode=lambda: "analysed",
        fire_scene=room.noop, fire_planned_scene=room.noop,
        fire_response=room.noop, fire_sequence=room.fire_sequence,
        fire_analysed_flare=room.flare, fire_scene_update=room.noop,
        select_color_set=room.noop, analysed_plan=lambda u, s: plan,
        render_intensity=lambda x: x, lead_ms=lambda t: 0,
        response_offset_ms=lambda a: 0, sequencer_enabled=lambda: False,
        select_scene=lambda i: "S", select_scene_from_pool=lambda p: "S",
        transition_intensity=lambda: 0.5, auto_generate=room.noop,
        auto_refresh=room.noop, switch_showing=room.showing,
        switch_settings=lambda: settings or ds.SwitchSettings(),
        switch_blocker=lambda: None, switch_pick=room.pick,
        fire_drop_switch=room.fire_drop_switch, rearm_phase=room.rearm)
    duration = int(fix["drop_sequences_store"]["detected"]["duration_ms"])

    async def run():
        await eng.on_track_state(uri)
        await eng.plan_analysed_flares(uri)
        for pos in range(0, duration + STEP, STEP):
            room.position = pos
            await eng.tick(pos)

    asyncio.run(run())
    drop_sequences.reset()
    return fix, room, {p.key: p for p in ds.plans_for(uri)}


def _switched(plans, handoff):
    return [p for p in plans.values() if p.switch and p.handoff == handoff
            and (p.outcome or {}).get("result") == "switched"]


def test_FINA_into_fireworks_cuts_on_the_drop_and_tells_the_lull_keep_three(monkeypatch):
    fix, room, plans = _meld_sweep(monkeypatch, "bh")
    # (an overstayed Fish still switches early, at the charge — rule B)
    into = [p for p in _switched(plans, ds.HANDOFF_KEEPERS)
            if p.moment == ds.MOMENT_DROP]
    assert into
    log = room.log
    for p in into:
        i = next(i for i, e in enumerate(log) if e[0] == "switch"
                 and e[2] == "fw" and abs(e[1] - p.drop_ms) <= STEP)
        assert log[i + 1][:3] == ("member", log[i][1], "drop")
        assert log[i + 1][3] == "fw"            # the drop arm on Fireworks
        # the lull before it was told what is coming
        told = [a for pos, a in room.told
                if p.lull_ms is not None and abs(pos - p.lull_ms) <= STEP]
        assert told and told[-1].keep == 3
        assert dict(told[-1].next_effect) == {"crystal": "fireworks"}


def test_FINA_fireworks_is_swallowed_by_the_black_hole_a_second_after_its_drop(monkeypatch):
    fix, room, plans = _meld_sweep(monkeypatch, "bh")
    out = [p for p in plans.values() if p.switch and p.handoff == ds.HANDOFF_SWALLOWED]
    assert out
    log = room.log
    on_time = 0
    for p in out:
        assert p.moment == ds.MOMENT_AFTER_DROP and p.outcome, p.sentence
        if p.outcome["at"] != ds.MOMENT_AFTER_DROP:
            assert p.outcome["at"] == "before_next_sequence"
            continue
        on_time += 1
        i = next(i for i, e in enumerate(log) if e[0] == "switch" and e[2] == "bh"
                 and p.release_ms <= e[1] <= p.release_ms + STEP)
        # Fireworks played its OWN drop first, a second earlier
        drop = [e for e in log[:i] if e[:3] == ("member", e[1], "drop")
                and abs(e[1] - p.drop_ms) <= STEP]
        assert drop and drop[-1][3] == "fw"
        assert p.release_ms - p.drop_ms == 1000
        # swallowed, not a flare: nothing fires with the cut
        assert log[i + 1][0] != "flare" or log[i + 1][1] != log[i][1]
    assert on_time


def test_FINA_fireworks_implodes_into_fish_on_the_next_big_hit(monkeypatch):
    """His real FINA, with a big analysed flare placed 1.3 s after the drop
    Fireworks plays at 44.5 s (FINA's own flares sit too far from its dense
    drops — measured: no released-by-hit cut on the unaltered song, every
    Out-2 switch there lands at its deadline or as the next sequence
    starts, which the next two tests cover)."""
    fix, room, plans = _meld_sweep(monkeypatch, "fish",
                                   extra_flares=[(44_528 + 1_300, 0.9)])
    out = [p for p in plans.values() if p.switch and p.handoff == ds.HANDOFF_IMPLODE_ON_HIT]
    assert out
    log = room.log
    by_hit = 0
    for p in out:
        assert p.moment == ds.MOMENT_NEXT_HIT and p.outcome, p.sentence
        at = p.outcome["at"]
        assert at in (ds.MOMENT_NEXT_HIT, "deadline", "before_next_sequence")
        if at == "before_next_sequence":
            continue
        i = next(i for i, e in enumerate(log) if e[0] == "switch" and e[2] == "fish"
                 and e[1] >= p.drop_ms)
        # the cut, then on the SAME tick a flare on the incoming scene — the
        # hit flare itself, or the one the deadline fires for it
        assert log[i + 1] == ("flare", log[i][1], "fish"), log[i:i + 2]
        assert log[i][1] > p.drop_ms
        if at == ds.MOMENT_NEXT_HIT:
            by_hit += 1
            assert p.release_by == "hit" and p.release_ms == 44_528 + 1_300
            assert abs(log[i][1] - p.release_ms) <= STEP
            # Fireworks played its own drop first, on Fireworks
            drop = [e for e in log[:i] if e[0] == "member" and e[2] == "drop"
                    and abs(e[1] - p.drop_ms) <= STEP]
            assert drop and drop[-1][3] == "fw"
            # and the hit flare fired exactly once — on the new scene
            assert sum(1 for e in log if e[0] == "flare"
                       and abs(e[1] - p.release_ms) <= STEP) == 1
    assert by_hit == 1


def test_FINA_with_no_hit_strong_enough_the_deadline_cuts_and_fires_the_flare(monkeypatch):
    fix, room, plans = _meld_sweep(monkeypatch, "fish",
                                   settings=ds.SwitchSettings(hit_threshold=0.999))
    out = [p for p in plans.values() if p.switch and p.handoff == ds.HANDOFF_IMPLODE_ON_HIT]
    assert out and all(p.release_by == "deadline" for p in out)
    deadlines = [p for p in out if (p.outcome or {}).get("at") == "deadline"]
    assert deadlines
    # FINA's drops are dense: the rest were cut as the next sequence began
    assert {(p.outcome or {}).get("at") for p in out} <= {
        "deadline", "before_next_sequence"}
    for p in deadlines:
        i = next(i for i, e in enumerate(room.log) if e[0] == "switch"
                 and e[2] == "fish" and e[1] >= p.deadline_ms)
        assert room.log[i][1] - p.deadline_ms <= STEP
        assert room.log[i + 1] == ("flare", room.log[i][1], "fish")
    # a pending switch is never left hanging: every late plan has an outcome
    assert all(p.outcome for p in out)
    # ... and one the next sequence reaches first is cut right before that
    # sequence's first member, which then builds on the incoming scene
    pre = [p for p in out if p.outcome["at"] == "before_next_sequence"]
    assert pre
    for p in pre:
        i = next(i for i, e in enumerate(room.log) if e[0] == "switch"
                 and e[2] == "fish" and e[1] > p.drop_ms)
        nxt = room.log[i + 1]
        assert nxt[0] == "member" and nxt[1] == room.log[i][1] and nxt[3] == "fish"
