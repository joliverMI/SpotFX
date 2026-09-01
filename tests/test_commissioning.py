"""THE COMMISSIONING RUN AND THE FROZEN TABLE.

Two things are proven here, and the second is the one that makes the first
worth anything:

  1. a SYNTHETIC room whose arrangement is known before the run — the whole
     chain, from the stored composition through the real `CommissionProgram`
     and the real pattern strings to the decode and the judged table —
     comes out green; and
  2. a DELIBERATELY CORRUPTED stack fails THE RIGHT ROW, with the
     attribution the plan's own table names, including the two
     his-data-is-wrong outcomes that must be reported as FINDINGS and never
     as commissioning failures.

The fake camera renders from the writes the REAL program produced, so the
lamp's wire format, the composition's index mapping and the decoder are
exercised against each other rather than against a convenient stub. No
network, no lights, no phone, no store outside a tmp path.
"""
from __future__ import annotations

import asyncio
import json
import math

import numpy as np
import pytest

from spectra.services import commission_compare as cc
from spectra.services import commissioning, gray_code

W, H = 320, 180


# ── his real tv-mapper's shape, as stored (read from the live config) ──────
# tv-mapper: mapping "copy", five segments across three fixtures
#   tv-backlight 0-559, sconce-right 0-27, sconce-right 28-87,
#   sconce-left 0-27, sconce-left 28-87                       = 736 pixels
def _virtual(vid, segments, mapping="span", rows=1, grouping=1):
    pixels = sum(hi - lo + 1 for _d, lo, hi in segments)
    return {"id": vid, "active": True,
            "segments": [[d, lo, hi, False, 0] for d, lo, hi in segments],
            "pixel_count": pixels,
            "config": {"mapping": mapping, "rows": rows, "grouping": grouping},
            "effect": {"type": "singleColor", "config": {}}}


def _idle(virtual):
    virtual["active"] = False
    return virtual


def _his_room(tv=60, sconce=8):
    """His composition in miniature — the same SHAPE (copy mapper, five
    segments, three fixtures, two of them split in two) at a size a test
    can render. The proportions are what the code sees; the pixel counts
    only decide how long a real run takes."""
    half = sconce // 2
    return {
        "tv-mapper": _virtual("tv-mapper", [
            ("tv-backlight", 0, tv - 1),
            ("sconce-kitchen-right", 0, half - 1),
            ("sconce-kitchen-right", half, sconce - 1),
            ("sconce-kitchen-left", 0, half - 1),
            ("sconce-kitchen-left", half, sconce - 1)], mapping="copy"),
        # IDLE, exactly as his real config has them: the copy carrier
        # stands in front of them, so the run has to bring each one up for
        # the capture and put it back.
        "tv-backlight": _idle(_virtual("tv-backlight",
                                       [("tv-backlight", 0, tv - 1)])),
        "sconce-kitchen-left": _idle(_virtual(
            "sconce-kitchen-left", [("sconce-kitchen-left", 0, sconce - 1)])),
        "sconce-kitchen-right": _idle(_virtual(
            "sconce-kitchen-right", [("sconce-kitchen-right", 0, sconce - 1)])),
    }


def _truth_layout(total: int, tv: int, sconce: int):
    """WHERE those pixels actually are, in the fake camera's frame: the TV
    as a wrapped ring, each sconce as a short vertical line to one side —
    his room's shape, and the answer the run must recover."""
    layout = {}
    per = tv // 4
    for i in range(tv):
        side, k = i // per, (i % per) / per
        if side == 0:
            layout[i] = (0.30 + 0.40 * k, 0.25)
        elif side == 1:
            layout[i] = (0.70, 0.25 + 0.35 * k)
        elif side == 2:
            layout[i] = (0.70 - 0.40 * k, 0.60)
        else:
            layout[i] = (0.30, 0.60 - 0.35 * k)
    for j in range(sconce):
        layout[tv + j] = (0.86, 0.30 + 0.30 * j / max(1, sconce - 1))
    for j in range(sconce):
        layout[tv + sconce + j] = (0.14, 0.30 + 0.30 * j / max(1, sconce - 1))
    assert len(layout) == total
    return layout


# ── the fakes ──────────────────────────────────────────────────────────────

