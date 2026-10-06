/** The Live view's POSITION TABLE: where every fixture pixel is drawn, and
 * which cell of the preview stream colours it.
 *
 * The renderer (stage.ts) knows nothing about fixtures, shapes or rooms. It
 * draws a `StagePlan`: a flat list of points, each with a place, a size and a
 * source cell, grouped by the stream device that feeds them. Anything that
 * can produce a StagePlan is a `PositionSource`.
 *
 * `layoutPositions` is the first source: a tidy arrangement built from the
 * server's layout (spectra/services/preview_layout.py) — the crystal as its
 * real hex lattice, a strip as a line, the TV strip as a frame, bulbs as
 * discs. The shapes are hints read off each fixture's type and name; only the
 * crystal's lattice is real geometry.
 *
 * THE ROOM MAP IS ANOTHER SOURCE, NOT ANOTHER RENDERER. roomMap.ts places
 * each point where one camera saw its light (and a fixture with no map in a
 * "not placed" tray) and returns the same StagePlan; everything downstream —
 * drawing, smoothing, solo, the click targets — is unchanged. Its one
 * addition is optional: a plan may carry a `glow` layer the stage draws
 * under the points.
 *
 * Units are abstract "stage units"; the view scales the stage to its box. */

export interface LiveFixture {
  device_id: string;
  name: string;
  type: string | null;
  kind: 'matrix' | 'strip' | 'frame' | 'bulbs' | 'dot';
  orient: 'h' | 'v';
  count: number;
  /** Stream cell per pixel; null = pixel i is cell i. */
  src: number[] | null;
  /** Matrix only: row-major position per pixel. */
  grid: number[] | null;
  /** The hex colour this fixture is actually HELD at right now (a frozen
   * Hue bulb — services/preview_layout.py's own `_held_hex`), or null to
   * draw its live render unchanged. A frozen Hue device's driving virtual
   * never stops rendering, so without this the preview shows whatever the
   * room's ordinary show happens to paint there, not the colour the real
   * bulb is actually showing (see hue_preview_colour.py's module
   * docstring for the Admiral's own report this closes). */
  held: string | null;
}

export interface LiveVirtual {
  id: string;
  name: string;
  rows: number;
  cols: number;
  cells: number;
  mapping: 'span' | 'copy';
  hex_lattice: boolean;
  favorite?: boolean;
  /** A single swatch colour for the whole virtual — only set when every
   * fixture it reaches is currently held (see `_virtual_held_hex`); null
   * otherwise, including a mix of held and live-rendered fixtures. */
  held: string | null;
  fixtures: LiveFixture[];
}

export interface LiveLayout {
  source: 'live' | 'stored';
  virtuals: LiveVirtual[];
}

/** The points one stream device feeds: `count` points starting at `first`. */
export interface StageGroup {
  visId: string;
  first: number;
  count: number;
  cells: number;
}

export interface StageFixture {
  key: string;
  deviceId: string;
  visId: string;
  name: string;
  detail: string;
  kind: LiveFixture['kind'];
  first: number;
  count: number;
  /** Bounds in stage units (the click target and the label anchor). */
  x: number;
  y: number;
  w: number;
  h: number;
  /** Room map only: how this piece came to be where it is. */
  placedBy?: 'camera' | 'hand';
  /** Room map only: where it sits in the camera's picture (the seed for
   * moving it by hand). */
  placement?: { x: number; y: number; size: number; angle: number };
  note?: string;
}

/** A measured light, ready to tint: the cells of the glow picture it reaches
 * (sparse) and the plan points whose live colour it takes. */
export interface GlowEmitter {
  cells: Uint16Array;
  weights: Uint8Array;
  points: Uint32Array;
}

/** A picture drawn UNDER the points: a small grid the stage fills each drawn
 * frame with every emitter's footprint times its live colour, added up, over
 * a dim backdrop. `crop` is the part of the grid the plan shows (u0, v0, u1,
 * v1 in 0..1). */
export interface GlowLayer {
  w: number;
  h: number;
  backdrop: Uint8Array | null;
  emitters: GlowEmitter[];
  crop: [number, number, number, number];
}

/** A static colour override per point, independent of the streamed frame —
 * a HELD Hue fixture's real colour (see `LiveFixture.held`). `mask[p]` is
 * 1 where `rgb[p*3..p*3+3)` must win over whatever the stream says. */
