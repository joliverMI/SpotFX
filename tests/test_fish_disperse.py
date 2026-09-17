"""FISH NEVER FADE OUT — they disperse off the screen — and the swim-burst
flare (his words on the Admiral's card fish-effect-disperse-off-screen-
instead--wyxr; see scripts/check_fish_disperse.py's own docstring).

The measured proof is scripts/check_fish_disperse.py: the lull (swirl, leak,
off the panel before the third, never dimmer while on it) at his real 0.9 s /
2.5 s / 6.04 s gaps, the outgoing Add crossfade into an effect with no blobs
(rendered pixels), an ordinary population trim, the burst at the effect, and
the flare on scene_response + flare_preview — each change with a RED control
against the pre-change module read out of git. It runs as a SUBPROCESS: it
repoints spectra.config's stores and device_model.CATEGORIES_FILE, which must
never leak into a shared pytest interpreter (tests/test_light_field_checks.py's
rule).

The crossfade SPLIT — merge where there are blobs, disperse where there are
none — runs in-process below on fx.headless, which touches no store.
"""
from __future__ import annotations

import asyncio
import copy
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fx import headless  # noqa: E402
from scripts.check_fish_disperse import BASELINE_REF  # noqa: E402

DT = 1.0 / 60.0
ROWS, COLS = 37, 72
HIS_MATRIX = {
    "particle_count": 6, "radius_scale": 1.8, "horizon_scale": 0.19,
    "blob_size": 2.5, "x_offset": 0.5, "y_offset": 0.5, "spin": 0.37,
    "base_speed": 0.3, "jiggle": 0.15, "tether_scatter": 0.0,
    "reactivity_scale": 1.0, "speed_jump": 1.0, "speed_jog": 1.0,
    "brightness_audio": 0.5, "size_audio": 0.5, "color_shift": 1,
    "impulse_decay": 0.06, "reverse": False, "camera_follow": 0.8,
}


def test_the_measured_dispersal_and_burst_proof_passes():
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_fish_disperse.py")],
        cwd=REPO, capture_output=True, text=True, timeout=1800,
    )
    tail = (proc.stdout + proc.stderr)[-4000:]
    assert proc.returncode == 0, tail
    assert "ALL CHECKS PASSED" in proc.stdout, tail
    # the red controls must have RUN, not been skipped
    assert "RED CONTROL" in proc.stdout and "SKIPPED" not in proc.stdout, tail
    # the scatter's colour, read at the rendered pixel: the hue-preserving
    # clip holds a lone fish's colour on every seed; the per-channel clip
    # it replaced fails the same bar on AT LEAST ONE seed (whether a given
    # seed's random draw ever saturates a channel at all is circumstantial
    # — fm/spotfx-fish-body-trails-head-tail-thrust's trail-based tail can
    # shift that seed to seed — so the instrument only needs to prove it
    # CAN see the defect, not that every seed's draw reproduces it; see
    # scripts/check_fish_disperse.py's own section_crossfade_hue for the
    # full reasoning).
    hue = [
        dict(field.split("=") for field in line.split()[1:])
        for line in proc.stdout.splitlines() if line.strip().startswith("HUE ")
    ]
    assert len(hue) == 3, tail
    for row in hue:
        tolerance = float(row["tolerance"])
        assert float(row["hue_clip_worst"]) <= tolerance, row
    assert any(
        float(row["per_channel_worst"]) > float(row["tolerance"])
        for row in hue
    ), tail


