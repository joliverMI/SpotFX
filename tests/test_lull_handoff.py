"""THE LULL HAND-OFF HOOK (fx/effects/lull_handoff.py + scene_response.
_drive_phase) — the fish-lull plan's phase 1, the shared interface the
drop-scene-variety work plugs a resolver into.

What is proven here, each on the real code it names:

- THE KEYS and their readers: told / not told, the keep clamp, the keep
  mark in seconds (told) or at progress 0.5 (not told), the drop scale
  anchored so 0.75 is the legacy drop and "not told" is None.
- THE ARM WRITE: a lull tells every LULL_HANDOFF_EFFECTS virtual every
  key on every arm (the default included), the real gap as lull_s (the flat
  ramp when the gap is unknowable), and never tells a non-member; a drop
  tells DROP_INTENSITY_EFFECTS the fire's intensity, floored so it is
  always TOLD; a charge tells nothing.
- THE RESOLVER SEAM: the default is the Admiral's keep 1; an installed
  resolver is asked with the scene, intensity, gap, every virtual's effect
  and the live song; its answer lands per virtual; a resolver that raises
  or answers garbage never reaches the fire (the default is used, NAMED);
  the instance override beats the process-wide install.
- THE RECORD and THE PREVIEW: the phase record names what was told, and the
  drop-sequence preview's per-lap step carries it — because the preview
  calls the same on_event, with the same process-wide resolver.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from random import Random
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model  # noqa: E402
from fx.effects import fish as fish_mod  # noqa: E402
from fx.effects import lull_handoff as lh  # noqa: E402
from spectra.services import room_controls as rc  # noqa: E402
from spectra.services import scene_response as sr  # noqa: E402


@pytest.fixture(autouse=True)
def _no_installed_resolver():
    sr.install_lull_handoff_resolver(None)
    yield
    sr.install_lull_handoff_resolver(None)


# ── the keys ──────────────────────────────────────────────────────────────

def test_not_told_is_the_effects_own_default():
    assert lh.keep({}) == lh.DEFAULT_KEEP == 1
    assert lh.next_effect({}) == ""
    assert not lh.told({})
    assert lh.drop_intensity({}) is None
    assert lh.drop_scale(None) is None


def test_keep_is_clamped_to_what_any_lull_effect_holds():
    assert lh.keys_for(99, "fireworks", 6.0)[lh.KEEP_KEY] == lh.MAX_KEEP
    assert lh.keys_for(-3, "", 6.0)[lh.KEEP_KEY] == 0
    assert lh.keys_for(3, None, -1.0) == {
        lh.KEEP_KEY: 3, lh.NEXT_KEY: "", lh.LULL_S_KEY: 0.0}


def test_the_keep_mark_is_seconds_when_told_and_half_progress_otherwise():
    told = lh.keys_for(1, "", 6.0)
    assert lh.keep_mark(told, progress=0.9, phase_t=1.5) == pytest.approx(0.5)
    assert lh.keep_mark(told, progress=0.0, phase_t=3.0) == pytest.approx(1.0)
    assert lh.keep_mark({}, progress=0.25, phase_t=99.0) == pytest.approx(0.5)
    assert lh.keep_mark({}, progress=0.5, phase_t=0.0) == pytest.approx(1.0)


def test_the_drop_scale_is_anchored_on_the_automatic_ceiling():
    assert lh.drop_scale(0.75) == pytest.approx(1.0)
    assert lh.drop_scale(1.0) == pytest.approx(lh.DROP_SCALE_MAX)
    assert lh.drop_scale(0.3) == pytest.approx(0.4 + 0.6 * 0.3 / 0.75)
    assert lh.drop_scale(0.01) >= 0.4
    # the floor is the effect's own knob
    assert lh.drop_scale(0.01, 0.8) == pytest.approx(0.8 + 0.2 * 0.01 / 0.75)
    assert lh.drop_scale(0.75, 0.8) == pytest.approx(1.0)


def test_a_told_drop_intensity_is_never_zero():
    assert lh.drop_keys_for(0.0)[lh.DROP_KEY] == lh.DROP_INTENSITY_FLOOR
    assert lh.drop_intensity(lh.drop_keys_for(0.0)) is not None
    assert lh.drop_keys_for(1.7)[lh.DROP_KEY] == 1.0


def test_the_fish_is_the_first_member_and_carries_every_key():
    assert device_model.LULL_HANDOFF_EFFECTS == {"fish"}
    assert device_model.DROP_INTENSITY_EFFECTS == {"fish"}
    assert device_model.LULL_HANDOFF_EFFECTS <= device_model.PHASE_EFFECTS
    keys = {str(k) for k in fish_mod.Fish2d.CONFIG_SCHEMA.schema}
    assert set(lh.KEYS) | {lh.DROP_KEY} <= keys
    assert set(lh.KEYS) | {lh.DROP_KEY} <= set(fish_mod.Fish2d.ADVANCED_KEYS)


def test_the_keys_never_reach_the_param_registry():
    """Rule 1: phase-write keys only — never an editor surface or a patch."""
    params = device_model.effect_params("fish")
    for k in (*lh.KEYS, lh.DROP_KEY):
        assert k not in params


# ── the arm write ─────────────────────────────────────────────────────────

class _Exec:
    def __init__(self):
        self.jumps, self.glides = [], []

    async def jump(self, vid, et, params):
        self.jumps.append((vid, et, dict(params)))

    async def glide(self, vid, et, params, ms):
        self.glides.append((vid, et, dict(params), ms))


def _responder(effects, *, song=(None, None), scene=None):
    ex = _Exec()
    conductor = SimpleNamespace(scene=scene, virtuals={
        vid: SimpleNamespace(effect_type=et) for vid, et in effects.items()})
    eng = sr.ResponseEngine(
        conductor=conductor, executor=ex, rng=Random(1),
        room_controls=lambda: rc.RoomControlState(),
        song_position=lambda: song)
    return eng, ex


def _told(ex):
    return {vid: p for vid, _et, p in ex.jumps}


def test_a_lull_tells_every_member_every_key_at_the_default():
    eng, ex = _responder({"m": "fish", "orb": "orbits", "bh": "blackhole"})
    rec = asyncio.run(eng._drive_phase("lull", gap_ms=6_000, intensity=0.5))
    told = _told(ex)
    assert told["m"][lh.KEEP_KEY] == 1
    assert told["m"][lh.NEXT_KEY] == ""
    assert told["m"][lh.LULL_S_KEY] == pytest.approx(6.0)
    for vid in ("orb", "bh"):
        assert not set(lh.KEYS) & set(told[vid]), vid
    assert rec["lull_handoff"] == {"keep": 1, "next": {}, "lull_s": 6.0,
                                   "resolver": "default"}


def test_an_unknowable_gap_tells_the_flat_ramp_as_the_lull():
    eng, ex = _responder({"m": "fish"})
    asyncio.run(eng._drive_phase("lull", gap_ms=None, intensity=0.5))
    flat_s = sr._phase_ramp_ms("lull", None) / 1000.0
    assert _told(ex)["m"][lh.LULL_S_KEY] == pytest.approx(flat_s)


def test_a_drop_tells_the_fires_intensity_and_a_charge_tells_nothing():
    eng, ex = _responder({"m": "fish", "orb": "orbits"})
    rec = asyncio.run(eng._drive_phase("drop", gap_ms=None, intensity=0.42))
    told = _told(ex)
    assert told["m"][lh.DROP_KEY] == pytest.approx(0.42)
    assert lh.DROP_KEY not in told["orb"]
    assert rec["drop_intensity"] == pytest.approx(0.42)
    assert not set(lh.KEYS) & set(told["m"])

    eng, ex = _responder({"m": "fish"})
    rec = asyncio.run(eng._drive_phase("charge", gap_ms=4_000, intensity=0.9))
    assert _told(ex)["m"] == {"phase": "charge", "phase_progress": 0.0}
    assert "lull_handoff" not in rec and "drop_intensity" not in rec


def test_no_member_no_handoff_record():
    eng, ex = _responder({"orb": "orbits"})
    rec = asyncio.run(eng._drive_phase("lull", gap_ms=6_000, intensity=0.5))
    assert "lull_handoff" not in rec
    rec = asyncio.run(eng._drive_phase("drop", intensity=0.5))
    assert "drop_intensity" not in rec


def test_an_installed_resolver_is_asked_and_answers_per_virtual():
    seen = []

    def drop_switch(ctx):
        seen.append(ctx)
        return sr.LullHandoff(keep=3, next_effect={"m": "fireworks"},
                              lull_s=ctx.lull_s)

    sr.install_lull_handoff_resolver(drop_switch)
    scene = SimpleNamespace(name="Fish")
    eng, ex = _responder({"m": "fish", "m2": "fish", "orb": "orbits"},
                         song=("spotify:track:x", 61_000), scene=scene)
    rec = asyncio.run(eng._drive_phase("lull", gap_ms=4_000, intensity=0.6))
    told = _told(ex)
    assert told["m"][lh.KEEP_KEY] == 3
    assert told["m"][lh.NEXT_KEY] == "fireworks"
    assert told["m2"][lh.NEXT_KEY] == ""          # absent = same effect
    assert told["m2"][lh.KEEP_KEY] == 3
    ctx = seen[0]
    assert ctx.scene is scene and ctx.intensity == 0.6
    assert ctx.gap_ms == 4_000 and ctx.lull_s == pytest.approx(4.0)
    assert ctx.virtuals == {"m": "fish", "m2": "fish", "orb": "orbits"}
    assert (ctx.uri, ctx.position_ms) == ("spotify:track:x", 61_000)
    assert rec["lull_handoff"] == {"keep": 3, "next": {"m": "fireworks"},
                                   "lull_s": 4.0, "resolver": "drop_switch"}


@pytest.mark.parametrize("bad", [
    lambda ctx: (_ for _ in ()).throw(RuntimeError("drop plan unreadable")),
    lambda ctx: {"keep": 3},
])
def test_a_failing_resolver_never_reaches_the_fire(bad):
    sr.install_lull_handoff_resolver(bad)
    eng, ex = _responder({"m": "fish"})
    rec = asyncio.run(eng._drive_phase("lull", gap_ms=6_000, intensity=0.5))
    assert _told(ex)["m"][lh.KEEP_KEY] == lh.DEFAULT_KEEP
    assert rec["lull_handoff"]["resolver"] == "default (resolver failed)"
    assert len(ex.glides) == 1     # the lull still ramped


def test_the_instance_override_beats_the_install():
    sr.install_lull_handoff_resolver(
        lambda ctx: sr.LullHandoff(keep=5, lull_s=ctx.lull_s))
    eng, ex = _responder({"m": "fish"})
    eng.lull_handoff_resolver = lambda ctx: sr.LullHandoff(
        keep=0, lull_s=ctx.lull_s)
    asyncio.run(eng._drive_phase("lull", gap_ms=6_000, intensity=0.5))
    assert _told(ex)["m"][lh.KEEP_KEY] == 0


def test_on_event_passes_the_fires_intensity_to_the_drop():
    eng, ex = _responder({"m": "fish"},
                         scene=SimpleNamespace(responses={}))
    rec = asyncio.run(eng.on_event("drop", 0.66))
    assert _told(ex)["m"][lh.DROP_KEY] == pytest.approx(0.66)
    assert rec["phase"]["drop_intensity"] == pytest.approx(0.66)


# ── the sequence preview ──────────────────────────────────────────────────

def test_the_sequence_preview_carries_what_the_lull_was_told():
    """The drop-sequence preview's live half runs each step through the
    same on_event, on a scratch responder — so it asks the same
    process-wide resolver and its per-lap record says what was told."""
    from spectra.services import phase_preview

    sr.install_lull_handoff_resolver(
        lambda ctx: sr.LullHandoff(keep=3, next_effect={"m": "fireworks"},
                                   lull_s=ctx.lull_s))
    eng, ex = _responder({"m": "fish"},
                         scene=SimpleNamespace(responses={}))
    program = phase_preview.PhaseSequenceProgram(
        SimpleNamespace(name="Fish"), gaps={"lull": 5_000})

    async def apply_scene():
        return None

    ctx = SimpleNamespace(first_open=False, responder=eng, intensity=0.5,
                          apply_scene=apply_scene)
    out = asyncio.run(program.execute("lull", ctx))
    handoff = out["record"]["phase"]["lull_handoff"]
    assert handoff["keep"] == 3 and handoff["next"] == {"m": "fireworks"}
    assert handoff["lull_s"] == pytest.approx(5.0)
    assert _told(ex)["m"][lh.KEEP_KEY] == 3


def test_the_live_engine_installs_no_resolver_so_a_fish_lull_keeps_one():
    """The default the Admiral sees: the production engine module wires no
    resolver, so an ordinary lull fire (on_event, the path the trigger clock
    and the bridge both reach) tells a fish `lull_keep = 1` — the searcher.
    Keep 0 (the old lull) only ever arrives when something TELLS it."""
    from spectra.services import engine as live_engine

    import ast
    import inspect
    calls = [n for n in ast.walk(ast.parse(inspect.getsource(live_engine)))
             if isinstance(n, ast.Call)
             and getattr(n.func, "attr", getattr(n.func, "id", ""))
             == "install_lull_handoff_resolver"]
    assert not calls, "engine.py installs a resolver — the default changed"
    assert live_engine.responses.lull_handoff_resolver is None
    eng, ex = _responder({"m": "fish"}, scene=SimpleNamespace(responses={}))
    rec = asyncio.run(eng.on_event("lull", 0.5, gap_ms=6_000))
    told = _told(ex)["m"]
    assert told[lh.KEEP_KEY] == 1 and told[lh.KEEP_KEY] != 0
    assert told[lh.LULL_S_KEY] == pytest.approx(6.0)
    assert rec["phase"]["lull_handoff"]["resolver"] == "default"