export interface HeldOverlay {
  mask: Uint8Array;
  rgb: Uint8Array;
}

export interface StagePlan {
  width: number;
  height: number;
  pointCount: number;
  /** x, y per point, stage units. */
  xy: Float32Array;
  /** Dot diameter per point, stage units. */
  size: Float32Array;
  /** Stream cell per point, within its group's device. */
  src: Uint32Array;
  groups: StageGroup[];
  fixtures: StageFixture[];
  glow?: GlowLayer;
  held?: HeldOverlay;
}

export type PositionSource = (layout: LiveLayout, wide: boolean) => StagePlan;

const GAP = 7;
const LABEL_H = 7;
const MATRIX_H = 56;
const FRAME_W = 42;
const BULB = 4.2;
const BULB_STEP = 5.8;
const BULBS_PER_ROW = 9;
const KIND_ORDER: Record<LiveFixture['kind'], number> = {
  matrix: 0, frame: 1, strip: 2, bulbs: 3, dot: 4,
};

export interface Box {
  virtual: LiveVirtual;
  fixture: LiveFixture;
  w: number;
  h: number;
  /** Fills xy/size for this fixture's points at an origin. */
  place: (ox: number, oy: number, xy: Float32Array, size: Float32Array, first: number) => void;
}

function matrixBox(virtual: LiveVirtual, fixture: LiveFixture): Box {
  const { rows, cols } = virtual;
  const hex = virtual.hex_lattice;
  // A hex lattice lights every other column, alternating by row: two columns
  // are one cell pitch, and rows sit sqrt(3)/2 of a pitch apart.
  const unitW = hex ? (cols - 1) * 0.5 : cols - 1;
  const unitH = hex ? (rows - 1) * 0.8660254 : rows - 1;
  const pitch = Math.min(MATRIX_H / Math.max(unitH, 1), 72 / Math.max(unitW, 1));
  const dot = pitch * (hex ? 0.8 : 0.86);
  const grid = fixture.grid ?? [];
  return {
    virtual, fixture, w: unitW * pitch + dot, h: unitH * pitch + dot,
    place: (ox, oy, xy, size, first) => {
      for (let i = 0; i < fixture.count; i++) {
        const cell = grid[i] ?? i;
        const row = Math.floor(cell / cols);
        const col = cell - row * cols;
        xy[(first + i) * 2] = ox + dot / 2 + col * pitch * (hex ? 0.5 : 1);
        xy[(first + i) * 2 + 1] = oy + dot / 2 + row * pitch * (hex ? 0.8660254 : 1);
        size[first + i] = dot;
      }
    },
  };
}

function lineBox(virtual: LiveVirtual, fixture: LiveFixture): Box {
  const n = fixture.count;
  const vertical = fixture.orient === 'v';
  const length = Math.max(14, Math.min(vertical ? 30 : 60, n * 0.34));
  const step = n > 1 ? length / (n - 1) : 0;
  const dot = Math.max(1.5, Math.min(3, step * 1.7));
  return {
    virtual, fixture, w: vertical ? dot : length + dot, h: vertical ? length + dot : dot,
    place: (ox, oy, xy, size, first) => {
      for (let i = 0; i < n; i++) {
        xy[(first + i) * 2] = ox + dot / 2 + (vertical ? 0 : i * step);
        // a vertical strip is drawn bottom-up: pixel 0 at the floor end
        xy[(first + i) * 2 + 1] = oy + dot / 2 + (vertical ? (n - 1 - i) * step : 0);
        size[first + i] = dot;
      }
    },
  };
}

/** A strip run around a screen: pixel 0 at the bottom-left corner, going up
 * the left side and round clockwise. The true start corner is not stored
 * anywhere; this is the drawing's own convention. */