class FakeSession:
    """A phone that is connected, locked, and renders whatever the run last
    wrote — including WHEN each fixture's light arrives, so the latency row
    is measuring something real rather than a stub. `render(elapsed_ms)` is
    supplied by the harness so a test can corrupt the room, or delay one
    fixture, without touching the run."""

    def __init__(self, render, clock, *, fps=30.0):
        self.pose_id = "pose-test"
        self.run_abort = None
        self.keep_full_frames = False
        self.full = []
        self._render = render
        self._clock = clock
        self._fps = fps
        self.lock = type("L", (), {"exposure_locked": True,
                                   "white_balance_locked": True,
                                   "exposure_mode": "manual",
                                   "white_balance_mode": "manual"})()

    def refusal(self):
        return None

    async def gather_full(self, seconds, *, min_frames=1):
        n = max(min_frames, int(seconds * self._fps))
        start = self._clock()
        self._advance(seconds)
        out = []
        for k in range(n):
            at = start + k / self._fps
            out.append(type("TF", (), {
                "at_s": at,
                "frame": self._render(
                    (at - self._write_at) * 1000.0).astype(np.uint8)})())
        return out

    #: when the run last landed a write, in the harness's own clock — what
    #: a fixture's arrival delay is measured from
    _write_at = 0.0
    #: the harness's clock, moved on by however long a gather covered
    _advance = staticmethod(lambda seconds: None)


class FakeCtx:
    def __init__(self, sink):
        self._sink = sink

    async def apply_scene(self, writes=None, transition_ms=None):
        self._sink(list(writes or []))


class Harness:
    """The room: it holds the live virtuals, runs the REAL program's writes
    through a fake camera, and records what the run did to it."""

    def __init__(self, *, tv=60, sconce=8, dead=None, corrupt=None,
                 layout=None, fps=30.0, device_delay_ms=None,
                 radius_px=2.0):
        self.virtuals = _his_room(tv, sconce)
        self.total = tv + 2 * sconce
        self.layout = layout or _truth_layout(self.total, tv, sconce)
        self.dead = set(dead or ())
        #: how big a camera pixel each composition pixel is worth. The field
        #: regime's whole problem is that this is far too small to tell them
        #: apart — see `test_a_composition_the_camera_cannot_resolve...`.
        self.radius_px = radius_px
        self.corrupt = corrupt          # callable(lit set) -> lit set
        self.writes: list[dict] = []
        self.closed = 0
        self.activated: list[str] = []
        self.deactivated: list[str] = []
        self.t = 0.0
        #: how long after a write each fixture's light actually appears —
        #: the thing row 5 measures. Zero for all of them by default.
        self.device_delay_ms = dict(device_delay_ms or {})
        self._blobs: dict = {}
        self._frame_cache: dict = {}
        self._write_seq = 0
        self.session = FakeSession(self.render, lambda: self.t, fps=fps)
        self.session._advance = self._advance_clock
        self.composition = None

    # the lamp -> the camera
    def _lit_indices(self) -> set[int]:
        lit: set[int] = set()
        for write in self.writes:
            if write.get("effect_type") != commissioning.PATTERN_EFFECT_TYPE:
                continue
            pattern = (write.get("config") or {}).get("pattern") or ""
            arr = self.composition.pixel_map.get(write["virtual_id"])
            if arr is None:
                continue
            for pixel, char in enumerate(pattern):
                if char == "1" and pixel < len(arr) and arr[pixel] >= 0:
                    lit.add(int(arr[pixel]))
        if self.corrupt is not None:
            lit = self.corrupt(lit)
        return lit

    def _device_of(self, index: int) -> str:
        for seg in self.composition.segments:
            if seg.start <= index <= seg.end:
                return seg.device_id
        return ""

    def render(self, elapsed_ms: float = 1e9) -> np.ndarray:
        """The room as the camera sees it `elapsed_ms` after the last write:
        a fixture whose light has not arrived yet is still dark.

        Cached per (write, set of arrived fixtures) so a fast camera in a
        test renders three distinct pictures rather than three hundred
        identical ones."""
        arrived = tuple(sorted(d for d, ms in
                               [(d, self.device_delay_ms.get(d, 0.0))
                                for d in self.composition.devices]
                               if ms <= elapsed_ms))
        key = (self._write_seq, arrived)
        got = self._frame_cache.get(key)
        if got is None:
            lit = {i for i in self._lit_indices()
                   if self._device_of(i) in arrived}
            got = gray_code.render_frame(
                self.layout, lit, width=W, height=H,
                radius_px=self.radius_px, dead=self.dead, blobs=self._blobs)
            self._frame_cache[key] = got
        return got

    # the deps
    def deps(self):
        from spectra.services import room_mapping

        async def get_virtuals():
            return self.virtuals

        async def open_hold(program, intensity, *, step, heartbeat_timeout_s):
            await program.execute(step, FakeCtx(self._take))
            return {"held": True, "step": step}

        async def close_hold():
            self.closed += 1
            return {"reverted": True}

        async def sleep(seconds):
            self.t += float(seconds)

        async def activate(vid):
            self.activated.append(vid)
            self.virtuals[vid]["active"] = True

        async def deactivate(vid):
            self.deactivated.append(vid)
            self.virtuals[vid]["active"] = False

        async def fixture_devices():
            return []

        async def carrier_devices():
            return {"tv-mapper": [{"id": d, "type": "wled"} for d in
                                  ("tv-backlight", "sconce-kitchen-left",
                                   "sconce-kitchen-right")]}

        return room_mapping.RunDeps(
            session=self.session, get_virtuals=get_virtuals,
            open_hold=open_hold, close_hold=close_hold, sleep=sleep,
            clock=lambda: self.t, carrier_devices=carrier_devices,
            spectra_owns=lambda: True, activate=activate,
            deactivate=deactivate, fixture_devices=fixture_devices)

    def _advance_clock(self, seconds: float) -> None:
        self.t += float(seconds)

    def _take(self, writes):
        self.writes = writes
        self._write_seq += 1
        self.t += 0.01
        self.session._write_at = self.t

    def run(self, **kw):
        comp = commissioning.resolve_composition(
            "tv-mapper", self.virtuals,
            [{"id": d, "type": "wled"} for d in
             ("tv-backlight", "sconce-kitchen-left", "sconce-kitchen-right")])
        self.composition = comp
        return asyncio.run(commissioning.run_commission(
            "tv-mapper", self.deps(), **kw))