# ── the trail-gain hotfix (2026-09-16, his live report the same night) ──
# "fish trails lasting at least 3 times too long and about 50% too big" —
# root cause: the crossfade's brightness compensation (`self._scatter
# ["gain"]`, up to 1/TRANSITION_GAIN_FLOOR) was being deposited into
# `self.trail`, the PERSISTENT, DECAYING buffer, so a departing fish's
# smear started from up to 3.33x its true peak and took correspondingly
# longer to decay below any given visible floor, and read wider once
# diffused. Fixed by feeding the trail the fish's TRUE brightness always,
# and drawing the gained body a second time, only for the current frame's
# composited output, never stored — fx/effects/fish.py's own render-block
# comment is the full writeup.
#
# FALSIFIER, his own words: "with the trail fed the ungained value, trail
# persistence and apparent width must return to the pre-274 behaviour —
# compare against 27b1eeb." BASELINE_REF (pinned above, the commit this
# whole disperse+scatter feature was built on — the precise "pre-274" this
# repo already uses for every other red control in this file) predates the
# scatter/gain concept ENTIRELY: its own render block has no `_scatter`,
# no `_clip_body_layer`, nothing but `np.minimum(frame, 255.0)` — so a
# trail that is now proven independent of gain is, by construction, decaying
# exactly as it would in a world where gain never existed, PROVIDED the
# decay/diffusion math itself was not also touched — checked directly
# below by comparing source, not by re-deriving the arithmetic. 27b1eeb
# predates BASELINE_REF further still and carries the identical decay
# line, confirmed with `git show 27b1eeb:fx/effects/fish.py` while writing
# this fix; BASELINE_REF is used here because it is the one line this
# file's other red controls already pin, and using two different
# historical refs for the same claim would be the drift this repo's own
# rule (see scripts/check_fish_camera.py::BASELINE_REF) exists to prevent.
def test_scattering_trail_is_fed_true_brightness_not_the_crossfade_gain():
    async def _trail_series(gain, seconds=2.0, seed=5):
        host = await headless.start_headless_host(
            str(Path(headless_tmp := __import__("tempfile").mkdtemp())
                / f"trailgain-{gain}"),
            pixel_count=ROWS * COLS, rows=ROWS, device_id=f"trailgain-{gain}",
        )
        virtual = host.virtuals.get(f"trailgain-{gain}")
        with headless.fake_clock() as clock:
            eff = headless.attach_effect(host, virtual, "fish",
                                         dict(HIS_MATRIX, particle_count=3))
            eff._rng = np.random.default_rng(seed)
            for _ in range(120):
                clock.advance(DT)
                virtual.assemble_frame()
            eff._scatter = {"left_s": seconds, "gain": gain}
            out = []
            for _ in range(int(seconds / DT)):
                clock.advance(DT)
                virtual.assemble_frame()
                out.append(np.array(eff.trail, copy=True))
        await host.shutdown()
        return np.array(out)

    async def main():
        low = await _trail_series(1.0)
        high = await _trail_series(1.0 / 0.3)  # TRANSITION_GAIN_FLOOR's cap
        assert np.array_equal(low, high), (
            "self.trail differs between gain=1.0 and gain=3.33 — the "
            "crossfade compensation is leaking back into the persistent "
            "trail buffer, which is exactly the regression this test "
            "exists to catch"
        )
    asyncio.run(main())

    # the decay/diffusion math itself — never touched by this hotfix —
    # is still literally the code the pre-scatter baseline ran.
    baseline_src = subprocess.run(
        ["git", "show", f"{BASELINE_REF}:fx/effects/fish.py"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout
    current_src = (REPO / "fx" / "effects" / "fish.py").read_text()
    decay_line = "self.trail *= np.float32(0.5 ** (dt / half_life))"
    assert decay_line in baseline_src, "the baseline pin has drifted"
    assert decay_line in current_src, (
        "the trail's own decay formula changed — this hotfix must only "
        "change WHAT is deposited into the trail, never how it decays"
    )
    assert "_clip_body_layer" not in baseline_src, (
        f"the pinned baseline {BASELINE_REF} already carries the scatter "
        "gain — it predates 2b1eeb's own scatter-free render block and "
        "cannot serve as the pre-274 control this test needs"
    )


def _fish_store():
    kinds = [
        {"name": "Flare patch 0–0.35", "type": "permanent", "jump": None,
         "params": {"particle_count": {"mode": "absolute", "value": 2.0,
                                       "offset": None, "lo": None, "hi": None}},
         "gain": 1.0, "hold_ms": None, "trigger_offset_ms": 0, "enabled": True},
        {"name": "Reverse Momentarily (500ms)", "type": "momentary",
         "jump": None,
         "params": {"reverse": {"mode": "absolute", "value": 1.0,
                                "offset": None, "lo": None, "hi": None}},
         "gain": 1.0, "hold_ms": 500, "trigger_offset_ms": 0, "enabled": True},
        {"name": "Colour Jump", "type": "drift_jump", "jump": "color_set",
         "params": {}, "gain": 1.0, "hold_ms": None, "trigger_offset_ms": 0,
         "enabled": True},
    ]
    bands = [
        {"intensity_min": lo, "intensity_max": hi, "curve": "linear",
         "gain": 1.0, "param_patch": {},
         "kinds": {"Flare patch 0–0.35": 1.0, "Colour Jump": 1.0,
                   "Reverse Momentarily (500ms)": 1.0},
         "kind_lanes": {}}
        for lo, hi in ((0.0, 0.35), (0.35, 0.7), (0.7, 1.0))
    ]
    return {
        "fish-id": {"id": "fish-id", "name": "Fish", "labels": [],
                    "devices": [], "flare_kinds": kinds,
                    "responses": {"flare": {"bands": bands,
                                            "reroll_dice": False,
                                            "color_set_jump": False}}},
        "other": {"id": "other", "name": "STAR", "devices": []},
    }


def _run_script(scenes, *args):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "add_fish_swim_burst_flare.py"),
         "--scenes-file", str(scenes), *args],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )


def test_the_migration_pools_the_burst_with_the_momentary_shape_flares(tmp_path):
    scenes = tmp_path / "scenes.json"
    before = _fish_store()
    scenes.write_text(json.dumps(before, indent=2))

    dry = _run_script(scenes)
    assert dry.returncode == 0, dry.stderr
    assert json.loads(scenes.read_text()) == before, "dry run wrote"

    applied = _run_script(scenes, "--apply")
    assert applied.returncode == 0, applied.stdout + applied.stderr
    after = json.loads(scenes.read_text())
    assert after["other"] == before["other"]
    fish = after["fish-id"]
    burst = [k for k in fish["flare_kinds"] if k["name"] == "Fish Swim Burst"]
    assert len(burst) == 1
    assert burst[0]["type"] == "momentary"
    assert burst[0]["hold_ms"] == 300 and burst[0]["trigger_offset_ms"] == 0
    assert set(burst[0]["params"]) == {"swim_burst"}
    for band in fish["responses"]["flare"]["bands"]:
        assert band["kinds"]["Fish Swim Burst"] == 1.0
        # "instead of other shape flares": pooled with the momentary shape
        # flare only — the permanent patch and the colour kind stay alongside
        assert band["kind_lanes"] == {
            "Fish Swim Burst": "Shape",
            "Reverse Momentarily (500ms)": "Shape",
        }

    again = _run_script(scenes, "--apply")
    assert again.returncode == 0
    assert json.loads(scenes.read_text()) == after, "not idempotent"

    reverted = _run_script(scenes, "--revert", "--apply")
    assert reverted.returncode == 0, reverted.stdout + reverted.stderr
    assert json.loads(scenes.read_text()) == before, "revert is not exact"


def test_the_migrated_store_parses_under_the_current_scene_model(tmp_path):
    from spectra.models.scene import SceneV2
    import scripts.add_fish_swim_burst_flare as mig

    raw = copy.deepcopy(_fish_store()["fish-id"])
    mig.forward(raw)
    scene = SceneV2(**raw)
    kind = next(k for k in scene.flare_kinds if k.name == mig.KIND_NAME)
    assert (kind.hold_ms, kind.trigger_offset_ms) == (300, 0)


@pytest.mark.parametrize("pooled", [
    ["Reverse Momentarily (500ms)"],   # his momentary shape flare
    ["Colour Jump"],                    # anything else he put there
])
def test_the_migration_refuses_a_shape_lane_he_already_built(tmp_path, pooled):
    """A "Shape" lane that exists before the script runs is HIS: merging the
    burst into it would change his pool, and --revert (which recomputes what
    it removes) would then tear his own pooling down too. So forward refuses
    by name and writes nothing."""
    scenes = tmp_path / "scenes.json"
    store = _fish_store()
    band = store["fish-id"]["responses"]["flare"]["bands"][1]
    band["kind_lanes"] = {name: "Shape" for name in pooled}
    scenes.write_text(json.dumps(store, indent=2))
    before = scenes.read_text()

    applied = _run_script(scenes, "--apply")
    assert applied.returncode != 0
    out = applied.stdout + applied.stderr
    assert "flare band 1" in out and pooled[0] in out, out
    assert scenes.read_text() == before, "a refusal must write nothing"
    assert not (tmp_path / "backups").exists()


