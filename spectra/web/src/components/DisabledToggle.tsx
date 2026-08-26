/** Temporary disable — a manual, reversible toggle, not a timer.
 *
 * Owner ask, 2026-08-18: "add an ability to disable a scene temporarily",
 * then 2026-08-25: "i want to be able to disable color sets like i can
 * scenes". ONE component for both, so the control, the wording, and the
 * fixed-size discipline are literally the same thing in both places —
 * `itemLabel` only changes the noun in the tooltip.
 *
 * Tap flips it. A disabled SCENE is dropped from every automatic pick (the
 * sequencer's own roll, a generated trigger's draw, the fire_scene_by_id
 * hard gate); a disabled COLOUR SET/GROUP is dropped from every automatic
 * colour pick (the sequencer's eligible pool, a Group's rotation, the
 * drift journey's destinations, a flare's colour jump, a select_color_set
 * trigger) — both regardless of room mode, which makes this stronger than
 * mode availability, which only narrows WHICH room mode an item plays in.
 * An explicit press in the moment still works on either (a scene's Fire or
 * a Force Scene pin; a colour card's Preview or POST /room-color/apply) and
 * the contradiction is named rather than silent.
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

export default function DisabledToggle({ value, onChange, itemLabel = 'scene' }: {
  value: boolean;
  onChange: (v: boolean) => void;
  /** The noun in the tooltip — 'scene' (default) or 'colour set'. The
   * button's own label is deliberately identical either way. */
  itemLabel?: string;
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
        ? `Disabled — never chosen automatically (an explicit press still works). Tap to re-enable this ${itemLabel}.`
        : `Enabled — tap to temporarily disable this ${itemLabel} (reversible; nothing is deleted)`}
      onClick={() => onChange(!value)}
    >
      {value ? '⛔ Disabled' : '● Enabled'}
    </button>
  );
}
