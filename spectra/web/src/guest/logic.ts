// The guest page's rules, pure (scripts/check_jukebox_guest_logic.mjs holds
// them): the "your song" strip's words, when the "you're next" banner shows
// and whether the phone buzzes, which phones get the Add to Home Screen hint,
// the tabs, how times read, and free play's words (the room's skip, bumps,
// the time-out). Times count from when THIS phone received the view (never
// the server's clock against the phone's — the two can disagree). Whether a
// skip, a bump or a time-out happens is SpotFX's; this only says it.
import type {
  BumpsInfo, By, Features, JailInfo, MySong, NextQuote, NextSong, SearchResult, SkipInfo, Strip,
  StripTone, TipInfo,
} from './types';

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
  if (strip.tone === 'jail') {
    if (strip.jail_kind === 'breakout') {
      return { tone: 'jail', label: "You're in jail",
               detail: `Tap here to break out (${strip.jail_fee ?? 10} credits)` };
    }
    const n = strip.jail_left ?? 0;
    return { tone: 'jail', label: "You're in a time-out",
             detail: `Your songs sit out ${n} more song${n === 1 ? '' : 's'}` };
  }
  if (strip.held && strip.tone !== 'playing') {
    return { tone: 'queued', label: 'Your song is on hold',
             detail: `${strip.title} · the host is holding it; it keeps its place` };
  }
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

/** The banner after a new view: a new "next" or "playing" shows; any other
 *  change of the strip takes a showing banner down — it would be stale. */
