/** THE DROP-SEQUENCE LAYER on the Timeline's audio-shape canvas
 * (drop-detection plan, phase 3 — built to plan.html's Timeline mock).
 * A click selects a sequence for the detail box; dragging a handle (or its
 * line) moves a GHOST of it (phase 4: the page's useDropSeqInteractions
 * keeps the ghost, the snap target and the add-a-drop preview in a ref this
 * layer reads every frame — ../dropEdit.ts), and one save goes out on
 * release.
 *
 * Three layers, because draw order and click priority pull different ways:
 *
 *   dropSeqRailBand (z 1)  the dark rail band across the top of the main
 *                          area, under everything — so the analysed scene
 *                          tabs and his legacy trigger triangles still sit
 *                          on top of it.
 *   dropSeqBody (z 45)     per sequence: the GOLD WEDGE (the charge's build,
 *                          rising for 90% of the way to its partner, then
 *                          holding), the BLUE BAND (the lull, its own rise
 *                          and its last-10% hang), the PINK FADE (the two
 *                          protected bars after the drop), the three member
 *                          lines and, for a handle he moved, the dotted
 *                          "where the analysis had it" line; the "not
 *                          captured" hatch before a mid-song capture; and
 *                          the SNAP RAILS in their own band under the main
 *                          area — bass spikes (taller = harder) over beats
 *                          (downbeats taller). Its click target, the member
 *                          lines, sits BELOW his legacy triggers (z 60), so
 *                          a line that coincides with one of his triggers
 *                          still drags that trigger.
 *   dropSeqRail (z 65)     the bracket, the three handles (ramp triangle,
 *                          pause bars, star), the state chip and the hover
 *                          label. Its click target, the handles, sits ABOVE
 *                          the legacy triggers but only in the rail band
 *                          below their ▼ triangles (y 9-30), so both stay
 *                          reachable.
 *
 * Everything it draws comes from ../dropSequences.ts (`buildDisplay`): the
 * looks, the builds (the engine's own ramp arithmetic) and the words. */
import type { CanvasFrame, CanvasLayer, DropSeqLayerData, Hit } from './frame';
import {
  HANDLES, LOOK_CHIP, LOOK_GLYPH, PHASE_COLOR, TAIL_BEATS, fmtHundredths, firstHandleMs,
  sequenceBuilds, type DisplaySeq, type Handle,
} from '../dropSequences';
import { editable, withGhost } from '../dropEdit';

/** The rail band at the top of the main area (mock: RAIL 30). */
export const RAIL_H = 30;
const HANDLE_Y = 17;
const RAIL_HIT_TOP = 9;          // below his legacy ▼ triangles (0-8 px)
const WEDGE_TOP = RAIL_H + 8;    // where a charge's build peaks
const LULL_TOP = RAIL_H + 26;    // where a lull's own rise peaks
const SPIKE_H = 18;              // the bass-spike rail; the beat rail is under it
const HANDLE_HIT_X = 11;
const LINE_HIT_X = 4;
const CHIP_H = 18;

const RGB: Record<Handle, string> = { charge: '251,191,36', lull: '56,189,248', drop: '236,72,153' };

const seqData = (f: CanvasFrame): DropSeqLayerData | null => f.data.dropSeq ?? null;

/** The sequences as drawn this frame: the ghost of the one being moved laid
 * over the saved list. */
const seqsOf = (d: DropSeqLayerData): DisplaySeq[] => withGhost(d.seqs, d.live?.current.ghost);

function dimOf(s: DisplaySeq): number {
  if (s.look === 'dismissed') return 0.22;
  if (s.fire === 'stands_down') return 0.45;
  if (s.look === 'suggested') return 0.6;
  return 1;
}

const dashOf = (s: DisplaySeq): number[] =>
  s.look === 'suggested' || s.fire === 'stands_down' ? [5, 4] : [];

function inView(f: CanvasFrame, s: DisplaySeq, beatMs: number): boolean {
  const a = firstHandleMs(s);
  const b = s.drop + TAIL_BEATS * beatMs;
  return b >= f.win.startMs && a <= f.win.endMs;
}

