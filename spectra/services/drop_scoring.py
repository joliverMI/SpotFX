"""Scoring the drop detector against HIS marks — the drop-detection plan's
own methodology (report section 5: "a drop counts as found within one beat
of his mark"), as ONE function the test bed's Drops reference table and
scripts/check_drop_detector.py both call, so the page and the acceptance
check can never disagree about what "found" means.

  found / extra   greedy nearest matching (testbed_metrics.match_marks, the
                  test bed's own matcher) of detected drops against his
                  enabled authored drop triggers, at ONE BEAT; every
                  detection left over is an extra.
  extras on what  what of his sits within one beat of each extra — his
                  drop, a scene change, a charge, a lull, a flare, a colour
                  change, or nothing (the plan's "7 on his scene changes,
                  6 on his flares, 1 on nothing").
  lull / charge   for each found drop that both he and the detector gave a
                  lull (charge), how far apart the two are; counted within
                  one beat (lull) and two beats (charge), the plan's
                  section 6 bars.

His drops are counted only inside the captured range (2 s after the first
sample to 1 s before the last — the testbed's own window): a capture that
starts 30 s into the song cannot be faulted for a drop at 20 s.
"""
from __future__ import annotations

import statistics
from typing import Optional

from spectra.services import drop_sequences, testbed_metrics
from spectra.services.drop_detector import TIER_CONFIDENT, SongDetection

SCENE_KINDS = ("fire_scene", "fire_scene_update")
EXTRA_KIND_ORDER = ("drop", "scene", "charge", "lull", "flare", "select_color_set")

CAPTURE_HEAD_MS = 2000
CAPTURE_TAIL_MS = 1000


def _kind_of(mark: drop_sequences.HisMark) -> str:
    return "scene" if mark.kind in SCENE_KINDS else mark.kind


def classify_extra(at_ms: int, marks: list[drop_sequences.HisMark], beat: float) -> str:
    kinds = {_kind_of(m) for m in marks if abs(m.timestamp_ms - at_ms) <= beat}
    for k in EXTRA_KIND_ORDER:
        if k in kinds:
            return k
    return "other" if kinds else "none"


def _timing(errors: list[int]) -> dict:
    if not errors:
        return {"median_abs_ms": None, "worst_abs_ms": None, "within_50ms": 0}
    a = [abs(e) for e in errors]
    return {"median_abs_ms": round(statistics.median(a), 1), "worst_abs_ms": max(a),
            "within_50ms": sum(1 for x in a if x <= 50)}


def _match(ref: list[int], est: list[int], tol: float) -> list[tuple[int, int]]:
    result = testbed_metrics.match_marks(ref, est, tol)
    return [(i, j) for i, j, _ in result.matches]


def score_song(detection: SongDetection, marks: list[drop_sequences.HisMark]) -> dict:
    """The plan's table row for one song: `detection` is what the detector
    produced (drop_detector.detect), `marks` his enabled authored triggers
    (drop_sequences.his_marks)."""
    beat = float(detection.beat_ms)
    lo = detection.captured_from_ms + CAPTURE_HEAD_MS
    hi = detection.captured_to_ms - CAPTURE_TAIL_MS
    groups, _ = drop_sequences.group_authored(marks)
    his = [g for g in groups if lo <= g["drop"]["timestamp_ms"] <= hi]
    his_drops = [g["drop"]["timestamp_ms"] for g in his]

    seqs = sorted(detection.sequences, key=lambda s: s.drop_ms)
    est_all = [s.drop_ms for s in seqs]
    conf = [s for s in seqs if s.tier == TIER_CONFIDENT]
    est_conf = [s.drop_ms for s in conf]

    pairs = _match(his_drops, est_all, beat)
    pairs_conf = _match(his_drops, est_conf, beat)
    hit_est = {j for _, j in pairs}
    hit_conf = {j for _, j in pairs_conf}
    errors = [est_all[j] - his_drops[i] for i, j in pairs]

    extras = [{"drop_ms": est_all[j], "tier": seqs[j].tier,
               "his_mark_here": classify_extra(est_all[j], marks, beat)}
              for j in range(len(est_all)) if j not in hit_est]
    extras_conf = [e for e in extras if e["tier"] == TIER_CONFIDENT]
    extras_by_kind: dict[str, int] = {}
    for e in extras:
        extras_by_kind[e["his_mark_here"]] = extras_by_kind.get(e["his_mark_here"], 0) + 1

    lull_err: list[int] = []
    charge_err: list[int] = []
    for i, j in pairs:
        g, s = his[i], seqs[j]
        if g["lull"] is not None and s.lull_ms is not None:
            lull_err.append(s.lull_ms - g["lull"]["timestamp_ms"])
        if g["charge"] is not None and s.charge_ms is not None:
            charge_err.append(s.charge_ms - g["charge"]["timestamp_ms"])

    missed = [his_drops[i] for i in range(len(his_drops)) if i not in {a for a, _ in pairs}]
    return {
        "beat_ms": round(beat, 1),
        "his_drops": len(his_drops),
        "found": len(pairs),
        "detected": len(est_all),
        "extra": len(extras),
        "confident_found": len(pairs_conf),
        "confident_detected": len(est_conf),
        "confident_extra": len(est_conf) - len(hit_conf),
        "extras": extras,
        "extras_by_kind": extras_by_kind,
        "confident_extras": extras_conf,
        "missed": missed,
        "drop_errors_ms": errors,
        **_timing(errors),
        "lull_compared": len(lull_err),
        "lull_within_1_beat": sum(1 for e in lull_err if abs(e) <= beat),
        "lull_errors_ms": lull_err,
        "charge_compared": len(charge_err),
        "charge_within_2_beats": sum(1 for e in charge_err if abs(e) <= 2 * beat),
        "charge_errors_ms": charge_err,
    }


def totals(rows: list[dict], *, edm_only: Optional[list[bool]] = None) -> dict:
    """Sum the table over songs (optionally only the EDM ones)."""
    pick = rows if edm_only is None else [r for r, e in zip(rows, edm_only) if e]
    keys = ("his_drops", "found", "detected", "extra", "confident_found",
            "confident_detected", "confident_extra", "lull_compared",
            "lull_within_1_beat", "charge_compared", "charge_within_2_beats",
            "within_50ms")
    out = {k: sum(int(r.get(k) or 0) for r in pick) for k in keys}
    errs = [e for r in pick for e in r.get("drop_errors_ms") or []]
    out.update({k: v for k, v in _timing(errs).items() if k != "within_50ms"})
    return out