export function bannerAfter(prev: StripTone | null, tone: StripTone,
                            showing: BannerKind | null): BannerKind | null {
  const kind = bannerFor(prev, tone);
  if (kind) return kind;
  if (prev !== null && prev !== tone) return null;
  return showing;
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

export type Tab = 'now' | 'queue' | 'add' | 'shop' | 'board';

/** The bottom bar: only what tonight's page can do (free play has no Shop;
 *  Add, Shop and Board arrive when SpotFX says they are open). */
export function tabsFor(f: Features): Tab[] {
  return ['now', 'queue', ...(f.add ? ['add' as Tab] : []), ...(f.shop ? ['shop' as Tab] : []),
          ...(f.board ? ['board' as Tab] : [])];
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

/** How long to wait after the last keystroke before searching (the
 *  guest app also rate-limits searches). */
export const SEARCH_DEBOUNCE_MS = 400;
export const SEARCH_MIN = 2;

export interface Badge { kind: 'ready' | 'long' | 'explicit' | 'in-line'; label: string }

/** A search result's badges: "Ready" (the lights already know it), a long
 *  song's length, explicit, already in line. */
export function badges(r: { known: boolean; long: boolean; duration_ms: number;
                            explicit: boolean; in_line: boolean }): Badge[] {
  const out: Badge[] = [];
  if (r.known) out.push({ kind: 'ready', label: 'Ready' });
  if (r.long) out.push({ kind: 'long', label: mmss(r.duration_ms) });
  if (r.explicit) out.push({ kind: 'explicit', label: 'Explicit' });
  if (r.in_line) out.push({ kind: 'in-line', label: 'In line' });
  return out;
}

function songs(n: number): string {
  return `${n} more song${n === 1 ? '' : 's'}`;
}

/** The line under the search box: requests closed, your songs in line. */
export function addStatus(req: { open: boolean; detail: string; closes_at: string;
                                 max_waiting: number; waiting: number },
                          approved: boolean, jail?: JailInfo): { canAdd: boolean; text: string } {
  if (!approved) return { canAdd: false, text: 'The host hasn\'t let this phone in yet — hang on.' };
  if (jail?.in) {
    return { canAdd: false, text: `You're in a time-out — you can add again after ${songs(jail.songs_left)}.` };
  }
  if (!req.open) return { canAdd: false, text: req.detail };
  if (req.waiting >= req.max_waiting) {
    return { canAdd: false,
             text: `You have ${req.waiting} song${req.waiting === 1 ? '' : 's'} in line — add another when one plays.` };
  }
  const left = req.max_waiting - req.waiting;
  return { canAdd: true,
           text: `You can add ${left} more song${left === 1 ? '' : 's'} · requests close at ${req.closes_at}` };
}

/** After an add: "Added — plays in ~25 min (~9:46)". */
export function addedText(startsInMs: number | null, nowMs: number, locale?: string): string {
  if (startsInMs === null) return 'Added to the line.';
  return `Added — plays ${inWords(startsInMs)} (~${clockAt(nowMs, startsInMs, locale)})`;
}

// ── free play ────────────────────────────────────────────────────────────

/** Under the vote buttons: how close the room is to skipping the song. */
export function skipLine(skip: SkipInfo | undefined, downs: number): string {
  if (!skip || skip.skipping) return '';
  if (skip.locked) return 'The host has kept this song from skips.';
  if (skip.mode === 'paid') return '';           // credits: the skip button says it all
  if (skip.needed === 0) {
    return skip.grace_left_ms > 0 ? 'The room has voted to skip it — it goes in a few seconds.'
      : 'The room has voted to skip it.';
  }
  if (downs === 0) return `${skip.rule}.`;
  return skip.needed === 1 ? 'One more ▼ skips this song.' : `${skip.needed} more ▼ skip this song.`;
}

/** The Queue's line about bumps. */
export function bumpsLine(bumps: BumpsInfo | undefined, jail: JailInfo | undefined): string {
  if (!bumps || bumps.per_hour === 0) return 'Bumps are off tonight.';
  if (jail?.in) return "No bumps during your time-out.";
  const how = 'tap ⇅ to move your song up, or someone else\'s down';
  if (bumps.left === 0) return `No bumps left this hour — the next is free at ${bumps.next_at ?? 'soon'}.`;
  return `${bumps.left} bump${bumps.left === 1 ? '' : 's'} left this hour · ${how}`;
}

export interface BumpOffer { dir: 'up' | 'down'; label: string; can: boolean; why: string }

/** What the move sheet offers for one song: your own up, others' down —
 *  and why not, when this phone can't right now. Null: nothing to offer.
 *  In credits mode (`balance` given) a move has its price instead of an
 *  hourly count. */
export function bumpOffer(song: NextSong, bumps: BumpsInfo | undefined,
                          jail: JailInfo | undefined, balance?: number): BumpOffer | null {
  if (song.kind !== 'jukebox' || song.committed || !song.bump) return null;
  const dir = song.bump;
  if (balance !== undefined) {
    const price = song.bump_price ?? 0;
    const label = `${dir === 'up' ? 'Move it up' : 'Move it down'} one place · ${price}`;
    if (jail?.in) return { dir, label, can: false, why: jailWhy(jail) };
    return { dir, label, can: balance >= price, why: balance >= price ? '' : needs(price, balance) };
  }
  const label = dir === 'up' ? 'Move it up one place' : 'Move it down one place';
  let why = '';
  if (jail?.in) why = `You're in a time-out — you can move songs again after ${songs(jail.songs_left)}.`;
  else if (!bumps || bumps.per_hour === 0) why = 'Bumps are off tonight.';
  else if (bumps.left === 0) {
    why = `You've used your ${bumps.per_hour} bump${bumps.per_hour === 1 ? '' : 's'} this hour — `
      + `the next one is free at ${bumps.next_at ?? 'soon'}.`;
  }
  return { dir, label, can: !why, why };
}

/** One of your songs, in words: playing, next, its place and time, or why
 *  it is waiting (the host's hold, your time-out). */
export function myStatus(m: MySong, elapsedMs: number, nowMs: number, locale?: string): string {
  if (m.state === 'playing') return 'Playing now';
  if (m.jailed) return 'Sits out your time-out · keeps its place';
  if (m.held) return 'On hold · the host is holding it, it keeps its place';
  if (m.starts_in_ms === null) return m.place ? `#${m.place}` : 'Further down the line';
  const left = Math.max(0, m.starts_in_ms - elapsedMs);
  const where = m.state === 'next' ? 'Next' : `#${m.place ?? '—'}`;
  return `${where} · ${inWords(left)} · ~${clockAt(nowMs, left, locale)}`;
}

// ── credits mode (PR 3.2) ────────────────────────────────────────────────

export function credits(n: number): string {
  return `${n} credit${n === 1 ? '' : 's'}`;
}

export function needs(price: number, balance: number): string {
  return `That needs ${credits(price)} — you have ${balance}.`;
}

function jailWhy(jail: JailInfo): string {
  return jail.kind === 'breakout'
    ? `You're in jail — break out (${credits(jail.fee ?? 10)}) to move songs again.`
    : `You're in a time-out — you can move songs again after ${songs(jail.songs_left)}.`;
}

export interface Offer { label: string; can: boolean; why: string }

/** The skip button in credits mode: the rest of the price (what's left
 *  after the pot), and the pot itself. Null: nothing to buy. */
export function skipOffer(skip: SkipInfo | undefined, balance: number): (Offer & { pot: string; price: number; need: number }) | null {
  if (!skip || skip.mode !== 'paid' || skip.skipping) return null;
  const price = skip.price ?? 0;
  const need = skip.need ?? price;
  const pot = skip.pot ?? 0;
  const label = pot > 0 ? `Skip · ${need} more` : `Skip · ${price}`;
  const why = skip.why || (balance < need ? needs(need, balance) : '');
  const potLine = pot > 0
    ? `Pot ${pot} of ${price}${skip.pot_mine ? ` · ${skip.pot_mine} yours` : ''} · it comes back if the song ends first`
    : `The price falls ${skip.per_down_pct ?? 15}% with every net ▼${skip.chip_in ? ' · or chip in with others' : ''}`;
  return { label, can: !why && !!skip.can, why, pot: potLine, price, need };
}

/** The tip button: tip the guest whose song this is. Null: nothing to say. */
export function tipOffer(tip: TipInfo | undefined, balance: number): Offer | null {
  if (!tip) return null;
  if (!tip.to) return { label: '', can: false, why: tip.why };
  const why = tip.why || (balance < tip.unit ? needs(tip.unit, balance) : '');
  return { label: `Tip ${tip.to} · ${tip.unit}`, can: tip.can && !why, why };
}

/** Play next on one of your songs. */
export function nextOffer(q: NextQuote | undefined, balance: number, jail?: JailInfo): Offer | null {
  if (!q) return null;
  const label = `Play next · ${q.price}`;
  if (jail?.in) return { label, can: false, why: jailWhy(jail) };
  if (!q.allowed) return { label, can: false, why: q.why };
  return { label, can: balance >= q.price, why: balance >= q.price ? '' : needs(q.price, balance) };
}

/** The Add button on a search result in credits mode. */
export function addOffer(r: SearchResult): { label: string; afford: boolean } {
  if (r.price === undefined) return { label: 'Add', afford: true };
  return { label: `Add · ${r.price}`, afford: r.afford !== false };
}

/** The jail card (credits): why, and the way out. */
export function jailCard(jail: JailInfo | undefined): { title: string; text: string; fee: number } | null {
  if (!jail?.in || jail.kind !== 'breakout') return null;
  return {
    title: "You're in jail",
    text: (jail.count >= jail.at
      ? `Your songs got ${jail.count} more ▼ than ▲ tonight (the bar at this party is ${jail.at}). `
      : `Your songs got too many ▼ tonight (the bar at this party is ${jail.at} more ▼ than ▲). `) +
      'They keep their places but wait until you break out. You can still vote — +1 each.',
    fee: jail.fee ?? 10,
  };
}

/** A history row's amount: "+2", "−4". */
export function signed(delta: number): string {
  return delta >= 0 ? `+${delta}` : `−${-delta}`;
}

/** After a vote: the "+1 credit" toast, when it paid. */
export function earnedToast(earned: number | undefined): string {
  return earned && earned > 0 ? `+${credits(earned)} for voting` : '';
}

// ── the Board (report §1 rule 11, §2.2) ──────────────────────────────────

/** How often the Board asks again while it is open. */
export const BOARD_POLL_MS = 15000;

/** A board song's line: who added it, its ▲, and how often it played. */
export function boardSongLine(s: { by: By; mine: boolean; ups: number; plays: number }): string {
  const played = s.plays > 1 ? ` · played ${s.plays} times` : '';
  return `${byLine(s.by, s.mine)} · ▲ ${s.ups}${played}`;
}

/** A people board's count in words: "1 song voted on", "3 songs voted on". */
export function peopleCount(value: number, p: { unit: string; unit_one?: string }): string {
  return `${value} ${value === 1 && p.unit_one ? p.unit_one : p.unit}`;
}

/** How long the page holds a tip before sending it, so a mis-tap can be undone. */
export const TIP_UNDO_MS = 3000;
