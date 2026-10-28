/** DROP SEQUENCES ON THE TIMELINE — the pure half of the sequence layer,
 * the full-song strip and the review list (drop-detection plan, phase 3:
 * /home/javi/fleet-spotfx/data/drop-detection-plan/report.md section 8,
 * built to plan.html's Timeline mock). What a hand on a sequence DOES
 * (drag, snap, add, undo — phase 4) is ./dropEdit.ts. What FIRES is the
 * server's answer (spectra/services/drop_firing.py, phase 5): each sequence
 * in the view carries `fires` for this song under the room's setting now.
 *
 * WHAT IT READS. GET /spectra/api/drop-sequences?uri= (spectra/services/
 * drop_sequences.py's `view`: the song's detected sequences merged with his
 * edits and his own charge/lull/drop triggers, grouped) and GET
 * /spectra/api/drop-sequences/rails?uri= (the detector's own bass spikes and
 * the beats). Every time is SONG time — the frame the audio shape and his
 * triggers are drawn in on the Timeline canvas.
 *
 * WHAT IT DECIDES (and nothing else does — the canvas layer, the strip and
 * the review card all draw from `buildDisplay`):
 *
 *   ONE SHAPE PER SEQUENCE. A detection that sits on one of his own phase
 *   triggers stands down as "matches yours" (the server's rule), so it is
 *   NOT drawn twice: his own grouped charge/lull/drop is drawn in the same
 *   shape instead (look `mine`), carrying the detection it matched so the
 *   detail box can say where the analysis put it.
 *
 *   THE LOOK. confident (solid) · suggested (dashed, faded) · confirmed ·
 *   edited (dotted line where the analysis had a moved handle) · added ·
 *   mine (his own triggers) · dismissed (hidden unless "show dismissed").
 *
 *   WHAT FIRES, under the approved design (decisions 2 and 3): his own
 *   triggers fire as they always have; a confirmed, edited or added
 *   sequence fires wherever his triggers fire and wherever the analysed
 *   show plays; a CONFIDENT detection fires only on a song that plays the
 *   analysed show; a suggestion waits for his confirm. The server says it
 *   per sequence (`fires`, the trigger clock's own rule); without that
 *   field (an older server) `analysedApplies` — the analysed plan's own
 *   `applies` — stands in. Numbered pills are the ones that fire, in time
 *   order; a suggestion is "?", a sequence this song will not play is "✦".
 *
 * THE BUILD each charge and lull is drawn with is the engine's own
 * arithmetic — phaseBlendSpan from ./phaseBlend.ts (scene_response.
 * _phase_ramp_ms, mirrored and drift-checked there): a sequence member
 * builds to its OWN partner (a charge to its lull, or its drop when it has
 * no lull; a lull to its drop), the phase-partner rule.
 *
 * THE PRE-DROP (predrop plan step 4) is the fourth member: a spike or a
 * vocal intro 250 ms to 4.5 s before the drop, orange (PRE_DROP_COLOR), its
 * glyph its kind's. A detection's comes from its own `pre_drop_*` fields; one
 * of HIS drops carries the rules' pre-drop with his edits to it
 * (AuthoredGroup.pre_drop) — the one member of his own sequence edited here,
 * through his "his:<drop id>" key. Its look follows its part state the way a
 * member's follows its tier (`preDropLook`): approved (or placed by him on
 * an older server) and a confident one solid, a suggested one dashed, one
 * switched off drawn as an off member is. A pre-drop that plays fades the
 * drop's colour change across it (PRE_DROP_IN_THE_ROOM).
 *
 * DOM-free, so scripts/check_drop_sequence_view.mjs drives it directly. */
import { phaseBlendSpan, type PhaseBlendSpan } from './phaseBlend';

/** THE PHASE COLOURS — gold building, sky-blue receding, magenta impact
 * (decision 5: they stay on the phases; nothing else on the Timeline may
 * wear them). One definition: the SPECTRA trigger strip's charge/lull/drop
 * markers (SpectraTriggerBar's RESPONSE_CLASS_COLOR) read these too. */
export const PHASE_COLOR: Record<Handle, string> = {
  charge: '#fbbf24',
  lull: '#38bdf8',
  drop: '#ec4899',
};

/** The pre-drop's colour (orange), the fourth member's on the Timeline and
 * in the Home Drops panel alike. */
export const PRE_DROP_COLOR = '#fb923c';

// ── the wire (spectra/services/drop_sequences.py) ─────────────────────────

export type DropServerState =
  | 'confident' | 'suggested' | 'confirmed' | 'edited' | 'added' | 'matches_yours' | 'dismissed';

export type Handle = 'charge' | 'lull' | 'drop';
export const HANDLES: Handle[] = ['charge', 'lull', 'drop'];

/** Every handle a sequence carries on the Timeline: the three phases and
 * the pre-drop, drawn in this order (the drop's star last, on top). */
export type SeqHandle = Handle | 'pre_drop';
export const SEQ_HANDLES: SeqHandle[] = ['charge', 'lull', 'pre_drop', 'drop'];

/** A drop's parts, in the order they play — the pre-drop is one (absent on
 * a drop that has none). */
