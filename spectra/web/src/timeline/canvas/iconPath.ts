/** A registry icon (../../components/iconRegistry.ts) stroked on a canvas,
 * so a canvas glyph and the same glyph everywhere else (the Home Drops
 * panel, the test bed) are ONE drawing, never a second one that can drift.
 *
 * It reads the icon's path straight from the registry and strokes it with
 * plain moveTo/lineTo — no Path2D (absent in Node, so the recording fake
 * canvas in scripts/check_drop_sequence_*.mjs can see every stroke). Only the
 * straight-line commands are understood (M L H V Z, absolute and relative,
 * with implicit repeats), which is all a stroked glyph like the pre-drop's
 * needs; a path with anything else answers null and the caller draws its
 * own fallback rather than a wrong shape. */
import { ICONS, type IconName } from '../../components/iconRegistry';

/** The icon's polylines in its own 24×24 box, or null when its path uses a
 * command this does not draw (a curve). */
export function iconPolylines(d: string): [number, number][][] | null {
  const toks = d.match(/[A-Za-z]|-?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?/g) ?? [];
  const out: [number, number][][] = [];
  let cur: [number, number][] | null = null;
  let x = 0; let y = 0; let sx = 0; let sy = 0;
  let cmd = '';
  let i = 0;
  const num = () => Number(toks[i++]);
  while (i < toks.length) {
    if (/^[A-Za-z]$/.test(toks[i])) {
      cmd = toks[i++];
      if (cmd === 'Z' || cmd === 'z') {
        if (cur) cur.push([sx, sy]);
        x = sx; y = sy;
        continue;
      }
      if (!'MmLlHhVv'.includes(cmd)) return null;
      continue;
    }
    if (!cmd) return null;
    if (cmd === 'M' || cmd === 'm') {
      x = cmd === 'M' ? num() : x + num();
      y = cmd === 'M' ? num() : y + num();
      cur = [[x, y]];
      out.push(cur);
      sx = x; sy = y;
      cmd = cmd === 'M' ? 'L' : 'l';           // further pairs are line-tos
      continue;
    }
    if (!cur) return null;
    if (cmd === 'L') { x = num(); y = num(); }
    else if (cmd === 'l') { x += num(); y += num(); }
    else if (cmd === 'H') x = num();
    else if (cmd === 'h') x += num();
    else if (cmd === 'V') y = num();
    else if (cmd === 'v') y += num();
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    cur.push([x, y]);
  }
  return out.length ? out : null;
}

const CACHE = new Map<IconName, [number, number][][] | null>();

/** Stroke registry icon `name` centred on (x, y), `size` px square, in the
 * current strokeStyle. False when the icon cannot be drawn this way (the
 * caller then draws its own fallback). */
export function strokeIcon(
  ctx: CanvasRenderingContext2D, name: IconName, x: number, y: number, size: number,
): boolean {
  if (!CACHE.has(name)) CACHE.set(name, iconPolylines(ICONS[name]));
  const lines = CACHE.get(name);
  if (!lines) return false;
  const k = size / 24;
  const ox = x - size / 2;
  const oy = y - size / 2;
  ctx.beginPath();
  for (const line of lines) {
    line.forEach(([px, py], j) => {
      const cx = ox + px * k;
      const cy = oy + py * k;
      if (j === 0) ctx.moveTo(cx, cy);
      else ctx.lineTo(cx, cy);
    });
  }
  ctx.stroke();
  return true;
}
