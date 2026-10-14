/** ONE 30px icon-toggle component (song-layout-plan, data/ui-layout-plan/
 * report.md §9 idea 6 — approved, all 8 ideas): replaces "chip filter"
 * text toggles across Timeline/Home/Test Bed with one look, purple-tinted
 * when on. A parallel task (ui-build-bar) also owns a shared icon-toggle
 * component for the consolidated top bar; if that one lands first, this
 * component should be rebased onto it rather than kept as a second
 * implementation — written self-contained here (no cross-import) so
 * either direction of merge is a drop-in replacement, not a rewrite. */
import Icon, { type IconName } from './Icon';

export default function IconToggle({
  icon, on, onToggle, title, size = 30,
}: {
  icon: IconName;
  on: boolean;
  onToggle: () => void;
  title: string;
  size?: number;
}) {
  return (
    <button
      type="button"
      className={`icon-toggle${on ? ' on' : ''}`}
      style={{ width: size, height: size }}
      aria-pressed={on}
      title={title}
      onClick={onToggle}
    >
      <Icon name={icon} size={Math.round(size * 0.55)} />
    </button>
  );
}
