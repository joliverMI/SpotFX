/** The Live view's ROOM MAP: the second position table for the same renderer.
 *
 * `roomMapPositions` takes the layout (which fixture pixel is which stream
 * cell — positions.ts) and one camera pose's view from the server
 * (spectra/services/room_view.py — that file is the binding statement for
 * what the data means) and returns a StagePlan in which every fixture pixel
 * sits where that camera saw its light.
 *
 * THE STAGE IS THE CAMERA'S PICTURE, 160 x 90 stage units for its 16:9
 * frame. Every position is a place in that picture and nothing else: not a
 * room coordinate and not where an LED hangs.
 *
 * Who decides where a piece (a run of one fixture's pixels) is drawn, first
 * that answers:
 *   his hand      a placement he made and saved for this pose
 *   per pixel     positions a camera read gave for each pixel (`xy`)
 *   a footprint   the centre of the piece's measured light (`at`)
 *   nobody        the piece goes to the "not placed" tray
 *
 * HOW A PIECE IS DRAWN AT ITS PLACE is this file's own convention, not a
 * measurement. A whole fixture keeps the shape the Layout view gives it (the
 * crystal's real lattice, a frame, a line), fitted to the size of its light.
 * A part of a strip the camera measured as one block is a small round
 * cluster — the camera saw where the block's light is, not which way the
 * strip runs. A piece he places by hand is that part of the fixture's own
 * shape, which he can turn.
 *
 * EVERY PIXEL IS IN THE PLAN, placed or not: an unplaced one has size 0 (it
 * is not drawn) but still carries its colour, because the glow of a measured
 * emitter is tinted by ALL the pixels that emitter lit. */
import { boxFor, detailFor } from './positions';
import type {
  GlowEmitter, GlowLayer, LiveFixture, LiveLayout, StageFixture, StagePlan,
} from './positions';

export interface RoomPlacement { x: number; y: number; size: number; angle: number }

export interface RoomPiece {
  key: string;
  virtual_id: string;
  device_id: string;
  first: number;
  count: number;
  label: string;
  /** "footprint", "unseen", "unmapped", or the name of a per-pixel source. */
  source: string;
  emitter: number | null;
  /** Centre and radius (share of the picture's width) of its measured light. */
  at: { x: number; y: number; r: number } | null;
  /** x, y per pixel, 0..1 of the picture. */
  xy: number[] | null;
  cluster: boolean;
  note: string;
}

export interface RoomEmitter {
  id: string;
  label: string;
  room: string;
  weight: number;
  centre: [number, number];
  /** base64 of grid.w x grid.h bytes. */
  glow: string;
  pixels: { virtual_id: string; device_id: string; first: number; count: number }[];
}

export interface RoomView {
  pose_id: string;
  label: string;
  rooms: { id: string; name: string }[];
  captured_at: number;
  grid: { w: number; h: number };
  aspect: number;
  backdrop: string | null;
  emitters: RoomEmitter[];
  pieces: RoomPiece[];
  hand: Record<string, RoomPlacement>;
  notes: string[];
  layout_source: string;
}

export interface RoomPose {
  pose_id: string;
  label: string;
  rooms: { id: string; name: string }[];
  mapped: number;
  unseen: number;
  decodes: number;
  captured_at: number;
}

/** A piece nobody has placed. */
export interface TrayPiece {
  key: string;
  label: string;
  fixtureKey: string;
  fixtureName: string;
  source: string;
  note: string;
  count: number;
  /** The size a first hand placement starts at. */
  defaultSize: number;
}

export interface RoomPlan extends StagePlan {
  tray: TrayPiece[];
  /** The part of the picture the plan shows, in stage units of the whole. */
  frame: { x: number; y: number; w: number; h: number };
  counts: { camera: number; hand: number; tray: number };
}

/** The view's pictures, decoded once per fetched view (not per plan). */
export interface DecodedRoomView {
  backdrop: Uint8Array | null;
  emitters: { cells: Uint16Array; weights: Uint8Array }[];
}

export const STAGE_W = 160;
export const STAGE_H = 90;
const OFF = -1000;
const MIN_DOT = 0.42;
const MAX_DOT = 3.4;
const SINGLE_DOT = 4.4;
const MIN_HIT = 3.2;
const GOLDEN = 2.399963;
const HAND_BASE: Record<LiveFixture['kind'], number> = {
  matrix: 0.16, frame: 0.3, strip: 0.2, bulbs: 0.2, dot: 0.06,
};
const SINGLE_SIZE = 0.026;

