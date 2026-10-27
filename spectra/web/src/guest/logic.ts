// The guest page's rules, pure (scripts/check_jukebox_guest_logic.mjs holds
// them): the "your song" strip's words, when the "you're next" banner shows
// and whether the phone buzzes, which phones get the Add to Home Screen hint,
// the tabs, and how times read. Times count from when THIS phone received the
// view (never the server's clock against the phone's — the two can disagree).
import type { By, Features, Strip, StripTone } from './types';

export function mmss(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** "in 12 min", "in 1:12" under ten minutes' worth of a song, "now". */
export function inWords(ms: number): string {
  if (ms <= 1000) return 'now';
  if (ms < 10 * 60_000) return `in ${mmss(ms)}`;
  return `in ${Math.round(ms / 60_000)} min`;
}

/** The phone's own clock time `inMs` from now: "9:46". */
export function clockAt(nowMs: number, inMs: number, locale?: string): string {
  return new Date(nowMs + inMs).toLocaleTimeString(locale, { hour: 'numeric', minute: '2-digit' })
    .replace(/\s?[AP]M$/i, '');
}

/** How long ago this phone received a view, so countdowns keep moving
 *  between polls. */
export function since(receivedAt: number, nowMs: number): number {
  return Math.max(0, nowMs - receivedAt);
}

export function progressNow(progressMs: number, durationMs: number, playing: boolean,
                            elapsedMs: number): number {
  const p = progressMs + (playing ? elapsedMs : 0);
  return durationMs > 0 ? Math.min(durationMs, Math.max(0, p)) : Math.max(0, p);
}

export interface StripText { tone: StripTone; label: string; detail: string }

/** The status strip under the header: what your songs are doing. */
export function stripText(strip: Strip, elapsedMs: number, nowMs: number,
                          canAdd: boolean, locale?: string): StripText {
  const left = strip.starts_in_ms === null ? null : Math.max(0, strip.starts_in_ms - elapsedMs);
  switch (strip.tone) {
    case 'playing':
      return { tone: 'playing', label: 'Your song is playing', detail: strip.title };
    case 'next':
      return { tone: 'next', label: 'Your song is next',
               detail: left === null ? strip.title : `${strip.title} · ${inWords(left)}` };
    case 'queued':
      return { tone: 'queued', label: `Your song #${strip.place ?? '—'}`,
               detail: left === null ? strip.title
                 : `plays ~${clockAt(nowMs, left, locale)} (${inWords(left)})` };
    default:
      return { tone: 'none', label: 'No songs of yours in line',
               detail: canAdd ? 'Tap ＋ to add one' : 'Vote on every song with ▲ and ▼' };
  }
}

export type BannerKind = 'next' | 'playing';

/** The "you're next" banner shows when the strip TURNS next or playing —
 *  once per change, never on every poll. */
export function bannerFor(prev: StripTone | null, tone: StripTone): BannerKind | null {
  if (prev === null || prev === tone) return null;
  return tone === 'next' || tone === 'playing' ? tone : null;
}

/** Android phones buzz with the banner (the Vibration API); iPhones have no
 *  Vibration API in a web page, so they never do. Browsers only allow it
 *  after the guest has tapped the page once. */
export function vibration(kind: BannerKind | null, canVibrate: boolean,
                          hasTapped: boolean): number[] | null {
  if (!kind || !canVibrate || !hasTapped) return null;
  return kind === 'next' ? [180, 90, 180] : [300, 120, 300, 120, 300];
}

/** iPhones and iPads not already opened from the Home Screen: the phones
 *  that get the Add to Home Screen hint (every iOS browser can add one since
 *  iOS 16.4). iPadOS reports a Mac, so a touch screen tells the two apart. */
export function wantsHomeScreenHint(ua: string, maxTouchPoints: number,
                                    standalone: boolean): boolean {
  if (standalone) return false;
  return /iPhone|iPod|iPad/.test(ua) || (/Macintosh/.test(ua) && maxTouchPoints > 1);
}

export type Tab = 'now' | 'queue' | 'add' | 'board';

/** The bottom bar: only what tonight's page can do (free play has no Shop;
 *  Add and Board arrive when SpotFX says they are open). */
export function tabsFor(f: Features): Tab[] {
  return ['now', 'queue', ...(f.add ? ['add' as Tab] : []), ...(f.board ? ['board' as Tab] : [])];
}

export function byLine(by: By, mine: boolean): string {
  if (mine) return 'Added by you';
  if (by.kind === 'set') return "Host's set";
  if (by.kind === 'host') return 'Added by the host';
  if (by.kind === 'guest') return `Added by ${by.name}`;
  return '';
}

/** The address to keep while the Add to Home Screen sheet is open: iPhone
 *  saves the page's address, and a Home Screen web app has storage of its
 *  own — so the phone's code rides in the address, and opening the icon
 *  brings the same name back. */
export function homeScreenAddress(phone: string, token: string | null): string {
  const q = new URLSearchParams();
  q.set('p', phone);
  if (token) q.set('t', token);
  return `/?${q.toString()}`;
}

/** What the page's own address carries: tonight's token and, from a Home
 *  Screen icon, the phone's code. */
export function fromAddress(search: string): { token: string | null; phone: string | null } {
  const q = new URLSearchParams(search);
  const ok = (v: string | null) => (v && /^[A-Za-z0-9_-]{8,128}$/.test(v) ? v : null);
  return { token: ok(q.get('t')), phone: ok(q.get('p')) };
}
