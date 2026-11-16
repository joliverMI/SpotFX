"""Headless proof for the Word Shapes shape library (Word Shapes plan row
W0.1, section 2.1): `fx/effects/word_shapes.py`, its told-key helper
`fx/effects/word_shape_keys.py`, and `scripts/check_word_shapes.py`.

Nothing here renders, writes or reaches anything live — it is pure
geometry and the read-only check script against the stored device profile.

What it holds down, and why each one earned a test:

- The three shipped entries, their unit box and their winding, so an
  effect can trust `SIZE * view` without re-measuring anything.
- `polar` against an INDEPENDENT ray cast of the same polyline (bisection
  on the sdf vs an analytic ray/segment solve), exactly and at the worst
  half-bin offset — the interpolation error is pinned so a future change
  to POLAR_BINS or an outline cannot quietly make the radius coarser.
- `at`/`tangent`/the arc-length table, the view Orbits' tethers and Fish's
  procession walk.
- `sdf`'s sign and magnitude against brute force, the view Sauron's iris
  and Fireworks' fill test read.
- That the heart's cleft is a NOTCH, not a fold (it is star-shaped, so it
  has a radius per angle at all), and that a shape which is genuinely not
  star-shaped — a crescent — is REFUSED by `polar` and reported by the
  check script rather than silently returning nonsense.
- The check script's own numbers for the three shapes, pinned: its outline
  cell counts are the denominators every wave-1 "outline coverage" clarity
  bar in the plan is a fraction of, so a changed outline has to be a
  deliberate change to this file too.
"""
from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import voluptuous as vol

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fx.effects import word_shape_keys as keys  # noqa: E402
from fx.effects import word_shapes  # noqa: E402
from scripts import check_word_shapes as check  # noqa: E402

SHIPPED = ("heart", "star", "diamond")

# The check script's measurements at the plan's default size (0.62 x the
# panel's half-height) on his live crystal-mapper mask. The outline count
# is the denominator of every wave-1 outline-coverage bar; changing one of
# these numbers means a shape's drawn outline moved, which is never
# accidental.
PINNED = {
    #            outline, inside, thinnest
    "heart":   (109, 168, 2),
    "star":    (115, 100, 2),
    "diamond": (79, 97, 2),
}


def _crescent() -> word_shapes.Shape:
    """A C — an annulus sector with a gap — built through the library's own
    `build()`. Deliberately NOT star-shaped about its centre: the centre
    sits in the hole, and a ray through the gap crosses the outline no
    times at all."""
    outer = np.linspace(math.radians(20.0), math.radians(340.0), 200)
    inner = outer[::-1]
    pts = np.concatenate([
        np.column_stack([np.cos(outer), np.sin(outer)]),
        0.6 * np.column_stack([np.cos(inner), np.sin(inner)]),
    ])
    return word_shapes.build("crescent", "Crescent", pts, ("moon",))


# ── the entries ────────────────────────────────────────────────────────────

def test_the_three_shapes_load_in_declaration_order():
    assert word_shapes.shape_ids() == SHIPPED
    assert tuple(word_shapes.SHAPES) == SHIPPED
    for shape_id in SHIPPED:
        shape = word_shapes.get(shape_id)
        assert shape.id == shape_id
        assert shape.name
        assert shape.upright is True
        assert word_shapes.has(shape_id)


def test_an_unknown_shape_id_raises_key_error():
    with pytest.raises(KeyError):
        word_shapes.get("octagon")
    assert not word_shapes.has("octagon")


def test_each_shape_carries_its_starting_sung_words():
    assert word_shapes.get("heart").words == (
        "love", "heart", "corazón", "amor", "kiss", "beso")
    assert word_shapes.get("star").words == (
        "star", "stars", "estrella", "shine", "twinkle", "night sky")
    assert word_shapes.get("diamond").words == (
        "diamond", "diamante", "jewel", "ring", "sparkle", "crystal")
    for shape_id in SHIPPED:
        words = word_shapes.get(shape_id).words
        assert isinstance(words, tuple) and len(words) >= 3
        assert all(w == w.strip() and w == w.lower() for w in words)


