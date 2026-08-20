/** The two-dimensional drift gradient's square preview (his ask: "The UI
 * should be very similar to the current gradient picker, just make it a
 * square. This is different from being able to rotate it, to be clear.").
 * Renders as N thin vertical column divs, each a plain CSS linear-gradient
 * from that column's bottom-edge colour to its top-edge colour — a direct,
 * inspectable rendering of "vertices only at the top and bottom, mapping
 * linearly between them," not a canvas/WebGL approximation. */
import { sampleEdge } from '../lib/gradient2dSample';

const COLUMNS = 48;

export default function GradientSquarePreview({
  top, bottom, size = 160, style,
}: {
  top: string;
  bottom: string;
  size?: number;
  style?: React.CSSProperties;
}) {
  return (
    <div
      style={{
        display: 'flex', width: size, height: size,
        borderRadius: 'var(--radius)', overflow: 'hidden',
        border: '1px solid var(--border)', ...style,
      }}
    >
      {Array.from({ length: COLUMNS }, (_, i) => {
        const x = i / (COLUMNS - 1);
        const topColor = sampleEdge(top, x) ?? '#000000';
        const bottomColor = sampleEdge(bottom, x) ?? '#000000';
        return (
          <div
            key={i}
            style={{
              flex: 1,
              background: `linear-gradient(to bottom, ${topColor}, ${bottomColor})`,
            }}
          />
        );
      })}
    </div>
  );
}