// ── z 1: the rail band ────────────────────────────────────────────────────

export const dropSeqRailBand: CanvasLayer = {
  id: 'dropSeqRailBand',
  z: 1,
  visible: (f) => !!seqData(f),
  draw(f) {
    const { ctx } = f;
    ctx.save();
    ctx.fillStyle = 'rgba(10,6,18,0.85)';
    ctx.fillRect(0, 0, f.w, RAIL_H - 4);
    ctx.restore();
  },
};

// ── z 45: the body ────────────────────────────────────────────────────────

function drawNotCaptured(f: CanvasFrame, d: DropSeqLayerData) {
  const from = d.capturedFromMs;
  if (from == null || from < 1000 || f.win.startMs >= from) return;
  const { ctx } = f;
  const x0 = Math.max(0, f.timeToX(Math.max(0, f.win.startMs)));
  const x1 = Math.min(f.w, f.timeToX(from));
  if (x1 <= x0) return;
  ctx.save();
  ctx.beginPath();
  ctx.rect(x0, RAIL_H, x1 - x0, f.mainH - RAIL_H);
  ctx.clip();
  ctx.fillStyle = 'rgba(0,0,0,0.35)';
  ctx.fillRect(x0, RAIL_H, x1 - x0, f.mainH - RAIL_H);
  ctx.strokeStyle = 'rgba(255,255,255,0.06)';
  ctx.lineWidth = 1;
  for (let x = x0 - f.mainH; x < x1; x += 9) {
    ctx.beginPath(); ctx.moveTo(x, f.mainH); ctx.lineTo(x + f.mainH, 0); ctx.stroke();
  }
  ctx.font = '600 10px system-ui, sans-serif';
  const long = `not captured · the recording starts at ${fmtHundredths(from)}`;
  const text = ctx.measureText(long).width + 12 <= x1 - x0 ? long : 'not captured';
  if (ctx.measureText(text).width + 12 <= x1 - x0) {
    ctx.fillStyle = 'rgba(255,255,255,0.55)';
    ctx.fillText(text, x0 + 6, RAIL_H + 14);
  }
  ctx.restore();
}

function drawRails(f: CanvasFrame, d: DropSeqLayerData) {
  const rails = d.rails;
  if (!rails || f.railH <= 0) return;
  const { ctx } = f;
  const top = f.mainH;
  ctx.save();
  ctx.fillStyle = 'rgba(255,255,255,0.03)';
  ctx.fillRect(0, top, f.w, f.railH);
  ctx.fillStyle = 'rgba(255,255,255,0.08)';
  ctx.fillRect(0, top, f.w, 1);
  // the snap target a dragged handle (or the add preview) is on lights up
  const live = d.live?.current;
  const hot = live?.guide ?? live?.addAt ?? null;
  const hotSpike = hot && hot.rail === 'spike' ? hot.ms : null;
  const hotBeat = hot && hot.rail === 'beat' ? hot.ms : null;
  for (const [ms, rise] of rails.spikes) {
    if (ms < f.win.startMs || ms > f.win.endMs) continue;
    const x = f.timeToX(ms);
    const r = Math.min(1, Math.max(0, rise));
    const h = 4 + 12 * r;
    if (ms === hotSpike) {
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(x - 1.5, top + 1, 3, SPIKE_H - 1);
      continue;
    }
    ctx.fillStyle = `rgba(68,221,136,${0.3 + 0.7 * r})`;
    ctx.fillRect(x - 1, top + SPIKE_H - h, 2, h);
  }
  for (const [ms, down] of rails.beats) {
    if (ms < f.win.startMs || ms > f.win.endMs) continue;
    const x = f.timeToX(ms);
    if (ms === hotBeat) {
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(x - 1, top + SPIKE_H + 1, 2, 14);
      continue;
    }
    ctx.fillStyle = down ? 'rgba(255,255,255,0.6)' : 'rgba(255,255,255,0.28)';
    ctx.fillRect(x - 0.5, top + SPIKE_H + (down ? 2 : 6), 1, down ? 12 : 8);
  }
  ctx.font = '9px ui-monospace, monospace';
  ctx.fillStyle = 'rgba(16,16,16,0.85)';
  ctx.fillRect(0, top + 1, 66, 11);
  ctx.fillRect(0, top + SPIKE_H + 2, 36, 11);
  ctx.fillStyle = 'rgba(255,255,255,0.6)';
  ctx.fillText('bass spikes', 4, top + 10);
  ctx.fillText('beats', 4, top + SPIKE_H + 11);
  ctx.restore();
}