def _rows(result):
    return {r["field"]: r for r in result.table["rows"]}


# ── the composition ────────────────────────────────────────────────────────

def test_composition_is_the_stored_mappers_own_five_segments():
    virtuals = _his_room(tv=560, sconce=88)
    comp = commissioning.resolve_composition("tv-mapper", virtuals, [])
    assert comp.total == 736                      # 560 + 28 + 60 + 28 + 60
    assert [(s.device_id, s.start, s.end) for s in comp.segments] == [
        ("tv-backlight", 0, 559),
        ("sconce-kitchen-right", 560, 603),
        ("sconce-kitchen-right", 604, 647),
        ("sconce-kitchen-left", 648, 691),
        ("sconce-kitchen-left", 692, 735)]
    # driven through the fixtures' own strips, never the copy carrier
    assert comp.virtual_ids == ["sconce-kitchen-left", "sconce-kitchen-right",
                                "tv-backlight"]
    assert comp.mapper_id not in comp.pixel_map
    # and every composition index is addressed exactly once
    used = np.concatenate([a[a >= 0] for a in comp.pixel_map.values()])
    assert sorted(used.tolist()) == list(range(736))
    assert gray_code.bits_needed(comp.total) == 10


def test_a_fixture_with_no_addressable_virtual_is_refused_by_name():
    virtuals = _his_room()
    del virtuals["sconce-kitchen-left"]
    with pytest.raises(commissioning.CompositionRefused) as exc:
        commissioning.resolve_composition("tv-mapper", virtuals, [])
    assert "sconce-kitchen-left" in str(exc.value)
    assert "cannot be commissioned as stored" in str(exc.value)


def test_grouped_pixels_are_refused_rather_than_averaged():
    virtuals = _his_room()
    virtuals["tv-backlight"]["config"]["grouping"] = 2
    with pytest.raises(commissioning.CompositionRefused) as exc:
        commissioning.resolve_composition("tv-mapper", virtuals, [])
    assert "groups 2 pixels" in str(exc.value)


def test_a_copy_mapper_with_no_stored_layout_says_so_rather_than_inventing_one():
    virtuals = _his_room()
    layout, note = commissioning.stored_layout(
        "tv-mapper", virtuals["tv-mapper"], 76, None)
    assert layout is None
    assert "stores a pixel ORDER but no 2-D layout" in note
    assert "device profile" in note


# ── the whole run, against a known arrangement ─────────────────────────────

