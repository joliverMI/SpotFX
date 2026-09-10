"""Precision/recall/F1 for the music-analysis test bed
(data/spotfx-music-analysis-plan/report.md, Part 1.2/1.4/4 — this module IS
that report's own methodology, made executable and reusable rather than
re-derived) — a greedy nearest-neighbor match between his real marks (the
reference) and one candidate engine's detected marks (the estimate), at a
configurable tolerance window.

Algorithm (the MIREX-standard shape mir_eval.util.match_events uses, and
what the report's own scratch scripts implemented): every (reference,
estimate) pair within tolerance_ms is a match candidate; candidates are
sorted by absolute time distance ascending and accepted greedily, each mark
usable at most once. This is deliberately NOT "nearest available in time
order" — sorting by distance first means a close pair elsewhere in the song
can't be starved by an earlier, worse pair being accepted first.

spectra/web/src/testbed/metrics.ts is a byte-for-byte TypeScript port of
this exact algorithm (the report's own Part 2.6 recommendation: one battle-
tested implementation, not two that can silently drift) — the frontend
recomputes locally so an interactive tolerance slider doesn't round-trip to
the server on every drag. scripts/check_testbed_metrics.mjs cross-checks
both sides against the same fixed vectors; touching the matching rule here
means updating that script's expected values too.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MatchResult:
    precision: float
    recall: float
    f1: float
    n_reference: int
    n_estimate: int
    n_matched: int
    mean_abs_offset_ms: float
    # (reference_index, estimate_index, abs_offset_ms) for every accepted
    # pair — the diff/agreement view's tinting reads this directly rather
    # than re-deriving which of his marks matched.
    matches: list[tuple[int, int, float]]


def match_marks(reference_ms: list[float], estimate_ms: list[float],
                tolerance_ms: float) -> MatchResult:
    """reference_ms = his real marks (sorted or not); estimate_ms = one
    engine's detected marks. tolerance_ms must be > 0."""
    n_ref = len(reference_ms)
    n_est = len(estimate_ms)

    candidates: list[tuple[float, int, int]] = []  # (distance, ref_i, est_j)
    for i, r in enumerate(reference_ms):
        for j, e in enumerate(estimate_ms):
            d = abs(r - e)
            if d <= tolerance_ms:
                candidates.append((d, i, j))
    candidates.sort(key=lambda c: c[0])

    matched_ref: set[int] = set()
    matched_est: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for d, i, j in candidates:
        if i in matched_ref or j in matched_est:
            continue
        matched_ref.add(i)
        matched_est.add(j)
        matches.append((i, j, d))

    n_matched = len(matches)
    precision = (n_matched / n_est) if n_est else 0.0
    recall = (n_matched / n_ref) if n_ref else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    mean_abs_offset_ms = (sum(d for _, _, d in matches) / n_matched) if n_matched else 0.0

    return MatchResult(
        precision=precision, recall=recall, f1=f1,
        n_reference=n_ref, n_estimate=n_est, n_matched=n_matched,
        mean_abs_offset_ms=mean_abs_offset_ms, matches=matches,
    )


def match_result_dict(result: MatchResult) -> dict:
    return {
        "precision": result.precision,
        "recall": result.recall,
        "f1": result.f1,
        "n_reference": result.n_reference,
        "n_estimate": result.n_estimate,
        "n_matched": result.n_matched,
        "mean_abs_offset_ms": result.mean_abs_offset_ms,
        "matches": [{"ref_index": i, "est_index": j, "abs_offset_ms": d}
                    for i, j, d in result.matches],
    }
