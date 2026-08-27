/** THE POWER BUTTON — one control for every enable/disable in SPECTRA.
 *
 * Owner ask, 2026-08-27, verbatim: "Replace disable/enable with a power
 * button, and light it green when it is on and dim when disabled. Allow me
 * to disable/enable straight from the selection bar for scenes and
 * colorsets and from the flare bar for flares."
 *
 * ONE component for all three, so the glyph, the colour language, and the
 * fixed-size discipline are literally the same thing wherever an item can
 * be switched off — the same reason its predecessor DisabledToggle.tsx
 * (removed in this change) was one component for scenes and colour sets. `itemLabel` only changes the noun in the
 * tooltip.
 *
 * The prop is `on` (green = enabled = plays), NOT `disabled` — every caller
 * translates its own stored polarity at the boundary (SceneV2.disabled and
 * ColorSetCard.disabled are stored inverted; FlareKind.enabled is stored
 * the same way round). A power button that read `disabled` would be lit
 * green for "off", which is exactly the confusion the glyph exists to
 * remove.
 *
 * Fixed size: same discipline as ModeAvailabilityToggle (see
 * fixedSizeToggleStyle.ts). Found 2026-08-19: a fixed WIDTH alone is not
 * enough — without `white-space: nowrap` a bolder label wraps and grows the
 * whole row taller. This control is square and glyph-only, so it can never
 * reflow a list row under a thumb on a phone; it still spreads the shared
 * helper rather than re-deriving the rule, so a future label change
 * inherits the fix instead of reintroducing the bug.
 *
 * `size` exists because a list row wants a smaller target than a toolbar;
 * the button is square at whatever size it is given, and the row must not
 * change height when it flips, at any size. */
import { fixedSizeToggleStyle } from './fixedSizeToggleStyle';

export default function PowerButton({
  on, onChange, itemLabel = 'scene', size = 26, title,
}: {
  /** true = ON (green, plays). Callers storing a `disabled` flag pass `!disabled`. */
  on: boolean;
  onChange: (on: boolean) => void;
  /** The noun in the tooltip — 'scene', 'colour set', 'flare'. */
  itemLabel?: string;
  size?: number;
  /** Overrides the whole tooltip when a caller has something more specific to say. */
  title?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={`${on ? 'Disable' : 'Enable'} this ${itemLabel}`}
      style={{
        ...fixedSizeToggleStyle(size),
        height: size,
        padding: 0,
        lineHeight: `${size}px`,
        fontSize: Math.round(size * 0.58),
        borderRadius: '50%',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'pointer',
        color: on ? 'var(--ok)' : 'var(--text-muted)',
        borderColor: on ? 'var(--ok)' : 'var(--border)',
        background: on ? 'rgba(74,222,128,0.14)' : 'transparent',
        textShadow: on ? '0 0 6px rgba(74,222,128,0.65)' : undefined,
        opacity: on ? 1 : 0.55,
      }}
      title={title ?? (on
        ? `On — tap to disable this ${itemLabel} (reversible; nothing is deleted, and an explicit press still works)`
        : `Off — never chosen automatically. Tap to re-enable this ${itemLabel}.`)}
      onClick={(e) => { e.stopPropagation(); onChange(!on); }}
      onPointerDown={(e) => e.stopPropagation()}
    >
      ⏻
    </button>
  );
}