export type PartKey = 'charge' | 'lull' | 'pre_drop' | 'drop';
export const PARTS: PartKey[] = ['charge', 'lull', 'pre_drop', 'drop'];
export type PartView = 'on' | 'waiting' | 'off' | 'absent';

/** One of his own enabled authored triggers, at the moment it fires. */
export interface HisMark {
  id: string;
  /** fire_response's event_class (flare / charge / lull / drop), else the
   * action kind (fire_scene / fire_scene_update / select_color_set). */
  kind: string;
  timestamp_ms: number;
}

export interface DropSequenceView {
  key: string;
  origin: 'detected' | 'added';
  state: DropServerState;
  charge_ms: number | null;
  lull_ms: number | null;
  drop_ms: number;
  tier: 'confident' | 'suggested' | null;
  detected_key: string | null;
  /** where the detector puts each handle (null on an added sequence) */
  auto: { charge_ms: number | null; lull_ms: number | null; drop_ms: number | null } | null;
  /** which handles he placed; `pre_drop` too (a drag or ＋ Pre-drop) */
  moved: Partial<Record<Handle | 'pre_drop', boolean>>;
  lull_off: boolean;
  charge_off: boolean;
  score: number | null;
  break_beats: number | null;
  step: number | null;
  rise: number | null;
  path: string | null;
  loud_before: boolean | null;
  capped: boolean;
  notes: string[];
  needs_review: boolean;
  detection_lost: boolean;
  matches: HisMark[];
  his_marks_near: HisMark[];
  /** phase 5 (drop_firing.annotate): whether it fires on this song under
   * the room's "Scene changes" setting now, and why (not). Absent from an
   * older server. */
  fires?: boolean;
  fires_reason?: 'his' | 'analysed_show' | 'analysed_show_off' | 'transitions_only'
    | 'matches_yours' | 'waits_for_confirm' | 'dismissed' | 'switched_off' | 'testing';
  /** THE HOME DROPS PANEL's per-part states (drop_sequences.py's PARTS):
   * on = approved, waiting = follows its tier, off = never plays, absent =
   * no such part. Absent from an older server. */
  parts?: Partial<Record<PartKey, PartView>>;
  /** the members that actually fire here, when it fires (drop_firing.annotate) */
  playing?: Handle[];
  /** members left out because one of his own triggers of that class fires
   * within two beats of it: handle -> his trigger id */
  stood_down?: Partial<Record<Handle, string>>;
  /** the intensity it fires at (before the room's render scaling) */
  intensity?: number;
  /** when its drop FIRES, song ms (drop_firing.annotate's THE FIRE MOMENT:
   * mark + the drop band's offset + the drop timing offset). Absent from an
   * older server — the drop's mark then. */
  fire_ms?: number;
  /** THE DROP-LED SCENE SWITCH (spectra/services/drop_switch.py): this
   * play's decision for the sequence — whether it changes the scene, to
   * what, when (a hard cut on the drop, or early in the charge) and why.
   * Absent until the trigger clock has reached the sequence. */
  switch?: DropSwitchPlan;
  /** THE PRE-DROP (spectra/services/predrop_detector.py; drop_sequences.py's
   * PRE-DROPS): where it plays (null when the drop has none or it is
   * switched off), its kind (kept while off, so its glyph still shows), where
   * the detector puts it (null when the detector found none — on an added
   * drop always), and how sure the detector is — tier and score are the
   * detector's, null once he placed it himself (`moved.pre_drop`). Its part
   * state is parts.pre_drop. Absent from an older server. Whether it plays is
   * decided at its lull (spectra/services/pre_drop_play.py). */
  pre_drop_ms?: number | null;
  pre_drop_kind?: PreDropKind | null;
  pre_drop_auto?: number | null;
  pre_drop_tier?: 'confident' | 'suggested' | null;
  pre_drop_score?: number | null;
  /** switched off: `pre_drop_ms` is null and `pre_drop_was` is where it comes
   * back when switched on again */
  pre_drop_off?: boolean;
  pre_drop_was?: number | null;
}

/** A pre-drop's kind: one loud hit in the high band, or a line in the mid
 * band entering out of a hush (predrop_detector.KIND_SPIKE / KIND_INTRO). */
export type PreDropKind = 'spike' | 'intro';

/** A pre-drop as a detection stores it (predrop_detector.PreDrop.stored). */
export interface PreDropFound {
  ms: number;
  kind: PreDropKind;
  lead_ms: number;
  score: number;
  tier: 'confident' | 'suggested';
}

/** The pre-drop of one of HIS OWN drops (an `authored` group or a `yours`
 * row): the rules' pre-drop for his drop's moment with his own edits to it
 * (stored under overrides["mine:<drop trigger id>"], drop_sequences.py's
 * PRE-DROPS). `ms` is where it plays (null while switched off; `was` is
 * where it comes back); `auto` where the rules put it (null when he placed
 * one the rules did not find); tier/score/lead_ms are the rules' and null
 * once he moved it. `part` is its part state (never 'absent': a drop with
 * no pre-drop carries `pre_drop: null`). */
