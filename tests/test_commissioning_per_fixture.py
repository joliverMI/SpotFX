"""COMMISSIONING PER TARGET, AND THE BOUNDARY THAT REFUSES A MARGINAL ONE.

THE CAPTAIN'S RULING (2026-09-01), after PR #226 proved his whole stitched
composition unreadable from any pose at the frame size the wire carries:
commission PER FIXTURE (or per segment), never the stitched whole — and
make the resolution-refusal boundary CONSERVATIVE, because "marginal is the
state that produces a confident wrong answer".

The wire's 320x180 frame contract is deliberately NOT touched here. That
change goes back to him or it does not happen; these proofs are about
asking a smaller question, not about widening the instrument.

Two things are proven, and the second is what stops the first from being a
quiet relaxation of the standard:

  1. a target — one fixture, or one stored segment — is gray-coded and
     judged by the SAME frozen table against the stored composition's own
     slice of ground truth, and the set of them aggregates back into one
     table of the same five rows with the same five tolerances; and
  2. the boundary refuses on BOTH sides of the margin, saying which state
     it was: MARGINAL (readable in principle, untrustworthy in practice)
     and IMPOSSIBLE (below Nyquist, unreadable however bright the room).

The camera in section 2 is a BOX-INTEGRATING one whose reported
`camera_px_per_index` IS the number under test by construction — which is
what makes a boundary provable on both sides rather than bracketed.
"""
from __future__ import annotations

import numpy as np
import pytest

from spectra.services import commission_compare as cc
from spectra.services import commissioning, gray_code, mapping_refusals

from tests.test_commissioning import W, H, Harness, _his_room


# ── the slice: the stored composition's own, re-addressed and nothing else ─

def _whole(tv=560, sconce=88):
    return commissioning.resolve_composition("tv-mapper", _his_room(tv, sconce),
                                             [])


def test_a_fixture_target_is_the_stored_segments_re_addressed():
    whole = _whole()
    right = commissioning.slice_composition(whole, "device:sconce-kitchen-right")
    assert whole.total == 736 and right.total == 88
    # its own two stored segments, keeping their stored numbers and order
    # _his_room splits each sconce in half (0-43, 44-87); his live config
    # splits his 28/60. Either way the slice keeps the STORED split.
    assert [s.index for s in right.segments] == [1, 2]
    assert [(s.start, s.end) for s in right.segments] == [(0, 43), (44, 87)]
    # and remembering exactly where they sit in the whole
    assert right.global_indices == list(range(560, 648))
    assert right.source_total == 736
    assert right.target == "device:sconce-kitchen-right"


def test_re_addressing_is_the_whole_point_of_a_target():
    """88 pixels are 7 patterns and need ~176 camera pixels; the stitched
    736 are 10 patterns and need ~1,472 of a frame whose entire border is
    ~1,000. Addressing a fixture's pixels as global indices 560..647 would
    keep the 10-bit stack and buy nothing."""
    whole = _whole()
    right = commissioning.slice_composition(whole, "device:sconce-kitchen-right")
    assert gray_code.bits_needed(right.total) == 7
    assert gray_code.bits_needed(whole.total) == 10
    assert int(right.total * gray_code.MIN_CAMERA_PX_PER_INDEX) == 176
    assert int(whole.total * gray_code.MIN_CAMERA_PX_PER_INDEX) == 1472
    assert 1472 > 2 * (W + H)          # no pose fixes the stitched whole


def test_the_pattern_map_carries_only_this_targets_pixels():
    whole = _whole()
    right = commissioning.slice_composition(whole, "device:sconce-kitchen-right")
    assert set(right.pixel_map) == {"sconce-kitchen-right"}
    arr = right.pixel_map["sconce-kitchen-right"]
    assert sorted(int(v) for v in arr if v >= 0) == list(range(88))
    # every other fixture is simply not addressed by this target
    assert "tv-backlight" not in right.pixel_map


