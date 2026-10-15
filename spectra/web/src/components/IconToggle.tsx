/** ONE icon-toggle component (UI declutter plan idea 6): a 30px square,
 * purple-tinted when on, replacing the "chip filter" text toggles
 * scattered across Timeline/Home/Test Bed (`chip filter ${on ? 'active'
 * : ''}` button text like "Analysed events" / "Drop sequences" / "Light
 * Show") with one consistent look and behaviour everywhere a boolean
 * display filter is toggled. Exported for reuse outside this package (the
 * Home page's own icon toggles for Analysed events / Drop sequences /
 * Light Show are built on this same component). */
import Icon, { type IconName } from './Icon';

export default function IconToggle({
  on, onChange, icon, glyph, label, title, ariaLabel, size = 30, disabled = false,
}: {
  on: boolean;
  onChange: (on: boolean) => void;
  /** A registry icon. Omit it when passing `glyph` or `label` instead. */
  icon?: IconName;
  /** A bespoke glyph, for a toggle whose meaning IS a drawn marker shape
   * rather than a stroke icon: Home's own three filter toggles draw the
   * actual scene square / charge-lull-drop pills / High-Low flags they
   * switch (design-fidelity pass, 2026-10-14 — audit H2, where the
   * registry's generic stroke icons rendered as ~6px squiggles inside
   * their 24-unit box and read as nothing at all). */
  glyph?: React.ReactNode;
  /** A short text label, for the mockup's own wide `.tgl.wide` variant
   * (Home's T / B / M / H band toggles, "Marks", "sections", "beats"). */
  label?: string;
  title: string;
  /** Falls back to `title` when the icon alone wouldn't announce enough. */
  ariaLabel?: string;
  size?: number;
  disabled?: boolean;
}) {
  const wide = label != null;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={ariaLabel ?? title}
      title={title}
      disabled={disabled}
      className={`icon-toggle${on ? ' icon-toggle-on' : ''}${wide ? ' icon-toggle-wide' : ''}`}
      style={wide ? { height: size } : { width: size, height: size }}
      onClick={() => onChange(!on)}
    >
      {glyph ?? (icon ? <Icon name={icon} size={Math.round(size * 0.55)} /> : null)}
      {label}
    </button>
  );
}
