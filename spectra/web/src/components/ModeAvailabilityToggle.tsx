/** Per-item display-mode availability toggle (owner ask 2026-08-17) —
 * scenes, colour sets, and colour groups each carry their own
 * display_availability. Cycles Hybrid → Light → Dark → Hybrid on tap.
 *
 * HARD REQUIREMENT (his words): the toggle must not change size as it
 * cycles — a fixed pixel width is reserved for the longest label
 * ("Hybrid") so the row never reflows under his thumb. Built via the
 * shared fixedSizeToggleStyle.ts (see DisabledToggle.tsx, which sits on
 * the same row and shipped without the `white-space: nowrap` this needs
 * to actually hold — this toggle's short labels just never happened to
 * wrap). */
import type { DisplayAvailability } from '../types';
import { fixedSizeToggleStyle } from './fixedSizeToggleStyle';

const ORDER: DisplayAvailability[] = ['default', 'light', 'dark'];
const LABEL: Record<DisplayAvailability, string> = { default: 'Hybrid', light: 'Light', dark: 'Dark' };
const ICON: Record<DisplayAvailability, string> = { default: '◐', light: '☀', dark: '☾' };
const COLOR: Record<DisplayAvailability, string> = {
  default: 'var(--text-muted)', light: '#ffca28', dark: '#7986cb',
};
const TITLE: Record<DisplayAvailability, string> = {
  default: 'Always available — tap to restrict to Light',
  light: 'Available in Light + Hybrid, skipped while the room is Dark — tap to restrict to Dark',
  dark: 'Available in Dark + Hybrid, skipped while the room is Light — tap to reset to Hybrid',
};

const TOGGLE_WIDTH = 82;

export default function ModeAvailabilityToggle({ value, onChange }: {
  value: DisplayAvailability;
  onChange: (v: DisplayAvailability) => void;
}) {
  const v = value ?? 'default';
  const next = () => onChange(ORDER[(ORDER.indexOf(v) + 1) % ORDER.length]);
  return (
    <button
      type="button"
      style={{
        ...fixedSizeToggleStyle(TOGGLE_WIDTH),
        color: COLOR[v], borderColor: v === 'default' ? undefined : 'var(--accent)',
      }}
      title={TITLE[v]}
      onClick={next}
    >
      {ICON[v]} {LABEL[v]}
    </button>
  );
}