function frameBox(virtual: LiveVirtual, fixture: LiveFixture): Box {
  const n = fixture.count;
  const w = FRAME_W;
  const h = (FRAME_W * 9) / 16;
  const perimeter = 2 * (w + h);
  const dot = Math.max(1.4, Math.min(2.6, (perimeter / n) * 1.8));
  return {
    virtual, fixture, w: w + dot, h: h + dot,
    place: (ox, oy, xy, size, first) => {
      for (let i = 0; i < n; i++) {
        let d = (i / n) * perimeter;
        let x: number;
        let y: number;
        if (d < h) { x = 0; y = h - d; }
        else if ((d -= h) < w) { x = d; y = 0; }
        else if ((d -= w) < h) { x = w; y = d; }
        else { x = w - (d - h); y = h; }
        xy[(first + i) * 2] = ox + dot / 2 + x;
        xy[(first + i) * 2 + 1] = oy + dot / 2 + y;
        size[first + i] = dot;
      }
    },
  };
}

function bulbBox(virtual: LiveVirtual, fixture: LiveFixture): Box {
  const n = fixture.count;
  // even rows: ten bulbs are 5 + 5, never 9 + 1
  const rowCount = Math.ceil(n / BULBS_PER_ROW);
  const perRow = Math.ceil(n / rowCount);
  const dot = fixture.kind === 'dot' ? BULB * 0.9 : BULB;
  return {
    virtual, fixture,
    w: (perRow - 1) * BULB_STEP + dot, h: (rowCount - 1) * BULB_STEP + dot,
    place: (ox, oy, xy, size, first) => {
      for (let i = 0; i < n; i++) {
        xy[(first + i) * 2] = ox + dot / 2 + (i % perRow) * BULB_STEP;
        xy[(first + i) * 2 + 1] = oy + dot / 2 + Math.floor(i / perRow) * BULB_STEP;
        size[first + i] = dot;
      }
    },
  };
}

export function boxFor(virtual: LiveVirtual, fixture: LiveFixture): Box {
  if (fixture.kind === 'matrix') return matrixBox(virtual, fixture);
  if (fixture.kind === 'frame') return frameBox(virtual, fixture);
  if (fixture.kind === 'strip') return lineBox(virtual, fixture);
  return bulbBox(virtual, fixture);
}

export function detailFor(fixture: LiveFixture, virtual: LiveVirtual): string {
  const n = fixture.count;
  if (fixture.kind === 'matrix') {
    return `${n} cells${virtual.hex_lattice ? ', hex lattice' : `, ${virtual.cols} × ${virtual.rows}`}`;
  }
  if (fixture.kind === 'bulbs') return `${n} bulb${n === 1 ? '' : 's'}`;
  if (fixture.kind === 'dot') return `${n} pixel${n === 1 ? '' : 's'}`;
  return `${n} LEDs`;
}

interface Placed { box: Box; x: number; y: number }

/** Left to right, wrapping at `width`; each row's boxes sit on its baseline. */
function flow(boxes: Box[], width: number): { placed: Placed[]; height: number; width: number } {
  const placed: Placed[] = [];
  let x = 0;
  let y = 0;
  let rowH = 0;
  let rowStart = 0;
  let used = 0;
  const closeRow = () => {
    for (let i = rowStart; i < placed.length; i++) placed[i].y = y + rowH - placed[i].box.h;
    y += rowH + LABEL_H + GAP;
    rowStart = placed.length;
    x = 0;
    rowH = 0;
  };
  for (const box of boxes) {
    // a label needs room too: a fixture's slot is at least as wide as its
    // name (about 0.9 units a character at the sizes the stage is drawn)
    const slot = Math.max(box.w, Math.min(26, Math.max(13, box.fixture.name.length * 0.9)));
    if (x > 0 && x + slot > width) closeRow();
    placed.push({ box, x: x + (slot - box.w) / 2, y: 0 });
    x += slot + GAP;
    used = Math.max(used, x - GAP);
    rowH = Math.max(rowH, box.h);
  }
  if (placed.length > rowStart) closeRow();
  return { placed, height: Math.max(0, y - GAP), width: used };
}

