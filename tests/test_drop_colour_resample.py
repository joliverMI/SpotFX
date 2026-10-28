"""THE DROP COLOUR RE-SAMPLE (fx/effects/drop_colour_resample.py +
scene_response._drive_phase) — widening the predrop plan's "Star
re-samples its palette as the colour fades" past the pre-drop fade.

The Admiral, asked whether Star should also change colour on a drop with
no pre-drop, answered (2026-10-28): "yes, the star should change color."
A drop with no pre-drop changes colour INSTANTLY, right before this
drop's own phase arm — so SpotFX tells Star directly, the same shape every
other told key (lull_dark, lull_handoff, phase_grammar, pre_drop) already
uses.

What is proven here:

- THE KEY and its reader: not told is False (rule 3); `key_for` round
  trips through `landed`.
- THE ARM WRITE (`scene_response.ResponseEngine._drive_phase`): a drop
  tells every `device_model.DROP_COLOUR_RESAMPLE_EFFECTS` virtual
  (radial) the key on every drop arm, even False — never a non-member,
  never a charge or lull arm.

The render-level proof — that a told drop actually re-samples Star's
thrown-back pieces from the live palette, and a held colour change leaves
them untouched — lives in tests/test_pre_drop_looks.py, beside the
pre-drop fade's own equivalent test, through the real effect on the real
pipeline.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from random import Random
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model  # noqa: E402
from fx.effects import drop_colour_resample as dcr  # noqa: E402
from spectra.services import room_controls as rc  # noqa: E402
from spectra.services import scene_response as sr  # noqa: E402


# ── the key ──────────────────────────────────────────────────────────────

def test_not_told_is_false():
    assert dcr.landed({}) is False
    assert dcr.KEY in dcr.schema_field()


def test_key_for_round_trips_through_landed():
    assert dcr.landed(dcr.key_for(True)) is True
    assert dcr.landed(dcr.key_for(False)) is False
    assert dcr.key_for("truthy-but-not-bool")[dcr.KEY] is True
    assert dcr.key_for(0)[dcr.KEY] is False


def test_the_key_never_reaches_the_param_registry():
    """Rule 1: phase-write keys only — never an editor surface or a patch."""
    assert dcr.KEY not in device_model.effect_params("radial")


def test_radial_declares_the_key_in_its_schema_and_advanced_keys():
    from fx.effects import radial
    keys = {str(k) for k in radial.Radial2d.CONFIG_SCHEMA.schema}
    assert dcr.KEY in keys
    assert dcr.KEY in radial.Radial2d.ADVANCED_KEYS


# ── the arm write ─────────────────────────────────────────────────────────

class _Exec:
    def __init__(self):
        self.jumps = []

    async def jump(self, vid, et, params):
        self.jumps.append((vid, et, dict(params)))

    async def glide(self, vid, et, params, ms):
        pass


def _responder(effects):
    ex = _Exec()
    conductor = SimpleNamespace(scene=None, virtuals={
        vid: SimpleNamespace(effect_type=et) for vid, et in effects.items()})
    eng = sr.ResponseEngine(
        conductor=conductor, executor=ex, rng=Random(1),
        room_controls=lambda: rc.RoomControlState(),
        song_position=lambda: (None, None))
    return eng, ex


def _told(ex):
    return {vid: p for vid, _et, p in ex.jumps}


def test_a_drop_tells_radial_the_claimed_colour_change():
    eng, ex = _responder({"star": "radial", "orb": "orbits"})
    asyncio.run(eng._drive_phase("drop", gap_ms=None, intensity=0.5,
                                 colour_landed=True))
    told = _told(ex)
    assert told["star"][dcr.KEY] is True
    assert dcr.KEY not in told["orb"], "only radial re-samples this way"


def test_a_drop_tells_radial_false_when_nothing_landed():
    eng, ex = _responder({"star": "radial"})
    asyncio.run(eng._drive_phase("drop", gap_ms=None, intensity=0.5,
                                 colour_landed=False))
    assert _told(ex)["star"][dcr.KEY] is False
    # the default, with no caller passing colour_landed at all
    eng, ex = _responder({"star": "radial"})
    asyncio.run(eng._drive_phase("drop", gap_ms=None, intensity=0.5))
    assert _told(ex)["star"][dcr.KEY] is False


def test_a_charge_or_lull_arm_never_carries_the_key():
    eng, ex = _responder({"star": "radial"})
    asyncio.run(eng._drive_phase("charge", gap_ms=4000, intensity=0.9,
                                 colour_landed=True))
    assert dcr.KEY not in _told(ex)["star"]
    eng, ex = _responder({"star": "radial"})
    asyncio.run(eng._drive_phase("lull", gap_ms=6000, intensity=0.5,
                                 colour_landed=True))
    assert dcr.KEY not in _told(ex)["star"]


def test_a_scene_with_no_radial_virtual_is_never_told():
    eng, ex = _responder({"fw": "fireworks", "orb": "orbits"})
    rec = asyncio.run(eng._drive_phase("drop", gap_ms=None, intensity=0.5,
                                       colour_landed=True))
    assert dcr.KEY not in _told(ex)["fw"]
    assert dcr.KEY not in _told(ex)["orb"]
    assert "drop_colour_resample" not in rec


def test_the_record_names_it_only_when_a_target_exists():
    eng, ex = _responder({"star": "radial"})
    rec = asyncio.run(eng._drive_phase("drop", gap_ms=None, intensity=0.5,
                                       colour_landed=True))
    assert rec["drop_colour_resample"] is True