export interface HisPreDrop {
  ms: number | null;
  kind: PreDropKind;
  auto: number | null;
  off: boolean;
  was: number | null;
  moved: boolean;
  lead_ms: number | null;
  score: number | null;
  tier: 'confident' | 'suggested' | null;
  part: Exclude<PartView, 'absent'>;
}

export interface DropSwitchPlan {
  key: string;
  switch: boolean;
  reason: string;
  sentence: string;
  stale_by: string[];
  from_scene_name: string | null;
  to_scene_name: string | null;
  to_effect: string | null;
  handoff: string | null;
  moment: 'drop' | 'charge_start' | 'charge_flare' | 'after_drop' | 'next_hit' | null;
  cut_ms: number | null;
  outcome: { result: string; at: string; skipped?: string } | null;
  lull_handoff?: { keep: number; next: Record<string, string> } | null;
}

const SWITCH_WHEN: Record<string, string> = {
  drop: 'on the drop', charge_start: 'at the charge', charge_flare: 'on a flare in the charge',
  // THE FIREWORKS MELDS (drop_switch.py): Fireworks plays its own drop first
  after_drop: 'after the drop', next_hit: 'on the next big hit',
};

/** The short chip for a switch ("⇄ STAR on the drop"), or null. */
export function switchChip(plan: DropSwitchPlan | undefined | null): string | null {
  if (!plan || !plan.switch || !plan.to_scene_name) return null;
  return `⇄ ${plan.to_scene_name} ${SWITCH_WHEN[plan.moment ?? 'drop'] ?? ''}`.trim();
}

/** One line on what this sequence did (or will do) to the scene — the
 * server's own sentence plus what actually happened. */
export function switchLine(plan: DropSwitchPlan | undefined | null): string | null {
  if (!plan) return null;
  const o = plan.outcome;
  let done = '';
  if (o?.result === 'switched') done = ' Done: the cut landed.';
  else if (o?.result === 'superseded') done = ' Not cut: the scene had already changed by then.';
  else if (o?.result === 'skipped') done = ` Not cut: ${o.skipped ?? 'held back'}.`;
  return `${plan.sentence}${done}`;
}

/** The trigger clock's gate for this song now (drop_firing.annotate). */
export interface DropFiring {
  effective_mode: string;
  has_authored: boolean;
  analysed_applies: boolean;
  his_applies: boolean;
  /** drop Testing (RoomControlState.drop_testing): every detected drop plays */
  testing?: boolean;
}

/** A protected window: no analysed scene change inside it, no analysed
 * flare in its lull or on its drop. */
export interface DropWindow {
  key: string;
  source: 'sequence' | 'yours';
  start_ms: number;
  lull_ms: number | null;
  drop_ms: number;
  end_ms: number;
}

export interface AuthoredGroup {
  charge: HisMark | null;
  lull: HisMark | null;
  drop: HisMark;
  /** the pre-drop before HIS drop, with his edits to it: null when there is
   * none, the key absent while it is not worked out yet (drop_sequences.py's
   * PRE-DROPS — only the read-through view works it out) */
  pre_drop?: HisPreDrop | null;
}

/** One of his phase triggers in a `yours` row, enabled or switched off. */
export interface YoursMember extends HisMark {
  enabled: boolean;
  /** the trigger's own trigger_offset_ms: `timestamp_ms` is the moment it
   * fires (its stored time plus this) */
  offset_ms?: number;
}

/** HIS OWN DROP, enabled or switched off (drop_sequences.yours_rows): his
 * charge/lull/drop triggers grouped the way `authored` groups the enabled
 * ones, and the detections it stands in for. */
export interface YoursRow {
  key: string;
  charge: YoursMember | null;
  lull: YoursMember | null;
  drop: YoursMember;
  enabled: boolean;
  detections: string[];
  detection: string | null;
  /** the pre-drop before his drop (as AuthoredGroup.pre_drop) */
  pre_drop?: HisPreDrop | null;
  /** when his drop FIRES, song ms (drop_firing.annotate's THE FIRE MOMENT) */
  fire_ms?: number;
}

export interface DropSequencesResponse {
  uri: string;
  status: 'ok' | 'not_detected' | 'unavailable' | 'error';
  reason: string | null;
  detector: {
    version: string | null; stamp: string | null; detected_at: number | null;
    confident_score: number | null; suggested_score: number | null;
  } | null;
  song: {
    tempo_bpm: number | null; beat_ms: number | null; captured_from_ms: number | null;
    captured_to_ms: number | null; duration_ms: number | null;
  } | null;
  sequences: DropSequenceView[];
  excluded: { drop_ms: number; score: number; reason: string }[];
  counts: Record<string, number>;
  authored: AuthoredGroup[];
  authored_lone: HisMark[];
  /** his own drops, enabled or switched off (the Home Drops panel) */
  yours?: YoursRow[];
  firing?: DropFiring;
  windows?: DropWindow[];
}

