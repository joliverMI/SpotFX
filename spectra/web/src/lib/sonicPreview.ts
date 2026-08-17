/** Formats a Sonic scene-edit's `preview` field (scene_console.py's
 * _diff_scenes — a real field-level diff between two stored scene
 * snapshots) into short, human-readable lines. Deliberately dumb: this
 * only stringifies what the server already computed from disk, never
 * re-derives or re-interprets a change — the whole point of the preview
 * mechanism is that it can't be talked into showing something that didn't
 * really happen.
 *
 * fmtValue never dumps a raw object/array (found live 2026-08-17: a
 * flare-kind edit diffs the WHOLE `flare_kinds` list wholesale — see
 * _diff_scenes's own docstring, "nested structure changed -> show the
 * whole field" — and a scene with several kinds already declared turned
 * that whole-field dump into a JSON blob long enough to bury the plain
 * "did it work" answer next to it. A list/object still IS the real stored
 * data, so this summarizes it (count, and names when the entries carry
 * one) rather than hiding it — never re-derives or invents content, only
 * formats what's already there differently). */
import type { SonicAppliedChange, SonicRejectedChange } from '../types';

function summarizeList(items: unknown[]): string {
  if (items.length === 0) return 'none';
  const names = items
    .map((it) => (it && typeof it === 'object' && 'name' in it ? String((it as { name: unknown }).name) : null))
    .filter((n): n is string => !!n);
  if (names.length === items.length) return names.join(', ');
  return `${items.length} item${items.length === 1 ? '' : 's'}`;
}

function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'boolean') return v ? 'On' : 'Off';
  if (Array.isArray(v)) return summarizeList(v);
  if (typeof v === 'object') return `${Object.keys(v).length} field(s) changed`;
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

/** The ONE definitive plain-language outcome line for an applied change —
 * built server-side from real structured fields (scene_console.py /
 * settings_console.py), never from the model's own prose. Always present
 * on a real applied result; the fallback only covers a result shape this
 * formatter doesn't yet recognize, not a genuine missing outcome. */
export function formatAppliedStatus(change: SonicAppliedChange): string {
  return change.summary ?? 'Done.';
}

/** Same role for a REFUSED write — `reason` is already the plain-language
 * failure statement (SceneOpError/SettingChangeError.payload()), so this
 * is a passthrough, not a re-interpretation. */
export function formatRejectedStatus(change: SonicRejectedChange): string {
  return change.reason ?? 'That request was refused.';
}
