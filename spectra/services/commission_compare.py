"""THE PRE-REGISTERED COMPARISON — frozen in the plan before any run, and
implemented here exactly as written.

THE PLAN'S OWN TABLE, quoted verbatim from `/home/javi/fleet-spotfx/
.lavish/room-light-field-plan.html` §8 ("The pre-registered comparison —
frozen before any run"), because a comparison judged AFTER the fact passes
by construction and the whole value of this test is that it could not:

    These fields, these tolerances, published here in advance. Judged
    exactly as written; nothing added or relaxed after the run. A pass is
    all rows green; any red row is reported as which side it indicts.

    Field            | Ground truth (stored, known-good) | Pass tolerance | A failure would mean...
    Pixel count seen | 560 (tv-backlight) + mapped sconce ranges | >= 98% of pixels identified | Under-count -> occlusion or blob-merge (commissioning defect) or dead pixels — the existing hardware wrong, worth him knowing.
    Pixel ordering   | Segment ranges & order in the tv-mapper (e.g. tv-backlight 0–559, sconce-right 0–27...) | Monotone order per segment, <= 2% outliers | Scrambled order -> commissioning sequencing defect (a wrong stored order would have shown in his scenes for months).
    2-D arrangement  | The mapper's stored pixel layout | Median position error <= 5% of the TV diagonal after one global scale/rotation/translation fit (camera pose is arbitrary; the shape is the truth) | Shape divergence -> camera-geometry defect or the hand-built mapper has been slightly wrong all along — arguably the most valuable outcome available.
    Cross-device stitch | Sconce segments' position relative to the TV ring | Same 5% bound, same fit | Stitch off -> per-device capture misalignment (commissioning) or a stale stitched segment in the stored mapper.
    Device latency   | The per-device instrument's reading for the same device, taken the same evening | +/- 15 ms between the two instruments | Disagreement indicts one of the two instruments, not the device — both get investigated.

    Every mismatch is attributed per the right-hand column before anyone
    reaches for an explanation — a comparison judged after the fact passes
    by construction, which is why this table ships in the plan and not in
    the report.

THE TOLERANCES BELOW ARE THAT TABLE AND NOTHING ELSE. 0.98, 0.02, 0.05,
0.05, 15 ms. They are not tuning knobs, they were not chosen by looking at
a run, and a future change that moves one has left the pre-registration —
at which point the honest act is a NEW pre-registration, published before
the next run, not an edit to these five numbers.

FOUR VERDICTS, NOT TWO, and the third is the one the brief insists on:

  pass        every row green.
  findings    a row is red and the table's own right-hand column attributes
              it to HIS DATA rather than to this instrument — dead pixels,
              or the hand-built mapper being off. Reported as FINDINGS, in
              the plan's own words "arguably the most valuable outcome
              available", and NEVER as a commissioning failure.
  incomplete  a row could not be measured at all (no stored 2-D layout to
              compare against; a camera cadence too slow to resolve 15 ms).
              An unmeasured row never passes silently — that is the one way
              a pre-registered test quietly becomes decoration.
  fail        a row is red and indicts THIS instrument.

Precedence when several apply: fail > incomplete > findings > pass.

NEVER A JUDGMENT CALL AT RUNTIME. Every attribution below is a rule
computed from the numbers — where the offenders sit, whether they are one
contiguous stretch or scattered, whether a segment is the right SHAPE in
the wrong PLACE — decided here, in advance, so a run in the middle of the
night produces the same verdict a run watched by three people would.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# ── the frozen numbers ─────────────────────────────────────────────────────
SEEN_MIN_FRACTION = 0.98            # ">= 98% of pixels identified"
ORDER_MAX_OUTLIER_FRACTION = 0.02   # "monotone order per segment, <= 2% outliers"
ARRANGEMENT_MAX_ERROR = 0.05        # "<= 5% of the TV diagonal"
STITCH_MAX_ERROR = 0.05             # "same 5% bound, same fit"
LATENCY_TOLERANCE_MS = 15.0         # "+/- 15 ms between the two instruments"

# ── the attribution rules, fixed in advance (see the docstring) ────────────
#: A gap of missing pixels this long or shorter, with decoded pixels on BOTH
#: sides, reads as dead pixels in the strip rather than as something this
#: instrument failed to see: an occlusion or a blob-merge takes out a
#: neighbourhood, not four pixels with working neighbours either side.
DEAD_RUN_MAX = 8
#: Missing indices separated by fewer than this many decoded ones are the
#: same gap for the purposes of the rule above.
RUN_GAP_SLACK = 1
#: A 2-D divergence is LOCALISED — the hand-built mapper being off in one
#: stretch — when this fraction of the pixels that MISS the consensus fit
#: fall in a single contiguous stretch of the composition. Anything more
#: scattered is a camera-geometry defect: an optical error is smooth across
#: the frame and does not confine itself to one authored stretch.
LOCALISED_FRACTION = 0.90
#: ...and only when a single similarity fit puts at least this fraction of
#: the decoded pixels inside the bound. That CONSENSUS fit is ATTRIBUTION
#: ONLY — the row's own pass/fail is judged on the ONE global fit the plan
#: freezes, and this never touches it. Its job is to answer a different
#: question: is most of the composition self-consistent with the stored
#: layout, with one stretch disagreeing (the mapper), or does nothing agree
#: with anything (this instrument's geometry)?
CONSENSUS_FRACTION = 0.5
#: A step this many times the segment's own median step is a JUMP, not a
#: continuation. Generous on purpose: a real strip's spacing varies with
#: perspective across a wrapped corner, and this row is meant to catch a
#: scrambled ORDER, not to grade the evenness of his LED pitch.
ORDER_JUMP_FACTOR = 3.0
#: A step counts as a BACKTRACK when its cosine against the previous step is
#: below this. Zero would be wrong and was measured to be wrong: a wrapped
#: TV's corner turns exactly ninety degrees, whose cosine is 0, and floating
#: point puts half of those a hair negative — the four corners of his own
#: television would have been reported as out-of-order pixels. Only a
#: genuine reversal (cosine approaching -1) is a backtrack; anything up to
#: about 102 degrees is a corner.
ORDER_BACKTRACK_COS = -0.2
#: A stitched segment is the right SHAPE in the wrong PLACE when removing
#: its own mean residual (a pure translation) brings its median residual
#: back inside the bound. That is a stale stored offset for that segment,
#: not a capture that misaligned it.
_STITCH_SHAPE_BOUND = STITCH_MAX_ERROR

PASS = "pass"
FAIL = "fail"
FINDING = "finding"
UNMEASURED = "unmeasured"


@dataclass
class Segment:
    """One segment of the stored composition, in composition order — the
    ground truth for rows 2 and 4. `start`/`end` are inclusive indices in
    the COMPOSITION's own global pixel order (the mapper's stored segment
    list walked in order); `device_id` is which fixture backs it."""
    index: int
    device_id: str
    virtual_id: str
    start: int
    end: int

    @property
    def length(self) -> int:
        return max(0, self.end - self.start + 1)

    @property
    def indices(self) -> range:
        return range(self.start, self.end + 1)

    def as_dict(self) -> dict:
        return {"index": self.index, "device_id": self.device_id,
                "virtual_id": self.virtual_id, "start": self.start,
                "end": self.end, "length": self.length}


@dataclass
class Row:
    """One judged row of the frozen table. `verdict` is one of PASS / FAIL /
    FINDING / UNMEASURED; `indicts` names the side per the table's own
    right-hand column and is empty on a pass."""
    field: str
    ground_truth: str
    tolerance: str
    verdict: str
    measured: str = ""
    indicts: str = ""
    detail: str = ""
    numbers: dict = field(default_factory=dict)

    @property
    def green(self) -> bool:
        return self.verdict == PASS

    def as_dict(self) -> dict:
        return {"field": self.field, "ground_truth": self.ground_truth,
                "tolerance": self.tolerance, "verdict": self.verdict,
                "measured": self.measured, "indicts": self.indicts,
                "detail": self.detail, "numbers": self.numbers}


def verdict_of(rows: list[Row]) -> str:
    kinds = {r.verdict for r in rows}
    if FAIL in kinds:
        return "fail"
    if UNMEASURED in kinds:
        return "incomplete"
    if FINDING in kinds:
        return "findings"
    return "pass"


# ── helpers, all pure ──────────────────────────────────────────────────────

def _runs(values: list[int], gap_slack: int = RUN_GAP_SLACK) -> list[list[int]]:
    """Consecutive-ish integers grouped into runs. A gap of `gap_slack` or
    fewer missing members keeps a run together."""
    out: list[list[int]] = []
    for v in sorted(values):
        if out and v - out[-1][-1] <= gap_slack + 1:
            out[-1].append(v)
        else:
            out.append([v])
    return out


def similarity_fit(source: np.ndarray, target: np.ndarray
                   ) -> tuple[float, np.ndarray, np.ndarray]:
    """ONE global scale/rotation/translation, least squares (Umeyama). The
    plan's own words: "camera pose is arbitrary; the shape is the truth" —
    so the fit is allowed to place and turn and size the stored layout
    freely, and nothing else. Never a per-segment fit and never a
    perspective one: either would absorb the very divergence this row
    exists to find."""
    src = np.asarray(source, dtype=np.float64)
    dst = np.asarray(target, dtype=np.float64)
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 2:
        raise ValueError(f"need matching Nx2 point sets, got {src.shape} "
                         f"and {dst.shape}")
    mu_s, mu_d = src.mean(axis=0), dst.mean(axis=0)
    s0, d0 = src - mu_s, dst - mu_d
    cov = (d0.T @ s0) / len(src)
    u, sig, vt = np.linalg.svd(cov)
    d = np.sign(np.linalg.det(u @ vt))
    correction = np.diag([1.0, d])
    rot = u @ correction @ vt
    var = float((s0 ** 2).sum() / len(src))
    scale = float((sig * np.array([1.0, d])).sum() / var) if var > 0 else 1.0
    trans = mu_d - scale * (rot @ mu_s)
    return scale, rot, trans


def apply_fit(points: np.ndarray, scale: float, rot: np.ndarray,
              trans: np.ndarray) -> np.ndarray:
    return (scale * (np.asarray(points, dtype=np.float64) @ rot.T)) + trans


# ── the five rows ──────────────────────────────────────────────────────────

def row_pixel_count(decode, segments: list[Segment]) -> Row:
    """ROW 1 — "Pixel count seen". Ground truth: every pixel of the stored
    composition. Pass: >= 98% identified.

    THE TABLE'S OWN TWO OUTCOMES, and they are attributed here rather than
    argued about later: an under-count is either occlusion / blob-merge
    (this instrument, a commissioning defect) or DEAD PIXELS (his hardware,
    worth him knowing). The rule: short gaps with working pixels on BOTH
    sides are dead LEDs — an occlusion or a merged blob takes out a
    neighbourhood, it does not remove four pixels and leave their
    neighbours perfect."""
    total = sum(s.length for s in segments)
    seen = set(decode.seen)
    missing = [i for i in range(total) if i not in seen]
    fraction = (total - len(missing)) / total if total else 0.0
    numbers = {"total": total, "seen": total - len(missing),
               "fraction": round(fraction, 5),
               "missing_count": len(missing), "missing": missing[:64]}
    row = Row(field="Pixel count seen",
              ground_truth=f"{total} pixels of the stored composition",
              tolerance=">= 98% of pixels identified",
              measured=f"{total - len(missing)} of {total} "
                       f"({fraction * 100:.1f}%)",
              verdict=PASS, numbers=numbers)
    if fraction >= SEEN_MIN_FRACTION:
        return row
    runs = _runs(missing)
    isolated = [r for r in runs
                if len(r) <= DEAD_RUN_MAX and r[0] - 1 in seen and r[-1] + 1 in seen]
    numbers["gaps"] = [[r[0], r[-1]] for r in runs][:32]
    numbers["dead_pixel_gaps"] = [[r[0], r[-1]] for r in isolated][:32]
    if len(runs) and len(isolated) == len(runs):
        row.verdict = FINDING
        row.indicts = "his hardware — dead pixels in the strip"
        row.detail = (
            f"{len(missing)} pixels never lit, in {len(runs)} short "
            f"gap(s) with working pixels either side "
            f"({', '.join(f'{r[0]}-{r[-1]}' for r in runs[:6])}). That is "
            f"the table's 'dead pixels — the existing hardware wrong, worth "
            f"him knowing' outcome: reported as a finding, not as a "
            f"commissioning failure.")
        return row
    row.verdict = FAIL
    row.indicts = "this instrument — occlusion or blob-merge (commissioning defect)"
    row.detail = (
        f"{len(missing)} pixels of {total} were never identified, spread "
        f"over {len(runs)} run(s) — too broad to be dead LEDs. Per the "
        f"table: occlusion or blob-merge. Check the phone can see the whole "
        f"composition from where it is standing.")
    return row


def row_pixel_ordering(decode, segments: list[Segment]) -> Row:
    """ROW 2 — "Pixel ordering". Ground truth: the segment ranges and order
    stored in the mapper. Pass: monotone order per segment, <= 2% outliers.

    MONOTONE ALONG THE SEGMENT'S OWN PATH, not along a straight line, and
    that distinction is forced by his actual hardware rather than chosen:
    `tv-backlight` is 560 pixels WRAPPED AROUND A TELEVISION, so its
    correctly-ordered pixels run right, then down, then left, then up.
    Projecting that onto any single axis makes a perfectly-ordered ring look
    scrambled — the check would fail on a good room, which is worse than no
    check at all.

    So a pixel is an OUTLIER when, taken in the stored composition order, it
    is not a continuation of the walk:

      * a JUMP — the step from its predecessor is more than
        `ORDER_JUMP_FACTOR` times this segment's own median step. Adjacent
        LEDs are adjacent in the picture; a pixel that lands far from the
        one before it is out of sequence.
      * a BACKTRACK — the step reverses against the previous one
        (`ORDER_BACKTRACK_COS`). A corner turns ninety degrees and is NOT
        flagged; only genuinely going back on itself is.

    Both are properties of the ORDER alone, computed per segment, with no
    reference to any stored geometry — which is what lets this row be judged
    even when row 3 has no layout to fit against.

    Only ONE side of the table applies here, and the plan says why: "a wrong
    stored order would have shown in his scenes for months", so a scrambled
    reading indicts this instrument's sequencing, not his data."""
    outliers: list[int] = []
    counted = 0
    per_segment = []
    for seg in segments:
        pts = [(i, decode.positions[i]) for i in seg.indices
               if i in decode.positions]
        if len(pts) < 4:
            per_segment.append({"segment": seg.index, "device_id": seg.device_id,
                                "decoded": len(pts), "outliers": 0,
                                "note": "too few decoded pixels to judge an "
                                        "order"})
            continue
        arr = np.array([p for _i, p in pts], dtype=np.float64)
        steps = np.diff(arr, axis=0)
        lengths = np.hypot(*steps.T)
        median_step = float(np.median(lengths)) or 1e-12
        bad: set[int] = set()
        for k in range(len(steps)):
            if lengths[k] > ORDER_JUMP_FACTOR * median_step:
                bad.add(k + 1)
            if k and lengths[k] > 0 and lengths[k - 1] > 0:
                cos = float(steps[k] @ steps[k - 1]) / (lengths[k] * lengths[k - 1])
                if cos < ORDER_BACKTRACK_COS:
                    bad.add(k + 1)
        counted += len(pts)
        outliers.extend(pts[k][0] for k in sorted(bad))
        per_segment.append({"segment": seg.index, "device_id": seg.device_id,
                            "decoded": len(pts), "outliers": len(bad),
                            "median_step": round(median_step, 5)})
    fraction = (len(outliers) / counted) if counted else 0.0
    row = Row(field="Pixel ordering",
              ground_truth="segment ranges & order in the stored mapper",
              tolerance="monotone order per segment, <= 2% outliers",
              measured=f"{len(outliers)} of {counted} out of order "
                       f"({fraction * 100:.2f}%)",
              verdict=PASS,
              numbers={"outliers": len(outliers), "counted": counted,
                       "fraction": round(fraction, 5),
                       "per_segment": per_segment,
                       "outlier_indices": sorted(outliers)[:64]})
    if counted == 0:
        row.verdict = UNMEASURED
        row.indicts = "neither — nothing was decoded to put in order"
        row.detail = ("no segment had enough decoded pixels to judge an "
                      "order; row 1 says why.")
        return row
    if fraction > ORDER_MAX_OUTLIER_FRACTION:
        row.verdict = FAIL
        row.indicts = "this instrument — commissioning sequencing defect"
        row.detail = (
            f"{len(outliers)} decoded pixels do not continue their own "
            f"segment's walk ({fraction * 100:.2f}%, over the 2% bound) — "
            f"they jump away from the pixel before them, or double back on "
            f"it. Per the table this indicts the commissioning sequencing: a "
            f"wrong STORED order would have shown in his scenes for months.")
    return row


