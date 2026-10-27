/** THE PRINTED CARD'S QR CODES (the plan's N2 and §8.1): the Wi-Fi code
 * (`WIFI:T:WPA;S:<name>;P:<password>;;`) and the Jukebox's join link with a
 * card's one-time bonus code (`?b=`). Pure, so scripts/check_jukebox_cards.mjs
 * can decode every code back (jsQR) and prove it says what the card says.
 *
 * The Wi-Fi password is typed at print time and lives only in this page:
 * nothing here sends or stores it. The encoder is qrcode-generator (MIT,
 * pinned), told to encode UTF-8 so a name like "Café" survives. */
import qrcode from 'qrcode-generator';

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

const utf8 = (s: string): number[] => Array.from(new TextEncoder().encode(s));

/** The QR modules for `text` (true = dark), error correction M. */
export function qrMatrix(text: string): boolean[][] {
  // byte mode reads qrcode.stringToBytes when it encodes; its default keeps
  // only each character's low 8 bits, so a name like "Café" needs UTF-8
  const prev = qrcode.stringToBytes;
  qrcode.stringToBytes = utf8;
  try {
    const qr = qrcode(0, 'M');
    qr.addData(text, 'Byte');
    qr.make();
    const n = qr.getModuleCount();
    return Array.from({ length: n }, (_, r) => Array.from({ length: n }, (_, c) => qr.isDark(r, c)));
  } finally {
    qrcode.stringToBytes = prev;
  }
}

export const QUIET = 4;     // the quiet zone a reader needs, in modules

/** An SVG path drawing the dark modules, one 1×1 square each, offset by the
 *  quiet zone (the viewBox is n + 2·QUIET square). */
export function qrPath(m: boolean[][]): string {
  const out: string[] = [];
  m.forEach((row, r) => row.forEach((dark, c) => {
    if (dark) out.push(`M${c + QUIET} ${r + QUIET}h1v1h-1z`);
  }));
  return out.join('');
}

/** The cards to print: `count` of them, each with the next unused code (or
 *  none, once the codes run out or when codes are left off). */
export function cardCodes(unused: string[], count: number, withCodes: boolean): (string | null)[] {
  const n = Math.max(0, Math.min(60, Math.floor(count)));
  return Array.from({ length: n }, (_, i) => (withCodes ? unused[i] ?? null : null));
}