export interface DropRails {
  uri: string;
  status: 'ok' | 'unavailable';
  reason: string | null;
  beat_ms: number | null;
  captured_from_ms: number | null;
  /** [song ms, rise] — every bass spike the detector counts */
  spikes: [number, number][];
  /** [song ms, 1 = downbeat] */
  beats: [number, number][];
  /** [song ms, strength 0..1] — every high-band attack (a clap, a hit): what
   * a dragged SPIKE pre-drop snaps to (predrop_detector.rails) */
  hits?: [number, number][];
  /** [song ms, strength 0..1] — every mid-band entry passing the vocal
   * intro's first three tests (loud, out of a hush, sharp): what a dragged
   * VOCAL INTRO pre-drop snaps to */
  entries?: [number, number][];
}

// ── the display model ─────────────────────────────────────────────────────

export type SeqLook =
  | 'confident' | 'suggested' | 'confirmed' | 'edited' | 'added' | 'mine' | 'dismissed';

/** fires = it fires on this song under the room's setting now (his own
 * triggers, a sequence of his, or a confident detection on a song that
 * plays the analysed show). muted = it would fire, but not on this song
 * under the room's setting now (a confident detection on a song that plays
 * only his own triggers; anything under "Transitions only"). waits = a
 * suggestion, waiting for his confirm. stands_down = a detection on one of
 * his lone phase triggers. */
export type FireStatus = 'fires' | 'muted' | 'waits' | 'stands_down' | 'dismissed';

export interface DisplaySeq {
  /** unique across the song: the detection's key, an added id, or
   * "his:<his drop trigger id>" */
  key: string;
  look: SeqLook;
  charge: number | null;
  lull: number | null;
  drop: number;
  /** where the pre-drop plays: null when the drop has none, it is switched
   * off, or it is not worked out yet */
  pre_drop: number | null;
  /** the pre-drop itself (kind, part state, how it was placed), null when
   * the drop has none (or, for one of his drops, not worked out yet) */
  preDrop: PreDropInfo | null;
  /** true while the pre-drop is not worked out yet — his drop's, before the
   * read-through view has looked; a detection's, from an older server */
  preDropUnknown?: boolean;
  /** where the analysis had each MOVED (or switched-off) handle — the dotted
   * line. Only handles he changed appear here; a pre-drop he moved off the
   * rules' place too. */
  analysisHad: Partial<Record<SeqHandle, number>>;
  off: { charge: boolean; lull: boolean; pre_drop: boolean };
  fire: FireStatus;
  /** 1-based, in time order, for sequences that fire or will; else null */
  number: number | null;
  /** the strip pill / review-list badge text: the number, "?", "✦" or "✕" */
  badge: string;
  /** the detection: its own, or (look `mine`) the one that matched him */
  view: DropSequenceView | null;
  his: AuthoredGroup | null;
}

/** A sequence's pre-drop, read off the wire the same way for a detection
 * (DropSequenceView.pre_drop_*) and for one of his own drops (HisPreDrop). */
export interface PreDropInfo {
  kind: PreDropKind;
  /** parts.pre_drop: on = approved, waiting = follows its own tier, off =
   * never plays; null from an older server that sends no parts */
  part: Exclude<PartView, 'absent'> | null;
  off: boolean;
  /** where a switched-off one comes back when switched on */
  was: number | null;
  /** where the rules put it: null when they found none (and on an added drop) */
  auto: number | null;
  /** he placed it himself (a drag, ＋ Pre-drop, a whole-sequence move) */
  moved: boolean;
  /** the rules' tier and score — null once he placed it */
  tier: 'confident' | 'suggested' | null;
  score: number | null;
}

function preDropOfView(v: DropSequenceView): PreDropInfo | null {
  const kind = v.pre_drop_kind;
  if (!kind) return null;
  const part = v.parts?.pre_drop;
  return {
    kind, part: part && part !== 'absent' ? part : null, off: !!v.pre_drop_off,
    was: v.pre_drop_was ?? null, auto: v.pre_drop_auto ?? null, moved: !!v.moved?.pre_drop,
    tier: v.pre_drop_tier ?? null, score: v.pre_drop_score ?? null,
  };
}

function preDropOfHis(p: HisPreDrop | null | undefined): PreDropInfo | null {
  if (!p || !p.kind) return null;
  return {
    kind: p.kind, part: p.part ?? null, off: !!p.off, was: p.was ?? null, auto: p.auto ?? null,
    moved: !!p.moved, tier: p.tier ?? null, score: p.score ?? null,
  };
}

/** The dotted line for a pre-drop he moved off the rules' place (one he
 * switched off is drawn at where it comes back instead — see the layer). */
function preDropHad(pd: PreDropInfo | null, ms: number | null): number | undefined {
  if (!pd || pd.off || !pd.moved || pd.auto == null || ms == null || ms === pd.auto) return undefined;
  return pd.auto;
}

const TIER_LOOK: Record<string, SeqLook> = { confident: 'confident', suggested: 'suggested' };

function lookOf(v: DropSequenceView): SeqLook {
  switch (v.state) {
    case 'confirmed': case 'edited': case 'added': case 'dismissed': return v.state;
    case 'confident': case 'suggested': return v.state;
    default: return TIER_LOOK[v.tier ?? 'suggested'] ?? 'suggested';
  }
}

