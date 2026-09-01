"""THE AMBIENT-STABILITY GATE — a window in frame, and both directions.

THE RUN THIS IS WRITTEN FROM (2026-09-01, his first per-fixture
commissioning run, the right sconce): the phone was pointed at the fixture
with a WINDOW IN VIEW, in daylight, with cloud moving. The pose was fine —
5.375 camera pixels per index, peak 49.3, floor 7.4, so the resolution gate
passed honestly. The decode still came back 34 of 88, 22 of those in the
wrong order, 392 of 473 lit camera pixels unconfident and 30 decoded
CONFIDENTLY to indices the fixture does not have. That last number is
§98's confident-wrong signature, and it can only mean the stack compared
two different scenes.

TWO DIRECTIONS, and the second is what stops the gate being a wall — the
same bar `gray_code.RESOLUTION_SAFETY_FACTOR`'s marginal boundary is held
to:

  RED    a moving cloud, at his own measured signal strength, driven
         through the REAL decode path: it reproduces today's signature
         (§98's, not the unresolvable one), and the gate refuses it BY
         NAME, early, with nothing judged.
  GREEN  a steady room, and a SHADED one that genuinely moves but stays
         inside the bound, both go all the way through to a judged table.
         A drift just under the bound passes and just over refuses, proven
         on both sides of the same number.

And one thing the gate must NOT do: absorb a failure it did not measure.
A stack broken by something else, with the ambient measured steady, still
fails the frozen table exactly as it did before this gate existed.

No room, no network, no phone: the fake camera renders from the writes the
REAL program produced, exactly as `tests/test_commissioning.py` does.
"""
from __future__ import annotations

import numpy as np
import pytest

from spectra.services import ambient_stability as amb
from spectra.services import commission_compare as cc
from spectra.services import commissioning, gray_code, mapping_refusals
from tests.test_commissioning import H, W, Harness

#: The camera's own dark level, as `gray_code.render_frame` renders it.
DARK_LEVEL = 8.0
LIT_LEVEL = 220.0
#: HIS OWN MEASURED SIGNAL, from the failing run: `peak` 49.3 grey levels.
#: The harness renders a far brighter room by default, so the red case is
#: dimmed to the field's own contrast — the bound is a fraction of `peak`,
#: so a test run at ten times his signal would prove nothing about his
#: night.
FIELD_PEAK = 49.3

#: DAYLIGHT THROUGH A WINDOW: brightest on the window side of the frame and
#: falling off across it. A graded field, not a flat rectangle, because a
#: flat one shifts every camera pixel by the same amount and is the one
#: shape a whole-frame median would notice most easily — this is the harder
#: case for the gate and the more honest one for the room.
WINDOW = ((np.linspace(1.0, 0.0, W)[None, :] ** 2)
          * np.linspace(1.0, 0.3, H)[:, None])
#: A room-wide change, for the tests that need the level they ask for to BE
#: the drift the gate measures. `WINDOW` is graded, so a 10 grey level
#: window step moves the frame's median by rather less than 10 — fine for
#: showing that a corner is caught, useless for proving a boundary.
EVERYWHERE = np.ones((H, W))


class WindowRoom(Harness):
    """The harness, with a window in shot.

    `ambient(capture_number) -> grey levels` is added to every rendered
    frame through `WINDOW`, so the room's own light moves between captures
    exactly as the weather does. `signal_peak` dims the composition to a
    stated `full - dark` peak so a test can run at the field's contrast."""

    def __init__(self, *, ambient=None, signal_peak: float | None = None,
                 field=None, **kw):
        super().__init__(**kw)
        self._ambient = ambient or (lambda _seq: 0.0)
        self._field = WINDOW if field is None else field
        self._gain = (1.0 if signal_peak is None
                      else float(signal_peak) / (LIT_LEVEL - DARK_LEVEL))

    def render(self, elapsed_ms: float = 1e9) -> np.ndarray:
        frame = np.asarray(super().render(elapsed_ms), dtype=np.float64)
        if self._gain != 1.0:
            frame = DARK_LEVEL + (frame - DARK_LEVEL) * self._gain
        level = float(self._ambient(self._write_seq))
        if level:
            frame = frame + self._field * level
        return np.clip(frame, 0.0, 255.0)


def _rows(result):
    return {r["field"]: r for r in result.table["rows"]}


def _moving_cloud(amplitude: float, period: float = 4.3):
    """Cloud crossing the sun: a smooth swing of `amplitude` grey levels
    with a period of about four shots. Deterministic — no seed, no RNG —
    so the red case is one reproducible instance of the class and not a
    lucky draw."""
    return lambda seq: amplitude / 2.0 * (
        1.0 + np.sin(2.0 * np.pi * float(seq) / period + 0.7))