def test_a_segment_target_is_finer_still():
    whole = _whole()
    seg = commissioning.slice_composition(whole, "segment:2")
    assert seg.total == 44 and [s.index for s in seg.segments] == [2]
    assert seg.global_indices == list(range(604, 648))
    assert "segment 2" in seg.target_label


def test_a_fixture_whose_segments_are_not_adjacent_slices_in_stored_order():
    """A device may back segments the mapper does NOT store next to each
    other. The slice concatenates them in the MAPPER's own order (never
    sorted, never merged), so `global_indices` is discontinuous while the
    local addressing stays 0..N-1 — which is exactly the shape that would
    break silently if the slice assumed one contiguous run."""
    def _v(vid, segs, mapping="span"):
        return {"id": vid, "active": True,
                "segments": [[d, lo, hi, False, 0] for d, lo, hi in segs],
                "pixel_count": sum(h - l + 1 for _d, l, h in segs),
                "config": {"mapping": mapping, "rows": 1, "grouping": 1},
                "effect": {"type": "singleColor", "config": {}}}

    virtuals = {"m": _v("m", [("A", 0, 9), ("B", 0, 4),
                              ("A", 10, 19), ("B", 5, 9)], mapping="copy"),
                "A": _v("A", [("A", 0, 19)]),
                "B": _v("B", [("B", 0, 9)])}
    whole = commissioning.resolve_composition("m", virtuals, [])
    assert [(s.index, s.device_id, s.start, s.end) for s in whole.segments] == [
        (0, "A", 0, 9), (1, "B", 10, 14), (2, "A", 15, 24), (3, "B", 25, 29)]

    a = commissioning.slice_composition(whole, "device:A")
    assert a.total == 20
    assert [(s.index, s.start, s.end) for s in a.segments] == [(0, 0, 9),
                                                               (2, 10, 19)]
    assert a.global_indices == list(range(0, 10)) + list(range(15, 25))
    # every local index addressed exactly once, through A's own pixels
    assert a.pixel_map["A"].tolist() == list(range(20))
    assert "B" not in a.pixel_map
    # and the stored layout follows the discontinuity rather than assuming
    # a run
    layout = {i: (i / 30.0, 0.5) for i in range(whole.total)}
    sliced = commissioning.slice_layout(layout, a)
    assert sliced[0] == layout[0]
    assert sliced[9] == layout[9]
    assert sliced[10] == layout[15]        # the jump, honoured
    assert sliced[19] == layout[24]


def test_a_target_that_names_nothing_is_refused_by_name():
    whole = _whole()
    with pytest.raises(commissioning.CompositionRefused) as exc:
        commissioning.slice_composition(whole, "device:lamp-that-does-not-exist")
    assert "no segment backed by" in str(exc.value)
    with pytest.raises(commissioning.CompositionRefused):
        commissioning.slice_composition(whole, "segment:99")


def test_expansion_reads_the_stored_composition_itself():
    whole = _whole()
    assert commissioning.expand_targets(whole, None) == [commissioning.TARGET_ALL]
    assert commissioning.expand_targets(whole, ["fixtures"]) == [
        "device:sconce-kitchen-left", "device:sconce-kitchen-right",
        "device:tv-backlight"]
    assert commissioning.expand_targets(whole, ["segments"]) == [
        f"segment:{i}" for i in range(5)]
    # de-duplicated and deterministic
    assert commissioning.expand_targets(
        whole, ["device:tv-backlight", "device:tv-backlight"]) == [
            "device:tv-backlight"]


def test_the_stored_layout_is_sliced_never_re_derived():
    """A slice must be judged against the stored composition's own pixels.
    A layout that does not carry one of them is UNMEASURED, never a guess
    fitted at the slice's own size."""
    whole = _whole()
    right = commissioning.slice_composition(whole, "device:sconce-kitchen-right")
    full = {i: (i / 736.0, 0.5) for i in range(736)}
    sliced = commissioning.slice_layout(full, right)
    assert sliced is not None and len(sliced) == 88
    assert sliced[0] == full[560] and sliced[87] == full[647]
    partial = {i: (0.0, 0.0) for i in range(600)}
    assert commissioning.slice_layout(partial, right) is None
    assert commissioning.slice_layout(None, right) is None