function fireOf(look: SeqLook, analysedApplies: boolean, serverFires?: boolean): FireStatus {
  switch (look) {
    case 'mine': return 'fires';
    case 'confirmed': case 'edited': case 'added':
      return serverFires === false ? 'muted' : 'fires';
    case 'confident':
      if (serverFires != null) return serverFires ? 'fires' : 'muted';
      return analysedApplies ? 'fires' : 'muted';
    case 'suggested': return 'waits';
    default: return 'dismissed';
  }
}

export function sequenceFires(s: Pick<DisplaySeq, 'fire'>): boolean {
  return s.fire === 'fires';
}

function analysisHad(v: DropSequenceView, pd: PreDropInfo | null): Partial<Record<SeqHandle, number>> {
  const out: Partial<Record<SeqHandle, number>> = {};
  const pre = preDropHad(pd, v.pre_drop_ms ?? null);
  if (pre != null) out.pre_drop = pre;
  if (!v.auto) return out;
  for (const h of HANDLES) {
    const was = v.auto[`${h}_ms` as const];
    if (was == null) continue;
    const off = (h === 'lull' && v.lull_off) || (h === 'charge' && v.charge_off);
    if (v.moved[h] || off) out[h] = was;
  }
  return out;
}

function fromView(v: DropSequenceView, analysedApplies: boolean): DisplaySeq {
  const look = lookOf(v);
  const pd = preDropOfView(v);
  return {
    key: v.key, look,
    charge: v.charge_ms, lull: v.lull_ms, drop: v.drop_ms,
    pre_drop: pd && !pd.off ? v.pre_drop_ms ?? null : null, preDrop: pd,
    preDropUnknown: v.pre_drop_ms === undefined && v.pre_drop_kind === undefined,
    analysisHad: analysisHad(v, pd),
    off: { charge: !!v.charge_off, lull: !!v.lull_off, pre_drop: !!pd?.off },
    // an added sequence on one of his own phase triggers stands down too;
    // a drop he switched off (the Home Drops panel) is listed but silent
    fire: v.fires === false && v.fires_reason === 'matches_yours' && look !== 'dismissed'
      ? 'stands_down'
      : v.fires_reason === 'switched_off' ? 'muted'
        // a suggestion drop Testing plays fires like a confident one
        : v.fires === true && v.fires_reason === 'testing' ? 'fires'
          : fireOf(look, analysedApplies, v.fires),
    number: null, badge: '', view: v, his: null,
  };
}

/** The detection that stood down on this group of his, if any — matched on
 * his drop first, then his lull, then his charge. */
export function matchedDetection(
  group: AuthoredGroup, views: DropSequenceView[],
): DropSequenceView | null {
  const standing = views.filter((v) => v.state === 'matches_yours');
  for (const m of [group.drop, group.lull, group.charge]) {
    if (!m) continue;
    const hit = standing.find((v) => v.matches.some((x) => x.id === m.id));
    if (hit) return hit;
  }
  return null;
}

export interface BuildOptions {
  showDismissed: boolean;
  /** the analysed plan's `applies` for this song: whether a CONFIDENT
   * detection would fire here (decision 2). Unknown counts as true. */
  analysedApplies: boolean;
}

/** Everything the layer, strip and list draw, in drop-time order. */
export function buildDisplay(
  resp: DropSequencesResponse | null | undefined, opts: BuildOptions,
): DisplaySeq[] {
  if (!resp) return [];
  const views = resp.sequences ?? [];
  const out: DisplaySeq[] = [];
  const claimed = new Set<string>();
  for (const g of resp.authored ?? []) {
    if (!g?.drop) continue;
    const det = matchedDetection(g, views);
    if (det) claimed.add(det.key);
    // the pre-drop before HIS drop (the rules' with his edits): the one
    // member of his own sequence the Timeline edits
    const pd = preDropOfHis(g.pre_drop);
    const preMs = pd && !pd.off ? g.pre_drop?.ms ?? null : null;
    const had = preDropHad(pd, preMs);
    out.push({
      key: `his:${g.drop.id}`, look: 'mine',
      charge: g.charge?.timestamp_ms ?? null, lull: g.lull?.timestamp_ms ?? null,
      drop: g.drop.timestamp_ms, pre_drop: preMs, preDrop: pd, preDropUnknown: g.pre_drop === undefined,
      analysisHad: had != null ? { pre_drop: had } : {},
      off: { charge: false, lull: false, pre_drop: !!pd?.off },
      fire: 'fires', number: null, badge: '', view: det, his: g,
    });
  }
  for (const v of views) {
    if (claimed.has(v.key)) continue;
    if (v.state === 'dismissed' && !opts.showDismissed) continue;
    const s = fromView(v, opts.analysedApplies);
    if (v.state === 'matches_yours') {
      // stood down on one of his LONE phase triggers (no drop of his to
      // group it with): drawn faded, never numbered — his trigger fires.
      s.look = v.tier === 'confident' ? 'confident' : 'suggested';
      s.fire = 'stands_down';
    }
    out.push(s);
  }
  out.sort((a, b) => a.drop - b.drop || (a.look === 'mine' ? -1 : 1));
  let n = 0;
  for (const s of out) {
    if (sequenceFires(s)) {
      n += 1;
      s.number = n;
      s.badge = String(n);
    } else {
      s.badge = s.fire === 'dismissed' ? '✕' : s.fire === 'muted' ? '✦' : '?';
    }
  }
  return out;
}

