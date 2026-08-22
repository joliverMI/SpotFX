/** Time formatting — ports of frontend/js/app.js fmtMs + builder.html m:ss.t helpers. */

export function fmtMs(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms)) return '--:--';
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

/** Countdown to the next trigger: "37s" above 10s, "3.2s" below. */
export function fmtCountdown(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms) || ms < 0) return '';
  if (ms >= 10000) return `${Math.floor(ms / 1000)}s`;
  return `${(ms / 1000).toFixed(1)}s`;
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

/** "just now" / "4s ago" / "20m ago" / "3h ago" — for a confirmation's AGE
 * shown next to a claim (the codebase's status-honesty rule: a snapshot
 * says when it was taken, not just what it found). */
export function fmtAgo(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return '';
  if (seconds < 1) return 'just now';
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}
