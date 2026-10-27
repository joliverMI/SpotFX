/** THE HOME DROPS PANEL, the pure half (predrop plan step 1 —
 * /home/javi/fleet-spotfx/data/predrop-plan/report.md section 3.6; the
 * Admiral: "tap the double checkmark button to approve the lull, charge,
 * drop, and predrop. Or, an icon for each individual one, to toggle them.
 * Or a button to remove it completely. All on the horizontal bar, just
 * toggle buttons, essentially"). What ./HomeDrops.tsx draws is decided
 * here, DOM-free, so scripts/check_home_drops_panel.mjs drives it directly.
 *
 * THE ROWS. One per drop of the song Home is showing, in time order: every
 * detection and every drop he added (not dismissed), and every drop of HIS
 * OWN (the view's `yours`, enabled or switched off). A detection standing
 * in for one of his drops is not listed twice — his row stands for both,
 * the Timeline's own rule (dropSequences.ts `buildDisplay`).
 *
 * EACH PART'S LOOK is the server's (drop_sequences.py's PARTS): on
 * (approved — it plays with its drop), waiting (it follows its tier), off
 * (never plays, not even in Testing), absent (no such part). His own rows'
 * parts are his triggers: on while enabled, off when switched off. A tap
 * goes waiting → on, on → off, off → on (`nextPartState`).
 *
 * WHAT PLAYS is the server's answer (drop_firing.annotate's `fires`), never
 * re-derived here. His own row plays when his drop is on and either his
 * triggers fire in this mode or a detection standing in for it does.
 *
 * TESTING (RoomControlState.drop_testing): while it is on, the drop that
 * just played is moved to the top and highlighted (`justPlayed`) — for a
 * quick tap — until the next one plays.
 *
 * THE PRE-DROP (predrop plan step 4) is the fourth part: its button wears
 * its KIND's glyph (a spike, or a vocal intro) in the pre-drop's orange and
 * the same four looks; its state comes from the server (`parts.pre_drop`,
 * or a row of his own's `pre_drop.part` — the pre-drop of his own drop is
 * stored in the drop store, never his song profile, so its tap asks
 * nothing first). A waiting pre-drop is something waiting for him: it
 * counts in the title and lights the double tick, his own rows included.
 * Nothing plays from a pre-drop yet; its words say so. The in-place
 * editor's pre-drop handle snaps to the rail of its kind — a spike to the
 * hits (`DropRails.hits`), a vocal intro to the entries — and stays inside
 * its kind's lead range (`snapPreDrop` / `stepPreDrop` / `clampPreDrop`). */
import type {
  DropSequencesResponse, DropSequenceView, PartKey, PartView, PreDropKind, YoursRow,
} from '../timeline/dropSequences';
import { PARTS, PHASE_COLOR, PRE_DROP_COLOR } from '../timeline/dropSequences';
import type { LastDrop } from '../types';

export type RowKind = 'detected' | 'added' | 'yours';

/** His song-profile provenance for one trigger (GET
 * /drop-sequences/provenance → the root process's rule). */
export interface TriggerProvenance {
  id: string;
  imported: boolean;
  /** by_hand | analysed_import_id | embedded_import | ai_generated | spectra_card */
  why: string;
  remove_would: 'delete' | 'disable';
}

export interface ProvenanceResponse {
  uri: string;
  imported_profile: boolean | null;
  triggers: TriggerProvenance[];
  status?: 'unknown' | 'no_profile';
}

export interface PanelRow {
  key: string;
  kind: RowKind;
  dropMs: number;
  chargeMs: number | null;
  lullMs: number | null;
  parts: Record<PartKey, PartView>;
  /** it plays on this song under the room's setting now */
  plays: boolean;
  stateLine: string;
  /** something on it is still waiting for him */
  waiting: boolean;
  /** listed but silent: a drop he switched off */
  switchedOff: boolean;
  /** the double tick would change something */
  canApprove: boolean;
  /** Testing is on and this drop is the one that just played */
  justPlayed: boolean;
  /** THE PRE-DROP: where it plays (null when none or switched off), its
   * kind (kept while off, for its glyph), where an off one comes back,
   * where the detector (or, on his own drop, the rules) put it, and
   * whether he placed it himself */
  preDropMs: number | null;
  preDropKind: PreDropKind | null;
  preDropWas: number | null;
  preDropAuto: number | null;
  preDropMoved: boolean;
  view: DropSequenceView | null;
  yours: YoursRow | null;
}