def _fit_residuals(decode, layout: dict[int, tuple[float, float]]
                   ) -> tuple[Optional[dict[int, float]],
                              Optional[dict[int, tuple[float, float]]],
                              Optional[dict]]:
    """ONE global similarity fit of the stored layout onto the decoded
    positions, and what it leaves behind: per-index residual DISTANCES and
    per-index residual VECTORS. The vectors are not decoration — row 4's
    "right shape, wrong place" rule is a translation test, and a set of
    scalar distances cannot say whether the misses all point the same way.

    Returns (distances, vectors, fit-info), or (None, None, None) when
    there is nothing to fit."""
    common = sorted(set(decode.positions) & set(layout))
    if len(common) < 3:
        return None, None, None
    src = np.array([layout[i] for i in common], dtype=np.float64)
    dst = np.array([decode.positions[i] for i in common], dtype=np.float64)
    scale, rot, trans = similarity_fit(src, dst)
    fitted = apply_fit(src, scale, rot, trans)
    delta = fitted - dst
    err = np.hypot(*delta.T)
    return ({i: float(e) for i, e in zip(common, err)},
            {i: (float(d[0]), float(d[1])) for i, d in zip(common, delta)},
            {"scale": float(scale), "points": len(common),
             "rotation_deg": float(np.degrees(np.arctan2(rot[1, 0], rot[0, 0])))})