function drawSequenceBody(f: CanvasFrame, d: DropSeqLayerData, s: DisplaySeq) {
  const { ctx } = f;
  const top = RAIL_H;
  const bot = f.mainH;
  const lineBot = bot + (f.railH > 0 ? SPIKE_H : 0);
  const X = (ms: number) => f.timeToX(ms);
  const dash = dashOf(s);
  const dismissed = s.look === 'dismissed';
  ctx.save();
  ctx.globalAlpha = dimOf(s);
  if (!dismissed) {
    const b = sequenceBuilds(s);
    if (b.charge) {
      const xc = X(b.charge.startMs);
      const re = X(b.charge.rampEndMs);
      const xe = X(b.charge.endMs);
      ctx.beginPath();
      ctx.moveTo(xc, bot); ctx.lineTo(re, WEDGE_TOP); ctx.lineTo(xe, WEDGE_TOP); ctx.lineTo(xe, bot);
      ctx.closePath();
      ctx.fillStyle = `rgba(${RGB.charge},0.13)`;
      ctx.fill();
      ctx.setLineDash(dash);
      ctx.strokeStyle = `rgba(${RGB.charge},0.85)`;
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(xc, bot); ctx.lineTo(re, WEDGE_TOP); ctx.lineTo(xe, WEDGE_TOP); ctx.stroke();
    }
    if (b.lull) {
      const xl = X(b.lull.startMs);
      const re = X(b.lull.rampEndMs);
      const xd = X(b.lull.endMs);
      ctx.fillStyle = `rgba(${RGB.lull},0.10)`;
      ctx.fillRect(xl, top, re - xl, bot - top);
      ctx.fillStyle = `rgba(${RGB.lull},0.05)`;
      ctx.fillRect(re, top, xd - re, bot - top);
      ctx.setLineDash(dash);
      ctx.strokeStyle = `rgba(${RGB.lull},0.85)`;
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(xl, bot); ctx.lineTo(re, LULL_TOP); ctx.lineTo(xd, LULL_TOP); ctx.stroke();
    }
    // the payoff tail: the two bars after the drop kept clear of scene changes
    const xd = X(s.drop);
    const tail = X(s.drop + TAIL_BEATS * d.beatMs);
    if (tail > xd) {
      const g = ctx.createLinearGradient(xd, 0, tail, 0);
      g.addColorStop(0, `rgba(${RGB.drop},0.28)`);
      g.addColorStop(1, `rgba(${RGB.drop},0)`);
      ctx.fillStyle = g;
      ctx.fillRect(xd, top, tail - xd, bot - top);
    }
  }
  for (const h of HANDLES) {
    const ms = s[h];
    if (ms == null) continue;
    const x = X(ms);
    ctx.setLineDash(dash);
    ctx.strokeStyle = dismissed ? '#888' : PHASE_COLOR[h];
    ctx.lineWidth = h === 'drop' ? 2.5 : 1.5;
    ctx.beginPath(); ctx.moveTo(x, top - 4); ctx.lineTo(x, lineBot); ctx.stroke();
  }
  ctx.setLineDash([]);
  if (!dismissed) {
    for (const h of HANDLES) {
      const had = s.analysisHad[h];
      if (had == null) continue;
      const x = X(had);
      ctx.setLineDash([2, 4]);
      ctx.strokeStyle = 'rgba(255,255,255,0.45)';
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bot); ctx.stroke();
      ctx.setLineDash([]);
      if (s[h] == null) {
        ctx.font = '9px ui-monospace, monospace';
        ctx.fillStyle = 'rgba(255,255,255,0.55)';
        ctx.fillText(`${h} off`, x + 3, bot - 4);
      }
    }
  }
  ctx.restore();
}

