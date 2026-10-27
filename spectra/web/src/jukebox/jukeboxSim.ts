/** THE PARTY SIMULATOR'S PLAYBACK — pure, no React, so
 * scripts/check_jukebox_editor.mjs drives it directly.
 *
 * The night itself is the server's (services/jukebox/simulator.py, one model
 * night recorded as it happened: frames of every guest's credits, the line
 * and the price at the back of it; the songs; the events). Everything here
 * only answers "what was true at minute t" and puts it into words; nothing
 * is simulated or re-derived. */
import type { SimCheck, SimEvent, SimFrame, SimGuest, SimNight, SimResult, SimRow, SimSong, SimUnit } from './types';

/** How long the whole night takes to play back, in real seconds. */
export const PLAY_SECONDS = [60, 120, 300] as const;
export const DEFAULT_PLAY_SECONDS = 300;
export const SIM_GUESTS = [4, 8, 12, 15, 20, 25, 30] as const;
export const DEFAULT_SIM_GUESTS = 20;

export function playLabel(seconds: number): string {
  return seconds < 120 ? `${seconds} s` : `${seconds / 60} min`;
}

/** Party minutes as "1:23" (hours:minutes into the party). */
export function clock(min: number): string {
  const m = Math.max(0, Math.floor(min));
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}`;
}

/** The last frame at or before `t` (the first frame before the night starts). */
export function frameAt(frames: SimFrame[], t: number): SimFrame | null {
  if (!frames.length) return null;
  let lo = 0;
  let hi = frames.length - 1;
  if (frames[0].t > t) return frames[0];
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (frames[mid].t <= t) lo = mid;
    else hi = mid - 1;
  }
  return frames[lo];
}

export function guestName(id: number | null | undefined): string {
  return id == null ? 'the host' : `Guest ${id + 1}`;
}

function songOf(of: number | null | undefined): string {
  return of == null ? 'a set song' : `${guestName(of)}'s song`;
}

const n = (x: number | undefined, unit = 'credits') => `${x ?? 0} ${x === 1 ? unit.replace(/s$/, '') : unit}`;

export function eventLine(e: SimEvent): string {
  const who = guestName(e.g);
  switch (e.kind) {
    case 'add': {
      const which = (e.rnd ?? 1) > 1 ? 'a 2nd song' : 'a song';
      const when = (e.wait ?? 0) < 1 ? 'plays next' : `plays in about ${Math.round(e.wait ?? 0)} min`;
      return `${who} added ${which} for ${n(e.price)} (${when})`;
    }
    case 'skip':
      return (e.payers?.length ?? 0) > 1
        ? `${e.payers!.length} guests chipped in ${n(e.price)} to skip ${songOf(e.of)}`
        : `${guestName(e.payers?.[0])} skipped ${songOf(e.of)} for ${n(e.price)}`;
    case 'jail':
      return `${who} went to jail (${e.downs} net ▼)`;
    case 'jail_out':
      return `${who} broke out of jail for ${n(e.fee)}`;
    case 'tip':
      return `${who} tipped ${guestName(e.to)} ${n(e.amt)}${e.bonus ? ` (+${e.bonus} bonus)` : ''}`;
    case 'next':
      return `${who} bought play next for ${n(e.price)}`;
    case 'bump_up':
      return `${who} bumped their song up for ${n(e.price)}`;
    case 'bump_down':
      return `${who} pushed ${songOf(e.of)} back for ${n(e.price)}`;
    case 'too_late':
      return `${who} was told a new song would play after last call`;
    case 'refund':
      return `${who} got ${n(e.amt)} back for a song that never played`;
  }
}

/** The newest `count` events at or before `t`, newest first. */
export function eventsUpTo(events: SimEvent[], t: number, count = 8): SimEvent[] {
  const out: SimEvent[] = [];
  for (let i = events.length - 1; i >= 0 && out.length < count; i--) {
    if (events[i].t <= t) out.push(events[i]);
  }
  return out;
}

export function here(g: SimGuest, t: number): boolean {
  return g.arrive <= t && t < g.leave;
}

export interface NowView {
  song: SimSong | null;
  songLine: string;
  present: number;
  line: number;
  back: number;
  price: number;
  jailed: number;
  heldPerGuest: number | null;
}

/** What is true at minute `t`: the song, who is here, the line. */
export function nowView(night: SimNight, t: number): NowView {
  const f = frameAt(night.frames, t);
  const song = f && f.song >= 0 ? night.songs[f.song] ?? null : null;
  const present = night.guests.filter((g) => here(g, t));
  const held = f && present.length ? present.reduce((a, g) => a + (f.cr[g.id] ?? 0), 0) / present.length : null;
  let songLine = 'Nothing playing yet';
  if (t >= night.minutes) songLine = 'The party is over';
  else if (song) {
    const votes = song.ups != null ? ` · ${song.ups} ▲ ${song.downs ?? 0} ▼` : '';
    songLine = `${song.by == null ? 'A set song' : `${guestName(song.by)}'s song`}${votes}${song.skipped != null && song.skipped <= t ? ' · skipped' : ''}`;
  }
  return {
    song, songLine, present: present.length, line: f?.line ?? 0, back: f?.back ?? 0,
    price: f?.price ?? 0, jailed: f?.jailed.length ?? 0, heldPerGuest: held,
  };
}

/** Songs a guest has had played by minute `t`. */
export function playedBy(night: SimNight, id: number, t: number): number {
  return night.songs.filter((s) => s.by === id && s.t <= t).length;
}

