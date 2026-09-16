/** How the debug page names an `xcorr_spike`. Two different things send one:
 * the post-lock drift monitor, after it CONFIRMED a mismatch (no `source`),
 * and the keep-searching sweep on a song that never locked
 * (`source: "keep_searching"`). A song still searching must not read as a
 * confirmed mismatch, so each is named for what it is; a monitor spike reads
 * exactly as it always has. */

export const KEEP_SEARCHING_SOURCE = 'keep_searching';

export type SpikeKind = 'recovery' | 'keep_searching' | 'other';

export interface SpikeHeading {
  title: string;
  note: string;
}

export function spikeKind(msg: Record<string, unknown>): SpikeKind {
  const source = msg.source;
  if (source == null || source === '') return 'recovery';
  return source === KEEP_SEARCHING_SOURCE ? 'keep_searching' : 'other';
}

export function spikeLine(msg: Record<string, unknown>): string {
  const body =
    `@${msg.spike_ms}ms → window [${msg.win_start}-${msg.win_end}] ` +
    `strength=${Number(msg.strength ?? 0).toFixed(2)}`;
  switch (spikeKind(msg)) {
    case 'recovery':
      return `spike ${body}`;
    case 'keep_searching':
      return `search spike ${body}  (keep-searching, not locked — no mismatch confirmed)`;
    default:
      return `spike ${body}  (source: ${String(msg.source)})`;
  }
}

export function spikeHeading(kinds: readonly SpikeKind[]): SpikeHeading {
  if (kinds.every((k) => k === 'recovery')) {
    return { title: 'Mismatch spikes', note: '(recovery windows)' };
  }
  if (kinds.every((k) => k === 'keep_searching')) {
    return { title: 'Search spikes', note: '(keep-searching windows — no mismatch confirmed)' };
  }
  return { title: 'Spikes', note: '(each line names its source)' };
}
