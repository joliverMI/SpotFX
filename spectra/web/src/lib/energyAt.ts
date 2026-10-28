/** ENERGY at a song-time moment, read off the server's own timeline
 * (GET /api/energy/timeline, spectra/services/energy.py). Pure lookup — no
 * math on the client, so every screen shows the number the engine acts on:
 * the section holding `ms`; before the first -> the first, after the last ->
 * the last; in a gap between two -> the nearer one (energy.Timeline.at's own
 * rule). No look-ahead: the screen shows where the song is now. */
import type { EnergySection } from '../types';

export function energyAt(sections: readonly EnergySection[] | null | undefined,
                         ms: number | null | undefined): number | null {
  if (!sections || sections.length === 0 || ms == null || !Number.isFinite(ms)) return null;
  let lo = 0;
  let hi = sections.length - 1;
  if (ms < sections[0].start_ms) return sections[0].energy;
  while (lo < hi) {                       // the last section starting at or before ms
    const mid = (lo + hi + 1) >> 1;
    if (sections[mid].start_ms <= ms) lo = mid; else hi = mid - 1;
  }
  const sec = sections[lo];
  if (ms < sec.end_ms || lo === sections.length - 1) return sec.energy;
  const next = sections[lo + 1];
  return ms - sec.end_ms <= next.start_ms - ms ? sec.energy : next.energy;
}

/** A drawn bar's height, 0..1 of the bar: Energy clamped (0 is empty, 1 or
 * more fills it to the top). */
export function energyFill(v: number | null | undefined): number {
  if (v == null || !Number.isFinite(v)) return 0;
  return Math.max(0, Math.min(1, v));
}
