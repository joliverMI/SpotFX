"""THE POSE FINGERPRINT, PROVEN IN EVERY DIRECTION IT CAN ANSWER.

The captain's requirement is what this file is written against: the
fingerprint must tell A MOVED CAMERA from A CHANGED ROOM, must NAME which it
believes, and must PREFER SAYING IT CANNOT TELL over guessing. A gate that
only ever refuses is a wall, and a gate that always answers confidently is
worse than one that says nothing — so every case here is proven, including
the ones whose right answer is "I do not know":

  MATCH         nothing moved.
  CAMERA MOVED  every anchor shifted by the same vector.
  ROOM CHANGED  one anchor moved and the others did not.
  CANNOT TELL   parallax (all moved, by different amounts); too few anchors;
                anchors all lighting one corner; an anchor that vanished;
                everything dimming together.

Half the file drives the REAL machinery — `pose_fingerprint.measure` through
`room_mapping._map_one`, the real footprint arithmetic and the real
centroid — against a synthetic camera that renders each fixture's light as a
soft blob at a known place. Moving the camera is moving every blob; moving
the room is moving one. Nothing here touches a room, a light or a webcam.
"""
from __future__ import annotations

import asyncio
import math

import numpy as np
import pytest

from spectra.models.calibration import PoseReference
from spectra.models.room_map import GRID_H, GRID_W, AxisCalibration, Point, RoomMap
from spectra.services import lever_selftest, light_field, mapping_refusals
from spectra.services import capture_settings as cs
from spectra.services import pose_fingerprint as pf
from spectra.services import room_mapping

AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))

#: A fixture's light lands as a soft blob. SMOOTH rather than a block of
#: cells on purpose: a hard-edged patch quantises its own centroid to the
#: 1/64 grid, which is half the tolerance under test, so the sub-cell
#: precision this whole design rests on could not be measured at all.
BLOB_SIGMA = 0.05
BLOB_PEAK = 200.0
#: What this camera settles on when nothing commands an integration time —
#: `lever_selftest.DEFAULT_BRIGHT_EXPOSURE`, so an ordinary capture and the
#: self-test's own bright regime measure the same room.
CONVERGED_EXPOSURE = float(lever_selftest.DEFAULT_BRIGHT_EXPOSURE)

_CX = (np.arange(GRID_W) + 0.5) / GRID_W
_CY = (np.arange(GRID_H) + 0.5) / GRID_H
_X, _Y = np.meshgrid(_CX, _CY)


def _blob(cx: float, cy: float, peak: float = BLOB_PEAK) -> np.ndarray:
    d2 = (_X - cx) ** 2 + (_Y - cy) ** 2
    return peak * np.exp(-d2 / (2 * BLOB_SIGMA ** 2))


class _SyntheticRoom:
    """WHERE EACH FIXTURE'S LIGHT LANDS, as this camera sees it.

    Moving the CAMERA is `shift()` — every blob moves by one vector, which
    is exactly what a camera rotation does to a frame. Moving the ROOM is
    `move_one()` — one blob moves and the rest do not. That is the whole
    experiment, and it is why this class exists rather than a canned array."""

    def __init__(self, blobs: dict[str, tuple[float, float]],
                 peaks: dict[str, float] | None = None):
        self.blobs = dict(blobs)
        self.peaks = dict(peaks or {})

    def shift(self, dx: float, dy: float) -> "_SyntheticRoom":
        return _SyntheticRoom({v: (x + dx, y + dy)
                               for v, (x, y) in self.blobs.items()}, self.peaks)

    def move_one(self, vid: str, dx: float, dy: float) -> "_SyntheticRoom":
        out = dict(self.blobs)
        x, y = out[vid]
        out[vid] = (x + dx, y + dy)
        return _SyntheticRoom(out, self.peaks)

    def dim(self, vid: str, factor: float) -> "_SyntheticRoom":
        peaks = dict(self.peaks)
        peaks[vid] = peaks.get(vid, BLOB_PEAK) * factor
        return _SyntheticRoom(self.blobs, peaks)

    def dim_all(self, factor: float) -> "_SyntheticRoom":
        return _SyntheticRoom(self.blobs, {v: self.peaks.get(v, BLOB_PEAK) * factor
                                           for v in self.blobs})

    def hide(self, vid: str) -> "_SyntheticRoom":
        return self.dim(vid, 0.0)

    def frame(self, lit: list[str], rng=None, scale: float = 1.0) -> np.ndarray:
        grid = np.zeros((GRID_H, GRID_W), dtype=np.float64)
        for vid in lit:
            if vid not in self.blobs:
                continue
            cx, cy = self.blobs[vid]
            grid += _blob(cx, cy, self.peaks.get(vid, BLOB_PEAK) * scale)
        if rng is not None:
            grid = grid + rng.uniform(-2.0, 2.0, grid.shape)
        return np.clip(grid, 0.0, 255.0)