# ── the run, per fixture ───────────────────────────────────────────────────

def test_every_fixture_is_commissioned_on_its_own_and_judged_the_same_way():
    h = Harness()
    result = h.run(layout=h.layout, instrument={}, targets=["fixtures"])
    assert result.ok
    assert result.target_specs == ["device:sconce-kitchen-left",
                                   "device:sconce-kitchen-right",
                                   "device:tv-backlight"]
    by = {e["label"]: e for e in result.targets}
    assert set(by) == {"tv-backlight", "sconce-kitchen-left",
                       "sconce-kitchen-right"}
    # each decodes its OWN pixel count, addressed 0..N-1
    assert by["tv-backlight"]["decodes"][0]["total"] == 60
    assert by["sconce-kitchen-left"]["decodes"][0]["total"] == 8
    for entry in by.values():
        assert entry["ok"]
        rows = {r["field"]: r for r in entry["table"]["rows"]}
        assert rows["Pixel count seen"]["verdict"] == cc.PASS
        # the SAME frozen tolerances, per target
        assert entry["table"]["tolerances"]["seen_min_fraction"] == 0.98


def test_a_per_fixture_run_aggregates_into_the_same_judged_shape():
    h = Harness()
    result = h.run(layout=h.layout, instrument={}, targets=["fixtures"])
    table = result.table
    assert [r["field"] for r in table["rows"]] == list(cc.FIELD_ORDER)
    assert table["tolerances"] == {
        "seen_min_fraction": cc.SEEN_MIN_FRACTION,
        "order_max_outlier_fraction": cc.ORDER_MAX_OUTLIER_FRACTION,
        "arrangement_max_error": cc.ARRANGEMENT_MAX_ERROR,
        "stitch_max_error": cc.STITCH_MAX_ERROR,
        "latency_tolerance_ms": cc.LATENCY_TOLERANCE_MS}
    row = table["rows"][0]
    assert row["verdict"] == cc.PASS
    assert row["numbers"]["per_target"] == {
        "tv-backlight": cc.PASS, "sconce-kitchen-left": cc.PASS,
        "sconce-kitchen-right": cc.PASS}
    assert [t["target"] for t in table["targets"]] == result.target_specs


def test_a_single_segment_target_runs_end_to_end():
    h = Harness()
    result = h.run(layout=h.layout, instrument={}, targets=["segment:0"])
    assert result.ok and len(result.targets) == 1
    entry = result.targets[0]
    assert entry["composition"]["total"] == 60      # the TV segment alone
    assert entry["decodes"][0]["seen"] == 60


def test_the_whole_composition_run_is_byte_for_byte_what_it_was():
    """No targets means what it always meant. The original shape is the
    result's own top level — no `targets` list, no aggregate — so nothing
    that already reads it moves."""
    h = Harness()
    result = h.run(layout=h.layout, instrument={})
    assert result.ok and result.targets == []
    assert result.target_specs == [commissioning.TARGET_ALL]
    assert result.decodes and result.decodes[0]["total"] == h.total
    assert [c["label"] for c in result.captures][:2] == ["run1/dark",
                                                         "run1/full"]


# ── a target that cannot be read never shrinks the denominator ─────────────