def test_a_known_arrangement_comes_back_and_the_frozen_table_is_green(tmp_path):
    h = Harness()
    result = h.run(layout=h.layout, instrument={})
    assert result.ok, result.reason
    rows = _rows(result)
    assert rows["Pixel count seen"]["verdict"] == cc.PASS
    assert rows["Pixel ordering"]["verdict"] == cc.PASS
    assert rows["2-D arrangement"]["verdict"] == cc.PASS
    assert rows["Cross-device stitch"]["verdict"] == cc.PASS
    # the latency row has no second instrument to compare against here, so
    # it is UNMEASURED and the verdict is therefore incomplete — never a
    # silent pass
    assert rows["Device latency"]["verdict"] == cc.UNMEASURED
    assert result.table["verdict"] == "incomplete"
    # ~22 captures: dark + full + 2 per bit
    bits = gray_code.bits_needed(h.total)
    assert len(result.captures) == 2 + 2 * bits


def test_the_run_restores_in_a_finally_even_though_it_succeeded():
    h = Harness()
    result = h.run(layout=h.layout, instrument={})
    assert result.ok
    # ONE continuous hold per pass, released by the run itself
    assert h.closed == 1
    # the idle substitutes were brought up and put back
    assert set(h.activated) == set(h.deactivated) == {
        "sconce-kitchen-left", "sconce-kitchen-right", "tv-backlight"}
    # the full-resolution ring is off again
    assert h.session.keep_full_frames is False


def test_running_it_twice_bounds_the_instruments_own_noise():
    h = Harness()
    result = h.run(repeat=2, layout=h.layout, instrument={})
    assert result.ok and result.repeats == 2
    assert h.closed == 2                       # one hold per pass
    assert result.agreement["compared"] >= int(0.9 * h.total)
    assert result.agreement["median_shift"] < 0.01


# ── the corrupted stacks: each fails ITS OWN row ───────────────────────────

def test_dead_pixels_are_a_finding_about_his_hardware_not_a_failure():
    h = Harness(dead={20, 21, 44})
    result = h.run(layout=h.layout, instrument={})
    row = _rows(result)["Pixel count seen"]
    assert row["verdict"] == cc.FINDING
    assert "dead pixels" in row["indicts"]
    assert result.table["verdict"] == "incomplete"   # never "fail"
    assert any("dead pixels" in f["indicts"] for f in result.table["findings"])


def test_a_whole_occluded_stretch_indicts_the_commissioning_run():
    # a third of the TV hidden behind something: broad, not dead LEDs
    h = Harness(dead=set(range(10, 34)))
    result = h.run(layout=h.layout, instrument={})
    row = _rows(result)["Pixel count seen"]
    assert row["verdict"] == cc.FAIL
    assert "occlusion or blob-merge" in row["indicts"]
    assert result.table["verdict"] == "fail"


def test_a_scrambled_order_indicts_the_sequencing():
    """The pixels are all seen, in the right places — but the composition
    order they are addressed in is shuffled inside one segment. That is the
    table's "scrambled order" row and nothing else."""
    truth = _truth_layout(76, 60, 8)
    shuffled = dict(truth)
    block = list(range(12, 40))
    rolled = block[::-1][:7] + block[7:]
    for a, b in zip(block, rolled):
        shuffled[a] = truth[b]
    h = Harness(layout=shuffled)
    result = h.run(layout=None, instrument={})
    rows = _rows(result)
    assert rows["Pixel ordering"]["verdict"] == cc.FAIL
    assert "sequencing defect" in rows["Pixel ordering"]["indicts"]
    assert result.table["verdict"] == "fail"


def test_one_stretch_off_the_stored_layout_is_a_finding_about_his_mapper():
    """The plan's "the hand-built mapper has been slightly wrong all along"
    outcome, and the shape it really takes: the room is exactly as it always
    was, and the STORED layout has the television at the wrong angle
    relative to the sconces. Most of the composition still agrees with one
    fit; one authored stretch does not.

    Reported as a FINDING — "arguably the most valuable outcome available",
    in the plan's own words — and never as a commissioning failure."""
    h = Harness()
    stored = dict(h.layout)
    tv = [i for i in range(h.total) if i < 60]
    cx = float(np.mean([h.layout[i][0] for i in tv]))
    cy = float(np.mean([h.layout[i][1] for i in tv]))
    turn = math.radians(35)
    for i in tv:
        x, y = h.layout[i]
        dx, dy = x - cx, y - cy
        stored[i] = (cx + dx * math.cos(turn) - dy * math.sin(turn),
                     cy + dx * math.sin(turn) + dy * math.cos(turn))
    result = h.run(layout=stored, instrument={})
    row = _rows(result)["2-D arrangement"]
    assert row["verdict"] == cc.FINDING, row
    assert "hand-built mapper" in row["indicts"]
    assert result.table["verdict"] in ("findings", "incomplete")
    assert "fail" != result.table["verdict"]