class _Session(cs.SessionCameraDouble):
    """A connected, locked, NATIVE camera session pointed at a synthetic
    room. `lit` is set by the fake hold as the real one would be — the
    program's own `lit_virtual_ids` for the "lit" step, nothing for "dark"."""
    pose_id = "pose-fp"
    id = "sess-fp"
    closed = False
    run_abort = None
    keep_full_frames = False
    lever_verdict = None
    source_size = (320, 180)

    class lock:
        exposure_locked = True
        white_balance_locked = True
        exposure_mode = "manual"
        white_balance_mode = "manual"
        locked = True

        @staticmethod
        def as_dict():
            return {"exposure_locked": True, "white_balance_locked": True,
                    "exposure_time": None, "gain": None,
                    "exposure_time_range": [3.0, 2047.0],
                    "manual_refusals": []}

    def __init__(self, room: _SyntheticRoom, *, noise: bool = False,
                 seed: int = 7, native: bool = True, host: str = "capture-pi",
                 device: str = "/dev/video0"):
        self.room = room
        self.lit: list[str] = []
        self.frames_per_capture = room_mapping.MIN_FRAMES
        self.rng = np.random.default_rng(seed) if noise else None
        self.hello = ({"client": lever_selftest.NATIVE_CLIENT, "host": host,
                       "camera": {"kind": "v4l2", "device": device}}
                      if native else {"user_agent": "Mozilla/5.0 (iPhone)"})
        self.camera_lock = dict(self.lock.as_dict())

    def refusal(self):
        return None

    def _camera_clock(self):
        return 0.0

    def _camera_lock_view(self):
        return {**self.camera_lock,
                "exposure_time": self.camera_request.exposure_time,
                "gain": self.camera_request.gain}

    async def gather(self, seconds, min_frames=1):
        n = max(min_frames, self.frames_per_capture)
        grids = [self.room.frame(self.lit, self.rng, scale=self.exposure_scale)
                 for _ in range(n)]
        return grids, [int(g.max()) for g in grids]

    @property
    def exposure_scale(self) -> float:
        """AN HONEST SENSOR: more commanded integration time, more light.
        Nothing in this file exercises it (a fingerprint pass commands
        nothing), but `capture_runs` runs the LEVER SELF-TEST before every
        calibration-grade run, and a camera whose light does not follow its
        own command would refuse every one of them — which is exactly what
        that self-test is for."""
        asked = self.camera_request.exposure_time
        return 1.0 if asked is None else float(asked) / CONVERGED_EXPOSURE


def _virtual(device):
    return {"active": True, "pixel_count": 20, "config": {"grouping": 1},
            "segments": [[device, 0, 19, False]],
            "effect": {"type": "singleColor", "config": {}}}


CARRIERS = ["north", "east", "south", "west"]
#: Anchors well spread across the frame and clear of its edges, so a blob's
#: centroid is not clipped by the frame boundary.
SPREAD_ROOM = _SyntheticRoom({
    "north": (0.25, 0.25), "east": (0.75, 0.30),
    "south": (0.70, 0.72), "west": (0.28, 0.70)})