def _consensus_outliers(decode, layout: dict[int, tuple[float, float]],
                        segments: list[Segment], bound: float
                        ) -> tuple[int, list[int]]:
    """ATTRIBUTION ONLY (see CONSENSUS_FRACTION): the largest set of decoded
    pixels one similarity fit can put inside `bound`, and the pixels left
    outside it.

    Seeded from each stored segment in turn plus the whole composition — a
    handful of fits, deterministic, no random sampling — because the
    question being asked is "does most of this composition agree with the
    stored layout while one authored stretch does not", and an authored
    stretch is exactly a segment or a run of them."""
    common = sorted(set(decode.positions) & set(layout))
    if len(common) < 3:
        return 0, []
    seeds = [list(seg.indices) for seg in segments] + [common]
    best_inside: list[int] = []
    for seed in seeds:
        picked = [i for i in seed if i in decode.positions and i in layout]
        if len(picked) < 3:
            continue
        src = np.array([layout[i] for i in picked], dtype=np.float64)
        dst = np.array([decode.positions[i] for i in picked], dtype=np.float64)
        try:
            scale, rot, trans = similarity_fit(src, dst)
        except (ValueError, np.linalg.LinAlgError):
            continue
        allsrc = np.array([layout[i] for i in common], dtype=np.float64)
        alldst = np.array([decode.positions[i] for i in common], dtype=np.float64)
        err = np.hypot(*(apply_fit(allsrc, scale, rot, trans) - alldst).T)
        inside = [i for i, e in zip(common, err) if e <= bound]
        if len(inside) > len(best_inside):
            best_inside = inside
    outside = sorted(set(common) - set(best_inside))
    return len(best_inside), outside