// ── geometry ──────────────────────────────────────────────────────────────

/** Two bars (4/4): the protected tail after a drop, and the zoom margin. */
export const TAIL_BEATS = 8;
export const DEFAULT_BEAT_MS = 500;

/** A sequence's times as the geometry reads them; the pre-drop is optional
 * (Home's Drops panel zooms on charge, lull and drop alone). */
export type SeqTimes = Pick<DisplaySeq, 'charge' | 'lull' | 'drop'> & Partial<Pick<DisplaySeq, 'pre_drop'>>;

/** The sequence's earliest handle — the pre-drop may sit before the lull
 * starts, even before a short charge. */
export function firstHandleMs(s: SeqTimes): number {
  const first = s.charge ?? s.lull ?? s.drop;
  return s.pre_drop != null && s.pre_drop < first ? s.pre_drop : first;
}

/** The build each phase runs, exactly as the engine will: a charge to its
 * own lull (or its drop with no lull), a lull to its own drop. */
export function sequenceBuilds(s: Pick<DisplaySeq, 'charge' | 'lull' | 'drop'>): {
  charge: PhaseBlendSpan | null; lull: PhaseBlendSpan | null;
} {
  return {
    charge: s.charge != null ? phaseBlendSpan('charge', s.charge, s.lull ?? s.drop) : null,
    lull: s.lull != null ? phaseBlendSpan('lull', s.lull, s.drop) : null,
  };
}

/** "Click one to jump the big graph to it, zoomed to fit from two bars
 * before the charge to two bars after the drop." */
export function zoomWindow(
  s: SeqTimes, beatMs: number | null | undefined,
  durationMs: number,
): { startMs: number; endMs: number } {
  const beat = beatMs && beatMs > 0 ? beatMs : DEFAULT_BEAT_MS;
  const margin = TAIL_BEATS * beat;
  const startMs = Math.max(0, firstHandleMs(s) - margin);
  const endMs = Math.min(Math.max(durationMs, s.drop + 1), s.drop + margin);
  return { startMs, endMs: Math.max(endMs, startMs + 1000) };
}

// ── words ─────────────────────────────────────────────────────────────────

/** m:ss.s — the review list. */
export function fmtTenths(ms: number): string {
  const m = Math.floor(ms / 60000);
  const s = (ms - m * 60000) / 1000;
  return `${m}:${s.toFixed(1).padStart(4, '0')}`;
}

/** m:ss.ss — the detail box. */
export function fmtHundredths(ms: number): string {
  const m = Math.floor(ms / 60000);
  const s = (ms - m * 60000) / 1000;
  return `${m}:${s.toFixed(2).padStart(5, '0')}`;
}

const secs = (ms: number) => `${(ms / 1000).toFixed(1)} s`;

const MARK_NAME: Record<string, string> = {
  flare: 'flare', charge: 'charge', lull: 'lull', drop: 'drop',
  fire_scene: 'scene change', fire_scene_update: 'scene update',
  select_color_set: 'colour change',
};

export function markName(kind: string): string {
  return MARK_NAME[kind] ?? kind;
}

/** The chip on the canvas: what this sequence is, in two or three words. */
export const LOOK_CHIP: Record<SeqLook, string> = {
  confident: 'detected ✦',
  suggested: 'suggested ?',
  confirmed: 'confirmed ✓',
  edited: 'yours ✎ edited',
  added: 'yours ＋ added',
  mine: 'your triggers',
  dismissed: 'dismissed ✕',
};

/** The one-glyph chip when there is no room for the words. */
export const LOOK_GLYPH: Record<SeqLook, string> = {
  confident: '✦', suggested: '?', confirmed: '✓', edited: '✎', added: '＋', mine: '★', dismissed: '✕',
};

/** The review list's "what is here" — his own words for the moment. */
export function reviewStatus(s: DisplaySeq): string {
  const v = s.view;
  const flag = v?.needs_review ? ' · ⚠ the analysis has moved it' : '';
  if (s.look === 'mine') {
    if (!v) return 'yours · the analysis did not find this drop';
    const kinds = new Set(v.matches.map((m) => m.kind));
    const which = kinds.has('drop') ? 'drop' : kinds.has('lull') ? 'lull' : 'charge';
    return `matches your ${which}`;
  }
  if (s.fire === 'stands_down') {
    const k = v?.matches[0]?.kind;
    return `stands down: you have a ${markName(k ?? 'drop')} here`;
  }
  const silent = s.fire === 'muted' ? ' · "Transitions only" fires no drops' : '';
  if (s.look === 'confirmed') return `confirmed by you${flag}${silent}`;
  if (s.look === 'edited') return `edited by you${flag}${silent}`;
  if (s.look === 'added') return `added by you${silent}`;
  if (s.look === 'dismissed') return 'dismissed · not a drop';
  const near = v?.his_marks_near ?? [];
  if (near.length) return `you have a ${markName(near[0].kind)} here`;
  if (s.look === 'confident') {
    return s.fire === 'muted'
      ? (s.view?.fires_reason === 'transitions_only'
        ? 'detected · "Transitions only" fires no drops'
        : 'detected · this song plays only your own triggers')
      : 'detected · fires with the analysed show';
  }
  return 'suggested · waits for your confirm';
}