def _deps(session, carriers=CARRIERS, save_room=None):
    async def get_virtuals():
        return {c: _virtual(f"{c}-fixture") for c in carriers}

    async def chains():
        return {c: [{"id": f"{c}-fixture", "type": "wled"}] for c in carriers}

    async def open_hold(program, intensity, *, step="dark", **kw):
        session.lit = list(program.lit_virtual_ids) if step == "lit" else []
        return {"held": True}

    async def close_hold():
        return None

    async def sleep(_s):
        return None

    return room_mapping.RunDeps(
        session=session, get_virtuals=get_virtuals, carrier_devices=chains,
        open_hold=open_hold, close_hold=close_hold, sleep=sleep,
        clock=lambda: 0.0, spectra_owns=lambda: True, save_room=save_room)


def _room(carriers=CARRIERS):
    return RoomMap(name="Lounge", carrier_ids=list(carriers), axis=AXIS)


def _measure(synthetic, *, emitter_ids=None, noise=False, seed=7):
    sess = _Session(synthetic, noise=noise, seed=seed)
    return asyncio.run(pf.measure(_room(), _deps(sess),
                                  emitter_ids=emitter_ids))


def _ref(emitter_id, x, y, weight=30.0, seen=True):
    return PoseReference(emitter_id=emitter_id, label=emitter_id, x=x, y=y,
                         weight=weight, seen=seen)


# ── 1. the measurement runs through the real machinery ─────────────────────

def test_it_measures_where_each_fixture_lands_its_light():
    """The whole chain: the map's own `_map_one`, the real footprint
    arithmetic, the real centroid. A blob painted at (0.25, 0.25) must come
    back at (0.25, 0.25)."""
    got = _measure(SPREAD_ROOM)
    assert {r.emitter_id for r in got.references} == set(CARRIERS)
    by_id = {r.emitter_id: r for r in got.references}
    for vid, (cx, cy) in SPREAD_ROOM.blobs.items():
        r = by_id[vid]
        assert r.seen, r
        assert math.dist((r.x, r.y), (cx, cy)) < 0.01, (vid, r)
        assert r.weight > light_field.UNSEEN_WEIGHT


def test_a_fixture_the_camera_cannot_see_is_a_reading_not_an_omission():
    """"We drove it and it was dark" and "we never drove it" are different
    facts — `EmitterFootprint.unseen`'s own rule, one level up."""
    got = _measure(SPREAD_ROOM.hide("east"))
    by_id = {r.emitter_id: r for r in got.references}
    assert set(by_id) == set(CARRIERS)
    assert by_id["east"].seen is False
    assert all(by_id[v].seen for v in ("north", "south", "west"))


def test_it_stores_nothing(tmp_path, monkeypatch):
    """A fingerprint's readings are compared with each other and must never
    be mistaken for the calibration's own map."""
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "ROOM_MAPS_FILE", tmp_path / "maps.json")
    _measure(SPREAD_ROOM)
    assert light_field.load_rooms() == []


def test_it_re_measures_only_the_named_anchors():
    got = _measure(SPREAD_ROOM, emitter_ids=["north", "south"])
    assert [r.emitter_id for r in got.references] == ["north", "south"]


def test_a_recorded_anchor_that_no_longer_resolves_is_named_not_a_crash():
    got = _measure(SPREAD_ROOM, emitter_ids=["north", "gone"])
    assert [r.emitter_id for r in got.references] == ["north"]
    assert any("gone" in p for p in got.problems)


# ── 2. THE TOLERANCE IS DERIVED, NOT ASSERTED ──────────────────────────────

def test_repeat_noise_sits_well_inside_the_centroid_tolerance():
    """`CENTROID_TOLERANCE` claims to be comfortably above the instrument's
    own wobble. MEASURE it: the same room, photographed twice with sensor
    noise, must land its centroids far closer together than the band that
    decides "moved" — otherwise the band is a number somebody hoped for."""
    a = _measure(SPREAD_ROOM, noise=True, seed=1)
    b = _measure(SPREAD_ROOM, noise=True, seed=2)
    by_a = {r.emitter_id: r for r in a.references}
    worst = max(math.dist((by_a[r.emitter_id].x, by_a[r.emitter_id].y),
                          (r.x, r.y)) for r in b.references)
    assert worst < pf.CENTROID_TOLERANCE / 3, worst
    # And a plain re-measure of an unchanged room is a MATCH end to end.
    assert pf.judge(a.references, b.references).verdict == mapping_refusals.POSE_MATCH