def test_every_outline_is_a_dense_closed_polyline_in_the_unit_box():
    for shape_id in SHIPPED:
        shape = word_shapes.get(shape_id)
        pts = shape.points
        assert pts.ndim == 2 and pts.shape[1] == 2
        assert len(pts) >= 200, f"{shape_id}: outline is not dense"
        # closed implicitly: no repeated closing point
        assert np.linalg.norm(pts[-1] - pts[0]) > 1e-6
        # height exactly 2, centred on (0, 0) by its bounding box
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        assert hi[1] - lo[1] == pytest.approx(2.0, abs=1e-12)
        assert (lo[1] + hi[1]) / 2 == pytest.approx(0.0, abs=1e-12)
        assert (lo[0] + hi[0]) / 2 == pytest.approx(0.0, abs=1e-12)
        # width is whatever the shape needs, but it is a real width
        assert 0.5 < hi[0] - lo[0] < 4.0


def test_every_outline_winds_counter_clockwise_in_the_coordinate_algebra():
    for shape_id in SHIPPED:
        pts = word_shapes.get(shape_id).points
        assert word_shapes._signed_area(pts) > 0.0


def test_build_normalises_and_orients_whatever_it_is_given():
    # a clockwise, off-centre, wrong-sized square with a duplicate closing
    # point: build() fixes all four
    square = [(10.0, 10.0), (10.0, 14.0), (14.0, 14.0), (14.0, 10.0),
              (10.0, 10.0)]
    shape = word_shapes.build("square", "Square", square, ("box",))
    assert len(shape.points) == 4          # the closing point was dropped
    assert word_shapes._signed_area(shape.points) > 0.0
    lo, hi = shape.points.min(axis=0), shape.points.max(axis=0)
    assert hi[1] - lo[1] == pytest.approx(2.0, abs=1e-12)
    assert np.allclose((lo + hi) / 2, 0.0, atol=1e-12)


def test_a_shape_declared_upright_false_keeps_that():
    shape = word_shapes.build("bar", "Bar",
                              [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0),
                               (-1.0, 1.0)], ("bar",), upright=False)
    assert shape.upright is False


def test_the_shipped_shapes_point_up_the_way_the_panel_does():
    # y is DOWN: a star's and a diamond's own point is at the TOP, so the
    # outline's minimum y is reached near x = 0.
    for shape_id in ("star", "diamond"):
        pts = word_shapes.get(shape_id).points
        top = pts[pts[:, 1].argmin()]
        assert abs(top[0]) < 1e-9
    # the heart's single point is at the BOTTOM, its cleft at the top
    heart = word_shapes.get("heart").points
    assert abs(heart[heart[:, 1].argmax()][0]) < 1e-9
    cleft_x = heart[heart[:, 1].argmin()][0]
    assert abs(cleft_x) > 0.1       # the top of a heart is two lobes


# ── the radius per angle ───────────────────────────────────────────────────

def test_all_three_shipped_shapes_are_star_shaped_about_their_centre():
    # the heart's cleft is a notch, not a fold — measured, not assumed
    for shape_id in SHIPPED:
        assert word_shapes.get(shape_id).star_shaped is True


def test_polar_matches_a_direct_ray_cast_of_the_polyline():
    thetas = np.radians(np.arange(360.0))
    for shape_id in SHIPPED:
        shape = word_shapes.get(shape_id)
        reference, counts = word_shapes.ray_radius(shape.points, thetas)
        assert np.all(counts == 1)
        got = shape.polar(thetas)
        rel = np.abs(got - reference) / reference
        assert rel.max() < 0.005, f"{shape_id}: polar is off by {rel.max():.3%}"


def test_polar_is_read_exactly_at_a_bin_and_pinned_between_two():
    # every whole degree IS a bin (720 bins = half a degree), so those are
    # exact; between two bins the radius is interpolated, which errs only
    # across a kink. Pinned so a coarser table or a kinkier outline shows up.
    thetas = np.radians(np.arange(360.0))
    offset = np.linspace(0.0, 2.0 * math.pi, 7200, endpoint=False)
    worst = {}
    for shape_id in SHIPPED:
        shape = word_shapes.get(shape_id)
        exact, _ = word_shapes.ray_radius(shape.points, thetas)
        assert np.allclose(shape.polar(thetas), exact, rtol=1e-9)
        ref, _ = word_shapes.ray_radius(shape.points, offset)
        worst[shape_id] = float((np.abs(shape.polar(offset) - ref) / ref).max())
    assert worst["heart"] < 0.010
    assert worst["star"] < 0.010
    assert worst["diamond"] < 0.001