export const dropSeqBody: CanvasLayer = {
  id: 'dropSeqBody',
  z: 45,
  visible: (f) => !!seqData(f),
  draw(f) {
    const d = seqData(f)!;
    drawNotCaptured(f, d);
    drawRails(f, d);
    const seqs = seqsOf(d);
    for (const s of seqs) {
      if (inView(f, s, d.beatMs) && s.key !== d.selectedKey) drawSequenceBody(f, d, s);
    }
    const sel = seqs.find((s) => s.key === d.selectedKey);
    if (sel && inView(f, sel, d.beatMs)) drawSequenceBody(f, d, sel);
  },
  hitTest(x, y, f): Hit {
    const d = seqData(f);
    if (!d || d.adding || y < RAIL_H || y > f.mainH + (f.railH > 0 ? SPIKE_H : 0)) return null;
    let best: { key: string; handle: Handle; dist: number } | null = null;
    for (const s of seqsOf(d)) {
      for (const h of HANDLES) {
        const ms = s[h];
        if (ms == null || ms < f.win.startMs || ms > f.win.endMs) continue;
        const dist = Math.abs(f.timeToX(ms) - x) - (s.key === d.selectedKey ? 0.5 : 0);
        if (dist <= LINE_HIT_X && (!best || dist < best.dist)) best = { key: s.key, handle: h, dist };
      }
    }
    return best ? { kind: 'drop-seq', key: best.key, handle: best.handle } : null;
  },
  tooltipAt(x, y, f) {
    const d = seqData(f);
    if (!d) return null;
    const rails = d.rails;
    if (rails && f.railH > 0 && y >= f.mainH && y <= f.mainH + f.railH) {
      const t = f.xToTime(x);
      const tol = (3 / Math.max(1, f.w)) * (f.win.endMs - f.win.startMs);
      if (y <= f.mainH + SPIKE_H) {
        let best: [number, number] | null = null;
        for (const sp of rails.spikes) {
          if (Math.abs(sp[0] - t) <= tol && (!best || Math.abs(sp[0] - t) < Math.abs(best[0] - t))) best = sp;
        }
        if (best) return `bass spike · ${fmtHundredths(best[0])} · rise ${best[1].toFixed(2)} (taller = harder)`;
        return 'bass spikes: where a drop can land — taller means a harder hit';
      }
      let best: [number, number] | null = null;
      for (const b of rails.beats) {
        if (Math.abs(b[0] - t) <= tol && (!best || Math.abs(b[0] - t) < Math.abs(best[0] - t))) best = b;
      }
      if (best) return `${best[1] ? 'downbeat (first beat of a bar)' : 'beat'} · ${fmtHundredths(best[0])}`;
      return 'beats: taller ticks are the first beat of a bar';
    }
    const from = d.capturedFromMs;
    if (from != null && from >= 1000 && y >= RAIL_H && y <= f.mainH && f.xToTime(x) < from) {
      return `not captured: the recording of this song starts at ${fmtHundredths(from)}, so nothing before it can be analysed`;
    }
    return null;
  },
};

// ── z 65: the rail ────────────────────────────────────────────────────────

function star(ctx: CanvasRenderingContext2D, x: number, y: number, r: number, color: string) {
  ctx.beginPath();
  for (let i = 0; i < 16; i++) {
    const a = (Math.PI * i) / 8 - Math.PI / 2;
    const rr = i % 2 ? r * 0.45 : r;
    ctx.lineTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr);
  }
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
}

/** The three handle glyphs — the phase SHAPES (report section 9: a ramp for
 * the charge, pause bars for the lull, a star for the drop), so a phase
 * never has to be told from a flag by colour alone. Shared with the strip
 * and the review card's own swatches through PHASE_COLOR. */