# ── 3. THE DISCRIMINATION, through the real measurement ────────────────────

def test_a_moved_camera_is_named_as_the_camera():
    """Every fixture's image shifts by one vector. Nothing in a room can do
    that to every fixture at once."""
    before = _measure(SPREAD_ROOM)
    after = _measure(SPREAD_ROOM.shift(0.09, -0.05))
    j = pf.judge(before.references, after.references)
    assert j.verdict == mapping_refusals.POSE_CAMERA_MOVED
    assert j.refuses is True
    assert "THE CAMERA HAS MOVED" in j.reason
    assert j.common_shift == pytest.approx(math.hypot(0.09, 0.05), abs=0.01)
    assert j.max_residual < pf.CENTROID_TOLERANCE


def test_a_LARGE_camera_move_is_still_named_as_the_camera():
    """FOUND BY SWEEPING, not by reasoning (`scripts/check_pose_fingerprint.py`
    §1): a big move pushes anchors near the frame edge partly out of shot, so
    their centroids shift LESS than the ones in the middle. Judged against a
    FIXED residual band, the most obvious camera move there is fell to
    `cannot_tell` while a small one was named — which is why the coherence
    bound is a FRACTION of the shared shift (`COHERENCE_FRACTION`) with the
    fixed band as its floor."""
    before = _measure(SPREAD_ROOM)
    after = _measure(SPREAD_ROOM.shift(0.25, 0.0))
    j = pf.judge(before.references, after.references)
    assert j.verdict == mapping_refusals.POSE_CAMERA_MOVED
    assert j.max_residual > pf.CENTROID_TOLERANCE      # the edge effect is real
    assert j.max_residual <= pf.coherence_allowance(j.common_shift)


def test_the_coherence_bound_never_lets_a_room_change_read_as_the_camera():
    """The bound grows with the shift, so it has to be shown that it cannot
    grow enough to swallow the room signature. A room change leaves at least
    one anchor PUT, so its residual is as large as its own common shift —
    a ratio of about 1.0 against a bar of a quarter."""
    before = [_ref("a", 0.2, 0.2), _ref("b", 0.8, 0.2), _ref("c", 0.5, 0.8),
              _ref("d", 0.2, 0.8)]
    for d in (0.1, 0.3, 0.6):
        after = [_ref("a", 0.2 + d, 0.2), _ref("b", 0.8, 0.2),
                 _ref("c", 0.5, 0.8), _ref("d", 0.2, 0.8)]
        j = pf.judge(before, after)
        assert j.verdict != mapping_refusals.POSE_CAMERA_MOVED, (d, j.verdict)


def test_a_changed_room_is_named_as_the_room_and_does_not_refuse():
    """THE CHAIR CASE, and the reason this whole module exists: one fixture
    reads differently, the rest land exactly where they did, and the run
    goes ahead."""
    before = _measure(SPREAD_ROOM)
    after = _measure(SPREAD_ROOM.move_one("east", 0.18, 0.10))
    j = pf.judge(before.references, after.references)
    assert j.verdict == mapping_refusals.POSE_ROOM_CHANGED
    assert j.refuses is False
    assert "THE ROOM HAS CHANGED" in j.reason
    assert j.moved == 1


def test_a_camera_slid_sideways_says_it_cannot_tell():
    """PARALLAX: a translation moves near fixtures more than far ones, so
    there is no shared vector. That is genuinely ambiguous against a room
    rearranged all at once, and the honest answer is to say so."""
    before = _measure(SPREAD_ROOM)
    slid = _SyntheticRoom({
        "north": (0.25 + 0.14, 0.25), "east": (0.75 + 0.05, 0.30),
        "south": (0.70 + 0.16, 0.72), "west": (0.28 + 0.04, 0.70)})
    after = _measure(slid)
    j = pf.judge(before.references, after.references)
    assert j.verdict == mapping_refusals.POSE_CANNOT_TELL
    assert j.refuses is False
    assert "CANNOT TELL" in j.reason
    assert "slid sideways" in j.why