def _step_at(capture: int, level: float):
    """The light changes once, part-way through the stack, and stays
    changed — the shape a cloud edge or a lamp switching on makes.

    Captures are numbered in the order the run takes them: 1 the opening
    dark, 2 the full reference, then 3/4 for bit 0 and its inverse, 5/6 for
    bit 1, and so on. A step landing on an EVEN one lands BETWEEN a pattern
    and its own inverse, which is the shape that corrupts a bit and the one
    the pair delta is built to catch."""
    return lambda seq: (level if int(seq) >= capture else 0.0)


# ── RED: today's signature, and the gate refusing it ──────────────────────

def test_a_moving_cloud_reproduces_todays_confident_wrong_signature():
    """The synthetic weather is the right weather: driven through the REAL
    decoder it produces §98's CONFIDENT-WRONG signature — real contrast on
    the low bit AND camera pixels decoding confidently to indices that do
    not exist — and not the unresolvable one, whose low bit is dead."""
    h = Harness()
    dark, full, pairs = gray_code.synthetic_stack(
        h.layout, width=W, height=H, radius_px=2.0,
        dark_level=DARK_LEVEL, lit_level=DARK_LEVEL + FIELD_PEAK)
    cloud = _moving_cloud(50.0)
    frames = [dark, full] + [f for pair in pairs for f in pair]
    shifted = [np.clip(f + WINDOW * cloud(i), 0.0, 255.0)
               for i, f in enumerate(frames)]
    drifted = gray_code.decode_stack(
        shifted[0], shifted[1],
        list(zip(shifted[2::2], shifted[3::2])), total=h.total)
    signature = gray_code.confident_wrong_signature(drifted)

    assert drifted.out_of_range_pixels > 0
    assert signature["low_bit_has_contrast"], signature
    assert signature["present"], signature
    # AND IT IS NOT THE OTHER FAILURE. The pose can resolve this target
    # perfectly well — which is exactly why the resolution gate let his
    # real run through and why this one was needed.
    assert drifted.resolution["verdict"] == gray_code.RESOLUTION_OK

    # the same stack with the weather held still decodes cleanly, so the
    # cloud is the only thing being tested here
    steady = gray_code.decode_stack(dark, full, pairs, total=h.total)
    assert steady.out_of_range_pixels == 0
    assert len(steady.seen) == h.total


def test_the_gate_refuses_a_moving_cloud_by_name_and_judges_nothing():
    h = WindowRoom(ambient=_moving_cloud(50.0), signal_peak=FIELD_PEAK)
    result = h.run(layout=h.layout, instrument={})

    assert not result.ok
    assert result.refusal == "ambient"
    # NOTHING WAS JUDGED. A refusal is a refusal, not a verdict.
    assert not result.table
    assert result.verdict == "refused"

    said = result.reason
    # HIS OWN NOUNS, and his own three options — never "unstable ambient".
    assert "window" in said.lower()
    assert "shade" in said.lower()
    assert "out of frame" in said.lower()
    assert "dark outside" in said.lower()
    assert "ambient" not in said.lower()
    # THE MEASUREMENT TRAVELS WITH THE SENTENCE, so the boundary is
    # inspectable rather than a number buried in a module.
    assert "grey levels" in said

    track = result.ambient
    assert track["measurable"] and track["exceeded"]
    assert track["max_drift"] > track["bound"] > 0
    assert track["bound"] == pytest.approx(
        amb.DRIFT_FRACTION_OF_PEAK * track["peak"], rel=1e-6)


def test_the_gate_refuses_early_rather_than_spending_the_rooms_dark_time():
    """CHECK BEFORE THE COST: the cloud arrives part-way through the stack
    and the run stops there, not at the end of it."""
    bits = gray_code.bits_needed(Harness().total)
    whole_stack = 3 + 2 * bits
    h = WindowRoom(ambient=_step_at(6, 40.0), signal_peak=FIELD_PEAK,
                   field=EVERYWHERE)
    result = h.run(layout=h.layout, instrument={})

    assert result.refusal == "ambient"
    # capture 6 is bit 1's inverse — the run stops on the pair it broke
    assert len(result.captures) == 6, [c["label"] for c in result.captures]
    assert result.captures[-1]["label"].endswith("bit1-inv")
    assert len(result.captures) < whole_stack
    # and the hold was released, not left holding his room dark
    assert h.closed >= 1


# ── GREEN: a gate that refuses everything is a wall ───────────────────────