def test_polar_wraps_and_is_vectorised():
    heart = word_shapes.get("heart")
    for theta in (0.0, 1.3, -2.2, 5.9):
        assert heart.polar(theta) == pytest.approx(
            heart.polar(theta + 2 * math.pi), rel=1e-12)
        assert heart.polar(theta) == pytest.approx(
            heart.polar(theta - 4 * math.pi), rel=1e-12)
    thetas = np.linspace(0.0, 2 * math.pi, 37)
    assert heart.polar(thetas).shape == (37,)


def test_polar_mean_is_the_table_mean_and_inside_the_box():
    for shape_id in SHIPPED:
        shape = word_shapes.get(shape_id)
        thetas = np.arange(word_shapes.POLAR_BINS) * (
            2 * math.pi / word_shapes.POLAR_BINS)
        assert shape.polar_mean == pytest.approx(
            float(shape.polar(thetas).mean()), rel=1e-12)
        assert 0.3 < shape.polar_mean < 1.2


# ── the walk along the outline ─────────────────────────────────────────────

def test_at_starts_at_the_first_point_and_wraps():
    for shape_id in SHIPPED:
        shape = word_shapes.get(shape_id)
        x0, y0 = shape.at(0.0)
        assert (float(x0), float(y0)) == pytest.approx(tuple(shape.points[0]),
                                                       abs=1e-12)
        x1, y1 = shape.at(1.0)
        assert (float(x1), float(y1)) == pytest.approx((float(x0), float(y0)),
                                                       abs=1e-12)
        # s wraps in both directions
        for s in (0.5, 0.25, 0.9):
            a = shape.at(s)
            b = shape.at(s + 3.0)
            c = shape.at(s - 1.0)
            assert (float(b[0]), float(b[1])) == pytest.approx(
                (float(a[0]), float(a[1])), abs=1e-12)
            assert (float(c[0]), float(c[1])) == pytest.approx(
                (float(a[0]), float(a[1])), abs=1e-12)


def test_at_half_way_is_half_the_perimeter_along_the_outline():
    for shape_id in SHIPPED:
        shape = word_shapes.get(shape_id)
        s = np.linspace(0.0, 1.0, 4001)
        x, y = shape.at(s)
        walked = np.sum(np.hypot(np.diff(x), np.diff(y)))
        assert walked == pytest.approx(shape.perimeter, rel=2e-3)
        # halfway by arc length really is halfway
        half = int(np.argmin(np.abs(s - 0.5)))
        run = np.concatenate([[0.0], np.cumsum(
            np.hypot(np.diff(x), np.diff(y)))])
        assert run[half] == pytest.approx(shape.perimeter / 2.0, rel=5e-3)


def test_the_arc_length_table_is_monotone_and_sums_to_the_perimeter():
    for shape_id in SHIPPED:
        shape = word_shapes.get(shape_id)
        cum = shape._cum
        assert len(cum) == len(shape.points) + 1
        assert cum[0] == 0.0
        assert np.all(np.diff(cum) > 0.0)
        closed = np.concatenate([shape.points, shape.points[:1]])
        direct = float(np.sum(np.linalg.norm(np.diff(closed, axis=0), axis=1)))
        assert shape.perimeter == pytest.approx(direct, rel=1e-12)
        assert float(cum[-1]) == pytest.approx(direct, rel=1e-12)


def test_every_point_on_the_outline_sits_on_the_outline():
    for shape_id in SHIPPED:
        shape = word_shapes.get(shape_id)
        x, y = shape.at(np.linspace(0.0, 1.0, 501))
        assert np.abs(shape.sdf(x, y)).max() < 1e-9


def test_tangent_is_a_unit_heading_pointing_the_way_at_travels():
    # sampled off the vertices on purpose: AT a corner either adjoining
    # edge is a defensible tangent, and which one a given float lands on is
    # a one-ulp question (the next test pins the corner case itself).
    s = (np.arange(401) + 0.37) / 401.0
    ds = 1e-7
    for shape_id in SHIPPED:
        shape = word_shapes.get(shape_id)
        tx, ty = shape.tangent(s)
        assert np.allclose(np.hypot(tx, ty), 1.0, atol=1e-12)
        ax, ay = shape.at(s)
        bx, by = shape.at(s + ds)
        step = np.hypot(bx - ax, by - ay)
        dot = ((bx - ax) / step) * tx + ((by - ay) / step) * ty
        assert dot.min() > 0.999, f"{shape_id}: tangent {dot.min():.4f}"


