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
 * EACH PART'S LOOK (`PartLook`) is the server's state (drop_sequences.py's
 * PARTS: on, waiting, off, absent) with WAITING SPLIT BY CONFIDENCE
 * (2026-10-28, his Q10-Q12): a waiting part the detector's own confident
 * tier stands behind is `confident` — drawn approved, with a small dot that
 * says the detector approved it, not him, and left out of "to review"; a
 * lower-confidence suggestion stays `waiting`, dashed. The drop, charge and
 * lull follow the sequence's tier (a drop demoted for sitting within 45 s of
 * a stronger one is already a suggestion there); the pre-drop follows its
 * own `pre_drop_tier`. Nothing about firing changes: a confident part plays
 * where the analysed show plays, as before. His own rows' parts are his
 * triggers: on while enabled, off when switched off. A tap goes waiting →
 * on, on or confident → off, off → on (`nextPartState`); a DOUBLE-TAP always
 * switches the part off (HomeDrops.tsx, his Q9). Any edit approves the whole
 * drop (drop_sequences.py's ANY EDIT APPROVES) — the server's rule, so the
 * panel just shows what comes back.
 *
 * WHAT PLAYS is the server's answer (drop_firing.annotate's `fires`), never
 * re-derived here. His own row plays when his drop is on and either his
 * triggers fire in this mode or a detection standing in for it does.
 *
 * JUST PLAYED AND NEXT (2026-10-28, his Q1-Q4): in every mode, the drop
 * that just played stays in its place and is highlighted (`justPlayed`)
 * until the next one plays — rows stay in time order. The drop that plays
 * next (`nextDropKey`: the first row that will actually play, by the server's
 * own answer, whose drop has not fired yet) wears a countdown to the moment
 * it FIRES (`fireMs`: the server's `fire_ms`, mark + drop timing — never
 * re-derived here). TESTING (RoomControlState.drop_testing) adds the
 * suggestions to what plays, and so to what can be next.
 *
 * THE PRE-DROP (predrop plan step 4) is the fourth part: its button wears
 * its KIND's glyph (a spike, or a vocal intro) in the pre-drop's orange and
 * the same four looks; its state comes from the server (`parts.pre_drop`,
 * or a row of his own's `pre_drop.part` — the pre-drop of his own drop is
 * stored in the drop store, never his song profile, so its tap asks
 * nothing first). A waiting pre-drop is something waiting for him: it
 * counts in the title and lights the double tick, his own rows included.
 * One that plays fades the drop's colour change across it; its words say
 * so (PRE_DROP_IN_THE_ROOM, the Timeline's). The in-place
 * editor's pre-drop handle snaps to the rail of its kind — a spike to the
 * hits (`DropRails.hits`), a vocal intro to the entries — and stays inside
 * its kind's lead range (`snapPreDrop` / `stepPreDrop` / `clampPreDrop`). */
import type {
  DropSequencesResponse, DropSequenceView, PartKey, PartView, PreDropKind, YoursRow,
} from '../timeline/dropSequences';
import { PARTS, PHASE_COLOR, PRE_DROP_COLOR, PRE_DROP_IN_THE_ROOM_SHORT } from '../timeline/dropSequences';
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
  /** each part as the panel draws it: the server's state with waiting split
   * by the detector's confidence (`PartLook`) */
  looks: Record<PartKey, PartLook>;
  /** when its drop FIRES (the server's `fire_ms`: mark + drop timing), song ms */
  fireMs: number;
  /** the double tick's look: lit = nothing waits (all his); half = only
   * high-confidence parts wait (the detector approved them); '' = a
   * suggestion waits */
  approveLook: 'lit' | 'half' | '';
  /** it plays on this song under the room's setting now */
  plays: boolean;
  stateLine: string;
  /** something on it is still waiting for him */
  waiting: boolean;
  /** listed but silent: a drop he switched off */
  switchedOff: boolean;
  /** the double tick would change something */
  canApprove: boolean;
  /** this drop is the one that just played (any mode) */
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

/** What a pre-drop's tooltip adds about the room (predrop step 5): the
 * Timeline's own words, read, never re-typed. */
export const PRE_DROP_IN_THE_ROOM = PRE_DROP_IN_THE_ROOM_SHORT;

/** A part as the panel draws it (module docstring's EACH PART'S LOOK). */
export type PartLook = 'on' | 'confident' | 'waiting' | 'off' | 'absent';

/** What a tap on a part does: waiting → on, off → on; on or confident (it
 * already looks approved) → off. A double-tap always ends off (HomeDrops). */
export function nextPartState(s: PartLook): 'on' | 'off' | null {
  if (s === 'waiting' || s === 'off') return 'on';
  if (s === 'on' || s === 'confident') return 'off';
  return null;
}

/** Two taps on one part within this many ms are a double-tap (his Q9: it
 * switches the part off; the first tap has already acted). */
export const DOUBLE_TAP_MS = 320;

/** A part button's words: its tooltip, and its aria-label. */
export function partTitle(row: Pick<PanelRow, 'kind'> & Partial<Pick<PanelRow, 'preDropKind'>>,
  part: PartKey, state: PartLook, provenance?: TriggerProvenance | null): string {
  const name = PART_LABEL[part];
  if (part === 'pre_drop') {
    // the pre-drop is never one of his triggers, his own drops included
    if (state === 'absent') return 'No pre-drop on this drop — add one in its editor (the pencil)';
    const named = row.preDropKind ? `${name} (${PRE_DROP_KIND_WORD[row.preDropKind]})` : name;
    if (state === 'on') return `${named}: approved — tap to switch it off; ${PRE_DROP_IN_THE_ROOM}`;
    if (state === 'confident') return `${named}: high confidence, the detector approved it — tap to switch it off; ${PRE_DROP_IN_THE_ROOM}`;
    if (state === 'off') return `${named}: off, never plays — tap to switch it back on; ${PRE_DROP_IN_THE_ROOM}`;
    return `${named}: a suggestion, waiting for you — tap to approve it (double-tap: off); ${PRE_DROP_IN_THE_ROOM}`;
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
  if (state === 'confident') return `${name}: high confidence, the detector approved it — tap to switch it off`;
  if (state === 'off') return `${name}: off, never plays — tap to switch it back on`;
  return `${name}: a suggestion, waiting for you — tap to approve the drop (double-tap: off)`;
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

/** A waiting part, split by the detector's own confidence (module
 * docstring's EACH PART'S LOOK): the drop, charge and lull follow the
 * sequence's tier, the pre-drop its own. */
function looksOfView(v: DropSequenceView, parts: Record<PartKey, PartView>): Record<PartKey, PartLook> {
  const out = {} as Record<PartKey, PartLook>;
  for (const k of PARTS) {
    const confident = k === 'pre_drop' ? v.pre_drop_tier === 'confident' : v.tier === 'confident';
    out[k] = parts[k] === 'waiting' && confident ? 'confident' : parts[k];
  }
  return out;
}

function looksOfYours(r: YoursRow, parts: Record<PartKey, PartView>): Record<PartKey, PartLook> {
  const out = { ...parts } as Record<PartKey, PartLook>;
  if (parts.pre_drop === 'waiting' && r.pre_drop?.tier === 'confident') out.pre_drop = 'confident';
  return out;
}

const LIVE = (s: PartLook) => s !== 'absent' && s !== 'off';

/** The double tick's look (PanelRow.approveLook). */
function approveLookOf(looks: Record<PartKey, PartLook>): PanelRow['approveLook'] {
  const live = PARTS.filter((k) => LIVE(looks[k]));
  if (live.some((k) => looks[k] === 'waiting')) return '';
  if (live.some((k) => looks[k] === 'confident')) return 'half';
  return 'lit';
}

/** Why a drop that is set to play does not play on this song now, in words
 * (the server's `fires_reason`, never re-derived). */
function notPlayingClause(reason: DropSequenceView['fires_reason']): string {
  if (reason === 'analysed_show_off') return ' · waits: only your own triggers play on this song';
  if (reason === 'transitions_only') return ' · waits: scene changes are on transitions only';
  if (reason === 'matches_yours') return ' · on your own trigger';
  return ' · does not play now';
}

function viewStateLine(v: DropSequenceView, looks: Record<PartKey, PartLook>,
  testing: boolean): string {
  if (looks.drop === 'off') return 'drop off · plays nothing';
  const playing = v.fires === true;
  if (v.origin === 'added') return `added by you${playing ? ' · plays' : notPlayingClause(v.fires_reason)}`;
  const live = PARTS.filter((k) => LIVE(looks[k]));
  const sugg = live.filter((k) => looks[k] === 'waiting');
  const conf = live.filter((k) => looks[k] === 'confident');
  if (v.state === 'matches_yours' && !playing) return 'on your own trigger';
  if (sugg.length === 0) {
    const who = conf.length === 0 ? 'approved by you' : 'high confidence';
    if (playing) return conf.length === 0 ? `${who} · plays` : `${who} · plays on its own`;
    return who + notPlayingClause(v.fires_reason);
  }
  if (looks.drop === 'waiting') {
    return testing ? 'suggested · plays while testing' : 'suggested · waits for you';
  }
  // the drop stands, but a lower-confidence part of it waits for him
  const who = looks.drop === 'on' ? 'approved by you' : 'high confidence';
  const names = sugg.map((k) => PART_LABEL[k].toLowerCase()).join(' and ');
  return `${who} · ${names} wait${sugg.length === 1 ? 's' : ''} for you`;
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

/** Every row the card lists, in the order it lists them: time order, always
 * (the drop that just played is highlighted in place, never moved). */
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
    const looks = looksOfYours(r, parts);
    const standIns = (r.detections ?? []).map((k) => byKey.get(k)).filter(Boolean) as DropSequenceView[];
    const firingStandIn = standIns.find((v) => v.fires === true) ?? null;
    const plays = r.enabled && (hisApplies || !!firingStandIn);
    const pre = r.pre_drop ?? null;
    // a waiting pre-drop is the one thing on his own drop that waits for him
    const preWaiting = r.enabled && looks.pre_drop === 'waiting';
    const preOpen = r.enabled && (looks.pre_drop === 'waiting' || looks.pre_drop === 'confident');
    // when it fires: his own trigger's moment where his triggers play, else
    // the detection standing in for it
    const fireMs = (!hisApplies && firingStandIn?.fire_ms != null) ? firingStandIn.fire_ms
      : (r.fire_ms ?? r.drop.timestamp_ms);
    rows.push({
      key: r.key, kind: 'yours', dropMs: r.drop.timestamp_ms,
      chargeMs: r.charge?.timestamp_ms ?? null, lullMs: r.lull?.timestamp_ms ?? null,
      parts, looks, fireMs, approveLook: preOpen ? approveLookOf(looks) : 'lit', plays,
      stateLine: yoursStateLine(r, prov) + preDropClause(parts.pre_drop, pre?.kind ?? null),
      waiting: preWaiting, switchedOff: !r.enabled, canApprove: preOpen, justPlayed: false,
      preDropMs: pre?.ms ?? null, preDropKind: pre?.kind ?? null,
      preDropWas: pre?.off ? (pre.was ?? null) : null, preDropAuto: pre?.auto ?? null,
      preDropMoved: !!pre?.moved, view: standIns[0] ?? null, yours: r,
    });
  }
  for (const v of views) {
    if (v.state === 'dismissed' || claimed.has(v.key)) continue;
    const parts = partsOfView(v);
    const looks = looksOfView(v, parts);
    const kind: RowKind = v.origin === 'added' ? 'added' : 'detected';
    const switchedOff = parts.drop === 'off';
    const open = kind === 'detected' && !switchedOff
      && PARTS.some((k) => looks[k] === 'waiting' || looks[k] === 'confident');
    rows.push({
      key: v.key, kind, dropMs: v.drop_ms, chargeMs: v.charge_ms, lullMs: v.lull_ms,
      parts, looks, fireMs: v.fire_ms ?? v.drop_ms,
      approveLook: open ? approveLookOf(looks) : 'lit', plays: v.fires === true,
      stateLine: viewStateLine(v, looks, testing)
        + preDropClause(parts.pre_drop, v.pre_drop_kind ?? null),
      // to review: a lower-confidence suggestion waits on it (his Q10:
      // high-confidence parts look approved and are left out)
      waiting: kind === 'detected' && !switchedOff && v.state !== 'matches_yours'
        && PARTS.some((k) => looks[k] === 'waiting'),
      switchedOff, canApprove: open,
      justPlayed: false,
      preDropMs: v.pre_drop_ms ?? null, preDropKind: v.pre_drop_kind ?? null,
      preDropWas: v.pre_drop_off ? (v.pre_drop_was ?? null) : null,
      preDropAuto: v.pre_drop_auto ?? null, preDropMoved: !!v.moved?.pre_drop,
      view: v, yours: null,
    });
  }
  rows.sort((a, b) => a.dropMs - b.dropMs || (a.kind === 'yours' ? -1 : 1));

  const last = opts.lastDrop;
  if (last && last.uri === resp.uri) {
    const i = rows.findIndex((r) => r.key === last.key
      || (r.yours?.detections ?? []).includes(last.key));
    if (i >= 0) rows[i] = { ...rows[i], justPlayed: true };
  }
  return rows;
}

/** The row whose drop plays next (his Q3): the first row that will actually
 * play — the server's own answer (`plays`) — whose drop has not FIRED yet
 * at `nowMs` (song time, the show clock). null when none is left. */
export function nextDropKey(rows: PanelRow[], nowMs: number | null): string | null {
  if (nowMs == null) return null;
  let best: PanelRow | null = null;
  for (const r of rows) {
    if (!r.plays || r.fireMs <= nowMs) continue;
    if (!best || r.fireMs < best.fireMs) best = r;
  }
  return best?.key ?? null;
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