def test_a_steady_room_passes_the_gate_and_the_measurement_goes_through():
    h = WindowRoom(signal_peak=FIELD_PEAK)
    result = h.run(layout=h.layout, instrument={})

    assert result.ok, result.reason
    rows = _rows(result)
    assert rows["Pixel count seen"]["verdict"] == cc.PASS
    assert rows["Pixel ordering"]["verdict"] == cc.PASS
    track = result.ambient
    assert track["measurable"] and not track["exceeded"]
    assert track["max_drift"] <= track["bound"]
    # the closing dark is a real, lamp-free reading and it is in the record
    assert any(r["label"].endswith("/dark-end") for r in track["readings"])


def test_a_shaded_window_that_really_moves_still_lets_the_run_through():
    """THE TWO-SIDED HALF. This room's light genuinely changes — a shaded
    window, or dusk coming on slowly — by more than nothing and less than
    the bound, and the run measures the fixture rather than refusing."""
    bound = amb.drift_bound(FIELD_PEAK)
    h = WindowRoom(signal_peak=FIELD_PEAK, field=EVERYWHERE,
                   ambient=_step_at(6, bound * 0.6))
    result = h.run(layout=h.layout, instrument={})

    assert result.ok, result.reason
    assert _rows(result)["Pixel ordering"]["verdict"] == cc.PASS
    track = result.ambient
    assert not track["exceeded"]
    assert 0.0 < track["max_drift"] <= track["bound"]


@pytest.mark.parametrize("factor,refused", [(0.7, False), (1.6, True)])
def test_the_bound_is_proven_on_both_sides_of_the_same_number(factor,
                                                              refused):
    """The marginal boundary's own bar: a number worth having is one that
    lets the case just under it through."""
    h = WindowRoom(signal_peak=FIELD_PEAK, field=EVERYWHERE,
                   ambient=_step_at(6, amb.drift_bound(FIELD_PEAK) * factor))
    result = h.run(layout=h.layout, instrument={})

    assert (result.refusal == "ambient") is refused, result.reason
    assert bool(result.table) is not refused
    assert result.ambient["exceeded"] is refused


# ── the gate must not absorb what it did not measure ──────────────────────

def test_a_steady_room_with_a_broken_stack_still_fails_the_frozen_table():
    """A scrambled stack is a real finding about his composition. The
    ambient gate measured the room steady, so it stands aside and the
    frozen table's own verdict is exactly what it was before this gate
    existed."""
    def scramble(lit):
        return {(i + 7) % 76 if i >= 30 else i for i in lit}

    h = WindowRoom(signal_peak=FIELD_PEAK, corrupt=scramble)
    result = h.run(layout=h.layout, instrument={})

    assert result.ok, result.reason
    assert not result.refusal
    assert result.ambient["measurable"] and not result.ambient["exceeded"]
    assert result.table["verdict"] in (cc.FAIL, "fail", "findings",
                                       "incomplete")
    assert _rows(result)["Pixel ordering"]["verdict"] != cc.PASS


def test_the_refusal_names_the_confirmation_only_when_it_has_one():
    """The cheap cross-check is a CONFIRMATION of a refusal that already
    stands on its own measurement — present when a whole stack happens to
    exist at the moment of refusal, and simply absent otherwise. It is
    never what the refusal rests on."""
    track = {"bound": 5.0, "max_drift": 22.0, "peak": 49.3,
             "worst": {"label": "run1/bit3", "kind": "pair",
                       "pair_label": "run1/bit3-inv", "worst_tile": "0,1"}}
    bare = mapping_refusals.ambient_drift(track, target_label="sconce-right")
    assert "decoded" not in bare
    confirmed = mapping_refusals.ambient_drift(
        track, target_label="sconce-right",
        signature={"present": True, "out_of_range_pixels": 30})
    assert "30 camera pixels decoded" in confirmed
    assert "different scenes" in confirmed
    # a signature that is NOT present never becomes a claim
    quiet = mapping_refusals.ambient_drift(
        track, signature={"present": False, "out_of_range_pixels": 0})
    assert "decoded" not in quiet


# ── it never refuses because it could not measure ─────────────────────────

def test_a_fixture_that_lights_the_walls_is_reported_never_refused():
    """A GATE THAT REFUSES EVERYTHING IS A WALL. A fixture whose own light
    reaches the whole frame puts a large, permanent distance between every
    lamp-ON capture and the opening dark — and none of it is the room. The
    spill is reported; only the lamp-free comparisons decide."""
    dark = np.full((H, W), 8.0)
    full = np.full((H, W), 200.0)          # the fixture fills the frame
    track = amb.AmbientTrack.open(dark, full)

    assert track.measurable
    assert track.spill > track.bound       # and it is visible in the record
    lit = track.observe("pattern", np.full((H, W), 120.0))
    assert lit.whole > track.bound         # measured...
    assert not lit.exceeded                # ...and never gated
    assert track.as_dict()["max_drift"] == 0.0
    assert track.as_dict()["max_seen"] > track.bound