def test_the_tangent_at_a_corner_is_one_of_that_corners_two_edges():
    diamond = word_shapes.get("diamond")
    closed = np.concatenate([diamond.points, diamond.points[:1]])
    steps = np.diff(closed, axis=0)
    steps /= np.linalg.norm(steps, axis=1)[:, None]
    corners = [i for i in range(len(diamond.points))
               if np.dot(steps[i], steps[i - 1]) < 0.999]
    assert len(corners) == 4                 # a rhombus has four
    for i in corners:
        tx, ty = diamond.tangent(diamond._cum[i] / diamond.perimeter)
        got = np.array([float(tx), float(ty)])
        assert (np.dot(got, steps[i]) > 0.999
                or np.dot(got, steps[i - 1]) > 0.999)


# ── the signed distance field ──────────────────────────────────────────────

def test_sdf_is_negative_inside_zero_on_the_outline_and_positive_outside():
    for shape_id in SHIPPED:
        shape = word_shapes.get(shape_id)
        assert float(shape.sdf(0.0, 0.0)) < 0.0
        assert float(shape.sdf(50.0, 50.0)) > 0.0
        # the far point's distance is the distance to the nearest outline
        # point, measured by brute force over a dense walk
        x, y = shape.at(np.linspace(0.0, 1.0, 20001))
        brute = float(np.hypot(x - 50.0, y - 50.0).min())
        assert float(shape.sdf(50.0, 50.0)) == pytest.approx(brute, rel=1e-6)
        # a point on the boundary is zero
        bx, by = shape.at(0.137)
        assert float(shape.sdf(bx, by)) == pytest.approx(0.0, abs=1e-12)


def test_sdf_magnitude_matches_brute_force_everywhere_on_a_grid():
    rng = np.random.default_rng(20261115)
    for shape_id in SHIPPED:
        shape = word_shapes.get(shape_id)
        px = rng.uniform(-1.6, 1.6, 400)
        py = rng.uniform(-1.6, 1.6, 400)
        x, y = shape.at(np.linspace(0.0, 1.0, 20001))
        brute = np.min(np.hypot(px[:, None] - x[None, :],
                                py[:, None] - y[None, :]), axis=1)
        got = np.abs(shape.sdf(px, py))
        assert np.allclose(got, brute, atol=2e-4)


def test_sdf_keeps_the_shape_of_its_inputs_and_broadcasts():
    heart = word_shapes.get("heart")
    assert heart.sdf(0.0, 0.0).shape == ()
    assert heart.sdf(np.zeros(7), np.zeros(7)).shape == (7,)
    assert heart.sdf(np.zeros((5, 9)), np.zeros((5, 9))).shape == (5, 9)
    col = np.linspace(-1.0, 1.0, 11)[:, None]
    row = np.linspace(-1.0, 1.0, 13)[None, :]
    assert heart.sdf(row, col).shape == (11, 13)
    # float32 in, float32 out (the speed lever an effect has)
    out = heart.sdf(np.zeros(4, dtype=np.float32), np.zeros(4, dtype=np.float32))
    assert out.dtype == np.float32


def test_sdf_agrees_with_the_radius_per_angle():
    # two views of one outline: at r = polar(theta) the field is zero
    thetas = np.linspace(0.0, 2 * math.pi, 257)
    for shape_id in SHIPPED:
        shape = word_shapes.get(shape_id)
        r = shape.polar(thetas)
        assert np.abs(shape.sdf(r * np.cos(thetas),
                                r * np.sin(thetas))).max() < 5e-3
        inside = shape.sdf(0.8 * r * np.cos(thetas), 0.8 * r * np.sin(thetas))
        assert np.all(inside < 0.0)


# ── a shape that is not star-shaped ────────────────────────────────────────

def test_a_crescent_is_not_star_shaped_and_polar_refuses_it():
    crescent = _crescent()
    assert crescent.star_shaped is False
    assert math.isnan(crescent.polar_mean)
    with pytest.raises(ValueError, match="not star-shaped"):
        crescent.polar(0.0)
    # the other two views still work: that is the whole point of recording
    # the verdict per shape instead of refusing the shape
    x, y = crescent.at(np.linspace(0.0, 1.0, 101))
    assert np.abs(crescent.sdf(x, y)).max() < 1e-9