def test_a_blocked_fixture_reads_as_the_room():
    """Nothing moved geometrically; one fixture lost most of its light and
    the others did not. A camera cannot do that to one fixture alone."""
    before = _measure(SPREAD_ROOM)
    after = _measure(SPREAD_ROOM.dim("west", 0.2))
    j = pf.judge(before.references, after.references)
    assert j.verdict == mapping_refusals.POSE_ROOM_CHANGED


def test_everything_dimming_together_says_it_cannot_tell():
    """A whole-frame brightness change is the camera's regime, the room's
    ambient, or a dimmer on everything. Naming one would be a guess."""
    before = _measure(SPREAD_ROOM)
    after = _measure(SPREAD_ROOM.dim_all(0.2))
    j = pf.judge(before.references, after.references)
    assert j.verdict == mapping_refusals.POSE_CANNOT_TELL


def test_one_vanished_anchor_beside_three_still_ones_is_the_room():
    """A fixture gone from the shot is ambiguous ON ITS OWN — but not beside
    three anchors that landed exactly where they did. The camera cannot have
    moved and left those three put, so the fourth going dark is the room."""
    before = _measure(SPREAD_ROOM)
    after = _measure(SPREAD_ROOM.hide("south"))
    j = pf.judge(before.references, after.references)
    assert j.verdict == mapping_refusals.POSE_ROOM_CHANGED
    assert j.refuses is False


def test_every_anchor_vanishing_says_it_cannot_tell():
    """With nothing left standing, a camera turned at a wall and a room shut
    down for the night look identical — and the answer is to say so."""
    dark = SPREAD_ROOM
    for vid in CARRIERS:
        dark = dark.hide(vid)
    j = pf.judge(_measure(SPREAD_ROOM).references, _measure(dark).references)
    assert j.verdict == mapping_refusals.POSE_CANNOT_TELL
    assert "only 0 of this pose's 4 reference fixtures produced a reading" in j.why


# ── 4. WHEN IT REFUSES TO GUESS AT ALL ─────────────────────────────────────

def test_two_anchors_can_never_discriminate_even_when_they_agree_perfectly():
    """With two shifts, any pair has a mean and equal-and-opposite
    residuals, so their agreement is an identity rather than evidence. This
    is the case that must NOT read as a moved camera."""
    before = [_ref("a", 0.2, 0.2), _ref("b", 0.8, 0.8)]
    after = [_ref("a", 0.3, 0.3), _ref("b", 0.9, 0.9)]
    j = pf.judge(before, after)
    assert j.verdict == mapping_refusals.POSE_CANNOT_TELL
    assert j.discriminating is False
    assert str(pf.MIN_DISCRIMINATING) in j.why


def test_clustered_anchors_can_never_discriminate():
    """Fixtures lighting one corner of the frame move together whichever of
    the two happened."""
    before = [_ref("a", 0.50, 0.50), _ref("b", 0.53, 0.51),
              _ref("c", 0.51, 0.54)]
    after = [_ref("a", 0.60, 0.50), _ref("b", 0.63, 0.51),
             _ref("c", 0.61, 0.54)]
    j = pf.judge(before, after)
    assert j.verdict == mapping_refusals.POSE_CANNOT_TELL
    assert j.discriminating is False
    assert "one part of the frame" in j.why


def test_an_unchanged_clustered_pose_still_matches():
    """A pose that cannot DISCRIMINATE can still tell that nothing changed —
    otherwise it would refuse to answer even the easy question."""
    refs = [_ref("a", 0.50, 0.50), _ref("b", 0.53, 0.51)]
    assert pf.judge(refs, refs).verdict == mapping_refusals.POSE_MATCH