def test_a_layout_nothing_agrees_with_indicts_the_camera_geometry():
    """The other side of the same row: every pixel of the stored layout
    nudged a different way. No single fit reconciles most of it, which is
    not what one wrong authored stretch looks like — so the failure indicts
    this instrument, per the table."""
    rng = np.random.default_rng(5)
    h = Harness()
    stored = {i: (min(0.99, max(0.01, x + rng.normal(0, 0.05))),
                  min(0.99, max(0.01, y + rng.normal(0, 0.05))))
              for i, (x, y) in h.layout.items()}
    result = h.run(layout=stored, instrument={})
    row = _rows(result)["2-D arrangement"]
    assert row["verdict"] == cc.FAIL
    assert "camera-geometry defect" in row["indicts"]
    assert result.table["verdict"] == "fail"


def test_a_stale_stitched_sconce_is_a_finding_about_the_stored_mapper():
    """Row 4's own his-data outcome: a sconce that is the right SHAPE in the
    wrong PLACE — a stale stored offset, not a capture that misaligned."""
    h = Harness()
    stored = dict(h.layout)
    for i in range(60, 68):                 # the whole right sconce, shifted
        x, y = stored[i]
        stored[i] = (min(0.99, x + 0.12), y)
    result = h.run(layout=stored, instrument={})
    row = _rows(result)["Cross-device stitch"]
    assert row["verdict"] == cc.FINDING
    assert "stale stitched segment" in row["indicts"]


def test_latency_disagreement_indicts_an_instrument_and_a_slow_camera_is_unmeasured():
    fast = cc.row_latency({"a": 10.0, "b": 40.0}, {"a": 0.0, "b": 5.0},
                          resolution_ms=8.0)
    assert fast.verdict == cc.FAIL
    assert "one of the two instruments" in fast.indicts

    agree = cc.row_latency({"a": 10.0, "b": 40.0}, {"a": 0.0, "b": 25.0},
                           resolution_ms=8.0)
    assert agree.verdict == cc.PASS

    slow = cc.row_latency({"a": 10.0, "b": 40.0}, {"a": 0.0, "b": 5.0},
                          resolution_ms=200.0)
    assert slow.verdict == cc.UNMEASURED
    assert "cannot resolve 15 ms" in slow.indicts


def test_the_run_measures_a_real_per_device_arrival_when_the_camera_is_fast():
    """The commissioning side of row 5 is a real measurement, not a stub:
    the fake camera's frames carry times, one fixture's light is made to
    arrive genuinely late, and the run recovers that delay from the
    dark -> full step."""
    h = Harness(fps=100.0, device_delay_ms={"sconce-kitchen-right": 40.0})
    result = h.run(layout=h.layout, instrument={})
    assert result.ok
    numbers = _rows(result)["Device latency"]["numbers"]
    assert numbers["resolution_ms"] == pytest.approx(10.0, abs=1.0)
    got = numbers["commissioning_ms"]
    assert set(got) == {"sconce-kitchen-left", "sconce-kitchen-right",
                        "tv-backlight"}
    # the injected 40 ms comes back, within the camera's own 5 ms cadence
    assert got["sconce-kitchen-right"] - got["tv-backlight"] == \
        pytest.approx(40.0, abs=8.0)


def test_the_two_instruments_are_compared_as_differences_and_can_disagree():
    """Row 5 end to end on the run itself: an instrument that AGREES with
    the measured delay passes; one that does not is a FAIL that indicts an
    instrument rather than the fixture."""
    delay = {"sconce-kitchen-right": 40.0}
    agreeing = Harness(fps=100.0, device_delay_ms=delay).run(
        layout=None,
        instrument={"tv-backlight": 0.0, "sconce-kitchen-right": 40.0,
                    "sconce-kitchen-left": 0.0})
    row = _rows(agreeing)["Device latency"]
    assert row["verdict"] == cc.PASS, row

    disagreeing = Harness(fps=100.0, device_delay_ms=delay).run(
        layout=None,
        instrument={"tv-backlight": 0.0, "sconce-kitchen-right": 0.0,
                    "sconce-kitchen-left": 0.0})
    row = _rows(disagreeing)["Device latency"]
    assert row["verdict"] == cc.FAIL
    assert "one of the two instruments" in row["indicts"]


# ── refusals, before anything is written ──────────────────────────────────