def test_the_check_script_reports_a_crescent_and_fails_a_false_claim():
    panel = check.load_panel(check.DEFAULT_PROFILE)
    size = check.DEFAULT_SIZE_FRACTION * panel.half_height
    crescent = _crescent()
    measured, _ = check.measure(crescent, panel, size)
    assert measured.walked_star_shaped is False
    assert measured.worst_ray_crossings != 1
    # honest about it = not a failure; claiming otherwise = a failure
    assert measured.claims_star_shaped is False
    object.__setattr__(crescent, "star_shaped", True)
    forged, _ = check.measure(crescent, panel, size)
    assert forged.claims_star_shaped is True
    assert forged.ok is False


# ── the told keys ──────────────────────────────────────────────────────────

def test_the_schema_defaults_are_not_told():
    config = vol.Schema(keys.schema_fields())({})
    assert set(config) == set(keys.KEYS)
    assert config == keys.NOT_TOLD
    assert keys.told(config) is None
    assert keys.told({}) is None


def test_a_write_round_trips_through_told():
    written = keys.keys_for("heart", 4, 0.5, 1.2, 0.75, 0.8)
    assert set(written) == set(keys.KEYS)
    config = vol.Schema(keys.schema_fields())(written)
    told = keys.told(config)
    assert told == keys.WordShapeTold("heart", 4, 0.5, 1.2, 0.75, 0.8)
    assert told.total_s == pytest.approx(2.45)


def test_a_clearing_write_sends_every_key(
):
    assert keys.keys_for("", 9, 1.0, 1.0, 1.0, 1.0) == keys.NOT_TOLD
    assert set(keys.NOT_TOLD) == set(keys.KEYS)


def test_told_refuses_a_shape_the_library_does_not_know():
    # a newer SpotFX naming a shape this build has never heard of must fall
    # through to "not told", never crash an effect's frame
    assert keys.told({keys.SHAPE_KEY: "octagon",
                      keys.FORM_KEY: 0.5, keys.HOLD_KEY: 1.0}) is None
    assert keys.told({keys.SHAPE_KEY: "heart"}) is None   # no times = nothing
    assert keys.told({keys.SHAPE_KEY: "heart", keys.FORM_KEY: 0.5}) is not None


def test_told_clamps_a_bad_number_rather_than_passing_it_on():
    told = keys.told({keys.SHAPE_KEY: "star", keys.FORM_KEY: -3.0,
                      keys.HOLD_KEY: 10_000.0, keys.RELEASE_KEY: "x",
                      keys.LEVEL_KEY: 7.0, keys.SEQ_KEY: -2})
    assert told.form_s == 0.0
    assert told.hold_s == keys.MAX_SECONDS
    assert told.release_s == 0.0
    assert told.level == 1.0
    assert told.seq == 0


def test_the_schema_accepts_every_shape_the_library_ships():
    schema = vol.Schema(keys.schema_fields())
    for shape_id in SHIPPED:
        config = schema(keys.keys_for(shape_id, 1, 0.5, 1.0, 0.75, 0.5))
        told = keys.told(config)
        assert told is not None and told.shape == shape_id
        # and the geometry is there to draw
        assert word_shapes.get(told.shape).star_shaped


def test_release_s_for_is_the_plans_ratio():
    assert keys.release_s_for(0.5) == pytest.approx(0.75)
    assert keys.release_s_for(0.9) == pytest.approx(1.35)
    assert keys.release_s_for(0.5, ratio=1.0) == pytest.approx(0.5)


# ── the envelope ───────────────────────────────────────────────────────────

def test_the_envelope_boundary_values():
    form, hold, release = 0.5, 1.0, 0.75
    e = lambda t: keys.envelope(t, form, hold, release)  # noqa: E731
    assert e(-1.0) == 0.0
    assert e(0.0) == 0.0
    assert e(form / 2) == pytest.approx(0.5)
    assert e(form) == 1.0
    assert e(form + hold / 2) == 1.0
    assert e(form + hold) == 1.0
    assert e(form + hold + release / 2) == pytest.approx(0.5)
    assert e(form + hold + release) == pytest.approx(0.0, abs=1e-12)
    assert e(form + hold + release + 5.0) == 0.0


