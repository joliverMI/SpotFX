/** The two-dimensional drift gradient's square preview (his ask: "The UI
 * should be very similar to the current gradient picker, just make it a
 * square. This is different from being able to rotate it, to be clear.").
 * Renders as N thin vertical column divs, each a plain CSS linear-gradient
 * from that column's bottom-edge colour to its top-edge colour (sampled along
 * the hue wheel, the same blend the room uses) — a direct,
 * inspectable rendering of "vertices only at the top and bottom, mapping
 * linearly between them," not a canvas/WebGL approximation. */
import { lerpHex, sampleEdge } from '../lib/gradient2dSample';

const COLUMNS = 48;
// Each column is drawn from this many hue-path samples: a plain two-stop
// CSS gradient would mix top and bottom in RGB (through grey/white) — not
// what the room does (gradient2d.py's _lerp_hex).
const ROWS = 12;

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
        const stops = Array.from({ length: ROWS + 1 }, (_, r) => {
          const y = 1 - r / ROWS;   // top of the square is y = 1
          return `${lerpHex(bottomColor, topColor, y)} ${((r / ROWS) * 100).toFixed(1)}%`;
        });
        return (
          <div
            key={i}
            style={{
              flex: 1,
              background: `linear-gradient(to bottom, ${stops.join(', ')})`,
            }}
          />
        );
      })}
    </div>
  );
}