export function drawHandle(
  ctx: CanvasRenderingContext2D, h: Handle, x: number, y: number, color: string,
) {
  if (h === 'charge') {
    ctx.beginPath(); ctx.moveTo(x - 7, y + 7); ctx.lineTo(x + 7, y + 7); ctx.lineTo(x + 7, y - 7);
    ctx.closePath(); ctx.fillStyle = color; ctx.fill();
  } else if (h === 'lull') {
    ctx.fillStyle = color;
    ctx.fillRect(x - 6, y - 7, 4.5, 14); ctx.fillRect(x + 1.5, y - 7, 4.5, 14);
  } else {
    star(ctx, x, y, 9, color);
  }
}

interface ChipBox { key: string; x: number; y: number; w: number; h: number }
/** The chips placed on the last frame drawn — a click on one selects its
 * sequence (hitTest has no canvas context to measure text with). */
let lastChips: ChipBox[] = [];

function chipStroke(s: DisplaySeq, selected: boolean): string {
  if (selected) return '#ffffff';
  if (s.look === 'suggested' || s.fire === 'stands_down') return 'rgba(255,255,255,0.35)';
  if (s.look === 'dismissed') return '#555';
  return PHASE_COLOR.drop;
}

function drawChip(ctx: CanvasRenderingContext2D, s: DisplaySeq, x: number, text: string,
                  w: number, selected: boolean) {
  const y = HANDLE_Y - CHIP_H / 2;
  ctx.save();
  ctx.fillStyle = 'rgba(10,6,18,0.86)';
  ctx.strokeStyle = chipStroke(s, selected);
  ctx.lineWidth = selected ? 1.5 : 1;
  if (s.look === 'suggested') ctx.setLineDash([3, 2]);
  ctx.beginPath();
  if (typeof ctx.roundRect === 'function') ctx.roundRect(x, y, w, CHIP_H, CHIP_H / 2);
  else ctx.rect(x, y, w, CHIP_H);
  ctx.fill(); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = s.look === 'dismissed' ? '#999' : '#f6eaff';
  ctx.font = '600 10.5px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(text, x + w / 2, y + 12.5);
  ctx.restore();
}

function drawRailFor(f: CanvasFrame, d: DropSeqLayerData, s: DisplaySeq, selected: boolean) {
  const { ctx } = f;
  const X = (ms: number) => f.timeToX(ms);
  const x0 = X(firstHandleMs(s));
  const xd = X(s.drop);
  const dim = dimOf(s);
  ctx.save();
  ctx.globalAlpha = dim;
  ctx.strokeStyle = selected ? 'rgba(255,255,255,0.7)' : 'rgba(255,255,255,0.3)';
  ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(x0, HANDLE_Y); ctx.lineTo(xd, HANDLE_Y); ctx.stroke();
  for (const h of HANDLES) {
    const ms = s[h];
    if (ms == null) continue;
    drawHandle(ctx, h, X(ms), HANDLE_Y, s.look === 'dismissed' ? '#888' : PHASE_COLOR[h]);
  }
  ctx.restore();
  const hover = d.hover && d.hover.key === s.key ? d.hover.handle : null;
  const selH: Handle = selected && d.selectedHandle && s[d.selectedHandle] != null ? d.selectedHandle : 'drop';
  ctx.save();
  if (selected) {
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(X(s[selH]!), HANDLE_Y, 12, 0, Math.PI * 2); ctx.stroke();
  }
  if (hover && s[hover] != null && !(selected && hover === selH)) {
    ctx.strokeStyle = 'rgba(255,255,255,0.7)';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(X(s[hover]!), HANDLE_Y, 11, 0, Math.PI * 2); ctx.stroke();
  }
  ctx.restore();
}