def test_a_frame_with_no_room_left_to_measure_stands_down():
    """"We could not check" and "we checked and it was fine" are different
    facts — the same distinction `witness.py` and `night_exit.py` draw."""
    dark = np.full((8, 8), 8.0)            # 64 camera pixels in total
    track = amb.AmbientTrack.open(dark, dark + 40.0)

    assert not track.measurable
    assert "ambient was NOT checked" in track.note
    assert not track.observe("x", dark + 90.0, lamp_free=True).exceeded


def test_the_background_set_survives_a_step_between_the_two_references():
    """A QUANTILE, NOT A THRESHOLD: an ambient step BETWEEN the dark and
    full references inflates `full - dark` everywhere, which is exactly
    when the gate must not go blind."""
    h = Harness()
    dark, full, _pairs = gray_code.synthetic_stack(
        h.layout, width=W, height=H, radius_px=2.0,
        dark_level=DARK_LEVEL, lit_level=DARK_LEVEL + FIELD_PEAK)
    stepped = np.clip(full + 30.0, 0.0, 255.0)
    track = amb.AmbientTrack.open(dark, stepped)

    assert track.measurable
    assert track.background_px >= amb.MIN_BACKGROUND_PX
    # A THRESHOLD would have collapsed the background set to nothing here.
    # The set survives, so the CLOSING dark still catches the step — late,
    # which is the right size of catch for a change that cancels in every
    # bit and only moves the brightness reference.
    end = track.observe("dark-end", np.clip(dark + 30.0, 0.0, 255.0),
                        lamp_free=True)
    assert end.exceeded and end.kind in ("whole", "regional")


def test_a_window_lifting_one_corner_is_caught_regionally():
    """A window is a REGION. A tile can move by twenty grey levels while
    the whole-frame median barely notices."""
    h = Harness()
    dark, full, _pairs = gray_code.synthetic_stack(
        h.layout, width=W, height=H, radius_px=2.0,
        dark_level=DARK_LEVEL, lit_level=DARK_LEVEL + FIELD_PEAK)
    track = amb.AmbientTrack.open(dark, full)
    corner = np.array(dark, dtype=np.float64)
    corner[: H // 4, : W // 4] += 4.0 * track.bound

    reading = track.observe("corner", corner, lamp_free=True)
    assert reading.exceeded and reading.kind == "regional"
    assert reading.regional > reading.whole
    assert reading.worst_tile == "0,0"


# ── the harness must be able to fail on the defect it was written for ─────

def test_without_the_gate_the_same_cloud_produces_todays_outcome(
        monkeypatch):
    """A PROOF BAR THAT CANNOT FAIL ON ITS OWN DEFECT IS DECORATION.

    With the bound lifted out of reach — the world as it was before this
    gate existed — the identical moving cloud runs the whole stack, spends
    the room's dark time, and hands the frozen table a decode to judge:
    exactly what happened in his room, and exactly what the refusal above
    is standing in front of."""
    monkeypatch.setattr(amb, "DRIFT_FLOOR_LEVELS", 1e9)
    monkeypatch.setattr(amb, "DRIFT_FRACTION_OF_PEAK", 1e9)
    h = WindowRoom(ambient=_moving_cloud(50.0), signal_peak=FIELD_PEAK)
    result = h.run(layout=h.layout, instrument={})

    assert not result.refusal            # nothing refused it
    assert result.table                  # and a table WAS judged
    assert result.table["verdict"] != "pass"
    # the whole stack was taken, at his room's expense
    bits = gray_code.bits_needed(h.total)
    assert len(result.captures) == 3 + 2 * bits


def test_the_closing_dark_catches_a_change_that_arrives_and_stays():
    """THE CHEAP CASE, AND WHY THE EXTRA CAPTURE EARNS ITS PLACE.

    A room light that comes on part-way and STAYS on lands on a pattern
    AND its own inverse, so it cancels in `pattern - inverse` exactly as it
    cancels in the bit — no pair delta sees it, and correctly so, because
    it corrupts no bit. What it does corrupt is the brightness reference
    every bit is judged against, and the only reading that can see it is a
    second dark taken with the lamp off again."""
    h = WindowRoom(signal_peak=FIELD_PEAK, field=EVERYWHERE,
                   ambient=_step_at(7, amb.drift_bound(FIELD_PEAK) * 3.0))
    result = h.run(layout=h.layout, instrument={})

    assert result.refusal == "ambient"
    assert result.captures[-1]["label"].endswith("/dark-end")
    worst = result.ambient["worst"]
    assert worst["lamp_free"] and worst["kind"] in ("whole", "regional")
    assert "dark-end" in worst["label"]
    # no pair ever saw it — the run went all the way to the closing dark
    bits = gray_code.bits_needed(h.total)
    assert len(result.captures) == 3 + 2 * bits
    assert not result.table