def test_one_unreadable_fixture_does_not_end_the_run_and_is_never_dropped():
    """THE HONESTY THIS WHOLE SPLIT RESTS ON: two fixtures green cannot
    outvote one nobody could measure. A refused target contributes
    UNMEASURED to every row of the aggregate, with its own sentence, and
    the verdict comes out INCOMPLETE."""
    # THE CAPTAIN'S OWN PICTURE, in miniature: the ring is given more
    # pixels than this pose can be TRUSTED to tell apart (marginal), while
    # the two sconces are comfortably readable at their own size.
    h = Harness(tv=2000, sconce=8)
    result = h.run(layout=h.layout, instrument={}, targets=["fixtures"])
    by = {e["label"]: e for e in result.targets}
    assert not by["tv-backlight"]["ok"]
    assert by["tv-backlight"]["refusal"] == "resolution"
    assert (by["tv-backlight"]["resolution"]["verdict"]
            == gray_code.RESOLUTION_MARGINAL)
    assert "MARGINAL" in by["tv-backlight"]["reason"]
    assert by["sconce-kitchen-left"]["ok"] and by["sconce-kitchen-right"]["ok"]
    # the refused one cost two captures, and the run carried on
    tv_caps = [c for c in result.captures if c["label"].startswith("tv-")]
    assert len(tv_caps) == 2
    row = result.table["rows"][0]
    assert row["numbers"]["per_target"]["tv-backlight"] == cc.UNMEASURED
    assert row["numbers"]["per_target"]["sconce-kitchen-left"] == cc.PASS
    assert result.table["verdict"] == "incomplete"
    assert any(t["refusal"] == "resolution" for t in result.table["targets"])
    # the room is still put back
    assert set(h.activated) == set(h.deactivated)


def test_a_fail_on_one_target_is_a_fail_for_the_whole_table():
    """The aggregate is as bad as its worst target — a split run can never
    read greener than the whole one it replaces."""
    green = {"field": "Pixel count seen", "verdict": cc.PASS,
             "ground_truth": "g", "tolerance": "t", "measured": "100%",
             "indicts": "", "detail": "", "numbers": {}}
    red = dict(green, verdict=cc.FAIL, indicts="commissioning",
               measured="50%")
    out = cc.aggregate([
        {"target": "a", "label": "a", "table": {"rows": [green]}},
        {"target": "b", "label": "b", "table": {"rows": [red]}}])
    assert out["rows"][0]["verdict"] == cc.FAIL
    assert out["rows"][0]["indicts"] == "commissioning"
    assert out["verdict"] == "fail"


def test_an_aggregate_of_nothing_is_incomplete_not_a_pass():
    out = cc.aggregate([])
    assert out["verdict"] == "incomplete"
    assert [r["field"] for r in out["rows"]] == list(cc.FIELD_ORDER)
    assert all(r["verdict"] == cc.UNMEASURED for r in out["rows"])


# ── THE MARGINAL BOUNDARY, both sides ─────────────────────────────────────

def _box_camera_stack(total, px_per_index, *, phase=0.37, noise=0.5,
                      seed=3, peak=180.0, row=90):
    """A camera whose reported `camera_px_per_index` IS `px_per_index`.

    Each composition index owns exactly that many camera columns, starting
    at a deliberately non-integer phase, and a column straddling two
    indices sees the MEAN of what they show — the same integration that
    makes a marginal pose dangerous in the first place."""
    edges = phase + px_per_index * np.arange(total + 1)
    cols = np.arange(W) + 0.5
    lo = np.maximum(edges[None, :-1], cols[:, None] - 0.5)
    hi = np.minimum(edges[None, 1:], cols[:, None] + 0.5)
    coverage = np.clip(hi - lo, 0.0, None)
    rng = np.random.default_rng(seed)

    def shot(on):
        mask = np.zeros(total)
        if on:
            mask[list(on)] = 1.0
        frame = np.full((H, W), 2.0)
        frame[row:row + 1, :] += ((coverage @ mask) * peak)[None, :]
        return np.clip(np.round(frame + rng.normal(0.0, noise, (H, W))),
                       0, 255).astype(np.uint8).astype(np.float64)

    def average(on):
        return np.mean([shot(on) for _ in range(4)], axis=0)

    every = set(range(total))
    dark, full = average(set()), average(every)
    pairs = []
    for bit in range(gray_code.bits_needed(total)):
        on = {i for i in every if gray_code.pattern_bits(np.array([i]), bit)[0]}
        pairs.append((average(on), average(every - on)))
    return dark, full, pairs