/** One line on what firing this sequence means, as the trigger clock will
 * do it (spectra/services/drop_firing.py). */
export function fireLine(s: DisplaySeq): string {
  const standing = Object.keys(s.view?.stood_down ?? {});
  const left = standing.length
    ? ` Its ${standing.join(' and ')} is left out: your own ${standing.join(' and ')} fires there.`
    : '';
  switch (s.fire) {
    case 'fires':
      if (s.look === 'mine') return 'Your own triggers — they fire wherever your triggers fire (your "Scene changes" setting decides that), exactly as they always have.';
      return (s.look === 'confident'
        ? 'Confident: it fires on its own, because this song plays the analysed show — charge, lull and drop as the ordinary responses, each build peaking on its own partner.'
        : 'Yours: it fires wherever your triggers fire, and with the analysed show too — charge, lull and drop as the ordinary responses, each build peaking on its own partner.')
        + left;
    case 'muted': return s.view?.fires_reason === 'transitions_only'
      ? 'Not on this setting: "Scene changes" is "Transitions only", which fires no drops, analysed or yours.'
      : 'Confident, but this song plays only your own triggers, so it does not fire here. Confirm it to make it yours and it will.';
    case 'waits': return 'A suggestion: it waits for your confirm and never fires on its own.';
    case 'stands_down': return 'Your own trigger sits here, so this detection stands down and yours fires.';
    default: return 'Dismissed: it never fires and is never offered again.';
  }
}

/** "Why it was found" — the detector's own measurements, in words. */
export function whyFound(v: DropSequenceView | null, confidentScore: number | null | undefined): string | null {
  if (!v || v.origin !== 'detected' || v.score == null) return null;
  const parts: string[] = [];
  if (v.path === 'roll') parts.push('a dense kick roll, a gap, then a hard bass hit');
  if (v.break_beats != null) parts.push(`bass returned after ${v.break_beats.toFixed(1)} quiet beats`);
  if (v.step != null) parts.push(`level stepped up by ${v.step.toFixed(2)}`);
  if (v.loud_before) parts.push('it was loud before the break');
  const from = confidentScore != null ? `confident from ${confidentScore.toFixed(1)}` : 'confident';
  const tier = v.tier === 'confident' ? `(${from})` : `(suggested; ${from})`;
  return `${parts.join('; ')}. Score ${v.score.toFixed(2)} ${tier}.`;
}

/** "What the room does" — each build's ramp and hang, from the engine's own
 * arithmetic (sequenceBuilds). */
export function roomLines(s: Pick<DisplaySeq, 'charge' | 'lull' | 'drop'>): string[] {
  const b = sequenceBuilds(s);
  const out: string[] = [];
  if (b.charge) {
    out.push(`Charge builds for ${secs(b.charge.rampEndMs - b.charge.startMs)}, holds `
      + `${secs(b.charge.endMs - b.charge.rampEndMs)}, peaking on the ${s.lull != null ? 'lull' : 'drop'}.`);
  }
  if (b.lull) {
    out.push(`Lull winds for ${secs(b.lull.rampEndMs - b.lull.startMs)}, hangs `
      + `${secs(b.lull.endMs - b.lull.rampEndMs)}, then the drop fires on its mark.`);
  }
  if (!b.charge && !b.lull) out.push('A drop on its own: it fires on its mark with no build.');
  return out;
}

/** Each handle's time and how it relates to the analysis — the detail box.
 * `analysis` is the detector's own place for a handle (his matched
 * detection for look `mine`, the automatic place for a moved handle). */
export interface HandleRow {
  handle: Handle;
  ms: number | null;
  /** "as detected" / "placed by you" / "analysis: 0:35.05 (+2929 ms)" … */
  note: string;
}

export function handleRows(s: DisplaySeq): HandleRow[] {
  return HANDLES.map((h) => {
    const ms = s[h];
    const v = s.view;
    if (s.look === 'mine') {
      const det = v?.[`${h}_ms` as const] ?? null;
      if (ms == null) return { handle: h, ms, note: h === 'drop' ? '' : 'none of yours' };
      if (det == null) return { handle: h, ms, note: 'your trigger' };
      const d = Math.round(ms - det);
      return { handle: h, ms, note: d === 0 ? 'your trigger · analysis agrees'
        : `your trigger · analysis: ${fmtHundredths(det)} (${d > 0 ? '+' : ''}${d} ms)` };
    }
    const had = s.analysisHad[h];
    if (ms == null) {
      const off = (h === 'lull' && s.off.lull) || (h === 'charge' && s.off.charge);
      const was = s.look === 'added' ? 'was' : 'analysis';
      return { handle: h, ms, note: off ? `switched off (${was}: ${had != null ? fmtHundredths(had) : '—'})`
        : s.look === 'added' ? 'none — add one from the buttons below' : 'none — no break before this drop' };
    }
    if (had != null) {
      const d = Math.round(ms - had);
      return { handle: h, ms, note: `analysis: ${fmtHundredths(had)} (${d > 0 ? '+' : ''}${d} ms)` };
    }
    return { handle: h, ms, note: s.look === 'added' ? 'placed by you' : 'as detected' };
  });
}