function bytes(b64: string): Uint8Array {
  const raw = atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export function decodeRoomView(view: RoomView): DecodedRoomView {
  const cellCount = view.grid.w * view.grid.h;
  const emitters = view.emitters.map((e) => {
    const full = bytes(e.glow);
    let n = 0;
    for (let i = 0; i < full.length && i < cellCount; i++) if (full[i]) n++;
    const cells = new Uint16Array(n);
    const weights = new Uint8Array(n);
    for (let i = 0, k = 0; i < full.length && i < cellCount; i++) {
      if (full[i]) { cells[k] = i; weights[k++] = full[i]; }
    }
    return { cells, weights };
  });
  const backdrop = view.backdrop ? bytes(view.backdrop) : null;
  return { backdrop: backdrop && backdrop.length === cellCount ? backdrop : null, emitters };
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** The size a hand placement of this piece starts at (share of the width). */
export function defaultHandSize(fixture: LiveFixture, count: number): number {
  if (count === 1) return SINGLE_SIZE;
  return clamp(HAND_BASE[fixture.kind] * (count / fixture.count), 0.04, 0.4);
}

interface Local { xy: Float32Array; size: Float32Array }

/** Part [first, first + count) of a fixture's own shape, moved so its middle
 * is at (cx, cy), scaled so its longer side is `extent`, turned `angle`. */
function placeSlice(local: Local, first: number, count: number, cx: number, cy: number,
                    extent: number, angle: number, xy: Float32Array, size: Float32Array,
                    base: number) {
  if (count === 1) {
    xy[base * 2] = cx;
    xy[base * 2 + 1] = cy;
    size[base] = clamp(extent, MIN_DOT, 12);
    return;
  }
  let x0 = Infinity; let x1 = -Infinity; let y0 = Infinity; let y1 = -Infinity;
  for (let i = first; i < first + count; i++) {
    const x = local.xy[i * 2]; const y = local.xy[i * 2 + 1];
    if (x < x0) x0 = x;
    if (x > x1) x1 = x;
    if (y < y0) y0 = y;
    if (y > y1) y1 = y;
  }
  const dot = local.size[first];
  const scale = extent / Math.max(Math.max(x1 - x0, y1 - y0) + dot, 1e-6);
  const mx = (x0 + x1) / 2; const my = (y0 + y1) / 2;
  const cos = Math.cos((angle * Math.PI) / 180); const sin = Math.sin((angle * Math.PI) / 180);
  for (let i = 0; i < count; i++) {
    const lx = (local.xy[(first + i) * 2] - mx) * scale;
    const ly = (local.xy[(first + i) * 2 + 1] - my) * scale;
    xy[(base + i) * 2] = cx + lx * cos - ly * sin;
    xy[(base + i) * 2 + 1] = cy + lx * sin + ly * cos;
    size[base + i] = clamp(local.size[first + i] * scale, MIN_DOT, MAX_DOT);
  }
}

/** A round cluster: `count` dots packed evenly in a disc. */
function placeCluster(count: number, cx: number, cy: number, radius: number,
                      xy: Float32Array, size: Float32Array, base: number) {
  const dot = clamp((radius * 1.5) / Math.sqrt(count), MIN_DOT, 1.7);
  for (let i = 0; i < count; i++) {
    const r = radius * Math.sqrt((i + 0.5) / count);
    xy[(base + i) * 2] = cx + r * Math.cos(i * GOLDEN);
    xy[(base + i) * 2 + 1] = cy + r * Math.sin(i * GOLDEN);
    size[base + i] = dot;
  }
}

function placeExact(piece: RoomPiece, xy: Float32Array, size: Float32Array, base: number) {
  const src = piece.xy!;
  let gaps = 0;
  for (let i = 0; i < piece.count; i++) {
    const x = src[i * 2] * STAGE_W; const y = src[i * 2 + 1] * STAGE_H;
    xy[(base + i) * 2] = x;
    xy[(base + i) * 2 + 1] = y;
    if (i) gaps += Math.hypot(x - xy[(base + i - 1) * 2], y - xy[(base + i - 1) * 2 + 1]);
  }
  const dot = piece.count > 1 ? clamp((gaps / (piece.count - 1)) * 0.9, MIN_DOT, 2.4) : SINGLE_DOT;
  size.fill(dot, base, base + piece.count);
}

const SOURCE_DETAIL: Record<string, string> = {
  footprint: 'at the centre of its measured light',
  decode: 'each pixel where the camera read it',
};

export function roomMapPositions(
  layout: LiveLayout, view: RoomView, decoded: DecodedRoomView,
  hand: Record<string, RoomPlacement>,
  /** `frame` pins the part of the picture shown (while a piece is being
   * dragged, so the picture does not slide under the pointer). */
  options: { fit: boolean; frame?: { x: number; y: number; w: number; h: number } },
): RoomPlan {
  const pointCount = layout.virtuals.reduce(
    (n, v) => n + v.fixtures.reduce((m, f) => m + f.count, 0), 0);
  const xy = new Float32Array(pointCount * 2).fill(OFF);
  const size = new Float32Array(pointCount);
  const src = new Uint32Array(pointCount);
  const groups: StagePlan['groups'] = [];
  const fixtures: StageFixture[] = [];
  const tray: TrayPiece[] = [];
  const counts = { camera: 0, hand: 0, tray: 0 };

  const byFixture = new Map<string, RoomPiece[]>();
  for (const piece of view.pieces) {
    const key = `${piece.virtual_id}/${piece.device_id}`;
    const list = byFixture.get(key);
    if (list) list.push(piece);
    else byFixture.set(key, [piece]);
  }

  const baseOf = new Map<string, number>();
  let next = 0;
  for (const virtual of layout.virtuals) {
    const groupFirst = next;
    for (const fixture of virtual.fixtures) {
      const fixtureKey = `${virtual.id}/${fixture.device_id}`;
      const base = next;
      baseOf.set(fixtureKey, base);
      for (let i = 0; i < fixture.count; i++) src[base + i] = fixture.src ? fixture.src[i] : i;
      next += fixture.count;

      let local: Local | null = null;
      const shape = (): Local => {
        if (!local) {
          local = { xy: new Float32Array(fixture.count * 2), size: new Float32Array(fixture.count) };
          boxFor(virtual, fixture).place(0, 0, local.xy, local.size, 0);
        }
        return local;
      };
      for (const piece of byFixture.get(fixtureKey) ?? []) {
        if (piece.first < 0 || piece.first + piece.count > fixture.count) continue;
        const at = base + piece.first;
        const mine = hand[piece.key];
        let placement: RoomPlacement | null = null;
        if (mine) {
          placeSlice(shape(), piece.first, piece.count, mine.x * STAGE_W, mine.y * STAGE_H,
            mine.size * STAGE_W, mine.angle, xy, size, at);
          placement = mine;
        } else if (piece.xy && piece.xy.length === piece.count * 2) {
          placeExact(piece, xy, size, at);
        } else if (piece.at) {
          const cx = piece.at.x * STAGE_W; const cy = piece.at.y * STAGE_H;
          const radius = piece.at.r * STAGE_W;
          if (piece.count === 1) {
            placeSlice(shape(), piece.first, 1, cx, cy, Math.min(radius * 2, SINGLE_DOT), 0, xy, size, at);
          } else if (piece.cluster) {
            placeCluster(piece.count, cx, cy, radius, xy, size, at);
          } else {
            placeSlice(shape(), piece.first, piece.count, cx, cy, radius * 2, 0, xy, size, at);
          }
          placement = { x: piece.at.x, y: piece.at.y, size: piece.count === 1 ? SINGLE_SIZE : piece.at.r * 2, angle: 0 };
        } else {
          tray.push({
            key: piece.key, label: piece.label, fixtureKey, fixtureName: fixture.name,
            source: piece.source, note: piece.note, count: piece.count,
            defaultSize: defaultHandSize(fixture, piece.count),
          });
          counts.tray++;
          continue;
        }
        if (mine) counts.hand++;
        else counts.camera++;
        let x0 = Infinity; let x1 = -Infinity; let y0 = Infinity; let y1 = -Infinity;
        for (let i = at; i < at + piece.count; i++) {
          const r = size[i] / 2;
          x0 = Math.min(x0, xy[i * 2] - r);
          x1 = Math.max(x1, xy[i * 2] + r);
          y0 = Math.min(y0, xy[i * 2 + 1] - r);
          y1 = Math.max(y1, xy[i * 2 + 1] + r);
        }
        if (!placement) {
          placement = {
            x: (x0 + x1) / 2 / STAGE_W, y: (y0 + y1) / 2 / STAGE_H,
            size: Math.max(x1 - x0, y1 - y0) / STAGE_W, angle: 0,
          };
        }
        const w = Math.max(x1 - x0, MIN_HIT); const h = Math.max(y1 - y0, MIN_HIT);
        const whole = piece.count === fixture.count;
        const how = mine ? 'placed by hand' : (SOURCE_DETAIL[piece.source] ?? `placed by ${piece.source}`);
        fixtures.push({
          key: piece.key, deviceId: fixture.device_id, visId: virtual.id, name: piece.label,
          detail: `${whole ? detailFor(fixture, virtual) : `${piece.count} ${fixture.kind === 'bulbs' ? 'lamp' : 'LED'}${piece.count === 1 ? '' : 's'}`} · ${how}`,
          kind: fixture.kind, first: at, count: piece.count,
          x: (x0 + x1) / 2 - w / 2, y: (y0 + y1) / 2 - h / 2, w, h,
          placedBy: mine ? 'hand' : 'camera', placement, note: piece.note,
        });
      }
    }
    if (next > groupFirst) {
      groups.push({ visId: virtual.id, first: groupFirst, count: next - groupFirst, cells: virtual.cells });
    }
  }

  // The part of the picture to show: everything, or the lights and a margin.
  const frame = { x: 0, y: 0, w: STAGE_W, h: STAGE_H };
  if (options.frame) {
    Object.assign(frame, options.frame);
  } else if (options.fit && (fixtures.length || view.emitters.length)) {
    let x0 = Infinity; let x1 = -Infinity; let y0 = Infinity; let y1 = -Infinity;
    for (const f of fixtures) {
      x0 = Math.min(x0, f.x); x1 = Math.max(x1, f.x + f.w);
      y0 = Math.min(y0, f.y); y1 = Math.max(y1, f.y + f.h);
    }
    for (const e of view.emitters) {
      x0 = Math.min(x0, e.centre[0] * STAGE_W - 4); x1 = Math.max(x1, e.centre[0] * STAGE_W + 4);
      y0 = Math.min(y0, e.centre[1] * STAGE_H - 4); y1 = Math.max(y1, e.centre[1] * STAGE_H + 4);
    }
    const w = Math.min(STAGE_W, Math.max((x1 - x0) * 1.3, ((y1 - y0) * 1.3 * STAGE_W) / STAGE_H, STAGE_W * 0.3));
    const h = (w * STAGE_H) / STAGE_W;
    frame.w = w;
    frame.h = h;
    frame.x = clamp((x0 + x1) / 2 - w / 2, 0, STAGE_W - w);
    frame.y = clamp((y0 + y1) / 2 - h / 2, 0, STAGE_H - h);
  }
  if (frame.x || frame.y) {
    for (let i = 0; i < pointCount; i++) {
      if (size[i] > 0) {
        xy[i * 2] -= frame.x;
        xy[i * 2 + 1] -= frame.y;
      }
    }
    for (const f of fixtures) { f.x -= frame.x; f.y -= frame.y; }
  }

  const emitters: GlowEmitter[] = view.emitters.map((e, index) => {
    let n = 0;
    for (const run of e.pixels) n += run.count;
    const points = new Uint32Array(n);
    let k = 0;
    for (const run of e.pixels) {
      const base = baseOf.get(`${run.virtual_id}/${run.device_id}`);
      if (base === undefined) continue;
      for (let i = 0; i < run.count; i++) {
        const p = base + run.first + i;
        if (p < pointCount) points[k++] = p;
      }
    }
    const pictures = decoded.emitters[index];
    return {
      cells: pictures?.cells ?? new Uint16Array(0), weights: pictures?.weights ?? new Uint8Array(0),
      points: k === n ? points : points.subarray(0, k),
    };
  });
  const glow: GlowLayer = {
    w: view.grid.w, h: view.grid.h, backdrop: decoded.backdrop, emitters,
    crop: [frame.x / STAGE_W, frame.y / STAGE_H,
      (frame.x + frame.w) / STAGE_W, (frame.y + frame.h) / STAGE_H],
  };

  return {
    width: frame.w, height: frame.h, pointCount, xy, size, src, groups, fixtures, glow,
    tray, frame, counts,
  };
}