SAFE = gray_code.MIN_CAMERA_PX_PER_INDEX * gray_code.RESOLUTION_SAFETY_FACTOR


def test_just_above_the_bar_passes_the_gate_and_decodes():
    dark, full, pairs = _box_camera_stack(88, SAFE + 0.1)
    report = gray_code.resolution_report(dark, full, total=88)
    assert report["camera_px_per_index"] > SAFE
    assert report["verdict"] == gray_code.RESOLUTION_OK
    assert report["resolvable"] is True
    assert len(gray_code.decode_stack(dark, full, pairs, total=88).seen) == 88


def test_just_below_the_bar_refuses_and_names_itself_marginal():
    dark, full, _pairs = _box_camera_stack(88, SAFE - 0.1)
    report = gray_code.resolution_report(dark, full, total=88)
    # above the absolute minimum — this is NOT the impossible case
    assert report["camera_px_per_index"] > gray_code.MIN_CAMERA_PX_PER_INDEX
    assert report["camera_px_per_index"] < SAFE
    assert report["verdict"] == gray_code.RESOLUTION_MARGINAL
    assert report["resolvable"] is False        # conservative, deliberately
    assert report["any_light"] is True          # with light in the frame
    words = mapping_refusals.unresolvable_composition(
        report, W, H, target_label="sconce-kitchen-right")
    assert "MARGINAL" in words
    assert "confident" in words and "WRONG" in words
    assert "sconce-kitchen-right" in words


def test_below_the_absolute_minimum_is_the_other_refusal():
    dark, full, _pairs = _box_camera_stack(88, 1.2)
    report = gray_code.resolution_report(dark, full, total=88)
    assert report["verdict"] == gray_code.RESOLUTION_IMPOSSIBLE
    words = mapping_refusals.unresolvable_composition(report, W, H)
    assert "MARGINAL" not in words
    assert "cancel" in words and "camera pixels" in words


def test_the_margin_is_arithmetic_and_named():
    dark, full, _pairs = _box_camera_stack(88, SAFE + 0.1)
    report = gray_code.resolution_report(dark, full, total=88)
    assert report["needed_camera_px"] == 176          # 88 x 2.0
    assert report["safe_camera_px"] == 220            # 88 x 2.0 x 1.25
    assert report["safety_factor"] == gray_code.RESOLUTION_SAFETY_FACTOR
    assert report["safe_camera_px_per_index"] == SAFE
    # and it is conservative, in that direction, by construction
    assert gray_code.RESOLUTION_SAFETY_FACTOR > 1.0


@pytest.mark.parametrize("lit,expected", [
    (175, gray_code.RESOLUTION_IMPOSSIBLE),   # one short of the Nyquist bar
    (176, gray_code.RESOLUTION_MARGINAL),     # exactly ON it
    (219, gray_code.RESOLUTION_MARGINAL),     # one short of the margin
    (220, gray_code.RESOLUTION_OK),           # exactly ON the margin
    (221, gray_code.RESOLUTION_OK),
])
def test_the_boundary_is_exact_at_the_pixel(lit, expected):
    """The three bands, asserted at the exact camera pixel they change on,
    with the reference pair built to light precisely `lit` of them. `>=`
    both times: the Nyquist bar itself is MARGINAL (readable in principle),
    and the margin itself is OK."""
    dark = np.zeros((60, 60))
    full = np.zeros((60, 60))
    full.reshape(-1)[:lit] = 100.0
    report = gray_code.resolution_report(dark, full, total=88)
    assert (report["needed_camera_px"], report["safe_camera_px"]) == (176, 220)
    assert report["lit_pixels"] == lit
    assert report["verdict"] == expected
    assert report["resolvable"] is (expected == gray_code.RESOLUTION_OK)