def test_the_envelope_is_continuous_and_has_zero_speed_at_both_ends():
    form, hold, release = 0.5, 1.0, 0.75
    t = np.linspace(-0.2, form + hold + release + 0.2, 6001)
    v = keys.envelope(t, form, hold, release)
    assert v.min() >= 0.0 and v.max() <= 1.0
    step = np.abs(np.diff(v))
    assert step.max() < 0.01, "the envelope jumps somewhere"
    dt = t[1] - t[0]
    # a smoothstep has zero slope at both ends of both ramps
    for edge in (0.0, form, form + hold, form + hold + release):
        i = int(np.argmin(np.abs(t - edge)))
        assert abs(v[i + 1] - v[i - 1]) / (2 * dt) < 0.08


def test_the_envelope_rises_and_falls_monotonically():
    form, hold, release = 0.9, 0.8, 1.35
    rise = keys.envelope(np.linspace(0.0, form, 200), form, hold, release)
    assert np.all(np.diff(rise) >= 0.0)
    fall = keys.envelope(np.linspace(form + hold, form + hold + release, 200),
                         form, hold, release)
    assert np.all(np.diff(fall) <= 0.0)


def test_the_envelope_survives_zero_length_segments():
    # told a form of 0: already complete at t = 0, no division anywhere
    assert keys.envelope(0.0, 0.0, 1.0, 0.5) == 1.0
    assert keys.envelope(1.0, 0.0, 1.0, 0.5) == 1.0
    assert keys.envelope(1.5, 0.0, 1.0, 0.5) == pytest.approx(0.0, abs=1e-12)
    # told no release: it ends on the hold
    assert keys.envelope(1.0, 0.5, 0.5, 0.0) == 1.0
    assert keys.envelope(1.001, 0.5, 0.5, 0.0) == 0.0
    # told nothing at all: nothing to draw
    assert keys.envelope(0.0, 0.0, 0.0, 0.0) == 1.0
    assert keys.envelope(0.001, 0.0, 0.0, 0.0) == 0.0


def test_the_envelope_returns_a_float_for_a_scalar_and_an_array_otherwise():
    assert isinstance(keys.envelope(0.3, 0.5, 1.0, 0.75), float)
    out = keys.envelope(np.array([0.0, 0.25, 0.5]), 0.5, 1.0, 0.75)
    assert isinstance(out, np.ndarray) and out.shape == (3,)


# ── the check script ───────────────────────────────────────────────────────

def test_the_check_scripts_numbers_for_the_three_shapes_are_pinned():
    panel = check.load_panel(check.DEFAULT_PROFILE)
    assert (panel.rows, panel.cols) == (37, 72)
    assert int(panel.grid.sum()) == 976
    size = check.DEFAULT_SIZE_FRACTION * panel.half_height
    assert size == pytest.approx(11.16)
    for shape_id, (outline, inside, thinnest) in PINNED.items():
        m, _ = check.measure(word_shapes.get(shape_id), panel, size)
        assert (m.outline_cells, m.inside_cells) == (outline, inside), (
            f"{shape_id}: the outline moved — every wave-1 coverage bar is a "
            f"fraction of the outline count, so update PINNED deliberately")
        assert m.thinnest == thinnest
        assert m.thinnest >= check.MIN_LIT_CELLS
        assert m.walked_star_shaped and m.claims_star_shaped
        assert m.ok


def test_the_thinnest_point_does_not_depend_on_how_finely_it_is_sampled():
    panel = check.load_panel(check.DEFAULT_PROFILE)
    size = check.DEFAULT_SIZE_FRACTION * panel.half_height
    original = check.OUTLINE_SAMPLES
    try:
        for samples in (360, 720, 1440):
            check.OUTLINE_SAMPLES = samples
            for shape_id in SHIPPED:
                m, _ = check.measure(word_shapes.get(shape_id), panel, size)
                assert m.thinnest == PINNED[shape_id][2]
    finally:
        check.OUTLINE_SAMPLES = original


def test_the_check_script_runs_clean_and_prints_the_table():
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_word_shapes.py")],
        capture_output=True, text=True, cwd=REPO_ROOT, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for shape_id in SHIPPED:
        assert shape_id in proc.stdout
    assert "PASS" in proc.stdout
    assert str(PINNED["heart"][0]) in proc.stdout
