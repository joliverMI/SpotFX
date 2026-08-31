"""THE MAP'S OWN PROOFS: a synthetic emitter painting a KNOWN region must
yield that region's grid, and the four field kinds must all come back
through the one interface.

The ground truth here is deliberately constructed rather than measured: a
fake emitter that lights exactly one rectangle of the frame, on top of a
non-uniform dark room, at a known amplitude. If the derivation is right the
footprint is that rectangle and nothing else — which is a claim the test can
check cell by cell, not eyeball.
"""
from __future__ import annotations

import numpy as np
import pytest

from spectra.models.room_map import (AXIS_BINS, GRID_H, GRID_W, AxisCalibration,
                                     CaptureContext, EmitterFootprint, Point,
                                     RoomMap)
from spectra.services import light_field as lf
from spectra.services.light_field_fields import (KINDS, DimWave, HueRotation,
                                                 explode, implode)

FW, FH = lf.FRAME_W, lf.FRAME_H


def _frame(value: float = 0.0) -> np.ndarray:
    return np.full((FH, FW), value, dtype=np.float64)


def _room_glow() -> np.ndarray:
    """A dark room that is NOT uniformly black — a window on the left, a
    standby LED, sensor offset. Everything here must cancel in the
    difference; that is the whole reason a dark reference is taken."""
    f = _frame(6.0)
    f[:, :40] += 14.0            # window
    f[100:104, 300:304] = 90.0   # standby LED
    return f


def _lit(region: tuple[int, int, int, int], amplitude: float) -> np.ndarray:
    y0, y1, x0, x1 = region
    f = _room_glow()
    f[y0:y1, x0:x1] += amplitude
    return f


def _axis() -> AxisCalibration:
    # floor at the bottom of the frame, ceiling at the top: the slice's case.
    return AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                           ceiling=Point(x=0.5, y=0.0))


# ── 1. derivation against known ground truth ──────────────────────────────

def test_a_fake_emitter_painting_a_known_region_yields_that_regions_grid():
    region = (20, 65, 100, 180)          # rows 20..64, cols 100..179 of the frame
    amplitude = 120.0
    dark = [lf.downsample(_room_glow()) for _ in range(3)]
    lit = [lf.downsample(_lit(region, amplitude)) for _ in range(7)]

    fp = lf.footprint_from_frames(
        emitter_id="sconce-left", virtual_ids=["v1"], dark_frames=dark,
        lit_frames=lit, axis=_axis(), capture=CaptureContext(
            pose_id="p1", exposure_locked=True, white_balance_locked=True))

    grid = np.asarray(fp.grid).reshape(GRID_H, GRID_W)
    # the region in GRID coordinates (the downsample is an exact 5x5 mean)
    gy0, gy1, gx0, gx1 = 20 // 5, 65 // 5, 100 // 5, 180 // 5
    inside = grid[gy0:gy1, gx0:gx1]
    outside = grid.copy()
    outside[gy0:gy1, gx0:gx1] = 0.0

    assert np.allclose(inside, amplitude / 255.0), "the lit region must read at its own amplitude"
    assert outside.max() == 0.0, ("everything the emitter did not light must be "
                                  "exactly zero — the window and the standby LED "
                                  "are in BOTH frames and must cancel")
    assert fp.capture.dark_frames == 3 and fp.capture.lit_frames == 7
    assert fp.mapped


def test_the_dark_reference_is_what_cancels_the_room(monkeypatch):
    """Negative control: derive the SAME lit frames against a black dark
    reference instead of the real one, and the room's own glow lands in the
    footprint as if the emitter had produced it."""
    region = (20, 65, 100, 180)
    lit = [lf.downsample(_lit(region, 120.0))]
    honest = lf.footprint_grid(lf.downsample(_room_glow()), lit[0])
    wrong = lf.footprint_grid(lf.downsample(_frame(0.0)), lit[0])

    assert honest[:, :8].max() == 0.0, "the window must cancel"
    assert wrong[:, :8].max() > 0.0, ("without a dark reference the window "
                                      "reads as emitter light — this is the "
                                      "failure the reference exists to prevent")