def test_a_marginal_target_refuses_the_RUN_not_only_the_report(monkeypatch):
    """The gate the run actually consults is `resolvable`, and `resolvable`
    follows the conservative verdict — so raising the margin turns a room
    the instrument was happily decoding into a refusal, by name, two
    captures in, with nothing judged."""
    h = Harness()
    ok = h.run(layout=h.layout, instrument={})
    assert ok.ok and ok.resolution["verdict"] == gray_code.RESOLUTION_OK
    margin = ok.resolution["camera_px_per_index"] / \
        gray_code.MIN_CAMERA_PX_PER_INDEX
    monkeypatch.setattr(gray_code, "RESOLUTION_SAFETY_FACTOR", margin * 1.5)
    h2 = Harness()
    refused = h2.run(layout=h2.layout, instrument={})
    assert not refused.ok and refused.refusal == "resolution"
    assert refused.resolution["verdict"] == gray_code.RESOLUTION_MARGINAL
    assert "MARGINAL" in refused.reason
    assert refused.table == {} and refused.decodes == []
    assert len(refused.captures) == 2
    assert h2.closed == 1 and set(h2.activated) == set(h2.deactivated)


def test_his_ring_alone_is_out_of_reach_at_the_wire_s_own_frame_size():
    """560 pixels need ~1,120 camera pixels of imaged strip to be readable
    at all and ~1,400 to be TRUSTED, against the ~1,000 the entire border
    of the 320x180 frame the phone sends can hold. The honest act is to say
    so — not to widen the wire, which is the captain's to decide."""
    ring = 560
    needed = int(np.ceil(ring * gray_code.MIN_CAMERA_PX_PER_INDEX))
    safe = int(np.ceil(ring * gray_code.MIN_CAMERA_PX_PER_INDEX
                       * gray_code.RESOLUTION_SAFETY_FACTOR))
    assert (needed, safe) == (1120, 1400)
    assert needed > 2 * (W + H)
    # one sconce, the target the ruling actually asks for, is comfortable
    assert int(np.ceil(88 * gray_code.MIN_CAMERA_PX_PER_INDEX)) == 176
    assert 176 < 2 * (W + H)


# ── the run ending mid-set, and the record it leaves ──────────────────────

def test_a_target_the_run_never_reached_is_unmeasured_never_absent():
    """A run aborted part-way through the set would otherwise aggregate over
    only the targets that happened to finish — the silently-shrinking
    denominator `aggregate` exists to refuse, arrived at from the other
    direction. Every spec that was ASKED FOR appears in the table, in the
    order it was going to run."""
    h = Harness()
    # end the session as soon as the second target starts its own stack
    seen: list[str] = []
    real = h.session.gather_full

    def _abort_after(n_captures):
        async def gather(seconds, *, min_frames=1):
            seen.append("x")
            if len(seen) > n_captures:
                h.session.run_abort = "the phone stopped sending frames"
            return await real(seconds, min_frames=min_frames)
        return gather

    # the first fixture (8 pixels -> 3 bits -> 8 captures) finishes; the
    # second is cut off part-way through its own stack
    h.session.gather_full = _abort_after(10)
    result = h.run(layout=h.layout, instrument={}, targets=["fixtures"])

    assert result.refusal == "aborted"
    # THE WHOLE SET IS REPORTED, not the part that answered
    assert [t["target"] for t in result.targets] == result.target_specs
    assert len(result.targets) == 3
    unreached = [t for t in result.targets if t["refusal"] == "not_attempted"]
    assert unreached, "a target the run never reached must say so"
    assert all("ended before this target was reached" in t["reason"]
               for t in unreached)
    row = result.table["rows"][0]
    assert set(row["numbers"]["per_target"]) == set(
        t["label"] for t in result.targets)
    assert row["verdict"] == cc.UNMEASURED
    assert result.table["verdict"] == "incomplete"
    # a run that did not complete is not a 200, even with tables in hand
    assert result.ok is False
    # and the room is still put back
    assert set(h.activated) == set(h.deactivated)