# ── the outgoing crossfade: merge where there are blobs ─────────────────
# Measured split (fx.headless): each of these reads the live fish sibling's
# snapshot on its own first draw and spawns its own particles from it. Pacman
# is the one of his named five with no adopt path; singleColor and concentric
# have no blobs at all.
ADOPTERS = ("blackhole", "orbits", "fireworks", "squiggles", "eye", "dancer",
            "fish")
NON_ADOPTERS = ("singleColor", "concentric", "pacman")
# gradient positions no incoming effect would pick for itself, so a particle
# carrying one can only have come from the fish
MARKED_GRAD = 0.0137


def _carried(incoming, eff, snap):
    """How many of the incoming effect's particles were built from the fish
    snapshot, read straight after its adoption ran."""
    if incoming == "dancer":
        return int(np.isin(eff.f_sx[: eff.n_f], snap["px"]).sum())
    if incoming == "squiggles":
        grads = [c["grad"] for c in eff.chains]
    elif incoming == "eye":
        grads = [] if eff._infall is None else eff._infall["grad"]
    else:
        grads = eff.p_grad[: eff.n]
    return int(np.isin(np.asarray(grads, dtype=np.float32),
                       snap["grad"]).sum())


async def _crossfade(tmp_path, incoming, seconds=0.5):
    tag = f"xf-{incoming}"
    host = await headless.start_headless_host(
        str(tmp_path / tag), pixel_count=ROWS * COLS, rows=ROWS,
        device_id=tag,
    )
    virtual = host.virtuals.get(tag)
    cm = headless.fake_clock()
    clock = cm.__enter__()

    def step():
        clock.advance(DT)
        frame = virtual.assemble_frame()
        if frame is not None:
            virtual.flush(frame)

    fish = headless.attach_effect(host, virtual, "fish", dict(HIS_MATRIX))
    fish._rng = np.random.default_rng(5)
    for _ in range(240):
        step()
    n = fish.n
    fish.p_grad[:n] = MARKED_GRAD * (1.0 + np.arange(n, dtype=np.float32))

    snaps = []
    live_snapshot = fish._handoff_snapshot

    def snapshot():
        snap = live_snapshot()
        snaps.append(snap)
        return snap
    fish._handoff_snapshot = snapshot

    eff = headless.attach_effect(
        host, virtual, incoming,
        dict(HIS_MATRIX) if incoming == "fish" else {},
    )
    eff._rng = np.random.default_rng(3)
    carried = []
    adopt = getattr(eff, "_adopt_handoff", None)
    if adopt is not None:
        def adopt_and_measure(*args, **kwargs):
            out = adopt(*args, **kwargs)
            carried.append(_carried(incoming, eff, snaps[-1]) if snaps else 0)
            return out
        eff._adopt_handoff = adopt_and_measure

    virtual._transition_effect = fish
    virtual._config["transition_mode"] = "Add"
    virtual.frame_transitions = virtual.transitions["Add"]
    virtual.transition_frame_total = int(round(virtual.refresh_rate * seconds))
    virtual.transition_frame_counter = 0
    dispersing, latched = [], []
    while virtual._transition_effect is fish:
        step()
        dispersing.append(int(np.count_nonzero(fish.p_mode[: fish.n] == 4)))
        latched.append(fish._scatter is not None)
    cm.__exit__(None, None, None)
    await host.shutdown()
    return n, snaps, carried, dispersing, latched


@pytest.mark.parametrize("incoming", ADOPTERS)
def test_an_incoming_effect_with_blobs_takes_the_fish_and_they_do_not_scatter(
        tmp_path, incoming):
    n, snaps, carried, dispersing, latched = asyncio.run(
        _crossfade(tmp_path, incoming))
    assert n > 0
    assert snaps, f"{incoming} never read the live fish snapshot"
    assert carried and carried[0] > 0, (
        f"{incoming} did not build any particle from the fish snapshot")
    assert max(dispersing) == 0 and not any(latched), (
        f"the fish scattered under {incoming}, which already took them as "
        "its own blobs — the shoal would show twice")


@pytest.mark.parametrize("incoming", NON_ADOPTERS)
def test_an_incoming_effect_without_blobs_still_gets_the_dispersal(
        tmp_path, incoming):
    n, _snaps, _carried_, dispersing, latched = asyncio.run(
        _crossfade(tmp_path, incoming))
    assert n > 0
    assert latched[0], f"the scatter did not latch under {incoming}"
    assert max(dispersing) == n, (
        f"every fish must disperse under {incoming}: nothing merges them")
