/** JS mirror of spectra/models/gradient2d.py's parse_stops/sample_edge — the
 * SAME "#rrggbb solid or linear-gradient(...)" string grammar every colour
 * value in this app already uses. Used to render the 2D drift gradient's
 * square preview client-side (no round-trip needed just to preview). Keep
 * this in sync with the Python implementation if either changes. */

const HEX_RE = /^#([0-9a-fA-F]{6})$/;
const GRADIENT_RE = /^linear-gradient\(([^,]+),(.+)\)$/i;
const STOP_RE = /(#[0-9a-fA-F]{6}|rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\))\s*([\d.]+)%?/gi;
const RGB_RE = /rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)/i;

function normalizeStopColor(s: string): string | null {
  if (HEX_RE.test(s)) return s.toLowerCase();
  const m = RGB_RE.exec(s);
  if (m) {
    const [, r, g, b] = m;
    return `#${(+r).toString(16).padStart(2, '0')}${(+g).toString(16).padStart(2, '0')}${(+b).toString(16).padStart(2, '0')}`;
  }
  return null;
}

export function parseStops(value: string | null | undefined): [number, string][] {
  const v = (value ?? '').trim();
  if (!v) return [];
  if (HEX_RE.test(v)) return [[0, v.toLowerCase()]];
  const m = GRADIENT_RE.exec(v);
  if (!m) return [];
  const stops: [number, string][] = [];
  let sm: RegExpExecArray | null;
  STOP_RE.lastIndex = 0;
  while ((sm = STOP_RE.exec(m[2])) !== null) {
    const norm = normalizeStopColor(sm[1]);
    if (norm === null) continue;
    stops.push([Math.max(0, Math.min(1, parseFloat(sm[2]) / 100)), norm]);
  }
  stops.sort((a, b) => a[0] - b[0]);
  return stops;
}

function lerpHex(a: string, b: string, t: number): string {
  const ar = parseInt(a.slice(1, 3), 16), ag = parseInt(a.slice(3, 5), 16), ab = parseInt(a.slice(5, 7), 16);
  const br = parseInt(b.slice(1, 3), 16), bg = parseInt(b.slice(3, 5), 16), bb = parseInt(b.slice(5, 7), 16);
  const clamp = (v: number) => Math.max(0, Math.min(255, Math.round(v)));
  const r = clamp(ar + (br - ar) * t), g = clamp(ag + (bg - ag) * t), b_ = clamp(ab + (bb - ab) * t);
  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b_.toString(16).padStart(2, '0')}`;
}

export function sampleEdge(value: string | null | undefined, x: number): string | null {
  const stops = parseStops(value);
  if (stops.length === 0) return null;
  if (stops.length === 1 || x <= stops[0][0]) return stops[0][1];
  if (x >= stops[stops.length - 1][0]) return stops[stops.length - 1][1];
  for (let i = 0; i < stops.length - 1; i++) {
    const [xa, ca] = stops[i], [xb, cb] = stops[i + 1];
    if (x >= xa && x <= xb) {
      const t = xb - xa <= 0 ? 0 : (x - xa) / (xb - xa);
      return lerpHex(ca, cb, t);
    }
  }
  return stops[stops.length - 1][1];
}

export function sample2d(top: string | null | undefined, bottom: string | null | undefined,
                         x: number, y: number): string | null {
  const topC = sampleEdge(top, x);
  const botC = sampleEdge(bottom, x);
  if (topC === null) return botC;
  if (botC === null) return topC;
  return lerpHex(botC, topC, Math.max(0, Math.min(1, y)));
}