def reference_diagonal(layout: dict[int, tuple[float, float]],
                       segments: list[Segment], scale: float) -> tuple[float, str]:
    """THE TV DIAGONAL the 5% is a percentage OF, and which device counts as
    "the TV": the fixture carrying the MOST pixels of the composition. A
    fixed rule, decided here rather than by whoever reads the report — the
    plan names the TV because it is the big one, and "the big one" is a
    number, not an opinion."""
    counts: dict[str, int] = {}
    for seg in segments:
        counts[seg.device_id] = counts.get(seg.device_id, 0) + seg.length
    if not counts:
        return 0.0, ""
    device = max(sorted(counts), key=lambda d: counts[d])
    pts = [layout[i] for seg in segments if seg.device_id == device
           for i in seg.indices if i in layout]
    if len(pts) < 2:
        return 0.0, device
    arr = np.array(pts, dtype=np.float64)
    span = arr.max(axis=0) - arr.min(axis=0)
    # In FITTED units, so the residuals and the diagonal are the same scale.
    return float(np.hypot(*span) * scale), device


def row_arrangement(decode, segments: list[Segment],
                    layout: Optional[dict[int, tuple[float, float]]],
                    layout_note: str = "") -> tuple[Row, Optional[dict]]:
    """ROW 3 — "2-D arrangement". Ground truth: the mapper's stored pixel
    layout. Pass: median position error <= 5% of the TV diagonal after ONE
    global scale/rotation/translation fit.

    UNMEASURED WHEN HIS MAPPER STORES NO 2-D LAYOUT AT ALL, which is not a
    hypothetical: his real `tv-mapper` is a `mapping: copy` virtual with
    `rows: 1` and no shape map, so the stored composition carries an ORDER
    (rows 1, 2 and 4's membership) and no geometry. Inventing a rectangle
    to compare against would be exactly the "admired for plausibility"
    failure this whole test exists to avoid — so the row says it cannot be
    judged, names what would make it judgeable, and the run's verdict comes
    out INCOMPLETE rather than green."""
    row = Row(field="2-D arrangement",
              ground_truth="the mapper's stored pixel layout",
              tolerance="median position error <= 5% of the TV diagonal "
                        "after one global scale/rotation/translation fit",
              verdict=UNMEASURED)
    if not layout:
        row.indicts = "neither — there is no stored 2-D layout to compare against"
        row.detail = layout_note or (
            "the stored mapper carries a pixel ORDER but no 2-D layout "
            "(rows: 1, no shape map), so there is no arrangement to fit "
            "against. Rows 1, 2 and 4's membership are unaffected.")
        return row, None
    residuals, vectors, fit = _fit_residuals(decode, layout)
    if residuals is None:
        row.indicts = "neither — too few decoded pixels to fit"
        row.detail = ("a global similarity fit needs at least three decoded "
                      "pixels that the stored layout also names")
        return row, None
    diagonal, device = reference_diagonal(layout, segments, fit["scale"])
    if diagonal <= 0:
        row.indicts = "neither — the stored layout has no extent to measure against"
        row.detail = "the stored layout's reference device spans nothing"
        return row, None
    bound = ARRANGEMENT_MAX_ERROR * diagonal
    values = np.array(list(residuals.values()))
    median = float(np.median(values))
    row.numbers = {"median_error": median, "p95_error": float(np.percentile(values, 95)),
                   "diagonal": diagonal, "bound": bound,
                   "median_fraction": round(median / diagonal, 5),
                   "reference_device": device, "fit": fit}
    row.measured = (f"median {median / diagonal * 100:.2f}% of the "
                    f"{device} diagonal")
    if median <= bound:
        row.verdict = PASS
        return row, {"residuals": residuals, "vectors": vectors,
                     "fit": fit, "diagonal": diagonal}
    offenders = sorted(i for i, e in residuals.items() if e > bound)
    # ATTRIBUTION, never the judgment: the median above already decided
    # pass/fail on the ONE global fit the plan freezes. This asks the
    # separate question of WHICH SIDE a failure indicts.
    agreed, outside = _consensus_outliers(decode, layout, segments, bound)
    runs = _runs(outside, gap_slack=2)
    biggest = max((len(r) for r in runs), default=0)
    decoded = len(set(decode.positions) & set(layout))
    localised = (outside and agreed >= CONSENSUS_FRACTION * decoded
                 and biggest >= LOCALISED_FRACTION * len(outside))
    row.numbers["offenders"] = len(offenders)
    row.numbers["consensus_inside"] = agreed
    row.numbers["consensus_outside"] = len(outside)
    row.numbers["offender_runs"] = [[r[0], r[-1]] for r in runs][:16]
    if localised:
        run = max(runs, key=len)
        touched = sorted({s.index for s in segments
                          for i in run if s.start <= i <= s.end})
        row.verdict = FINDING
        row.indicts = "his data — the hand-built mapper is off in one stretch"
        row.detail = (
            f"one fit puts {agreed} of {decoded} decoded pixels inside the "
            f"bound, and {biggest} of the {len(outside)} it does not are one "
            f"contiguous stretch ({run[0]}-{run[-1]}, segment(s) {touched}). "
            f"An optical error is smooth across a whole frame; most of the "
            f"composition agreeing while one authored stretch does not is "
            f"the table's 'the hand-built mapper has been slightly wrong all "
            f"along' outcome — a finding, not a commissioning failure.")
    else:
        row.verdict = FAIL
        row.indicts = "this instrument — camera-geometry defect"
        row.detail = (
            f"median position error is {median / diagonal * 100:.2f}% of the "
            f"{device} diagonal, over the 5% bound, and no single fit "
            f"reconciles more than {agreed} of {decoded} decoded pixels with "
            f"the stored layout ({len(outside)} outside it, across "
            f"{len(runs)} stretches). Nothing agrees with anything, which is "
            f"not what one wrong authored stretch looks like. Per the table: "
            f"a camera-geometry defect in this instrument.")
    return row, {"residuals": residuals, "vectors": vectors,
                 "fit": fit, "diagonal": diagonal}