function drawHover(f: CanvasFrame, d: DropSeqLayerData) {
  const hv = d.hover;
  if (!hv || d.live?.current.ghost) return;
  const s = d.seqs.find((q) => q.key === hv.key);
  const ms = s?.[hv.handle];
  if (!s || ms == null) return;
  const { ctx } = f;
  const extra = s.look === 'mine' ? 'your trigger'
    : s.view?.score != null && hv.handle === 'drop' ? `${LOOK_CHIP[s.look]} · score ${s.view.score.toFixed(2)}`
    : LOOK_CHIP[s.look];
  const how = editable(s) ? 'drag to move · double-click for details' : 'click for details';
  const text = `${hv.handle} · ${fmtHundredths(ms)} · ${extra} · ${how}`;
  ctx.save();
  ctx.font = '11px system-ui, sans-serif';
  const tw = ctx.measureText(text).width;
  const x = Math.min(Math.max(2, f.timeToX(ms) + 8), f.w - tw - 10);
  ctx.fillStyle = 'rgba(0,0,0,0.85)';
  ctx.fillRect(x - 4, RAIL_H + 2, tw + 8, 16);
  ctx.fillStyle = '#ffffff';
  ctx.fillText(text, x, RAIL_H + 14);
  ctx.restore();
}

function label(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, w: number,
               bg = 'rgba(0,0,0,0.85)') {
  ctx.font = '600 10px system-ui, sans-serif';
  const tw = ctx.measureText(text).width + 10;
  const lx = Math.min(Math.max(2, x), w - tw - 2);
  ctx.fillStyle = bg;
  ctx.fillRect(lx, y, tw, 16);
  ctx.fillStyle = '#ffffff';
  ctx.fillText(text, lx + 5, y + 11.5);
}

/** While a handle is moving: what it snapped to, named, at the bottom of the
 * graph (mock: "snap: bass spike"). */
function drawGuide(f: CanvasFrame, d: DropSeqLayerData) {
  const g = d.live?.current.guide;
  if (!g) return;
  const { ctx } = f;
  ctx.save();
  label(ctx, `snap: ${g.what} · ${fmtHundredths(g.ms)}`, f.timeToX(g.ms) + 6, f.mainH - 22, f.w);
  ctx.restore();
}

/** "＋ Add a drop" armed: the instruction, and a dashed drop line where a
 * click would put it. */
function drawAdding(f: CanvasFrame, d: DropSeqLayerData) {
  if (!d.adding) return;
  const { ctx } = f;
  ctx.save();
  ctx.font = '600 11px system-ui, sans-serif';
  const text = 'click a bass spike (or anywhere) to add a drop there — it goes to the nearest bass spike · Esc cancels';
  const tw = ctx.measureText(text).width + 12;
  ctx.fillStyle = 'rgba(10,6,18,0.9)';
  ctx.fillRect(4, RAIL_H + 2, Math.min(tw, f.w - 8), 17);
  ctx.fillStyle = PHASE_COLOR.drop;
  ctx.fillText(text, 10, RAIL_H + 14);
  const at = d.live?.current.addAt;
  if (at && at.ms >= f.win.startMs && at.ms <= f.win.endMs) {
    const x = f.timeToX(at.ms);
    ctx.setLineDash([4, 3]);
    ctx.strokeStyle = PHASE_COLOR.drop;
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(x, 4); ctx.lineTo(x, f.mainH + (f.railH > 0 ? SPIKE_H : 0)); ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 0.7;
    drawHandle(ctx, 'drop', x, HANDLE_Y, PHASE_COLOR.drop);
    ctx.globalAlpha = 1;
    label(ctx, `add a drop: ${at.what} · ${fmtHundredths(at.ms)}`, x + 8, f.mainH - 22, f.w);
  }
  ctx.restore();
}

/** Where each visible sequence's chip goes: its words to the right of the
 * drop, else to the left of its first handle, else its one glyph — never
 * over a neighbour; the selected one always gets its words, drawn last. */