def test_negative_differences_are_clipped_not_carried():
    """A cell the emitter cannot reach can read very slightly DARKER than
    the reference (sensor noise). A negative weight would pull the weighted
    average the wrong way for a region the emitter never touches."""
    dark = lf.downsample(_frame(20.0))
    lit = lf.downsample(_frame(18.0))
    assert lf.footprint_grid(dark, lit).min() == 0.0


def test_a_frame_that_does_not_divide_the_grid_is_refused_not_resampled():
    with pytest.raises(ValueError, match="does not divide"):
        lf.downsample(np.zeros((181, 321)))


def test_saturation_is_measured_on_frames_not_on_the_average():
    hot = _frame(255.0)
    cool = _frame(10.0)
    assert lf.saturated_fraction([hot]) == 1.0
    assert lf.saturated_fraction([cool]) == 0.0
    # averaging two frames hides the clipping; the frames do not
    assert lf.saturated_fraction([hot, cool]) == 0.5


# ── 2. the axis ───────────────────────────────────────────────────────────

def test_axis_position_runs_floor_zero_to_ceiling_one():
    pos = lf.axis_positions(_axis()).reshape(GRID_H, GRID_W)
    assert pos[-1].mean() < 0.1, "the bottom row is the floor"
    assert pos[0].mean() > 0.9, "the top row is the ceiling"
    assert np.all(np.diff(pos[:, 0]) <= 0), "monotone from ceiling down to floor"


def test_axis_profile_puts_a_high_emitter_high_and_a_low_one_low():
    high = lf.downsample(_lit((0, 40, 0, FW), 100.0))
    low = lf.downsample(_lit((FH - 40, FH, 0, FW), 100.0))
    dark = lf.downsample(_room_glow())
    axis = _axis()
    hp = lf.axis_profile(lf.footprint_grid(dark, high), axis)
    lp = lf.axis_profile(lf.footprint_grid(dark, low), axis)
    assert int(np.argmax(hp)) > AXIS_BINS * 0.7
    assert int(np.argmax(lp)) < AXIS_BINS * 0.3


def test_an_uncalibrated_axis_falls_back_to_image_height_and_says_so():
    bare = AxisCalibration()
    assert not bare.calibrated
    pos = lf.axis_positions(bare).reshape(GRID_H, GRID_W)
    assert pos[0].mean() > pos[-1].mean()


# ── 3. the effect interface, all four kinds ───────────────────────────────

def _footprint_at(axis_lo: float, axis_hi: float, emitter_id: str) -> EmitterFootprint:
    """An emitter whose light lands in one horizontal band, expressed
    directly as a grid so the test's ground truth is the band, not a
    capture."""
    grid = np.zeros((GRID_H, GRID_W))
    y0 = int((1.0 - axis_hi) * GRID_H)
    y1 = max(y0 + 1, int((1.0 - axis_lo) * GRID_H))
    grid[y0:y1, :] = 1.0
    return EmitterFootprint(emitter_id=emitter_id, grid=[float(v) for v in grid.reshape(-1)],
                            weight=float(grid.sum()), virtual_ids=[f"{emitter_id}-v"])


def _samples(*bands):
    axis = _axis()
    return [lf.samples_for(_footprint_at(lo, hi, name), axis) for lo, hi, name in bands]


def test_per_emitter_scalar_is_the_weighted_average_over_the_footprint():
    low = _footprint_at(0.0, 0.2, "low")
    s = lf.samples_for(low, _axis())
    # a field that just reports the axis position: the gain must be the
    # emitter's own weighted mean axis position, which for a 0..0.2 band is
    # about 0.1
    got = lf.per_emitter_scalar(lambda smp, t: smp.axis, 0.0, samples=[s])
    assert got["low"] == pytest.approx(0.1, abs=0.03)