// ── the pre-drop ──────────────────────────────────────────────────────────

/** A pre-drop's kind as a noun ("a spike", "a vocal intro" in a sentence). */
export const PRE_DROP_KIND_NAME: Record<PreDropKind, string> = { spike: 'spike', intro: 'vocal intro' };

/** What a pre-drop does in the room (predrop steps 5-9): when it plays —
 * its kind on and its gap inside the showing scene's window — every effect
 * with a pre-drop look plays it (Fireworks, Pulse, Orbits, Black Hole, Fish,
 * Star, Sauron and the strip phase members, fx.device_model.PRE_DROP_EFFECTS)
 * and the drop's colour change fades across it. The one wording, shared by
 * the Home Drops panel. */
export const PRE_DROP_IN_THE_ROOM = 'When a pre-drop plays, every effect with a pre-drop look (Fireworks, Pulse, Orbits, Black Hole, Fish, Star, Sauron and the strips) plays it, and the drop\'s colour change fades across it, landing on the drop. Each scene chooses which kinds play, and each device\'s look, on its Phase tab.';
/** The same, as a tooltip's tail. */
export const PRE_DROP_IN_THE_ROOM_SHORT = 'when it plays, the effects with a pre-drop look play it and the drop\'s colour fades across it';

/** How a pre-drop is drawn, following its part state the way a member's look
 * follows its tier: `his` — approved (or, from an older server with no part
 * states, placed by him) — solid; `confident` — waiting, and it will play on
 * its own — solid; `suggested` — waiting for his approval
 * (a suggested one, or one he placed and has not approved) — dashed; `off` —
 * switched off, drawn as an off member is. Null: nothing to draw. */
export type PreDropLook = 'his' | 'confident' | 'suggested' | 'off';

export function preDropLook(s: Pick<DisplaySeq, 'preDrop' | 'pre_drop'>): PreDropLook | null {
  const p = s.preDrop;
  if (!p) return null;
  if (p.off || p.part === 'off') return 'off';
  if (s.pre_drop == null) return null;
  if (p.part === 'on' || (p.part == null && p.moved)) return 'his';
  return p.tier === 'confident' ? 'confident' : 'suggested';
}

const PRE_DROP_LOOK_WORD: Record<PreDropLook, string> = {
  his: 'approved',
  confident: 'waiting · confident: it will play on its own',
  suggested: 'waiting for your approval',
  off: 'switched off · never plays',
};

/** The detail box's pre-drop row. */
export interface PreDropRow {
  /** where it sits: where it plays, or — switched off — where it comes back */
  at: number | null;
  kind: PreDropKind | null;
  /** how far before its drop it sits */
  leadMs: number | null;
  look: PreDropLook | null;
  /** "as detected" / "placed by you" / "analysis: 1:23.45 (+120 ms)" … */
  note: string;
  /** its lead, tier and part state in words, or null when there is none */
  state: string | null;
}

export function preDropRow(s: DisplaySeq): PreDropRow {
  const p = s.preDrop;
  if (!p) {
    return {
      at: null, kind: null, leadMs: null, look: null, state: null,
      note: s.preDropUnknown ? 'not worked out yet'
        : s.look === 'mine' ? 'none before your drop' : 'none — no hit or vocal entry leads into this drop',
    };
  }
  const at = s.pre_drop ?? (p.off ? p.was ?? p.auto : null);
  const leadMs = at != null ? Math.round(s.drop - at) : null;
  const look = preDropLook(s);
  let note: string;
  if (p.off) note = `switched off (comes back at ${at != null ? fmtHundredths(at) : '—'})`;
  else if (p.moved && p.auto != null && at != null && at !== p.auto) {
    const d = Math.round(at - p.auto);
    note = `analysis: ${fmtHundredths(p.auto)} (${d > 0 ? '+' : ''}${d} ms)`;
  } else if (p.moved) note = 'placed by you';
  else note = s.look === 'mine' ? 'found before your drop' : 'as detected';
  const tier = p.tier ? `${p.tier}${p.score != null ? ` (score ${p.score.toFixed(2)})` : ''}` : null;
  const bits = [leadMs != null ? `${leadMs} ms before the drop` : null, tier,
    look ? PRE_DROP_LOOK_WORD[look] : null].filter((b): b is string => !!b);
  return { at, kind: p.kind, leadMs, look, note, state: bits.length ? bits.join(' · ') : null };
}

/** The strip's hover text for one sequence. */
export function stripTitle(s: DisplaySeq): string {
  const head = s.number != null ? `${s.number} · ` : '';
  const sw = switchChip(s.view?.switch);
  const pre = s.preDrop && s.pre_drop != null
    ? ` · ${PRE_DROP_KIND_NAME[s.preDrop.kind]} pre-drop at ${fmtTenths(s.pre_drop)}` : '';
  return `${head}${fmtTenths(s.drop)} · ${LOOK_CHIP[s.look]} · ${reviewStatus(s)}${pre}${sw ? ` · ${sw}` : ''}`;
}