export function fmtValue(unit: SimUnit, v: number | null): string {
  if (v == null) return '–';
  switch (unit) {
    case 'share':
      return `${Math.round(v * 100)}%`;
    case 'min':
      return `${Math.round(v)} min`;
    case 'credits':
      return v.toFixed(1);
    case 'rate':
      return v < 1 ? v.toFixed(2) : v.toFixed(1);
    case 'count':
      return Number.isInteger(v) ? String(v) : v.toFixed(1);
  }
}

/** The comparison table as he reads it: one column when his settings ARE
 * the tuned ones, two otherwise, with a row marked when it moved. */
export function rowCells(r: SimRow, same: boolean): { label: string; yours: string; tuned: string | null; moved: boolean } {
  const yours = fmtValue(r.unit, r.yours);
  if (same) return { label: r.label, yours, tuned: null, moved: false };
  const tuned = fmtValue(r.unit, r.tuned);
  return { label: r.label, yours, tuned, moved: yours !== tuned };
}

export function checkLine(c: SimCheck): { mark: 'ok' | 'bad' | 'none'; text: string } {
  const v = c.value == null ? 'nobody to measure' : fmtValue(c.key === 'got_played' ? 'share'
    : c.key === 'skips_hr' ? 'rate' : c.key === 'songs_per_lurk' ? 'count' : 'min', c.value);
  return { mark: c.ok == null ? 'none' : c.ok ? 'ok' : 'bad', text: `${c.label} — ${v} (wanted ${c.target})` };
}

const PRESET_WORDS: Record<string, string> = {
  small: 'Small (every other)', medium: 'Medium (2 jukebox songs per set song)', large: 'Large (jukebox first)',
};

/** When a promise fails AND the night did not run the plan's mix for the
 * size, the hint names the preset that fits. */
export function presetHint(r: SimResult): string | null {
  if (r.mix_is_plans || !r.checks.some((c) => c.ok === false)) return null;
  return `The plan's preset for ${r.guests} guests is ${PRESET_WORDS[r.plan_preset] ?? r.plan_preset} — try "The preset for this size".`;
}

export function resultLine(r: SimResult): string {
  return `${r.guests} guests, four hours, ${r.program}. The night you watch is the first of the ${r.nights} averaged below.`;
}

// ── the chart: the add price at the back of the line and the credits held
// per guest over the night — one unit (credits), one axis ────────────────

export interface ChartPoint { t: number; price: number; held: number | null }

export function chartPoints(night: SimNight): ChartPoint[] {
  return night.frames.map((f) => {
    const present = night.guests.filter((g) => here(g, f.t));
    const held = present.length ? present.reduce((a, g) => a + (f.cr[g.id] ?? 0), 0) / present.length : null;
    return { t: f.t, price: f.price, held };
  });
}

export interface ChartGeometry {
  pricePath: string;
  heldPath: string;
  /** Where each line's direct label sits: at its last point, pulled apart
   * when the two would overlap. */
  labels: { key: 'price' | 'held'; x: number; y: number; text: string }[];
  yMax: number;
  ticks: number[];
  x: (t: number) => number;
  y: (v: number) => number;
  /** The party minute at a chart x (the hover and the click). */
  tAt: (x: number) => number;
}

function niceMax(v: number): number {
  for (const step of [5, 10, 20, 25, 50, 100]) {
    if (v <= step * 4) return Math.ceil(v / step) * step;
  }
  return Math.ceil(v / 100) * 100;
}

export function chartGeometry(points: ChartPoint[], minutes: number, w: number, h: number,
  pad = { l: 30, r: 8, t: 8, b: 18 }): ChartGeometry {
  const top = Math.max(1, ...points.map((p) => Math.max(p.price, p.held ?? 0)));
  const yMax = niceMax(top);
  const plotW = w - pad.l - pad.r;
  const x = (t: number) => pad.l + (Math.min(Math.max(t, 0), minutes) / minutes) * plotW;
  const tAt = (px: number) => Math.max(0, Math.min(minutes, ((px - pad.l) / plotW) * minutes));
  const y = (v: number) => pad.t + (1 - v / yMax) * (h - pad.t - pad.b);
  const path = (key: 'price' | 'held') => {
    let d = '';
    let pen = false;
    for (const p of points) {
      const v = p[key];
      if (v == null) { pen = false; continue; }
      d += `${pen ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    }
    return d;
  };
  const step = yMax / 4;
  const last = (key: 'price' | 'held') => {
    for (let i = points.length - 1; i >= 0; i--) {
      const v = points[i][key];
      if (v != null) return y(v);
    }
    return null;
  };
  const lp = last('price');
  const lh = last('held');
  const labels: ChartGeometry['labels'] = [];
  const lx = w - pad.r - 2;
  if (lp != null && lh != null && Math.abs(lp - lh) < 16) {
    const mid = (lp + lh) / 2;
    const up = lp <= lh;
    labels.push({ key: 'price', x: lx, y: mid + (up ? -8 : 8) - 3, text: 'add price' });
    labels.push({ key: 'held', x: lx, y: mid + (up ? 8 : -8) - 3, text: 'held' });
  } else {
    if (lp != null) labels.push({ key: 'price', x: lx, y: lp - 5, text: 'add price' });
    if (lh != null) labels.push({ key: 'held', x: lx, y: lh - 5, text: 'held' });
  }
  for (const l of labels) l.y = Math.max(pad.t + 8, Math.min(h - pad.b - 2, l.y));
  return { pricePath: path('price'), heldPath: path('held'), labels, yMax, ticks: [0, step, 2 * step, 3 * step, yMax], x, y, tAt };
}

/** The point nearest minute `t` (the chart's hover). */
export function pointAt(points: ChartPoint[], t: number): ChartPoint | null {
  let best: ChartPoint | null = null;
  for (const p of points) {
    if (p.t <= t) best = p;
    else break;
  }
  return best ?? points[0] ?? null;
}