def test_an_unmapped_emitter_contributes_nothing_rather_than_a_default_gain():
    empty = EmitterFootprint(emitter_id="nope", grid=[0.0] * (GRID_W * GRID_H))
    s = lf.samples_for(empty, _axis())
    assert lf.per_emitter_scalar(lambda smp, t: 1.0, samples=[s]) == {}


def test_dim_wave_is_the_only_built_kind_and_depth_zero_is_an_exact_no_op():
    assert [k for k, v in KINDS.items() if v["built"]] == ["dim_wave"]
    s = _samples((0.0, 0.3, "a"), (0.6, 1.0, "b"))
    flat = lf.per_emitter_scalar(DimWave(depth=0.0), 3.7, samples=s)
    assert set(flat) == {"a", "b"}
    for gain in flat.values():
        assert gain == 1.0, "depth 0 must be exactly 1.0, not approximately"


def test_dim_wave_separates_two_emitters_at_different_axis_positions():
    """The wave is a wave: at a wavelength of one full axis, an emitter at
    the floor and one at the ceiling cannot both sit on the crest."""
    s = _samples((0.0, 0.15, "floor"), (0.85, 1.0, "ceiling"))
    wave = DimWave(wavelength=1.0, speed=0.0, depth=1.0)
    g = lf.per_emitter_scalar(wave, 0.0, samples=s)
    assert g["floor"] > 0.9, "axis 0 sits on the crest at t=0"
    assert g["ceiling"] > 0.9, "axis 1 is one whole wavelength on — also the crest"
    mid = lf.per_emitter_scalar(wave, 0.0, samples=_samples((0.45, 0.55, "mid")))
    assert mid["mid"] < 0.1, "half a wavelength up is the trough"


def test_a_broad_emitter_averages_the_wave_and_a_narrow_one_does_not():
    """The plan's own claim, checked: softness is physics, not smoothing.
    A fixture that lights the whole wall averages a full cycle to the
    wave's mean; a fixture that lights one band tracks the wave."""
    wave = DimWave(wavelength=1.0, speed=0.0, depth=1.0)
    broad = lf.per_emitter_scalar(wave, 0.0, samples=_samples((0.0, 1.0, "broad")))
    narrow = lf.per_emitter_scalar(wave, 0.0, samples=_samples((0.45, 0.55, "narrow")))
    assert 0.35 < broad["broad"] < 0.65, "a whole cycle averages to the middle"
    assert narrow["narrow"] < 0.1


def test_the_three_unbuilt_kinds_come_back_through_the_same_interface():
    """His instruction: the INTERFACE serves four kinds from day one. None
    of these three writes a light; all three must reduce through
    per_emitter_scalar without the map needing anything it does not store."""
    s = _samples((0.0, 0.2, "low"), (0.8, 1.0, "high"))

    hue = lf.per_emitter_scalar(HueRotation(wavelength=1.0, speed=0.0,
                                            span_deg=180.0), 0.0, samples=s)
    assert set(hue) == {"low", "high"}
    assert all(0.0 <= v <= 180.0 for v in hue.values()), "degrees, not a gain"

    # implode and explode read x/y — the 2-D reason the whole grid is stored
    # t chosen so the two rings are genuinely at different radii (an
    # explosion and an implosion cross at travel 0.5 and would agree there)
    out = lf.per_emitter_scalar(explode(cx=0.5, cy=0.5, speed=1.0, width=0.25,
                                        depth=1.0), 0.3, samples=s)
    inw = lf.per_emitter_scalar(implode(cx=0.5, cy=0.5, speed=1.0, width=0.25,
                                        depth=1.0), 0.3, samples=s)
    assert set(out) == set(inw) == {"low", "high"}
    assert out["low"] != pytest.approx(inw["low"], abs=1e-6), \
        "an outward ring at 0.3 is not an inward ring at 0.7"


