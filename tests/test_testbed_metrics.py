"""spectra/services/testbed_metrics.py — the report's own greedy
nearest-neighbor P/R/F1 methodology (Part 1.2/1.4/4), made executable.
Cross-checked against spectra/web/src/testbed/metrics.ts by
scripts/check_testbed_metrics.mjs (same fixed vectors)."""
from __future__ import annotations

from spectra.services.testbed_metrics import match_marks


def test_perfect_match_gives_f1_1():
    r = match_marks([1000, 2000, 3000], [1000, 2000, 3000], tolerance_ms=100)
    assert r.precision == 1.0
    assert r.recall == 1.0
    assert r.f1 == 1.0
    assert r.n_matched == 3
    assert r.mean_abs_offset_ms == 0.0


def test_no_overlap_gives_zero_everything():
    r = match_marks([1000, 2000], [50000, 60000], tolerance_ms=500)
    assert r.precision == 0.0
    assert r.recall == 0.0
    assert r.f1 == 0.0
    assert r.n_matched == 0


def test_empty_reference_or_estimate_never_divides_by_zero():
    r = match_marks([], [1000], tolerance_ms=500)
    assert r.recall == 0.0  # 0/0 -> 0, not NaN
    assert r.precision == 0.0

    r2 = match_marks([1000], [], tolerance_ms=500)
    assert r2.precision == 0.0
    assert r2.recall == 0.0

    r3 = match_marks([], [], tolerance_ms=500)
    assert r3.precision == 0.0 and r3.recall == 0.0 and r3.f1 == 0.0


def test_over_segmentation_hurts_precision_not_recall():
    # 1 real mark, 4 detected marks nearby -> recall high, precision low.
    r = match_marks([1000], [900, 950, 1050, 1100], tolerance_ms=200)
    assert r.recall == 1.0
    assert r.precision == 0.25
    assert r.n_matched == 1


def test_greedy_matching_prefers_closest_pair_not_first_seen():
    # ref[0]=1000 is within tolerance of BOTH est[0]=900 (d=100) and
    # est[1]=1010 (d=10); 2000 is out of range of both. The closest overall
    # pair (1000<->1010, d=10) must be accepted, leaving est[0]=900
    # unmatched (nothing else is close enough to it) rather than the
    # looser (1000<->900) pair winning by being seen "first."
    r = match_marks([1000, 2000], [900, 1010], tolerance_ms=150)
    assert r.n_matched == 1
    assert r.matches == [(0, 1, 10.0)]  # ref index 0 matched to est index 1


def test_mean_abs_offset_only_averages_matched_pairs():
    r = match_marks([1000, 2000], [1050], tolerance_ms=200)
    assert r.n_matched == 1
    assert r.mean_abs_offset_ms == 50.0


def test_match_result_dict_shape():
    from spectra.services.testbed_metrics import match_result_dict
    r = match_marks([1000], [1010], tolerance_ms=100)
    d = match_result_dict(r)
    assert d["n_matched"] == 1
    assert d["matches"] == [{"ref_index": 0, "est_index": 0, "abs_offset_ms": 10}]
