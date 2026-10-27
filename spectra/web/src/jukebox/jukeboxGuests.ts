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

export type PhoneState = 'blocked' | 'waiting' | 'welcome' | 'in';

export function phoneState(p: GuestPhone): PhoneState {
  if (p.blocked) return 'blocked';
  if (!p.approved) return 'waiting';
  return p.joined ? 'in' : 'welcome';
}

export const PHONE_WORDS: Record<PhoneState, string> = {
  blocked: 'blocked for the night',
  waiting: 'waiting for your approval',
  welcome: 'on the welcome screen',
  in: 'in',
};

export function phoneLine(p: GuestPhone): string {
  const parts = [PHONE_WORDS[phoneState(p)]];
  if (p.waiting) parts.push(`${p.waiting} in line`);
  if (p.played) parts.push(`${p.played} played`);
  if (p.votes) parts.push(`${p.votes} vote${p.votes === 1 ? '' : 's'}`);
  if (p.name_locked) parts.push('name locked');
  return parts.join(' · ');
}

/** The buttons a phone gets: Approve only while it waits; Block or Unblock;
 * Lock or Unlock its name; Rename. */
export function phoneActions(p: GuestPhone): ('approve' | 'block' | 'unblock' | 'lock' | 'unlock' | 'rename')[] {
  const out: ('approve' | 'block' | 'unblock' | 'lock' | 'unlock' | 'rename')[] = [];
  if (!p.approved && !p.blocked) out.push('approve');
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
 * do to each: hold or let go of a waiting song; remove any (a song already
 * sent to Spotify is skipped as it starts). */
export function lineRows(line: LineEntry[], phones: GuestPhone[]) {
  return line
    .filter((e) => e.state === 'queued' || e.state === 'committed')
    .map((e) => ({
      entry: e,
      by: adderName(e, phones),
      round: e.added_by === 'host' ? '' : `${ordinal(e.round ?? 1)} song`,
      sent: e.state === 'committed',
      held: !!e.held,
      canHold: e.state === 'queued',
      doomed: e.doomed,
    }));
}
