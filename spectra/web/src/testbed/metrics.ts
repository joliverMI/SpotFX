/** Byte-for-byte TypeScript port of spectra/services/testbed_metrics.py's
 * greedy nearest-neighbor matcher (data/spotfx-music-analysis-plan/
 * report.md, Part 1.2/1.4/4's own methodology). Kept deliberately
 * IDENTICAL to the Python side — see that module's docstring — so the
 * frontend can recompute instantly on every tolerance-slider drag without
 * round-tripping to the server, and never disagree with what the server
 * would have computed for the same inputs.
 *
 * scripts/check_testbed_metrics.mjs cross-checks both sides against the
 * same fixed vectors; touching the matching rule here means updating that
 * script's expected values too. */
import type { TestbedMatch, TestbedMetrics } from '../types';

export function matchMarks(
  referenceMs: number[], estimateMs: number[], toleranceMs: number,
): TestbedMetrics {
  const nRef = referenceMs.length;
  const nEst = estimateMs.length;

  const candidates: [number, number, number][] = []; // [distance, refIdx, estIdx]
  for (let i = 0; i < nRef; i++) {
    for (let j = 0; j < nEst; j++) {
      const d = Math.abs(referenceMs[i] - estimateMs[j]);
      if (d <= toleranceMs) candidates.push([d, i, j]);
    }
  }
  candidates.sort((a, b) => a[0] - b[0]);

  const matchedRef = new Set<number>();
  const matchedEst = new Set<number>();
  const matches: TestbedMatch[] = [];
  for (const [d, i, j] of candidates) {
    if (matchedRef.has(i) || matchedEst.has(j)) continue;
    matchedRef.add(i);
    matchedEst.add(j);
    matches.push({ ref_index: i, est_index: j, abs_offset_ms: d });
  }

  const nMatched = matches.length;
  const precision = nEst ? nMatched / nEst : 0;
  const recall = nRef ? nMatched / nRef : 0;
  const f1 = (precision + recall) ? (2 * precision * recall) / (precision + recall) : 0;
  const meanAbsOffsetMs = nMatched
    ? matches.reduce((sum, m) => sum + m.abs_offset_ms, 0) / nMatched
    : 0;

  return {
    precision, recall, f1,
    n_reference: nRef, n_estimate: nEst, n_matched: nMatched,
    mean_abs_offset_ms: meanAbsOffsetMs,
    matches,
  };
}
