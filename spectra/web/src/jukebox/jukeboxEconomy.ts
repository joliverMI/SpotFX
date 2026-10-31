/** THE LIVE TAB'S ECONOMY PANEL, IN WORDS — pure, so
 * scripts/check_jukebox_editor.mjs drives it directly. Every number is the
 * server's (SpotFX services/jukebox/economy_live.py, the report's own
 * vocabulary); this only says them: the credits right now, the prices a guest
 * sees now, the night's recent events, and the line with who added each song,
 * what it paid, and whether it is held or sitting out a time-out. */
import { lineBadge } from './jukeboxLearning';
import { entryLine } from './jukeboxEditor';
import { adderName, ordinal } from './jukeboxGuests';
import type { EconomyCredits, EconomyEvent, EconomyPrices, GuestPhone, JukeboxEconomy, LineEntry } from './types';

const two = (n: number) => String(n).padStart(2, '0');
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** A moment in the house's time: "21:42". */
export function clock(ms: number): string {
  const d = new Date(ms);
  return `${two(d.getHours())}:${two(d.getMinutes())}`;
}

/** Signed credits: "+2", "−6", "" for none. */
export function signed(n: number): string {
  if (!n) return '';
  return n > 0 ? `+${n}` : `−${-n}`;
}

/** Who is here: "6 phones here in the last 15 min · 5 joined · 1 in a time-out". */
export function roomLine(e: JukeboxEconomy): string {
  const parts = [`${plural(e.crowd ?? 0, 'phone')} here in the last 15 min`, `${e.joined ?? 0} joined`];
  if (e.jailed) parts.push(`${e.jailed} in a time-out`);
  return parts.join(' · ');
}

/** Free play has no credits: what the room has done instead. */
export function freePlayLine(e: JukeboxEconomy): string {
  return `Free play: nothing costs anything — ${plural(e.votes ?? 0, 'vote')} and `
    + `${plural(e.time_outs ?? 0, 'time-out')} so far tonight.`;
}

/** The credits right now: held, per guest, made, still unspent. */
export function creditsLine(c: EconomyCredits): string {
  const parts = [`${plural(c.held, 'credit')} held`];
  if (c.held_per_guest != null) parts.push(`${c.held_per_guest} a guest`);
  parts.push(`${c.minted} made tonight`);
  if (c.unspent_share != null) parts.push(`${Math.round(c.unspent_share * 100)}% still unspent`);
  return parts.join(' · ');
}

const rate = (r: number | null, what: string) => (r == null ? '' : `${what} ${r}/h`);

/** What the night has done with them: adds, the hourly rates, votes paid. */
export function activityLine(c: EconomyCredits): string {
  return [plural(c.adds, 'song') + ' added', rate(c.skips_hr, 'skips'), rate(c.nexts_hr, 'play next'),
    rate(c.tips_hr, 'tips'), `${plural(c.votes, 'vote')} paid`, `${c.free} free credits handed out`]
    .filter(Boolean).join(' · ');
}

export interface PriceRow { label: string; value: string }

/** The prices a guest sees right now. */
export function priceRows(p: EconomyPrices): PriceRow[] {
  return [
    { label: 'A 1st song, now', value: String(p.add_first) },
    { label: p.back_wait_min != null ? `At the back of the line (~${Math.round(p.back_wait_min)} min)`
      : 'At the back of the line', value: String(p.add_back) },
    { label: 'Skip the song playing', value: p.skip_now == null ? 'nothing playing' : String(p.skip_now) },
    { label: 'Play next', value: `from ${p.next_from}` },
    { label: 'Break out of jail', value: String(p.jail_fee) },
  ];
}

/** One recent event: "21:42 · Disco Ana added “Dopamine”" and its credits. */
export function eventWords(ev: EconomyEvent): { when: string; text: string; credits: string } {
  return { when: clock(ev.at_ms), text: `${ev.who} ${ev.what}`, credits: signed(ev.credits) };
}

/** The Live tab's line: who added each song (by name, never a phone's
 *  code), its place in fair order, what it paid, held or sitting out. */
export function liveLineWords(e: LineEntry, phones: GuestPhone[]): string {
  const guest = e.added_by !== 'host';
  const parts: string[] = [];
  if (e.state === 'queued') {
    parts.push(`waiting · added by ${adderName(e, phones)}`);
    if (guest) parts.push(`${ordinal(e.round ?? 1)} song`);
    if (e.held) parts.push('on hold');
    if (guest && phones.some((p) => p.id === e.added_by && p.jail_left)) parts.push('sits out a time-out');
  } else {
    parts.push(entryLine(e));
    parts.push(`added by ${adderName(e, phones)}`);
  }
  if (e.paid) parts.push(`paid 🎟 ${e.paid}`);
  const learning = lineBadge(e);
  if (learning) parts.push(learning);
  return parts.join(' · ');
}