export const PART_LABEL: Record<PartKey, string> = {
  charge: 'Charge', lull: 'Lull', pre_drop: 'Pre-drop', drop: 'Drop',
};

/** The colours are the Timeline's own (dropSequences.ts PHASE_COLOR and
 * PRE_DROP_COLOR, read, never re-typed). */
export const PART_COLOR: Record<PartKey, string> = { ...PHASE_COLOR, pre_drop: PRE_DROP_COLOR };

/** A pre-drop's kind, in words. */
export const PRE_DROP_KIND_WORD: Record<PreDropKind, string> = {
  spike: 'a spike', intro: 'a vocal intro',
};

/** What a pre-drop's tooltip adds while no pre-drop plays in the room yet
 * (drop_firing.PRE_DROPS_PLAY: the engine that plays them is a later step). */
export const PRE_DROPS_DO_NOT_PLAY = 'pre-drops do not play in the room yet';

/** What a tap on a part does: waiting → on, on → off, off → on. */
export function nextPartState(s: PartView): 'on' | 'off' | null {
  if (s === 'waiting' || s === 'off') return 'on';
  if (s === 'on') return 'off';
  return null;
}

/** A part button's words: its tooltip, and its aria-label. */
export function partTitle(row: Pick<PanelRow, 'kind'> & Partial<Pick<PanelRow, 'preDropKind'>>,
  part: PartKey, state: PartView, provenance?: TriggerProvenance | null): string {
  const name = PART_LABEL[part];
  if (part === 'pre_drop') {
    // the pre-drop is never one of his triggers, his own drops included
    if (state === 'absent') return 'No pre-drop on this drop — add one in its editor (the pencil)';
    const named = row.preDropKind ? `${name} (${PRE_DROP_KIND_WORD[row.preDropKind]})` : name;
    if (state === 'on') return `${named}: approved — tap to switch it off; ${PRE_DROPS_DO_NOT_PLAY}`;
    if (state === 'off') return `${named}: off, never plays — tap to switch it back on; ${PRE_DROPS_DO_NOT_PLAY}`;
    return `${named}: waiting for you — tap to approve it; ${PRE_DROPS_DO_NOT_PLAY}`;
  }
  if (state === 'absent') return `No ${name.toLowerCase()} on this drop`;
  if (row.kind === 'yours') {
    if (state === 'off') return `${name}: your trigger is switched off — tap to switch it back on`;
    const how = provenance?.remove_would === 'delete'
      ? 'tap to delete it (you placed it by hand)'
      : provenance?.remove_would === 'disable'
        ? 'tap to switch it off (imported, so it stays in your song)'
        : 'tap to take it out';
    return `${name}: your trigger — ${how}`;
  }
  if (state === 'on') return `${name}: approved — tap to switch it off`;
  if (state === 'off') return `${name}: off, never plays — tap to switch it back on`;
  return `${name}: waiting for you — tap to approve it`;
}

function partsOfView(v: DropSequenceView): Record<PartKey, PartView> {
  const out = {} as Record<PartKey, PartView>;
  const p = v.parts ?? {};
  for (const k of PARTS) {
    // an older server sends no parts: read the legacy shape (his = on)
    out[k] = p[k] ?? (k === 'pre_drop' ? 'absent'
      : (k === 'drop' ? (['confirmed', 'edited', 'added'].includes(v.state) ? 'on' : 'waiting')
        : (v[`${k}_ms` as 'charge_ms' | 'lull_ms'] == null ? (v[`${k}_off` as 'charge_off' | 'lull_off'] ? 'off' : 'absent')
          : (['confirmed', 'edited', 'added'].includes(v.state) ? 'on' : 'waiting'))));
  }
  return out;
}