def test_a_pose_says_at_establishment_when_it_cannot_discriminate():
    """SAID WHEN THE POSE IS TAKEN, not months later as a refusal."""
    ok, note = pf.discriminating([_ref("a", 0.2, 0.2), _ref("b", 0.8, 0.8)])
    assert ok is False
    assert "at least 3" in note
    ok2, note2 = pf.discriminating([_ref("a", 0.50, 0.50),
                                    _ref("b", 0.52, 0.51),
                                    _ref("c", 0.51, 0.53)])
    assert ok2 is False and "within" in note2
    ok3, note3 = pf.discriminating([_ref("a", 0.2, 0.2), _ref("b", 0.8, 0.2),
                                    _ref("c", 0.5, 0.8)])
    assert ok3 is True and note3 == ""


# ── 5. a different camera is a different pose, and costs no dark room ──────

def test_a_different_camera_is_the_camera_and_short_circuits():
    was = pf.identity_from_hello({"client": "spectra-capture-client",
                                  "host": "pi-a",
                                  "camera": {"device": "/dev/video0"}})
    now = pf.identity_from_hello({"client": "spectra-capture-client",
                                  "host": "pi-b",
                                  "camera": {"device": "/dev/video0"}})
    note = pf.identity_changed(was, now)
    assert "capture machine is pi-b" in note
    j = pf.judge([_ref("a", 0.2, 0.2)], [], identity_note=note)
    assert j.verdict == mapping_refusals.POSE_CAMERA_MOVED
    assert j.refuses is True
    # AND IT SAYS SO IN ITS OWN WORDS: "they all shifted together" would
    # describe a measurement this deliberately never took.
    assert "THIS IS A DIFFERENT CAMERA" in j.reason
    assert "pi-b" in j.reason


def test_a_blank_recorded_identity_never_invents_a_mismatch():
    """A fingerprint taken before a client reported an identity has nothing
    to disagree with, and inventing one out of a blank is the confident
    wrong answer this module exists to avoid."""
    assert pf.identity_changed({}, {"host": "pi-a"}) == ""
    assert pf.identity_changed({"host": ""}, {"host": "pi-a"}) == ""
    assert pf.identity_changed({"host": "pi-a"}, {}) == ""


# ── 6. anchor selection maximises spread, not brightness ───────────────────

def test_select_anchors_prefers_spread_over_a_bright_cluster():
    """A bright cluster is a WORSE fingerprint than a dimmer spread, because
    a clustered set cannot discriminate at all."""
    measured = [_ref("bright-a", 0.50, 0.50, weight=100.0),
                _ref("bright-b", 0.52, 0.51, weight=99.0),
                _ref("bright-c", 0.51, 0.53, weight=98.0),
                _ref("far-a", 0.10, 0.10, weight=20.0),
                _ref("far-b", 0.90, 0.90, weight=19.0)]
    chosen = pf.select_anchors(measured, limit=3)
    assert {c.emitter_id for c in chosen} == {"bright-a", "far-a", "far-b"}
    assert pf.discriminating(chosen)[0] is True


def test_select_anchors_drops_what_the_camera_could_not_see():
    measured = [_ref("a", 0.2, 0.2), _ref("b", 0.8, 0.8, seen=False, weight=0.0)]
    assert [c.emitter_id for c in pf.select_anchors(measured)] == ["a"]


def test_select_anchors_is_deterministic():
    measured = [_ref(f"e{i}", 0.1 * i, 0.9 - 0.1 * i, weight=50 - i)
                for i in range(8)]
    first = [c.emitter_id for c in pf.select_anchors(measured)]
    assert first == [c.emitter_id for c in pf.select_anchors(measured)]
    assert len(first) == pf.MAX_REFERENCES


# ── 7. absence ─────────────────────────────────────────────────────────────

def test_an_unestablished_pose_says_so_rather_than_matching():
    """ABSENCE IS A READ: "we have never looked" must not read as "we looked
    and everything matched"."""
    j = pf.judge([], [])
    assert j.verdict == mapping_refusals.POSE_CANNOT_TELL
    assert "no reference fixtures recorded" in j.why


def test_a_room_with_no_carriers_refuses_by_name():
    sess = _Session(SPREAD_ROOM)
    empty = RoomMap(name="Empty", carrier_ids=[], axis=AXIS)
    got = asyncio.run(pf.measure(empty, _deps(sess)))
    assert got.refusal
    assert "No pose could be recorded" in got.refusal
    assert got.references == []