def row_stitch(decode, segments: list[Segment], fitted: Optional[dict],
               reference_device: str) -> Row:
    """ROW 4 — "Cross-device stitch". Ground truth: the sconce segments'
    position relative to the TV ring. Pass: the same 5% bound, THE SAME FIT
    — not a second one, which is what makes this a stitch check rather than
    four independent shape checks.

    The two sides of the table are separated by asking whether a segment is
    the right SHAPE in the wrong PLACE: if removing that segment's own mean
    residual (a pure translation) brings it back inside the bound, the
    capture read the segment correctly and the STORED offset for it is
    stale — his data. If it is still out after that, the segment was
    captured misaligned — this instrument."""
    row = Row(field="Cross-device stitch",
              ground_truth="the other devices' segments, placed relative to "
                           "the reference device by the SAME fit",
              tolerance="same 5% bound, same fit",
              verdict=UNMEASURED)
    if not fitted:
        row.indicts = "neither — row 3's fit could not be made"
        row.detail = ("this row is judged on the SAME global fit as the 2-D "
                      "arrangement row, and there was none to judge with")
        return row
    residuals = fitted["residuals"]
    vectors = fitted["vectors"]
    bound = STITCH_MAX_ERROR * fitted["diagonal"]
    others = [s for s in segments if s.device_id != reference_device]
    if not others:
        row.indicts = "neither — this composition spans one device only"
        row.detail = ("cross-device stitch needs at least two fixtures in "
                      "the composition")
        return row
    per_segment = []
    worst_shape_ok: list[str] = []
    worst_shape_bad: list[str] = []
    all_errors: list[float] = []
    for seg in others:
        errs = [residuals[i] for i in seg.indices if i in residuals]
        if len(errs) < 3:
            per_segment.append({"segment": seg.index, "device_id": seg.device_id,
                                "decoded": len(errs), "median": None})
            continue
        all_errors.extend(errs)
        median = float(np.median(errs))
        # RIGHT SHAPE, WRONG PLACE? Subtract this segment's OWN mean
        # residual vector — a pure translation — and re-measure. Vectors,
        # not distances: three pixels each 0.1 off in three different
        # directions are not a segment that merely sits in the wrong place.
        vecs = np.array([vectors[i] for i in seg.indices if i in vectors],
                        dtype=np.float64)
        shifted = float(np.median(np.hypot(*(vecs - vecs.mean(axis=0)).T)))
        per_segment.append({"segment": seg.index, "device_id": seg.device_id,
                            "decoded": len(errs), "median": median,
                            "median_after_translation": shifted,
                            "within": median <= bound})
        if median > bound:
            (worst_shape_ok if shifted <= bound else worst_shape_bad).append(
                f"segment {seg.index} ({seg.device_id})")
    if not all_errors:
        row.indicts = "neither — no other device decoded enough pixels"
        row.detail = "row 1 says how much of the composition was seen"
        return row
    median = float(np.median(all_errors))
    row.numbers = {"median_error": median, "bound": bound,
                   "diagonal": fitted["diagonal"],
                   "median_fraction": round(median / fitted["diagonal"], 5),
                   "reference_device": reference_device,
                   "per_segment": per_segment}
    row.measured = (f"median {median / fitted['diagonal'] * 100:.2f}% of the "
                    f"{reference_device} diagonal")
    if median <= bound:
        row.verdict = PASS
        return row
    if worst_shape_ok and not worst_shape_bad:
        row.verdict = FINDING
        row.indicts = "his data — a stale stitched segment in the stored mapper"
        row.detail = (
            f"{', '.join(worst_shape_ok)} came out the right SHAPE in the "
            f"wrong PLACE: removing a pure translation brings it back inside "
            f"the 5% bound. Per the table that is a stale stitched segment "
            f"in the stored mapper — a finding, not a commissioning failure.")
        return row
    row.verdict = FAIL
    row.indicts = "this instrument — per-device capture misalignment"
    row.detail = (
        f"the non-reference segments sit {median / fitted['diagonal'] * 100:.2f}% "
        f"of the diagonal off the same global fit, and a pure translation "
        f"does not bring {', '.join(worst_shape_bad) or 'them'} back. Per "
        f"the table: per-device capture misalignment in this instrument.")
    return row


