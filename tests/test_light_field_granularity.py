"""SUB-DEVICE GRANULARITY — the enumeration's rules, the map schema's
backward compatibility, and the gain mask's own contract.

The expensive proofs live in the two check scripts (the range lamp and the
per-pixel mask, both on the REAL render pipeline through fx.headless — see
tests/test_light_field_checks.py, which runs them as subprocesses). This
file holds the fast properties: what an emitter id IS, what an old stored
footprint still means, and how a mask composes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import virtual_gain_mask
from spectra.models.room_map import (GRID_H, GRID_W, AxisCalibration,
                                     EmitterFootprint, PixelRange, Point,
                                     RoomMap)
from spectra.services import emitters as em
from spectra.services import room_effects
from spectra.services.light_field_fields import DimWave

DEVICE = "tv-mapper"
VIRTUAL = "tv-mapper-v"
PIXELS = 60
SEG = 20
AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))


def _virtual(pixel_count=PIXELS, segments=None, mapping="span", grouping=1):
    return {"active": True, "pixel_count": pixel_count,
            "config": {"mapping": mapping, "grouping": grouping},
            "segments": segments if segments is not None else [
                [DEVICE, 0, SEG - 1, False],
                [DEVICE, SEG, 2 * SEG - 1, False],
                [DEVICE, 2 * SEG, PIXELS - 1, False]],
            "effect": {"type": "singleColor", "config": {}}}


STRIP = {VIRTUAL: _virtual()}


@pytest.fixture(autouse=True)
def _clean_masks():
    virtual_gain_mask.clear()
    yield
    virtual_gain_mask.clear()


# ── 1. the id shape the schema always anticipated ─────────────────────────

def test_whole_carrier_granularity_is_the_carrier_id_and_no_ranges():
    """The coarse case: one emitter, the carrier's own id, no ranges — the
    shape a stored footprint has when a room was mapped whole."""
    [e] = em.enumerate_carrier(VIRTUAL, STRIP[VIRTUAL], granularity="whole")
    assert e.emitter_id == VIRTUAL
    assert e.whole_carrier and e.ranges == []
    assert e.virtual_ids == [VIRTUAL]
    # "device" is the pre-carrier wire word for it, accepted from a saved
    # room or an already-open page
    [alias] = em.enumerate_carrier(VIRTUAL, STRIP[VIRTUAL], granularity="device")
    assert alias.emitter_id == VIRTUAL and alias.whole_carrier


def test_a_sub_carrier_emitter_id_names_its_pixel_range():
    out = em.enumerate_carrier(VIRTUAL, STRIP[VIRTUAL], granularity="segment")
    assert [e.emitter_id for e in out] == [
        f"{VIRTUAL}:seg0[0-19]", f"{VIRTUAL}:seg1[20-39]",
        f"{VIRTUAL}:seg2[40-59]"]
    assert all(len(e.ranges) == 1 and e.ranges[0].virtual_id == VIRTUAL
               for e in out)
    assert [(e.ranges[0].start, e.ranges[0].end) for e in out] == [
        (0, 19), (20, 39), (40, 59)]
    blocks = em.enumerate_carrier(VIRTUAL, STRIP[VIRTUAL], granularity="block",
                                  block_pixels=30)
    assert [e.emitter_id for e in blocks] == [
        f"{VIRTUAL}:blk0[0-29]", f"{VIRTUAL}:blk1[30-59]"]


def test_a_carrier_spans_every_fixture_it_fans_out_to():
    """The reason the carrier is the right key: his tv-mapper reaches a
    backlight and two sconces, and a wave along it has to run across all
    three as ONE continuous run of pixels. A device-keyed enumeration could
    only ever have seen the third of it one fixture backs."""
    segments = [["tv-backlight", 0, 19, False],
                ["sconce-kitchen-left", 0, 19, False],
                ["sconce-kitchen-right", 0, 19, False]]
    virtual = _virtual(pixel_count=60, segments=segments)
    out = em.enumerate_carrier("tv-mapper", virtual, granularity="segment")
    assert [(e.ranges[0].start, e.ranges[0].end) for e in out] == [
        (0, 19), (20, 39), (40, 59)]
    covered = {i for e in out for i in range(e.ranges[0].start,
                                             e.ranges[0].end + 1)}
    assert covered == set(range(60))
    blocks = em.enumerate_carrier("tv-mapper", virtual, granularity="block",
                                  block_pixels=15)
    assert {i for e in blocks
            for i in range(e.ranges[0].start, e.ranges[0].end + 1)} == set(range(60))


def test_ranges_are_read_from_the_config_walk_including_gap_segments():
    """The fork's own `_segments_by_device` advances `data_start` through a
    gap device's pixels because they occupy the virtual's buffer. A range
    that compacted them out would address the wrong pixels."""
    segments = [[DEVICE, 0, 9, False], ["gap-x", 0, 4, False],
                [DEVICE, 0, 9, False]]
    virtual = _virtual(pixel_count=25, segments=segments)
    out = em.enumerate_carrier(VIRTUAL, virtual, granularity="segment")
    assert [(e.ranges[0].start, e.ranges[0].end) for e in out] == [
        (0, 9), (10, 14), (15, 24)]


def test_an_unsplittable_virtual_is_reported_not_silently_mismapped():
    copied = _virtual(mapping="copy")
    [e] = em.enumerate_carrier(VIRTUAL, copied, granularity="segment")
    assert e.whole_carrier and "copies" in e.note


def test_auto_is_per_carrier_never_a_global():
    """His 'default segment for strips, device for Hue' — resolved at
    enumeration time, per carrier, from what that carrier can actually do
    and whether its whole chain is single lamps."""
    assert em.resolve_granularity("auto", STRIP[VIRTUAL]) == "segment"
    bulb = _virtual(pixel_count=1, segments=[["hue-bulb", 0, 0, False]])
    assert em.resolve_granularity("auto", bulb, point=True) == "whole"
    assert em.resolve_granularity("auto", bulb) == "whole"
    # an explicit choice is never overridden by auto's own reasoning
    assert em.resolve_granularity("block", bulb, point=True) == "block"
    # and an unknown value off the wire falls back rather than raising
    assert em.resolve_granularity("nonsense", STRIP[VIRTUAL]) == "segment"


def test_block_granularity_puts_the_remainder_in_the_last_block():
    out = em.enumerate_carrier(VIRTUAL, STRIP[VIRTUAL], granularity="block",
                               block_pixels=25)
    assert [(e.ranges[0].start, e.ranges[0].end) for e in out] == [(0, 24), (25, 59)]


def test_ranges_are_in_effect_pixel_space_when_grouping_is_on():
    grouped = _virtual(grouping=2)
    assert em.effective_pixel_count(grouped) == 30
    out = em.enumerate_carrier(VIRTUAL, grouped, granularity="segment")
    assert [(e.ranges[0].start, e.ranges[0].end) for e in out] == [
        (0, 9), (10, 19), (20, 29)]


def test_a_run_is_capped_and_says_so():
    big = {VIRTUAL: _virtual(pixel_count=4000,
                             segments=[[DEVICE, 0, 3999, False]])}
    plan = em.plan_run([VIRTUAL], big, {VIRTUAL: [{"id": DEVICE, "type": "wled"}]},
                       granularity="block", block_pixels=1)
    assert plan.truncated
    assert len(plan.emitters) == em.MAX_EMITTERS_PER_RUN
    assert any("past the" in p for p in plan.problems)


def test_a_carrier_with_no_live_virtual_is_named_not_dropped_silently():
    plan = em.plan_run([VIRTUAL], {}, {VIRTUAL: [{"id": DEVICE, "type": "wled"}]})
    assert plan.emitters == []
    assert any(VIRTUAL in p and "rendering" in p for p in plan.problems)


def test_a_carrier_whose_chain_emits_nothing_is_skipped_and_named():
    """The run's backstop for a room saved before the picker filtered, or a
    chain re-wired since. Skipped, and SAID."""
    plan = em.plan_run([VIRTUAL], STRIP,
                       {VIRTUAL: [{"id": "radial-dummy", "type": "dummy"}]})
    assert plan.emitters == []
    said = [p for p in plan.problems if p.startswith(f"{VIRTUAL}:")]
    assert len(said) == 1
    assert "emits light" in said[0] and "skipped" in said[0]


# ── 2. the map schema, forwards and backwards ─────────────────────────────

def _fp(emitter_id, carrier_id="", ranges=()):
    return EmitterFootprint(emitter_id=emitter_id, carrier_id=carrier_id,
                            ranges=list(ranges), grid=[0.0] * (GRID_W * GRID_H),
                            weight=1.0)


def test_a_whole_carrier_footprint_names_itself():
    """A whole-carrier footprint carries no `carrier_id` because its emitter
    id IS the carrier id — `carrier` is the one place that resolves."""
    fp = _fp(VIRTUAL)
    assert fp.carrier == VIRTUAL and fp.whole_carrier


def test_a_carrier_mapped_per_segment_reads_as_mapped():
    room = RoomMap(name="R", carrier_ids=[VIRTUAL], axis=AXIS)
    for i in range(3):
        room.put_footprint(_fp(f"{VIRTUAL}:seg{i}[0-9]", VIRTUAL,
                               [PixelRange(virtual_id=VIRTUAL, start=0, end=9)]))
    assert room.mapped_carriers() == [VIRTUAL]
    assert room.unmapped_ids() == []
    assert len(room.mapped_ids()) == 3


def test_remapping_a_carrier_drops_its_old_granularity_first():
    """A carrier carries footprints from exactly ONE granularity, or the
    room effect would drive the whole fixture AND its parts and dim it
    twice."""
    room = RoomMap(name="R", carrier_ids=[VIRTUAL, "other"], axis=AXIS)
    room.put_footprint(_fp(VIRTUAL))
    room.put_footprint(_fp("other"))
    assert room.drop_carrier_footprints(VIRTUAL) == 1
    assert [f.emitter_id for f in room.footprints] == ["other"]


# ── 3. the gain mask's own contract ───────────────────────────────────────

def test_no_masks_installed_is_a_short_circuit():
    assert virtual_gain_mask.mask_for(VIRTUAL) is None
    virtual_gain_mask.apply_masks({VIRTUAL: np.ones(4)})
    assert virtual_gain_mask.mask_for(VIRTUAL) is not None
    assert virtual_gain_mask.mask_for("someone-else") is None
    virtual_gain_mask.apply_masks({})
    assert virtual_gain_mask.mask_for(VIRTUAL) is None


def test_apply_masks_replaces_the_whole_set():
    """Whole-set replacement, not per-virtual edits: a leftover entry for a
    virtual that stopped being driven would keep dimming it forever."""
    virtual_gain_mask.apply_masks({"a": np.ones(3), "b": np.ones(3)})
    virtual_gain_mask.apply_masks({"a": np.ones(3)})
    assert sorted(virtual_gain_mask.lengths()) == ["a"]


def test_an_empty_mask_is_dropped_not_stored_as_a_zero_length_array():
    virtual_gain_mask.apply_masks({"a": np.array([])})
    assert virtual_gain_mask.lengths() == {}


# ── 4. how gains compose into one mask ────────────────────────────────────

def _driven(emitter_id, lo, hi, ranges):
    from spectra.services import light_field
    grid = np.zeros((GRID_H, GRID_W))
    y0 = int(round((1.0 - hi) * GRID_H))
    y1 = max(y0 + 1, int(round((1.0 - lo) * GRID_H)))
    grid[y0:y1, :] = 1.0
    fp = EmitterFootprint(emitter_id=emitter_id, carrier_id=DEVICE,
                          virtual_ids=[VIRTUAL], ranges=list(ranges),
                          grid=[float(v) for v in grid.reshape(-1)],
                          weight=float(grid.sum()))
    return room_effects._Driven(emitter_id, light_field.samples_for(fp, AXIS),
                                [VIRTUAL], list(ranges))


def test_two_ranges_become_one_mask_over_the_virtual_they_share():
    # deliberately NOT symmetric about the wave's own half-cycle: two bands
    # equidistant from the crest sit at the SAME gain, which would make this
    # assertion pass for the wrong reason.
    driven = [_driven("low", 0.05, 0.20,
                      [PixelRange(virtual_id=VIRTUAL, start=0, end=9)]),
              _driven("high", 0.45, 0.60,
                      [PixelRange(virtual_id=VIRTUAL, start=10, end=19)])]
    scalar, masks = room_effects.compute_gains(
        driven, DimWave(wavelength=1.0, speed=0.25, depth=0.9), 0.0,
        {VIRTUAL: 20})
    assert scalar == {}, "a ranged emitter never produces a scalar gain"
    assert set(masks) == {VIRTUAL} and masks[VIRTUAL].shape == (20,)
    lo_half = masks[VIRTUAL][:10]
    hi_half = masks[VIRTUAL][10:]
    assert np.allclose(lo_half, lo_half[0]) and np.allclose(hi_half, hi_half[0])
    assert abs(float(lo_half[0]) - float(hi_half[0])) > 0.05, (
        "the two ends of one strip sit at different points of the wave — "
        "the whole point of the mask")


def test_uncovered_pixels_are_left_exactly_as_the_show_wrote_them():
    driven = [_driven("low", 0.05, 0.20,
                      [PixelRange(virtual_id=VIRTUAL, start=0, end=4)])]
    _scalar, masks = room_effects.compute_gains(
        driven, DimWave(depth=1.0), 0.0, {VIRTUAL: 20})
    assert list(masks[VIRTUAL][5:]) == [1.0] * 15


def test_a_whole_device_emitter_on_a_masked_virtual_scales_the_whole_mask():
    """One composition rule, so a virtual reached both ways is never
    ambiguous: the whole-virtual gain multiplies the finished mask."""
    ranged = _driven("r", 0.05, 0.20,
                     [PixelRange(virtual_id=VIRTUAL, start=0, end=9)])
    whole = _driven("w", 0.05, 0.20, [])
    _s, only_range = room_effects.compute_gains(
        [ranged], DimWave(depth=0.5), 0.0, {VIRTUAL: 20})
    scalar, both = room_effects.compute_gains(
        [ranged, whole], DimWave(depth=0.5), 0.0, {VIRTUAL: 20})
    assert scalar == {}, "the whole-device gain folded into the mask instead"
    g = room_effects.light_field.per_emitter_scalar(
        DimWave(depth=0.5), 0.0, samples=[whole.samples])["w"]
    assert np.allclose(both[VIRTUAL], only_range[VIRTUAL] * g)


def test_overlapping_ranges_average_rather_than_last_wins():
    a = _driven("a", 0.05, 0.20,
                [PixelRange(virtual_id=VIRTUAL, start=0, end=9)])
    b = _driven("b", 0.80, 0.95,
                [PixelRange(virtual_id=VIRTUAL, start=5, end=14)])
    _s, masks = room_effects.compute_gains(
        [a, b], DimWave(depth=0.9), 0.0, {VIRTUAL: 20})
    m = masks[VIRTUAL]
    assert np.allclose(m[5:10], (m[0] + m[10]) / 2.0)


def test_a_range_past_the_end_of_the_virtual_is_clipped_not_an_error():
    driven = [_driven("r", 0.05, 0.20,
                      [PixelRange(virtual_id=VIRTUAL, start=15, end=99)])]
    _s, masks = room_effects.compute_gains(
        driven, DimWave(depth=0.5), 0.0, {VIRTUAL: 20})
    assert masks[VIRTUAL].shape == (20,)
    assert list(masks[VIRTUAL][:15]) == [1.0] * 15


def test_no_ranges_anywhere_produces_no_mask_at_all():
    """The bit-identity property, at the unit: with nothing sub-device
    driven the mask dict is empty, so fx/virtuals.py's multiply is never
    reached."""
    driven = [_driven("w", 0.05, 0.95, [])]
    scalar, masks = room_effects.compute_gains(
        driven, DimWave(depth=0.5), 0.0, {VIRTUAL: 20})
    assert masks == {} and set(scalar) == {VIRTUAL}


# ── 5. the wire: granularity is an argument to a run, and a plan is a read ──

def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


AXIS_BODY = {"kind": "vertical", "floor": {"x": 0.5, "y": 1.0},
             "ceiling": {"x": 0.5, "y": 0.0}}


def test_a_room_remembers_the_granularity_control_without_it_becoming_a_setting():
    """The room stores the last choice so the page's control comes back
    where he left it. A RUN still takes its own granularity as an argument —
    that is what "per capture, never a global" means here."""
    with _client() as client:
        room = client.post("/api/rooms", json={
            "name": "Living room", "carrier_ids": [VIRTUAL], "axis": AXIS_BODY,
        }).json()
        assert room["granularity"] == "auto" and room["block_pixels"] == 30
        saved = client.post("/api/rooms", json={
            "id": room["id"], "name": "Living room", "carrier_ids": [VIRTUAL],
            "granularity": "block", "block_pixels": 12,
        }).json()
        assert saved["granularity"] == "block" and saved["block_pixels"] == 12
        # an unknown value off the wire falls back rather than 500ing
        bad = client.post("/api/rooms", json={
            "id": room["id"], "name": "Living room", "carrier_ids": [VIRTUAL],
            "granularity": "nonsense",
        }).json()
        assert bad["granularity"] == "auto"


def test_editing_a_room_keeps_a_sub_carrier_mapped_footprints():
    """The room edit prunes footprints by CARRIER. Matching on emitter id
    would silently discard every measurement taken at a sub-device
    granularity the next time he renamed the room."""
    from spectra.services import light_field
    with _client() as client:
        room = client.post("/api/rooms", json={
            "name": "Living room", "carrier_ids": [VIRTUAL], "axis": AXIS_BODY,
        }).json()
        stored = light_field.get_room(room["id"])
        stored.put_footprint(EmitterFootprint(
            emitter_id=f"{VIRTUAL}:seg0[0-19]", carrier_id=VIRTUAL,
            ranges=[PixelRange(virtual_id=VIRTUAL, start=0, end=19)],
            grid=[1.0] * (GRID_W * GRID_H), weight=1.0))
        light_field.put_room(stored)
        renamed = client.post("/api/rooms", json={
            "id": room["id"], "name": "The lounge", "carrier_ids": [VIRTUAL],
        }).json()
        assert [f["emitter_id"] for f in renamed["footprints"]] == [
            f"{VIRTUAL}:seg0[0-19]"]
        assert renamed["mapped_carriers"] == [VIRTUAL]
        assert renamed["unmapped_ids"] == []
        assert renamed["footprints"][0]["ranges"] == [
            {"virtual_id": VIRTUAL, "start": 0, "end": 19}]


def test_the_plan_route_is_a_read_and_touches_no_light(monkeypatch):
    from spectra.services import room_mapping

    async def fake_get_virtuals():
        return {VIRTUAL: _virtual()}

    async def fake_carrier_devices():
        return {VIRTUAL: [{"id": DEVICE, "type": "wled"}]}

    def fake_deps(session):
        return room_mapping.RunDeps(
            session=session, get_virtuals=fake_get_virtuals,
            carrier_devices=fake_carrier_devices)

    monkeypatch.setattr(room_mapping, "production_deps", fake_deps)
    monkeypatch.setattr(room_mapping, "spectra_owns_lights", lambda: True)
    with _client() as client:
        room = client.post("/api/rooms", json={
            "name": "Living room", "carrier_ids": [VIRTUAL], "axis": AXIS_BODY,
        }).json()
        plan = client.get(f"/api/rooms/{room['id']}/plan"
                          "?granularity=segment&block_pixels=30").json()
        assert plan["count"] == 3 and plan["sub_device"] is True
        assert plan["per_carrier"] == {VIRTUAL: "segment"}
        assert plan["estimated_seconds"] > 0
        assert [e["emitter_id"] for e in plan["emitters"]] == [
            f"{VIRTUAL}:seg0[0-19]", f"{VIRTUAL}:seg1[20-39]",
            f"{VIRTUAL}:seg2[40-59]"]
        whole = client.get(f"/api/rooms/{room['id']}/plan"
                           "?granularity=device").json()
        assert whole["count"] == 1 and whole["sub_device"] is False
        # a plan never stores the granularity it was asked about
        assert client.get("/api/rooms").json()["rooms"][0]["granularity"] == "auto"


def test_the_plan_names_the_ownership_problem_rather_than_hiding_it(monkeypatch):
    from spectra.services import room_mapping

    async def fake_get_virtuals():
        return {VIRTUAL: _virtual()}

    async def fake_carrier_devices():
        return {VIRTUAL: [{"id": DEVICE, "type": "wled"}]}

    def fake_deps(session):
        return room_mapping.RunDeps(
            session=session, get_virtuals=fake_get_virtuals,
            carrier_devices=fake_carrier_devices)

    monkeypatch.setattr(room_mapping, "production_deps", fake_deps)
    monkeypatch.setattr(room_mapping, "spectra_owns_lights", lambda: False)
    with _client() as client:
        room = client.post("/api/rooms", json={
            "name": "Living room", "carrier_ids": [VIRTUAL], "axis": AXIS_BODY,
        }).json()
        plan = client.get(f"/api/rooms/{room['id']}/plan"
                          "?granularity=block&block_pixels=10").json()
        assert plan["sub_device"] is True and plan["spectra_owns"] is False
        assert any("SPECTRA is not driving" in p for p in plan["problems"])
