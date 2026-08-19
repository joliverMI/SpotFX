/** Temporary scene disable (owner ask, 2026-08-18: "add an ability to
 * disable a scene temporarily") — a manual, reversible toggle, not a timer.
 * Tap flips it; a disabled scene is dropped from every AUTOMATIC pick (the
 * sequencer's own roll, a generated trigger's draw, the fire_scene_by_id
 * hard gate) regardless of room mode — stronger than mode availability,
 * which only narrows WHICH room mode a scene plays in. Force Scene and a
 * manual Fire/test-fire still work on a disabled scene, same as they
 * already bypass mode availability.
 *
 * Same fixed-size discipline as ModeAvailabilityToggle.tsx (see
 * fixedSizeToggleStyle.ts) — the row must not reflow under a thumb on a
 * phone. Found 2026-08-19: a fixed WIDTH alone isn't enough — without
 * `white-space: nowrap`, the bold "⛔ Disabled" label wrapped onto a second
 * line at 88px and grew the button (and the whole toolbar row) taller.
 * ModeAvailabilityToggle only escaped this by accident (its labels are
 * short enough not to wrap) — the shared helper is what actually closes it
 * for both. */
import { fixedSizeToggleStyle } from './fixedSizeToggleStyle';

const TOGGLE_WIDTH = 88;

export default function DisabledToggle({ value, onChange }: {
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      style={{
        ...fixedSizeToggleStyle(TOGGLE_WIDTH),
        color: value ? 'var(--danger)' : 'var(--text-muted)',
        borderColor: value ? 'var(--danger)' : undefined,
        fontWeight: value ? 600 : undefined,
      }}
      title={value
        ? 'Disabled — never fires automatically (Force Scene / Fire still work). Tap to re-enable.'
        : 'Enabled — tap to temporarily disable this scene (reversible; nothing is deleted)'}
      onClick={() => onChange(!value)}
    >
      {value ? '⛔ Disabled' : '● Enabled'}
    </button>
  );
}
