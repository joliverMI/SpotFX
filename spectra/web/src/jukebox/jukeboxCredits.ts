/** THE JUKEBOX CREDITS TAB'S WORDS AND CHECKS — pure, no React, so
 * scripts/check_jukebox_editor.mjs drives them directly.
 *
 * Every setting's card, label, unit and RANGE arrive from the server
 * (`GET /api/jukebox/show`'s `fields`, read off models.jukebox.EconomyConfig's
 * own bounds); nothing here repeats a number. `checkValue` only spares a
 * round trip for an obviously bad entry — the server's validator is still
 * the one that decides. The price check is the server's (the real economy
 * on real examples); these functions only put it into sentences. */
import type { EconomyField, PresetInfo, PriceCheck } from './types';

export interface FieldCard {
  card: string;
  fields: EconomyField[];
}

/** The settings grouped as §4's cards, in the server's order. */
export function groupFields(fields: EconomyField[]): FieldCard[] {
  const out: FieldCard[] = [];
  for (const f of fields) {
    let c = out.find((x) => x.card === f.card);
    if (!c) {
      c = { card: f.card, fields: [] };
      out.push(c);
    }
    c.fields.push(f);
  }
  return out;
}

export type ValueCheck = { ok: true; value: number } | { ok: false; reason: string };

/** A typed value for a numeric setting: a number, whole for an int, and
 * inside the setting's own range. */
export function checkValue(f: EconomyField, raw: string): ValueCheck {
  const t = raw.trim();
  if (t === '' || !/^-?\d+(\.\d+)?$/.test(t)) return { ok: false, reason: `${f.label}: a number, please` };
  const v = Number(t);
  if (f.kind === 'int' && !Number.isInteger(v)) return { ok: false, reason: `${f.label}: a whole number, please` };
  if (f.min != null && v < f.min) return { ok: false, reason: `${f.label}: at least ${f.min}` };
  if (f.max != null && v > f.max) return { ok: false, reason: `${f.label}: at most ${f.max}` };
  return { ok: true, value: v };
}

export function rangeLine(f: EconomyField): string {
  if (f.kind === 'bool') return '';
  if (f.min == null && f.max == null) return '';
  return `${f.min ?? '…'}–${f.max ?? '…'}${f.unit ? ` ${f.unit}` : ''}`;
}

export function presetTitle(p: PresetInfo): string {
  return `${p.name[0].toUpperCase()}${p.name.slice(1)} · ${p.guests} guests`;
}

const min = (n: number) => `${n} min`;

export interface PriceRow {
  label: string;
  value: string;
}

/** The price check as he reads it: what each thing costs right now. */
export function priceRows(pc: PriceCheck): { title: string; rows: PriceRow[] }[] {
  return [
    {
      title: 'Free credits',
      rows: [
        { label: 'First visit', value: `${pc.start.now} now + ${pc.start.later} after ${min(pc.start.after_min)}` },
        { label: 'Top-up', value: pc.topup.every_min > 0
          ? `+1 every ${min(pc.topup.every_min)}, paused at ${pc.topup.pauses_at} held` : 'off' },
      ],
    },
    {
      title: 'Add a song (a typical 3:36 song)',
      rows: [
        ...pc.add.map((a) => ({ label: a.wait_min === 0 ? 'plays next' : `plays in ${min(a.wait_min)}`, value: `${a.price}` })),
        { label: 'a 6:30 song, playing next', value: `${pc.add_long.price}` },
        { label: 'not learned yet, playing next', value: `${pc.add_not_learned}` },
        { label: 'songs in line per guest', value: `${pc.songs_in_line}` },
      ],
    },
    {
      title: `Skip (a room of ${pc.guests})`,
      rows: pc.skip.map((s) => ({
        label: `${s.line_min === 0 ? 'nothing waiting' : `a ${min(s.line_min)} line`}, ${s.downs} net ▼`,
        value: `${s.price}`,
      })),
    },
    {
      title: 'Play next',
      rows: pc.play_next.map((n) => ({ label: `jumps ${min(n.jump_min)}`, value: `${n.price}` })),
    },
    {
      title: 'Bumps',
      rows: [
        ...pc.bump_up.map((b) => ({ label: `up, ${b.behind} behind it`, value: `${b.price}` })),
        ...pc.bump_down.map((b) => ({ label: `down, ${b.ahead} ahead of it`, value: `${b.price}` })),
      ],
    },
    {
      title: 'Jail and tips',
      rows: [
        { label: `jail at (a room of ${pc.guests})`, value: `${pc.jail.threshold} net ▼` },
        { label: 'break out', value: `${pc.jail.fee}` },
        { label: 'tips', value: pc.tips.on
          ? `up to ${pc.tips.max_per_song} a song; first ${pc.tips.double_first} given count double` : 'off' },
      ],
    },
  ];
}