def row_latency(measured: dict, instrument: dict, resolution_ms: float) -> Row:
    """ROW 5 — "Device latency". Ground truth: the per-device instrument's
    reading for the same device, taken the same evening. Pass: +/- 15 ms
    between the two instruments.

    BOTH SIDES ARE COMPARED AS DIFFERENCES BETWEEN DEVICES, never as two
    absolute numbers, for the reason `spectra/services/device_equalization.
    py` states at length: each absolute reading carries a systematic this
    instrument shares in every measurement (there, the audio path; here,
    the camera pipeline and the frame clock), and subtracting one device
    from another cancels it exactly. An absolute comparison would be two
    different quantities pretending to be one.

    UNMEASURED WHEN THE CAMERA CANNOT RESOLVE 15 ms. A fixture's step from
    dark to full is far faster than a video frame, so the crossing time can
    only be pinned to about one frame interval: at the mapping tap's 5 fps
    that is 200 ms, and a 15 ms tolerance is simply not a question this
    camera can answer. Saying so is the honest outcome; passing a row whose
    error bar is thirteen times its tolerance would not be."""
    row = Row(field="Device latency",
              ground_truth="the per-device instrument's reading for the same "
                           "device, taken the same evening",
              tolerance="+/- 15 ms between the two instruments",
              verdict=UNMEASURED)
    row.numbers = {"resolution_ms": round(resolution_ms, 1),
                   "commissioning_ms": {k: round(v, 1) for k, v in measured.items()},
                   "instrument_ms": {k: round(v, 1) for k, v in instrument.items()}}
    if resolution_ms > LATENCY_TOLERANCE_MS:
        row.indicts = "neither — this camera cannot resolve 15 ms"
        row.detail = (
            f"the capture ran at one frame every {resolution_ms:.0f} ms, so "
            f"the moment a fixture lights can only be pinned to about that. "
            f"A +/- 15 ms comparison needs frames at least every 15 ms "
            f"(~67 fps). Reported unmeasured rather than passed.")
        return row
    shared = sorted(set(measured) & set(instrument))
    if len(shared) < 2:
        row.indicts = "neither — fewer than two devices measured by both instruments"
        row.detail = ("the comparison is between-device DIFFERENCES, so it "
                      "needs at least two devices measured by both "
                      "instruments (run /avsync per device first)")
        return row
    base = shared[0]
    deltas = {d: (measured[d] - measured[base]) - (instrument[d] - instrument[base])
              for d in shared[1:]}
    worst = max(deltas, key=lambda d: abs(deltas[d]))
    row.numbers["reference_device"] = base
    row.numbers["deltas_ms"] = {k: round(v, 1) for k, v in deltas.items()}
    row.measured = (f"worst disagreement {deltas[worst]:+.1f} ms ({worst} vs "
                    f"{base})")
    if abs(deltas[worst]) <= LATENCY_TOLERANCE_MS:
        row.verdict = PASS
        return row
    row.verdict = FAIL
    row.indicts = ("one of the two instruments — not the device; both get "
                   "investigated")
    row.detail = (
        f"the two instruments disagree by {deltas[worst]:+.1f} ms on "
        f"{worst} relative to {base}, past the +/- 15 ms bound. Per the "
        f"table this indicts one of the two instruments, not the fixture.")
    return row