def test_a_radial_pulse_genuinely_reads_the_two_d_grid_not_the_axis():
    """The load-bearing claim behind storing 64x36 instead of a 1-D profile:
    two emitters at the SAME axis band but different sides of the frame must
    get different gains from a point-anchored field. Collapse the map to an
    axis profile and this test cannot pass."""
    def band(x0: int, x1: int, name: str) -> EmitterFootprint:
        grid = np.zeros((GRID_H, GRID_W))
        grid[GRID_H // 2 - 2:GRID_H // 2 + 2, x0:x1] = 1.0
        return EmitterFootprint(emitter_id=name,
                                grid=[float(v) for v in grid.reshape(-1)],
                                weight=float(grid.sum()))
    axis = _axis()
    left = lf.samples_for(band(0, 8, "left"), axis)
    right = lf.samples_for(band(GRID_W - 8, GRID_W, "right"), axis)
    assert left.axis.mean() == pytest.approx(right.axis.mean(), abs=1e-9), \
        "same axis band — a 1-D map could not tell these apart"
    g = lf.per_emitter_scalar(
        explode(cx=0.05, cy=0.5, speed=0.0, width=0.2, depth=1.0), 0.0,
        samples=[left, right])
    assert g["left"] > g["right"] + 0.3, "a pulse at the LEFT edge must reach the left emitter"


def test_faint_spill_is_kept_not_floored_away():
    """The regression this file exists to hold: an early version dropped
    cells below 2% of the footprint's peak "for speed", which quietly
    discards broad dim spill onto a ceiling — the exact light the
    where-it-shines idea is about. Only exact zeros are dropped now, and
    dropping those cannot change a weighted average at all."""
    grid = np.zeros((GRID_H, GRID_W))
    grid[5:20, 10:50] = 1.0
    grid += 0.005                                  # a faint everywhere-glow
    fp = EmitterFootprint(emitter_id="e", grid=[float(v) for v in grid.reshape(-1)],
                          weight=float(grid.sum()))
    s = lf.samples_for(fp, _axis())
    assert s.weight.size == GRID_W * GRID_H, "every non-zero cell is kept"

    sparse = np.zeros((GRID_H, GRID_W))
    sparse[5:20, 10:50] = 1.0
    fp2 = EmitterFootprint(emitter_id="e2",
                           grid=[float(v) for v in sparse.reshape(-1)],
                           weight=float(sparse.sum()))
    s2 = lf.samples_for(fp2, _axis())
    assert s2.weight.size == 15 * 40, "exact zeros carry no weight and are dropped"
    wave = DimWave(wavelength=0.7, speed=0.3, depth=0.9)
    full = lf.per_emitter_scalar(wave, 1.3, samples=[
        lf.EmitterSamples("e2", lf._CX, lf._CY, lf.axis_positions(_axis()),
                          sparse.reshape(-1))])
    assert lf.per_emitter_scalar(wave, 1.3, samples=[s2])["e2"] == \
        pytest.approx(full["e2"], abs=1e-12), "dropping zeros is exact"


# ── 4. the store ──────────────────────────────────────────────────────────

def test_the_store_round_trips_a_room_and_its_footprints(tmp_path):
    room = RoomMap(name="Kitchen wall", carrier_ids=["sconce-l", "sconce-r"],
                   axis=_axis())
    room.put_footprint(_footprint_at(0.2, 0.5, "sconce-l"))
    light_field_path = tmp_path / "maps.json"
    lf.put_room(room, light_field_path)
    back = lf.load_rooms(light_field_path)
    assert len(back) == 1
    assert back[0].mapped_ids() == ["sconce-l"]
    assert back[0].unmapped_ids() == ["sconce-r"]
    assert back[0].axis.calibrated


def test_a_footprint_grid_of_the_wrong_size_is_refused():
    with pytest.raises(ValueError, match="footprint grid must be"):
        EmitterFootprint(emitter_id="x", grid=[0.0, 1.0])
