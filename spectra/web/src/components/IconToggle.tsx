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
  on, onChange, icon, title, ariaLabel, size = 30,
}: {
  on: boolean;
  onChange: (on: boolean) => void;
  icon: IconName;
  title: string;
  /** Falls back to `title` when the icon alone wouldn't announce enough. */
  ariaLabel?: string;
  size?: number;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={ariaLabel ?? title}
      title={title}
      className={`icon-toggle${on ? ' icon-toggle-on' : ''}`}
      style={{ width: size, height: size }}
      onClick={() => onChange(!on)}
    >
      <Icon name={icon} size={Math.round(size * 0.55)} />
    </button>
  );
}
