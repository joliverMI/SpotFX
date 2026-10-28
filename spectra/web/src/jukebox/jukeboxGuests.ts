/** The Guests tab's words and rules, pure (scripts/check_jukebox_editor.mjs
 * holds them): how a phone stands, which buttons a phone and a song get, and
 * who added each song. The decisions are the server's
 * (services/jukebox/guests.py); this only says them. */
import type { GuestPhone, LineEntry } from './types';

export function ordinal(n: number): string {
  const s = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
}

export type PhoneState = 'blocked' | 'waiting' | 'welcome' | 'jailed' | 'in';

export function phoneState(p: GuestPhone): PhoneState {
  if (p.blocked) return 'blocked';
  if (!p.approved) return 'waiting';
  if (p.jail_left) return 'jailed';
  return p.joined ? 'in' : 'welcome';
}

/** Credits mode's jail lasts until the guest breaks out (or you pardon). */
function jailWords(p: GuestPhone): string {
  return p.jail_kind === 'breakout' ? 'in jail (until they break out)'
    : `in a time-out (${songs(p.jail_left ?? 0)} to go)`;
}

export const PHONE_WORDS: Record<PhoneState, string> = {
  blocked: 'blocked for the night',
  waiting: 'waiting for your approval',
  welcome: 'on the welcome screen',
  jailed: 'in a time-out',
  in: 'in',
};

function songs(n: number): string {
  return `${n} song${n === 1 ? '' : 's'}`;
}

export function phoneLine(p: GuestPhone): string {
  const parts = [PHONE_WORDS[phoneState(p)]];
  if (p.jail_left) {
    parts[0] = jailWords(p);
  } else if (p.jail_count && p.jail_count > 0 && p.jail_at) {
    parts.push(`net ▼ ${p.jail_count} of ${p.jail_at}`);
  }
  if (p.credits !== undefined) parts.push(`🎟 ${p.credits}`);
  if (p.waiting) parts.push(`${p.waiting} in line`);
  if (p.played) parts.push(`${p.played} played`);
  if (p.votes) parts.push(`${p.votes} vote${p.votes === 1 ? '' : 's'}`);
  if (p.name_locked) parts.push('name locked');
  if (p.merged_from?.length) parts.push(`merged with ${p.merged_from.join(', ')}`);
  return parts.join(' · ');
}

const two = (n: number) => String(n).padStart(2, '0');

/** When a phone first opened the page tonight, in the house's time ("since
 *  21:42") — so a new phone late in the night stands out (report §12). */
export function sinceWords(ms: number): string {
  const d = new Date(ms);
  return `since ${two(d.getHours())}:${two(d.getMinutes())}`;
}

export type PhoneTake = 'zero' | 'merge';

/** The host's two bigger buttons (§4): Zero while it holds credits (credits
 *  mode), Merge while another phone could join it. Never on a blocked one. */
export function phoneTakes(p: GuestPhone, phones: GuestPhone[]): PhoneTake[] {
  if (p.blocked) return [];
  const out: PhoneTake[] = [];
  if ((p.credits ?? 0) > 0) out.push('zero');
  if (mergeCandidates(p, phones).length) out.push('merge');
  return out;
}

/** The phones that could join this one: any other, not blocked. */
export function mergeCandidates(keep: GuestPhone, phones: GuestPhone[]): GuestPhone[] {
  return phones.filter((q) => q.id !== keep.id && !q.blocked);
}

/** What a merge does, in words, before he confirms it. The guest keeps the
 *  name of whichever phone came first tonight (the server's rule). */
export function mergeWords(keep: GuestPhone, retire: GuestPhone): string {
  const first = retire.created_ms < keep.created_ms ? retire : keep;
  const bits = [retire.waiting || retire.played ? 'songs' : '', 'votes',
                retire.jail_left ? 'time-out' : '',
                retire.credits !== undefined ? `${retire.credits} credit${retire.credits === 1 ? '' : 's'}` : '']
    .filter(Boolean);
  return `${retire.name} becomes part of ${keep.name}: its ${bits.join(', ')} come here, both codes `
    + `work as one guest, and they're called ${first.name}.`;
}

/** §12's vote-farming flag, in words: who this phone always votes with. It
 *  is a flag, not a verdict — two friends tapping together look the same. */
export function lockstepWords(p: GuestPhone): string {
  const rows = p.lockstep ?? [];
  if (!rows.length) return '';
  const names = rows.map((r) => r.name);
  const who = names.length === 1 ? names[0]
    : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
  const most = Math.max(...rows.map((r) => r.songs));
  return `Votes with ${who} — the same way, within a second, on every song (${most} so far)`;
}

export type PhoneAction = 'approve' | 'pardon' | 'block' | 'unblock' | 'lock' | 'unlock' | 'rename';

/** The buttons a phone gets: Approve only while it waits; Pardon only in a
 * time-out; Block or Unblock; Lock or Unlock its name; Rename. */
export function phoneActions(p: GuestPhone): PhoneAction[] {
  const out: PhoneAction[] = [];
  if (!p.approved && !p.blocked) out.push('approve');
  if (p.jail_left) out.push('pardon');
  out.push(p.blocked ? 'unblock' : 'block');
  out.push(p.name_locked ? 'unlock' : 'lock');
  out.push('rename');
  return out;
}

/** Who added a song: "the host", a guest's name, or "a guest" when the
 * phone isn't known. */
export function adderName(e: LineEntry, phones: GuestPhone[]): string {
  if (e.added_by === 'host') return 'the host';
  return phones.find((p) => p.id === e.added_by)?.name ?? 'a guest';
}

/** The jukebox songs still to play, in line order, with what the host can
 * do to each: hold or let go of a waiting song; play it next (when the show
 * lets the host, or always in credits mode); keep it from every skip, or
 * let it be skipped again; remove any (a song already sent to Spotify is
 * skipped as it starts). A song whose adder is in a time-out says so, and
 * in credits mode each row carries what its adder paid for it. */
export function lineRows(line: LineEntry[], phones: GuestPhone[], playNext = false,
                         noSkip: string[] = []) {
  const jailed = new Set(phones.filter((p) => p.jail_left).map((p) => p.id));
  const waiting = line.filter((e) => e.state === 'queued');
  return line
    .filter((e) => e.state === 'queued' || e.state === 'committed')
    .map((e) => ({
      entry: e,
      by: adderName(e, phones),
      round: e.added_by === 'host' ? '' : `${ordinal(e.round ?? 1)} song`,
      sent: e.state === 'committed',
      held: !!e.held,
      jailed: e.state === 'queued' && jailed.has(e.added_by),
      canHold: e.state === 'queued',
      canPlayNext: playNext && e.state === 'queued' && waiting[0]?.id !== e.id,
      skipLocked: noSkip.includes(e.uri),
      paid: e.paid ?? 0,
      doomed: e.doomed,
    }));
}
