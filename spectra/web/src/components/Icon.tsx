/** Renders an icon from `iconRegistry.ts` as inline SVG — see that file's
 * own docstring for why (the "appears as an X" root-cause fix). `name` is
 * typed to the closed `IconName` union, so an unregistered name is a
 * compile error; the runtime fallback below only matters if that type
 * check is bypassed (e.g. `name={x as any}`), and it is deliberately
 * NOT a literal "X" glyph — that would look like a (differently) broken
 * icon instead of a visibly-flagged bug. */
import { ICONS, type IconName } from './iconRegistry';

export type { IconName };

export default function Icon({
  name, size = 16, title, className, style,
}: {
  name: IconName;
  size?: number;
  /** When present, the SVG carries an accessible <title> and role="img";
   * omit it when the icon sits beside its own text label (purely
   * decorative) so screen readers don't announce it twice. */
  title?: string;
  className?: string;
  style?: React.CSSProperties;
}) {
  const d = ICONS[name];
  if (!d) {
    // Unreachable through the type system — see the module docstring.
    // eslint-disable-next-line no-console
    console.error(`Icon: unknown icon name ${JSON.stringify(name)}`);
    return (
      <span
        className={className}
        style={{
          display: 'inline-block', width: size, height: size,
          border: '1px dashed currentColor', borderRadius: 3, ...style,
        }}
        title={title ?? `unknown icon: ${String(name)}`}
      />
    );
  }
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      style={style}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
    >
      {title && <title>{title}</title>}
      <path d={d} />
    </svg>
  );
}