export const layoutPositions: PositionSource = (layout, wide) => {
  const boxes: Box[] = [];
  for (const virtual of layout.virtuals) {
    for (const fixture of virtual.fixtures) boxes.push(boxFor(virtual, fixture));
  }
  boxes.sort((a, b) => KIND_ORDER[a.fixture.kind] - KIND_ORDER[b.fixture.kind]);
  const matrices = boxes.filter((b) => b.fixture.kind === 'matrix');
  const others = boxes.filter((b) => b.fixture.kind !== 'matrix');

  const placed: Placed[] = [];
  let width: number;
  let height: number;
  if (wide && matrices.length && others.length) {
    // Big grids down the left, everything else flowing beside them.
    const left = flow(matrices, Math.max(...matrices.map((b) => b.w)));
    const right = flow(others, 118);
    height = Math.max(left.height, right.height);
    const leftY = (height - left.height) / 2;
    const rightY = (height - right.height) / 2;
    const rightX = left.width + GAP * 2;
    left.placed.forEach((p) => placed.push({ ...p, y: p.y + leftY }));
    right.placed.forEach((p) => placed.push({ ...p, x: p.x + rightX, y: p.y + rightY }));
    width = rightX + right.width;
  } else {
    const all = flow(boxes, wide ? 150 : 62);
    all.placed.forEach((p) => placed.push(p));
    width = all.width;
    height = all.height;
  }

  // Points are stored grouped by stream device, so one frame fills one run.
  const byVirtual = new Map<string, Placed[]>();
  for (const p of placed) {
    const list = byVirtual.get(p.box.virtual.id) ?? [];
    list.push(p);
    byVirtual.set(p.box.virtual.id, list);
  }
  const pointCount = boxes.reduce((n, b) => n + b.fixture.count, 0);
  const plan: StagePlan = {
    width: Math.max(width, 1), height: Math.max(height, 1), pointCount,
    xy: new Float32Array(pointCount * 2), size: new Float32Array(pointCount),
    src: new Uint32Array(pointCount), groups: [], fixtures: [],
  };
  let next = 0;
  for (const virtual of layout.virtuals) {
    const members = byVirtual.get(virtual.id);
    if (!members) continue;
    const groupFirst = next;
    for (const { box, x, y } of members) {
      const { fixture } = box;
      box.place(x, y, plan.xy, plan.size, next);
      for (let i = 0; i < fixture.count; i++) plan.src[next + i] = fixture.src ? fixture.src[i] : i;
      plan.fixtures.push({
        key: `${virtual.id}/${fixture.device_id}`, deviceId: fixture.device_id,
        visId: virtual.id, name: fixture.name, detail: detailFor(fixture, virtual),
        kind: fixture.kind, first: next, count: fixture.count,
        x, y, w: box.w, h: box.h,
      });
      next += fixture.count;
    }
    plan.groups.push({ visId: virtual.id, first: groupFirst, count: next - groupFirst, cells: virtual.cells });
  }
  return plan;
};

function hexTriplet(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  return [parseInt(h.slice(0, 2), 16) || 0, parseInt(h.slice(2, 4), 16) || 0, parseInt(h.slice(4, 6), 16) || 0];
}

/** `plan` with every HELD fixture's points carrying a static colour
 * override instead of the streamed frame — a held Hue bulb's real colour
 * (see `LiveFixture.held`'s own docstring). A position source (this file,
 * roomMap.ts) builds the plan; this is a pure post-step over either one,
 * so neither has to know about Hue holds itself. A plan with nothing held
 * is returned unchanged — no allocation on the common, un-held path. */
export function withHeldOverlay<T extends StagePlan>(plan: T, layout: LiveLayout): T {
  const byKey = new Map<string, string>();
  for (const virtual of layout.virtuals) {
    for (const fixture of virtual.fixtures) {
      if (fixture.held) byKey.set(`${virtual.id}/${fixture.device_id}`, fixture.held);
    }
  }
  if (byKey.size === 0) return plan;
  const mask = new Uint8Array(plan.pointCount);
  const rgb = new Uint8Array(plan.pointCount * 3);
  for (const f of plan.fixtures) {
    // Keyed by (virtual, device) — NOT `f.key`, which the room map splits
    // into one key per PIECE of a fixture (one bulb placed at a time), so
    // several StageFixtures here can share one underlying device.
    const hex = byKey.get(`${f.visId}/${f.deviceId}`);
    if (!hex) continue;
    const [r, g, b] = hexTriplet(hex);
    for (let p = f.first; p < f.first + f.count; p++) {
      mask[p] = 1;
      rgb[p * 3] = r; rgb[p * 3 + 1] = g; rgb[p * 3 + 2] = b;
    }
  }
  return { ...plan, held: { mask, rgb } };
}
