/** THE PRINTED CARD'S QR CODES (the plan's N2 and §8.1): the Wi-Fi code
 * (`WIFI:T:WPA;S:<name>;P:<password>;;`) and the Jukebox's join link with a
 * card's one-time bonus code (`?b=`). Pure, so scripts/check_jukebox_cards.mjs
 * can decode every code back (jsQR) and prove it says what the card says.
 *
 * The Wi-Fi password is typed at print time and lives only in this page:
 * nothing here sends or stores it. The actual QR encoder
 * (`qrMatrix`/`qrPath`/`QUIET`) now lives in ../lib/qr.ts — shared with the
 * TV app's own join QR (data/tv-display-plan/plan.html PR 1.3/1.4) — and
 * is re-exported here so nothing that already imports from this module
 * needs to change. */
export { qrMatrix, qrPath, QUIET } from '../lib/qr';

export type WifiSecurity = 'WPA' | 'WEP' | 'nopass';

export interface Wifi { ssid: string; password: string; security: WifiSecurity; hidden: boolean }

/** The Wi-Fi QR format's own escaping: \ ; , : and " are backslashed. */
export function wifiEscape(s: string): string {
  return s.replace(/([\\;,:"])/g, '\\$1');
}

/** The text a phone's camera reads to join a Wi-Fi network. */
export function wifiPayload(w: Wifi): string {
  const parts = [`T:${w.security}`, `S:${wifiEscape(w.ssid)}`];
  if (w.security !== 'nopass') parts.push(`P:${wifiEscape(w.password)}`);
  if (w.hidden) parts.push('H:true');
  return `WIFI:${parts.join(';')};;`;
}

/** Why the Wi-Fi details can't make a code yet ('' when they can). */
export function wifiProblem(w: Wifi): string {
  if (!w.ssid.trim()) return 'Type the guest Wi-Fi\'s name.';
  if (w.security !== 'nopass' && !w.password) return 'Type the guest Wi-Fi\'s password (it stays on this page).';
  if (w.security === 'WPA' && w.password.length < 8) return 'A WPA password is at least 8 characters.';
  return '';
}

/** The join link with a card's bonus code (used once the guest joins). */
export function joinLink(link: string, code: string | null): string {
  if (!code) return link;
  return `${link}${link.includes('?') ? '&' : '?'}b=${encodeURIComponent(code)}`;
}

/** The cards to print: `count` of them, each with the next unused code (or
 *  none, once the codes run out or when codes are left off). */
export function cardCodes(unused: string[], count: number, withCodes: boolean): (string | null)[] {
  const n = Math.max(0, Math.min(60, Math.floor(count)));
  return Array.from({ length: n }, (_, i) => (withCodes ? unused[i] ?? null : null));
}