def judge(decode, segments: list[Segment],
          layout: Optional[dict[int, tuple[float, float]]] = None,
          layout_note: str = "",
          latency_measured: Optional[dict] = None,
          latency_instrument: Optional[dict] = None,
          latency_resolution_ms: float = 1e9) -> dict:
    """The whole frozen table, judged. Five rows, in the plan's own order,
    plus the verdict its precedence produces."""
    r1 = row_pixel_count(decode, segments)
    r2 = row_pixel_ordering(decode, segments)
    r3, fitted = row_arrangement(decode, segments, layout, layout_note)
    reference = (r3.numbers.get("reference_device")
                 or reference_diagonal(layout or {}, segments, 1.0)[1])
    r4 = row_stitch(decode, segments, fitted, reference)
    r5 = row_latency(latency_measured or {}, latency_instrument or {},
                     latency_resolution_ms)
    rows = [r1, r2, r3, r4, r5]
    return {"verdict": verdict_of(rows),
            "rows": [r.as_dict() for r in rows],
            "findings": [r.as_dict() for r in rows if r.verdict == FINDING],
            "tolerances": {
                "seen_min_fraction": SEEN_MIN_FRACTION,
                "order_max_outlier_fraction": ORDER_MAX_OUTLIER_FRACTION,
                "arrangement_max_error": ARRANGEMENT_MAX_ERROR,
                "stitch_max_error": STITCH_MAX_ERROR,
                "latency_tolerance_ms": LATENCY_TOLERANCE_MS}}


#: The order the aggregate resolves a field in when several targets
#: disagree about it, worst first. It is `verdict_of`'s own precedence read
#: one row at a time, and it is the reason a per-target run cannot come out
#: greener than the whole-composition run it replaces: one target's FAIL is
#: the whole table's FAIL, and one target that could not be MEASURED — a
#: refusal included — makes the table INCOMPLETE rather than quietly
#: shrinking the denominator to the targets that happened to work.
_FIELD_PRECEDENCE = (FAIL, UNMEASURED, FINDING, PASS)

