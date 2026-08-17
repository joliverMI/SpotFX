/** Per-scene colour-set PREFERENCE toggle (owner ask 2026-08-17: "black
 * hole would prefer dark mode color sets... they don't run light mode
 * color sets unless the system is set to light mode").
 *
 * A SECOND, separate control from ModeAvailabilityToggle.tsx — that one
 * decides whether an item plays AT ALL in the current room mode; this one
 * decides WHICH COLOUR SETS a scene draws from once it does play. Same
 * three-value cycle and fixed-width shape (his "must not change size as it
 * cycles" requirement carries over), deliberately not the same component —
 * the tooltips describe a different rule and conflating them would blur
 * the two axes he asked to keep apart. */
import type { DisplayAvailability } from '../types';

const ORDER: DisplayAvailability[] = ['default', 'dark', 'light'];
const LABEL: Record<DisplayAvailability, string> = { default: 'Any', dark: 'Prefers Dark', light: 'Prefers Light' };
const ICON: Record<DisplayAvailability, string> = { default: '◐', dark: '☾', light: '☀' };
const COLOR: Record<DisplayAvailability, string> = {
  default: 'var(--text-muted)', dark: '#7986cb', light: '#ffca28',
};
const TITLE: Record<DisplayAvailability, string> = {
  default: 'No colour-set preference — draws from every set this scene already accepts, marked or not — tap to prefer Dark-marked sets',
  dark: 'Draws from Dark-marked + unmarked sets, skips Light-marked ones — UNLESS the room is explicitly set to Light, which overrides this — tap to prefer Light-marked sets',
  light: 'Draws from Light-marked + unmarked sets, skips Dark-marked ones — UNLESS the room is explicitly set to Dark, which overrides this — tap to reset to no preference',
};

const TOGGLE_WIDTH = 100;

export default function ColorSetPreferenceToggle({ value, onChange }: {
  value: DisplayAvailability;
  onChange: (v: DisplayAvailability) => void;
}) {
  const v = value ?? 'default';
  const next = () => onChange(ORDER[(ORDER.indexOf(v) + 1) % ORDER.length]);
  return (
    <button
      type="button"
      style={{
        fontSize: 12, width: TOGGLE_WIDTH, flexShrink: 0, textAlign: 'center',
        color: COLOR[v], borderColor: v === 'default' ? undefined : 'var(--accent)',
      }}
      title={TITLE[v]}
      onClick={next}
    >
      {ICON[v]} {LABEL[v]}
    </button>
  );
}
