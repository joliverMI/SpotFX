/** BURN-IN SAFETY (data/tv-display-plan/plan.html PR 1.5, §2.4): "the
 * whole layout drifts up to +-16 px over 8 minutes; the QR swaps corners
 * every 10 minutes... nothing static for hours." Pure functions of
 * elapsed time, so scripts/check_tv_burnin.mjs can prove "no element
 * static for > 10 min" over simulated time without a browser.
 *
 * The drift period (8 min) is deliberately SHORTER than the acceptance
 * window (10 min): a continuous, non-constant function with a period
 * under the sampling window cannot hold one value across the whole
 * window — it has already cycled through its full range and started
 * again before 10 minutes are up. The Attract screen's own card rotation
 * (every 15s) and the QR's own corner swap (every 10 min) are each
 * independently non-static over any 10-minute stretch too, so "no
 * element" holds for every visible thing on this screen, not just the
 * layout's own position. */
export const DRIFT_PERIOD_MS = 8 * 60 * 1000;
export const DRIFT_AMPLITUDE_PX = 16;
export const QR_SWAP_PERIOD_MS = 10 * 60 * 1000;

function triangleWave(t: number, period: number): number {
  // A 0..1..0 triangle wave with period `period`, defined for any real t
  // (including negative, via the double-modulo).
  const phase = (((t % period) + period) % period) / period; // 0..1
  return phase < 0.5 ? phase * 2 : (1 - phase) * 2; // 0..1..0
}

/** A slow (dx, dy) drift, in pixels, for anything that must never hold
 * one position for the whole 10-minute burn-in window. The y-phase is
 * offset by a third of the period so x and y don't peak together (a
 * diagonal-only drift would still be "one position" along the other
 * axis at the same instant). */
export function driftOffsetPx(elapsedMs: number): { dx: number; dy: number } {
  const dx = (triangleWave(elapsedMs, DRIFT_PERIOD_MS) - 0.5) * 2 * DRIFT_AMPLITUDE_PX;
  const dy = (triangleWave(elapsedMs + DRIFT_PERIOD_MS / 3, DRIFT_PERIOD_MS) - 0.5)
             * 2 * DRIFT_AMPLITUDE_PX;
  return { dx, dy };
}

export type Corner = 'tl' | 'tr' | 'bl' | 'br';
const CORNERS: readonly Corner[] = ['tl', 'tr', 'br', 'bl'];

export function qrCorner(elapsedMs: number): Corner {
  const i = Math.floor(Math.max(0, elapsedMs) / QR_SWAP_PERIOD_MS) % CORNERS.length;
  return CORNERS[i];
}

/** The Attract screen's slow deck (plan §2.2: "a slow deck — join, top
 * songs, now playing"). 15s per card is the plan's own cadence target
 * ("every few minutes" for the QR corner implies the deck itself moves
 * much faster) and, at 3 cards, completes 40 full rotations within any
 * 10-minute window — comfortably non-static. */
export const ATTRACT_CARDS = ['join', 'top', 'now'] as const;
export type AttractCard = typeof ATTRACT_CARDS[number];
export const ATTRACT_CARD_MS = 15_000;

export function attractCard(elapsedMs: number): AttractCard {
  const i = Math.floor(Math.max(0, elapsedMs) / ATTRACT_CARD_MS) % ATTRACT_CARDS.length;
  return ATTRACT_CARDS[i];
}
