/** THE ONE QR GENERATOR — shared between the printed guest cards
 * (jukebox/cardQr.ts, the plan's N2) and the TV app's join QR
 * (data/tv-display-plan/plan.html PR 1.3/1.4: "one QR generator (shared
 * with N2)"). Extracted here, out of cardQr.ts, so a second encoder
 * never gets written for the TV screens.
 *
 * Pure — no DOM, no network — so scripts/check_jukebox_cards.mjs (and any
 * future TV-side check) can decode every code back (jsQR) and prove it
 * says what the caller asked for. The encoder is qrcode-generator (MIT,
 * pinned), told to encode UTF-8 so a name like "Café" survives. */
import qrcode from 'qrcode-generator';

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
