/** Formats a Sonic scene-edit's `preview` field (scene_console.py's
 * _diff_scenes — a real field-level diff between two stored scene
 * snapshots) into short, human-readable lines. Deliberately dumb: this
 * only stringifies what the server already computed from disk, never
 * re-derives or re-interprets a change — the whole point of the preview
 * mechanism is that it can't be talked into showing something that didn't
 * really happen. */
import type { SonicAppliedChange } from '../types';

function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'boolean') return v ? 'On' : 'Off';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

export function formatPreview(change: SonicAppliedChange): string | null {
  const preview = change.preview as Record<string, { before: unknown; after: unknown }> | undefined;
  if (!preview || Object.keys(preview).length === 0) return null;
  const label = change.scene_name ? `${change.scene_name} — ` : '';
  const lines = Object.entries(preview).map(
    ([field, { before, after }]) => `${field}: ${fmtValue(before)} → ${fmtValue(after)}`,
  );
  return `${label}what actually changed:\n${lines.join('\n')}`;
}