def test_the_aggregate_keeps_the_pre_registration_on_an_unmeasured_row():
    """`ground_truth` and `tolerance` are the pre-registration itself, not a
    property of whichever target came out worst. A refused target's filler
    row carries neither, and inheriting from it would render rows of a
    pre-registered table with no pre-registration in them."""
    h = Harness(tv=2000, sconce=8)
    result = h.run(layout=h.layout, instrument={}, targets=["fixtures"])
    rows = result.table["rows"]
    # the ring is unmeasured, so every row it appears in is unmeasured
    assert rows[0]["verdict"] == cc.UNMEASURED
    for row in rows[:3]:
        assert row["ground_truth"], f"{row['field']} lost its ground truth"
        assert row["tolerance"], f"{row['field']} lost its tolerance"
    assert "98" in rows[0]["tolerance"]


def test_the_pose_s_margin_survives_a_refused_hold():
    """`RunResult.resolution` says "carried whether the run went on or
    refused". A hold refused after the reference captures must not take the
    measurement down with it."""
    h = Harness()
    real_open = None

    from spectra.services import room_mapping

    deps = h.deps()
    calls = {"n": 0}
    inner = deps.open_hold

    async def refusing_open(program, intensity, *, step, heartbeat_timeout_s):
        calls["n"] += 1
        if calls["n"] > 2:                     # dark and full land; then no
            return {"held": False, "reason": "nothing was rendering"}
        return await inner(program, intensity, step=step,
                           heartbeat_timeout_s=heartbeat_timeout_s)

    patched = room_mapping.RunDeps(
        session=deps.session, get_virtuals=deps.get_virtuals,
        open_hold=refusing_open, close_hold=deps.close_hold,
        sleep=deps.sleep, clock=deps.clock,
        carrier_devices=deps.carrier_devices, spectra_owns=deps.spectra_owns,
        activate=deps.activate, deactivate=deps.deactivate,
        fixture_devices=deps.fixture_devices)
    h.composition = commissioning.resolve_composition(
        "tv-mapper", h.virtuals,
        [{"id": d, "type": "wled"} for d in
         ("tv-backlight", "sconce-kitchen-left", "sconce-kitchen-right")])
    import asyncio
    result = asyncio.run(commissioning.run_commission(
        "tv-mapper", patched, layout=h.layout, instrument={}))
    assert not result.ok and result.refusal == "hold"
    assert result.resolution, "the pose's own margin went down with the hold"
    assert result.resolution["verdict"] == gray_code.RESOLUTION_OK
    assert result.resolution["camera_px_per_index"] > 0


def test_a_failed_repeat_never_sits_next_to_an_accepted_table():
    """If pass 1 decodes and pass 2 does not, the judged table belongs to
    pass 1 — so the record carries a NOTE, never a refusal beside an
    accepted answer, and never pass 2's margin describing pass 1's decode."""
    h = Harness()
    real = h.session.gather_full
    n = {"i": 0}
    # a full pass is 2 + 2*bits_needed(76) captures; cut the SECOND one off
    first_pass = 2 + 2 * gray_code.bits_needed(h.total)

    async def gather(seconds, *, min_frames=1):
        n["i"] += 1
        if n["i"] > first_pass + 2:
            return []                          # too few frames to average
        return await real(seconds, min_frames=min_frames)

    h.session.gather_full = gather
    result = h.run(layout=h.layout, instrument={}, targets=["device:tv-backlight"],
                   repeat=2)
    entry = result.targets[0]
    assert entry["ok"] and entry["table"] is not None
    assert entry["refusal"] == "" and entry["reason"] == ""
    assert entry["notes"] and "later repeat" in entry["notes"][0]
    # the margin reported is the one the accepted decode came from
    assert entry["resolution"]["verdict"] == gray_code.RESOLUTION_OK
    assert len(entry["decodes"]) == 1