#: The five fields, in the plan's own order, so an aggregate has a row for
#: each even when every target refused and there is not one table to read
#: the order off.
FIELD_ORDER = ("Pixel count seen", "Pixel ordering", "2-D arrangement",
               "Cross-device stitch", "Device latency")


def aggregate(entries: list[dict]) -> dict:
    """THE PER-TARGET RESULT SET, IN THE SAME JUDGED SHAPE — five rows, the
    same five tolerances, one verdict.

    A per-fixture run is the SAME pre-registered comparison applied to a
    slice of the same stored ground truth, so it is judged by the same
    table and it aggregates into the same shape rather than into a second,
    friendlier one. Nothing here re-judges anything: every row of every
    target was already decided by `judge` against tolerances frozen in the
    plan, and this only resolves what the set of them means.

    THE TWO RULES, and both exist to stop a split run reading greener than
    the whole one it replaces:

      * a field is as bad as its worst target (`_FIELD_PRECEDENCE`);
      * a target that produced NO table — refused for resolution, for the
        camera, for anything — contributes UNMEASURED to every field, with
        its own sentence. It is never simply absent. A denominator that
        silently drops the pieces that could not be read is exactly the
        failure this whole instrument exists to refuse.

    `entries` is [{target, label, table (dict or None), reason, refusal}].
    """
    entries = list(entries or [])
    fields: list[str] = []
    for entry in entries:
        for row in ((entry.get("table") or {}).get("rows") or []):
            if row.get("field") not in fields:
                fields.append(str(row.get("field")))
    if not fields:
        fields = list(FIELD_ORDER)

    rows: list[Row] = []
    for name in fields:
        per: list[tuple[str, dict]] = []
        for entry in entries:
            table = entry.get("table") or {}
            label = str(entry.get("label") or entry.get("target") or "?")
            found = next((r for r in (table.get("rows") or [])
                          if r.get("field") == name), None)
            if found is None:
                found = {"field": name, "verdict": UNMEASURED,
                         "ground_truth": "", "tolerance": "",
                         "measured": "not measured",
                         "indicts": "",
                         "detail": str(entry.get("reason") or
                                       "this target produced no decode"),
                         "numbers": {}}
            per.append((label, found))
        verdict = next((v for v in _FIELD_PRECEDENCE
                        if any(r.get("verdict") == v for _l, r in per)),
                       UNMEASURED)
        worst = [(l, r) for l, r in per if r.get("verdict") == verdict]
        template = worst[0][1] if worst else {
            "verdict": UNMEASURED, "ground_truth": "", "tolerance": "",
            "measured": "not measured", "indicts": "",
            "detail": "no target produced a decode"}
        # GROUND TRUTH AND TOLERANCE ARE THE PRE-REGISTRATION, not a
        # property of the worst target — a refused target's filler row has
        # neither, and taking them from it would render three rows of a
        # pre-registered table with no pre-registration in them. They are
        # constant per field, so the first target that carries them is the
        # right source; only `indicts` and `detail` come from the worst.
        stated = next((r for _l, r in per if r.get("ground_truth")), template)
        bound = next((r for _l, r in per if r.get("tolerance")), template)
        counts = {v: sum(1 for _l, r in per if r.get("verdict") == v)
                  for v in _FIELD_PRECEDENCE}
        rows.append(Row(
            field=name,
            ground_truth=str(stated.get("ground_truth") or ""),
            tolerance=str(bound.get("tolerance") or ""),
            verdict=verdict,
            measured="; ".join(f"{l}: {r.get('measured') or r.get('verdict')}"
                               for l, r in per),
            indicts=str(template.get("indicts") or ""),
            detail=(f"{len(worst)} of {len(per)} targets "
                    f"{verdict}: {', '.join(l for l, _r in worst)}. "
                    + str(template.get("detail") or "")).strip(),
            numbers={"per_target": {l: r.get("verdict") for l, r in per},
                     "counts": {k: v for k, v in counts.items() if v}}))

    return {"verdict": verdict_of(rows),
            "rows": [r.as_dict() for r in rows],
            "findings": [r.as_dict() for r in rows if r.verdict == FINDING],
            "targets": [{"target": e.get("target"), "label": e.get("label"),
                         "verdict": ((e.get("table") or {}).get("verdict")
                                     or ("refused" if not e.get("table")
                                         else "")),
                         "refusal": e.get("refusal") or "",
                         "reason": e.get("reason") or ""}
                        for e in entries],
            "tolerances": {
                "seen_min_fraction": SEEN_MIN_FRACTION,
                "order_max_outlier_fraction": ORDER_MAX_OUTLIER_FRACTION,
                "arrangement_max_error": ARRANGEMENT_MAX_ERROR,
                "stitch_max_error": STITCH_MAX_ERROR,
                "latency_tolerance_ms": LATENCY_TOLERANCE_MS}}
