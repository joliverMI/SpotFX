"""THE ONE-CALL HARD CUT (fx/VENDOR.md #63) — the drop-led scene switch's
switch is a cut, not the virtual's stored crossfade, and only for that one
write (spectra/services/drop_switch.py; his ruling: "just switch at the
drop ... switching at the drop should be clean").

Measured on the real vendored pipeline (fx.headless, frame-stepped under a
fake clock, a 72x37 matrix whose virtual carries Add / 0.5 s — his live
matrices' own stored transition):

  1. a cut leaves NOTHING of the outgoing effect on the first frame, where
     the stored blend keeps it for ~0.4 s — the control that makes the
     difference unambiguous (a solid red outgoing effect);
  2. the incoming effect's own drop begins ON the cut frame (Black Hole's
     payoff burst is live on the first frame after the cut + its arm);
  3. a cut hands the particles across through particle_handoff's
     no-transition path (the outgoing deactivate() leaves its snapshot);
  4. the stored transition is untouched, so the next ordinary write still
     blends — through fx_seam.apply_writes on a real facade host, too.

Offline throughout: tmp_path dummy hosts, no live storage or network.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless, light_ownership as lo  # noqa: E402
from fx.effects import particle_handoff  # noqa: E402
from fx.host import FxHost  # noqa: E402

PIXELS, ROWS = 72 * 37, 37
STORED_TRANSITION_S = 0.5
_ORIGINAL_OWNERSHIP_FILE = lo.OWNERSHIP_FILE


@pytest.fixture(autouse=True)
def _restore_ownership_file():
    yield
    lo.OWNERSHIP_FILE = _ORIGINAL_OWNERSHIP_FILE


async def _host(tmp_path, sub, **cfg):
    d = str(tmp_path / sub)
    headless.write_headless_config(d, pixel_count=PIXELS, rows=ROWS, **cfg)
    headless.silence_audio()
    host = FxHost(d)
    host.audio = headless.SyntheticAudioSource()
    await host.start()
    v = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
    v._config["transition_mode"] = "Add"
    v._config["transition_time"] = STORED_TRANSITION_S
    return host, v


async def _switch_on_the_drop(tmp_path, sub, *, cut, out_type, out_cfg):
    """Outgoing effect running, then a switch to Black Hole with its drop
    arm written straight after (the trigger clock's order), frames out."""
    host, v = await _host(tmp_path, sub)
    try:
        with headless.fake_clock() as clk:
            headless.attach_effect(host, v, out_type, out_cfg)
            headless.render_frames(v, 90, clock=clk)
            new = host.effects.create(ledfx=host, type="blackhole",
                                      config={"gradient": "#00ff00"})
            v.set_effect(new, activate=False, cut=cut)
            snapshot_left = particle_handoff._store.get(v.id) is not None
            transition_live = v._transition_effect is not None
            new.update_config({"phase": "drop", "phase_progress": 0.0})
            red, bursts = [], []
            for _ in range(40):
                f = headless.render_frames(v, 1, clock=clk)[0]
                red.append(int(((f[:, 0] > 40) & (f[:, 1] < 20)).sum()))
                bursts.append(int(np.sum(new.p_is_burst)))
            stored_time = v._config["transition_time"]
    finally:
        await host.shutdown()
    return dict(snapshot_left=snapshot_left, transition_live=transition_live,
                red=red, bursts=bursts, stored_time=stored_time)


def test_cut_vs_stored_blend_on_the_real_pipeline(tmp_path):
    cut = asyncio.run(_switch_on_the_drop(
        tmp_path, "cut", cut=True, out_type="singleColor",
        out_cfg={"color": "#ff0000"}))
    blend = asyncio.run(_switch_on_the_drop(
        tmp_path, "blend", cut=False, out_type="singleColor",
        out_cfg={"color": "#ff0000"}))
    # the control: the stored blend really does keep the outgoing red for
    # a good part of its 0.5 s (otherwise this test proves nothing)
    assert blend["transition_live"] is True
    assert sum(1 for r in blend["red"] if r > 0) >= 15, blend["red"]
    # the cut: no crossfade at all, from the very first frame
    assert cut["transition_live"] is False
    assert cut["red"] == [0] * 40, cut["red"]
    # the incoming scene's own drop begins on the cut frame
    assert cut["bursts"][0] > 0, cut["bursts"]
    # and the cut never touched the stored transition
    assert cut["stored_time"] == STORED_TRANSITION_S


def test_a_cut_hands_the_particles_across_through_the_registry(tmp_path):
    """particle_handoff's no-transition path: the outgoing deactivate()
    stores its snapshot, which a crossfade never needs (it reads the
    outgoing instance live) — so the registry holding one is the proof the
    switch took the cut's path."""
    cut = asyncio.run(_switch_on_the_drop(
        tmp_path, "pcut", cut=True, out_type="orbits",
        out_cfg={"gradient": "#ff0000"}))
    blend = asyncio.run(_switch_on_the_drop(
        tmp_path, "pblend", cut=False, out_type="orbits",
        out_cfg={"gradient": "#ff0000"}))
    assert cut["snapshot_left"] is True
    assert blend["snapshot_left"] is False and blend["transition_live"] is True


def test_fx_seam_cut_is_one_write_only(tmp_path):
    """Through the real write seam on a facade host (SPECTRA owning): an
    ordinary type switch still blends over the virtual's stored transition;
    apply_writes(cut=True) switches with no blend; the next ordinary write
    blends again."""
    from fx import facade
    from spectra.services import fx_seam

    async def main():
        d = str(tmp_path / "seam")
        headless.write_headless_config(
            d, initial_effect={"type": "singleColor",
                               "config": {"color": "#000080"}})
        headless.silence_audio()
        host = FxHost(d)
        host.audio = headless.SyntheticAudioSource()
        await host.start()
        facade.set_host(host)
        lo.OWNERSHIP_FILE = tmp_path / "ownership.json"
        lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
        v = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
        v._config["transition_mode"] = "Add"
        v._config["transition_time"] = STORED_TRANSITION_S
        vid = headless.DEFAULT_VIRTUAL_ID
        try:
            await fx_seam.apply_writes(
                [{"virtual_id": vid, "effect_type": "power",
                  "config": {"gradient": "#00ff00"}}], transition_ms=300)
            ordinary = v._transition_effect is not None
            await fx_seam.apply_writes(
                [{"virtual_id": vid, "effect_type": "blackhole",
                  "config": {"gradient": "#ff0000"}}], transition_ms=300,
                cut=True)
            after_cut = (v.active_effect.type, v._transition_effect)
            await fx_seam.apply_writes(
                [{"virtual_id": vid, "effect_type": "orbits",
                  "config": {"gradient": "#0000ff"}}], transition_ms=300)
            after_next = v._transition_effect is not None
            stored = v._config["transition_time"]
        finally:
            facade.set_host(None)
            await host.shutdown()
        return ordinary, after_cut, after_next, stored

    ordinary, after_cut, after_next, stored = asyncio.run(main())
    assert ordinary is True
    assert after_cut == ("blackhole", None)
    assert after_next is True
    assert stored == STORED_TRANSITION_S