function partsOfYours(r: YoursRow): Record<PartKey, PartView> {
  const m = (x: YoursRow['charge']): PartView => (x == null ? 'absent' : x.enabled ? 'on' : 'off');
  // his pre-drop's state is the drop store's (YoursRow.pre_drop.part);
  // none, or not worked out yet, is absent
  return { charge: m(r.charge), lull: m(r.lull), pre_drop: r.pre_drop?.part ?? 'absent',
    drop: m(r.drop) };
}

/** The state line's pre-drop clause: its kind, or that it is off. */
function preDropClause(part: PartView, kind: PreDropKind | null): string {
  if (part === 'absent' || !kind) return '';
  if (part === 'off') return ' · pre-drop off';
  return kind === 'intro' ? ' · vocal-intro pre-drop' : ' · spike pre-drop';
}

const PRESENT = (s: PartView) => s !== 'absent';

function viewStateLine(v: DropSequenceView, parts: Record<PartKey, PartView>, testing: boolean): string {
  if (parts.drop === 'off') return 'switched off · never plays';
  if (v.origin === 'added') return 'added by you';
  const present = PARTS.filter((k) => PRESENT(parts[k]));
  const on = present.filter((k) => parts[k] === 'on');
  const waiting = present.filter((k) => parts[k] === 'waiting');
  if (waiting.length === 0) return 'approved';
  if (on.length > 0) return 'partly approved';
  if (v.state === 'matches_yours') return 'on your own trigger';
  if (v.tier === 'confident') return 'detected · plays on its own';
  return testing ? 'suggested · playing while testing' : 'suggested · waits for you';
}

function yoursStateLine(r: YoursRow, prov: Map<string, TriggerProvenance> | null): string {
  if (!r.enabled) return 'yours · switched off';
  if (!prov) return 'yours';
  const ids = [r.charge, r.lull, r.drop].filter((m) => m && m.enabled).map((m) => m!.id);
  const ways = new Set(ids.map((id) => prov.get(id)?.remove_would).filter(Boolean));
  if (ways.size === 1) return ways.has('delete') ? 'yours · placed by hand' : 'yours · imported';
  if (ways.size > 1) return 'yours · placed by hand and imported';
  return 'yours';
}

export interface BuildPanelOptions {
  testing: boolean;
  lastDrop?: LastDrop | null;
  provenance?: ProvenanceResponse | null;
}

/** Every row the card lists, in the order it lists them. */
export function buildPanelRows(resp: DropSequencesResponse | null | undefined,
  opts: BuildPanelOptions): PanelRow[] {
  if (!resp) return [];
  const testing = !!opts.testing;
  const prov = opts.provenance && opts.provenance.triggers?.length
    ? new Map(opts.provenance.triggers.map((t) => [t.id, t])) : null;
  const views = resp.sequences ?? [];
  const byKey = new Map(views.map((v) => [v.key, v]));
  const rows: PanelRow[] = [];
  const claimed = new Set<string>();
  const hisApplies = !!resp.firing?.his_applies;

  for (const r of resp.yours ?? []) {
    for (const k of r.detections ?? []) claimed.add(k);
    const parts = partsOfYours(r);
    const standIns = (r.detections ?? []).map((k) => byKey.get(k)).filter(Boolean) as DropSequenceView[];
    const plays = r.enabled && (hisApplies || standIns.some((v) => v.fires === true));
    const pre = r.pre_drop ?? null;
    // a waiting pre-drop is the one thing on his own drop that waits for him
    const preWaiting = r.enabled && parts.pre_drop === 'waiting';
    rows.push({
      key: r.key, kind: 'yours', dropMs: r.drop.timestamp_ms,
      chargeMs: r.charge?.timestamp_ms ?? null, lullMs: r.lull?.timestamp_ms ?? null,
      parts, plays,
      stateLine: yoursStateLine(r, prov) + preDropClause(parts.pre_drop, pre?.kind ?? null),
      waiting: preWaiting, switchedOff: !r.enabled, canApprove: preWaiting, justPlayed: false,
      preDropMs: pre?.ms ?? null, preDropKind: pre?.kind ?? null,
      preDropWas: pre?.off ? (pre.was ?? null) : null, preDropAuto: pre?.auto ?? null,
      preDropMoved: !!pre?.moved, view: standIns[0] ?? null, yours: r,
    });
  }
  for (const v of views) {
    if (v.state === 'dismissed' || claimed.has(v.key)) continue;
    const parts = partsOfView(v);
    const kind: RowKind = v.origin === 'added' ? 'added' : 'detected';
    const waitingParts = PARTS.filter((k) => parts[k] === 'waiting');
    const switchedOff = parts.drop === 'off';
    rows.push({
      key: v.key, kind, dropMs: v.drop_ms, chargeMs: v.charge_ms, lullMs: v.lull_ms,
      parts, plays: v.fires === true,
      stateLine: viewStateLine(v, parts, testing)
        + preDropClause(parts.pre_drop, v.pre_drop_kind ?? null),
      waiting: kind === 'detected' && !switchedOff && waitingParts.length > 0
        && v.state !== 'matches_yours',
      switchedOff, canApprove: kind === 'detected' && !switchedOff && waitingParts.length > 0,
      justPlayed: false,
      preDropMs: v.pre_drop_ms ?? null, preDropKind: v.pre_drop_kind ?? null,
      preDropWas: v.pre_drop_off ? (v.pre_drop_was ?? null) : null,
      preDropAuto: v.pre_drop_auto ?? null, preDropMoved: !!v.moved?.pre_drop,
      view: v, yours: null,
    });
  }
  rows.sort((a, b) => a.dropMs - b.dropMs || (a.kind === 'yours' ? -1 : 1));

  const last = opts.lastDrop;
  if (testing && last && last.uri === resp.uri) {
    const i = rows.findIndex((r) => r.key === last.key
      || (r.yours?.detections ?? []).includes(last.key));
    if (i >= 0) {
      const [hit] = rows.splice(i, 1);
      rows.unshift({ ...hit, justPlayed: true });
    }
  }
  return rows;
}

