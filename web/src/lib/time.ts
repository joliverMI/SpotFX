/** Time formatting — ports of frontend/js/app.js fmtMs + builder.html m:ss.t helpers. */

export function fmtMs(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms)) return '--:--';
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

/** m:ss.t (tenths) — the trigger dialog's timestamp format. */
export function fmtMsTenths(ms: number): string {
  const totalSec = ms / 1000;
  const m = Math.floor(totalSec / 60);
  const s = totalSec - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, '0')}`;
}

/** Parse "m:ss.t", "m:ss", "ss.t" or plain seconds into ms; null if invalid. */
export function parseMsTenths(text: string): number | null {
  const t = text.trim();
  const colon = t.match(/^(\d+):(\d{1,2}(?:\.\d+)?)$/);
  if (colon) return Math.round((parseInt(colon[1], 10) * 60 + parseFloat(colon[2])) * 1000);
  const secs = t.match(/^(\d+(?:\.\d+)?)$/);
  if (secs) return Math.round(parseFloat(secs[1]) * 1000);
  return null;
}