def test_an_unlocked_camera_refuses_before_a_light_is_touched():
    h = Harness()
    h.session.refusal = lambda: "this browser will not lock EXPOSURE"
    result = h.run(layout=h.layout, instrument={})
    assert not result.ok and result.refusal == "camera_lock"
    assert h.writes == [] and h.closed == 0


def test_spot_effects_owning_the_lights_refuses_by_name():
    from spectra.services import room_mapping
    h = Harness()
    h.composition = commissioning.resolve_composition("tv-mapper", h.virtuals, [])
    deps = h.deps()
    deps = room_mapping.RunDeps(**{**deps.__dict__, "spectra_owns": lambda: False})
    result = asyncio.run(commissioning.run_commission("tv-mapper", deps))
    assert not result.ok and result.refusal == "ownership"
    assert "pattern lamp is an effect inside this process" in result.reason
    assert h.writes == []


# ── the store ──────────────────────────────────────────────────────────────

def test_results_are_stored_bounded_and_a_refusal_is_stored_too(tmp_path):
    path = tmp_path / "commissioning.json"
    h = Harness()
    body = commissioning.save_result(h.run(layout=h.layout, instrument={}),
                                     path=path)
    assert body["verdict"] == "incomplete"
    refused = commissioning.RunResult(mapper_id="tv-mapper", ok=False,
                                      reason="camera not locked",
                                      refusal="camera_lock")
    commissioning.save_result(refused, path=path)
    rows = commissioning.load_results(path)
    assert len(rows) == 2 and rows[-1]["refusal"] == "camera_lock"
    json.loads(path.read_text())            # genuinely serialisable
    for _ in range(commissioning.MAX_STORED_RESULTS + 3):
        commissioning.save_result(refused, path=path)
    assert len(commissioning.load_results(path)) == \
        commissioning.MAX_STORED_RESULTS


# ── THE FIELD REGIME (2026-09-01) ─────────────────────────────────────────
#
# Both of his real runs held the room dark for ~42 s, decoded 0 of 736, and
# handed the frozen table a "0 of 736" it could only attribute to occlusion
# or blob-merge — pointing at his room for a camera that, from where it was
# standing, images the whole composition into a few dozen pixels. The run
# now asks that question from the reference pair alone.

def _one_glow(total: int, span_px: float = 6.0):
    """Every composition pixel inside one small glow — his pose, where the
    whole thing arrives as three of these."""
    return {i: ((160.0 + (i / max(1, total - 1) - 0.5) * span_px) / W,
                90.0 / H) for i in range(total)}


def test_a_composition_the_camera_cannot_resolve_is_refused_by_name():
    h = Harness(layout=_one_glow(76), radius_px=1.0)
    result = h.run(layout=h.layout, instrument={})
    assert not result.ok
    assert result.refusal == "resolution"
    # the sentence names the measurement, the bar and what to do
    assert "cannot tell these pixels apart" in result.reason
    assert "camera pixels" in result.reason and "closer" in result.reason
    # TWO captures, not twenty-two: the dark and full references answer it
    assert len(result.captures) == 2
    assert [c["label"] for c in result.captures] == ["run1/dark", "run1/full"]
    # nothing judged, nothing claimed
    assert result.table == {} and result.decodes == []
    assert result.verdict == "refused"
    # and the measurement itself travels with the refusal
    assert 0 < result.resolution["camera_px_per_index"] < 2.0
    assert result.resolution["needed_camera_px"] == 152


def test_the_room_is_put_back_after_an_unresolvable_refusal():
    h = Harness(layout=_one_glow(76), radius_px=1.0)
    h.run(layout=h.layout, instrument={})
    assert h.closed == 1
    assert set(h.activated) == set(h.deactivated) == {
        "sconce-kitchen-left", "sconce-kitchen-right", "tv-backlight"}
    assert h.session.keep_full_frames is False


def test_a_resolvable_run_carries_the_same_measurement(tmp_path):
    """The number is worth as much on a green run — it says how much margin
    the pose had — so it is reported, not only refused on."""
    h = Harness()
    result = h.run(layout=h.layout, instrument={})
    assert result.ok
    assert result.resolution["resolvable"] is True
    assert result.resolution["camera_px_per_index"] >= 2.0
    assert result.decodes[0]["resolution"]["total"] == h.total
    # and every bit's own contrast, so a future failure says where it died
    contrast = result.decodes[0]["bit_contrast"]
    assert len(contrast) == gray_code.bits_needed(h.total)
    assert all(c["median_strength"] > gray_code.BIT_CONFIDENCE
               for c in contrast)