/** The card's title count: the drops still waiting for him. */
export function toReview(rows: PanelRow[]): number {
  return rows.filter((r) => r.waiting).length;
}

/** m:ss.t — the row's time. */
export function fmtDropTime(ms: number): string {
  const m = Math.floor(ms / 60000);
  const s = (ms - m * 60000) / 1000;
  return `${m}:${s.toFixed(1).padStart(4, '0')}`;
}

/** The row nearest `ms` (a tap on the song timeline's drop pill or the
 * audio shape), within `reachMs`. */
export function rowNear(rows: PanelRow[], ms: number, reachMs = 2000): PanelRow | null {
  let best: PanelRow | null = null;
  for (const r of rows) {
    const d = Math.abs(r.dropMs - ms);
    if (d <= reachMs && (!best || d < Math.abs(best.dropMs - ms))) best = r;
  }
  return best;
}

/** The row's Remove, in words: what it would do (the tooltip). */
export function removeTitle(row: PanelRow, prov: ProvenanceResponse | null | undefined): string {
  if (row.kind === 'added') return 'Remove: delete the drop you added';
  if (row.kind === 'detected') return 'Remove: not a drop — never offered here again';
  const map = prov?.triggers?.length ? new Map(prov.triggers.map((t) => [t.id, t])) : null;
  const members = [row.yours?.charge, row.yours?.lull, row.yours?.drop].filter((m) => m && m.enabled);
  // a member the answer does not name is not guessed at either way
  if (!map || members.some((m) => !map.has(m!.id))) {
    return 'Remove: take your drop out (placed by hand: deleted; imported: switched off)';
  }
  const del = members.filter((m) => map.get(m!.id)?.remove_would === 'delete').length;
  const off = members.length - del;
  const bits = [];
  if (del) bits.push(`delete ${del} trigger${del === 1 ? '' : 's'} you placed by hand`);
  if (off) bits.push(`switch off ${off} imported trigger${off === 1 ? '' : 's'}`);
  return `Remove: ${bits.join(', ') || 'nothing left to remove'}`;
}

// ── the pre-drop handle (the in-place editor) ─────────────────────────────

/** The pre-drop handle's rails, range, snap and step are the Timeline's own
 * (timeline/dropEdit.ts) — one definition, so the two editors can never
 * place a pre-drop differently. */
export {
  PRE_DROP_LEAD_MS, preDropRail, snapPreDrop, stepPreDrop, clampPreDrop,
} from '../timeline/dropEdit';
