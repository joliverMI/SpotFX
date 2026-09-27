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

const ACHROMATIC = 0.05;

function rgbToHsv(r: number, g: number, b: number): [number, number, number] {
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  let h = 0;
  if (d > 0) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h = ((h / 6) % 1 + 1) % 1;
  }
  return [h, max === 0 ? 0 : d / max, max];
}

function hsvToRgb(h: number, s: number, v: number): [number, number, number] {
  const i = Math.floor(h * 6), f = h * 6 - i;
  const p = v * (1 - s), q = v * (1 - f * s), t = v * (1 - (1 - f) * s);
  switch (((i % 6) + 6) % 6) {
    case 0: return [v, t, p];
    case 1: return [q, v, p];
    case 2: return [p, v, t];
    case 3: return [p, q, v];
    case 4: return [t, p, v];
    default: return [v, p, q];
  }
}

/** Blend along the HUE WHEEL, never through RGB — mirrors gradient2d.py's
 * _lerp_hex exactly (shortest-arc hue, linear saturation/value, an
 * achromatic end adopts the other end's hue and saturation). An RGB mix of
 * two distant hues lands near grey, which a Hue bulb shows as white. */
export function lerpHex(a: string, b: string, t: number): string {
  const ch = (h: string, i: number) => parseInt(h.slice(i, i + 2), 16) / 255;
  let [ha, sa, va] = rgbToHsv(ch(a, 1), ch(a, 3), ch(a, 5));
  let [hb, sb, vb] = rgbToHsv(ch(b, 1), ch(b, 3), ch(b, 5));
  const greyA = sa < ACHROMATIC || va < ACHROMATIC;
  const greyB = sb < ACHROMATIC || vb < ACHROMATIC;
  if (greyA && !greyB) { ha = hb; sa = sb; } else if (greyB && !greyA) { hb = ha; sb = sa; }
  const dh = ((((hb - ha + 0.5) % 1) + 1) % 1) - 0.5;
  const h = (((ha + dh * t) % 1) + 1) % 1;
  const rgb = hsvToRgb(h, sa + (sb - sa) * t, va + (vb - va) * t);
  const hex = (v: number) => Math.max(0, Math.min(255, Math.round(v * 255))).toString(16).padStart(2, '0');
  return `#${hex(rgb[0])}${hex(rgb[1])}${hex(rgb[2])}`;
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
