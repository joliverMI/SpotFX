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
  if (p.jail_left) parts[0] += ` (${songs(p.jail_left)} to go)`;
  else if (p.jail_count && p.jail_count > 0 && p.jail_at) parts.push(`net ▼ ${p.jail_count} of ${p.jail_at}`);
  if (p.waiting) parts.push(`${p.waiting} in line`);
  if (p.played) parts.push(`${p.played} played`);
  if (p.votes) parts.push(`${p.votes} vote${p.votes === 1 ? '' : 's'}`);
  if (p.name_locked) parts.push('name locked');
  return parts.join(' · ');
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
 * lets the host); remove any (a song already sent to Spotify is skipped as
 * it starts). A song whose adder is in a time-out says so. */
export function lineRows(line: LineEntry[], phones: GuestPhone[], playNext = false) {
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
      doomed: e.doomed,
    }));
}