function layoutChips(f: CanvasFrame, d: DropSeqLayerData, visible: DisplaySeq[]): ChipBox[] {
  const { ctx } = f;
  ctx.save();
  ctx.font = '600 10.5px system-ui, sans-serif';
  const out: (ChipBox & { text: string; s: DisplaySeq })[] = [];
  let lastRight = -Infinity;
  visible.forEach((s, i) => {
    if (s.key === d.selectedKey) return;
    const x0 = f.timeToX(firstHandleMs(s));
    const xd = f.timeToX(s.drop);
    // a sequence whose drop is off the left edge (only its tail shows) or
    // whose first handle is off the right edge gets no chip: a chip pinned
    // to the edge would name a sequence the eye cannot find
    if (xd < 0 || x0 > f.w) return;
    const nextX0 = i + 1 < visible.length ? f.timeToX(firstHandleMs(visible[i + 1])) : f.w;
    const label = LOOK_CHIP[s.look];
    const tw = ctx.measureText(label).width + 12;
    const limit = Math.min(f.w - 2, nextX0 - 8);
    let placed: { x: number; w: number; text: string } | null = null;
    if (xd + 14 + tw <= limit && xd + 14 >= lastRight + 4) placed = { x: xd + 14, w: tw, text: label };
    else if (x0 - tw - 14 >= Math.max(2, lastRight + 4) && x0 - 14 <= f.w) placed = { x: x0 - tw - 14, w: tw, text: label };
    else if (xd + 12 + CHIP_H <= limit && xd + 12 >= lastRight + 2) {
      placed = { x: xd + 12, w: CHIP_H, text: LOOK_GLYPH[s.look] };
    }
    if (placed) {
      out.push({ key: s.key, x: placed.x, y: HANDLE_Y - CHIP_H / 2, w: placed.w, h: CHIP_H, text: placed.text, s });
      lastRight = placed.x + placed.w;
    }
  });
  ctx.restore();
  for (const c of out) drawChip(ctx, c.s, c.x, c.text, c.w, false);
  return out.map(({ key, x, y, w, h }) => ({ key, x, y, w, h }));
}

export const dropSeqRail: CanvasLayer = {
  id: 'dropSeqRail',
  z: 65,
  visible: (f) => !!seqData(f),
  draw(f) {
    const d = seqData(f)!;
    const { ctx } = f;
    const visible = seqsOf(d).filter((s) => inView(f, s, d.beatMs));
    for (const s of visible) if (s.key !== d.selectedKey) drawRailFor(f, d, s, false);
    const chips = layoutChips(f, d, visible);
    const sel = visible.find((s) => s.key === d.selectedKey);
    if (sel) {
      drawRailFor(f, d, sel, true);
      ctx.save();
      ctx.font = '600 10.5px system-ui, sans-serif';
      const label = LOOK_CHIP[sel.look];
      const tw = ctx.measureText(label).width + 12;
      ctx.restore();
      const xd = f.timeToX(sel.drop);
      const x0 = f.timeToX(firstHandleMs(sel));
      let cx = xd + 14;
      if (cx + tw > f.w - 2) cx = x0 - tw - 14;
      cx = Math.min(Math.max(2, cx), f.w - tw - 2);   // the selected one is always readable
      drawChip(ctx, sel, cx, label, tw, true);
      chips.push({ key: sel.key, x: cx, y: HANDLE_Y - CHIP_H / 2, w: tw, h: CHIP_H });
    }
    lastChips = chips;
    drawHover(f, d);
    drawGuide(f, d);
    drawAdding(f, d);
  },
  hitTest(x, y, f): Hit {
    const d = seqData(f);
    if (!d || d.adding || y < RAIL_HIT_TOP || y > RAIL_H) return null;
    for (let i = lastChips.length - 1; i >= 0; i--) {
      const c = lastChips[i];
      if (x >= c.x && x <= c.x + c.w && y >= c.y && y <= c.y + c.h) {
        return { kind: 'drop-seq', key: c.key, handle: 'drop', chip: true };
      }
    }
    let best: { key: string; handle: Handle; dist: number } | null = null;
    for (const s of seqsOf(d)) {
      for (const h of HANDLES) {
        const ms = s[h];
        if (ms == null || ms < f.win.startMs || ms > f.win.endMs) continue;
        const dist = Math.abs(f.timeToX(ms) - x) - (h === 'drop' ? 0.5 : 0);
        if (dist <= HANDLE_HIT_X && (!best || dist < best.dist)) best = { key: s.key, handle: h, dist };
      }
    }
    return best ? { kind: 'drop-seq', key: best.key, handle: best.handle } : null;
  },
};
