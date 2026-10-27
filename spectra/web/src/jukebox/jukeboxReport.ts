/** THE POST-PARTY REPORT'S WORDS — pure, no React, so
 * scripts/check_jukebox_editor.mjs drives them directly. The numbers are
 * the server's (services/jukebox/night_report.py); a measure the night
 * could not take shows "–" with the server's own reason, never a 0. */
import { fmtValue } from './jukeboxSim';
import type { ReportCredits, ReportNight, ReportRow } from './types';

export interface Fact { label: string; value: string }

const pct = (v: number | null) => (v == null ? '–' : `${Math.round(v * 100)}%`);
const num = (v: number | null, unit = '') => (v == null ? '–' : `${v}${unit}`);

export function nightFacts(n: ReportNight): Fact[] {
  return [
    { label: 'Length', value: n.hours == null ? '–' : `${n.hours} h` },
    { label: 'Set songs played', value: String(n.played.set) },
    { label: 'Jukebox songs played', value: String(n.played.jukebox) },
    { label: 'Skipped', value: String(n.played.skipped) },
    { label: 'Jukebox share', value: pct(n.jukebox_share) },
    { label: 'Songs an hour', value: num(n.songs_per_hour) },
    { label: 'Songs added to the line', value: `${n.line.added} (${n.line.by_guests} by guests)` },
    { label: 'Removed / still waiting', value: `${n.line.removed} / ${n.line.waiting_at_end}` },
    { label: 'Add to play (median)', value: n.add_to_play_median_min == null ? '–' : `${Math.round(n.add_to_play_median_min)} min` },
  ];
}

export function creditFacts(c: ReportCredits): Fact[] {
  return [
    { label: 'Guests who used credits', value: String(c.phones) },
    { label: 'Credits made', value: String(c.minted) },
    { label: 'Held at the end', value: `${c.held_at_end} (${pct(c.unspent_share)})` },
    { label: 'Songs bought', value: String(c.adds) },
  ];
}

/** One comparison row: this night beside the model's nights. */
export function compareCells(r: ReportRow): { label: string; night: string; model: string; why: string | null } {
  return { label: r.label, night: fmtValue(r.unit, r.this_night), model: fmtValue(r.unit, r.yours ?? null),
    why: r.this_night == null ? r.why : null };
}

export function endLine(n: ReportNight): string {
  if (n.state === 'running') return 'Still running — the report so far.';
  return n.end_detail ? `Ended: ${n.end_detail}` : 'Ended.';
}
