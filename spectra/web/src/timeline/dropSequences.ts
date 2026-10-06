/** DROP SEQUENCES ON THE TIMELINE — the pure half of the sequence layer,
 * the full-song strip and the review list (drop-detection plan, phase 3:
 * /home/javi/fleet-spotfx/data/drop-detection-plan/report.md section 8,
 * built to plan.html's Timeline mock). What a hand on a sequence DOES
 * (drag, snap, add, undo — phase 4) is ./dropEdit.ts; nothing detected
 * fires yet (phase 5).
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
 *   triggers fire today; a confirmed, edited or added sequence will fire
 *   wherever his triggers fire; a CONFIDENT detection will fire only on a
 *   song that plays the analysed show (`analysedApplies`, the analysed
 *   plan's own `applies`); a suggestion waits for his confirm. Numbered
 *   pills are the ones that fire or will, in time order; a suggestion is
 *   "?", a confident detection this song will not play is "✦".
 *
 * THE BUILD each charge and lull is drawn with is the engine's own
 * arithmetic — phaseBlendSpan from ./phaseBlend.ts (scene_response.
 * _phase_ramp_ms, mirrored and drift-checked there): a sequence member
 * builds to its OWN partner (a charge to its lull, or its drop when it has
 * no lull; a lull to its drop), the phase-partner rule.
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

// ── the wire (spectra/services/drop_sequences.py) ─────────────────────────

export type DropServerState =
  | 'confident' | 'suggested' | 'confirmed' | 'edited' | 'added' | 'matches_yours' | 'dismissed';

export type Handle = 'charge' | 'lull' | 'drop';
export const HANDLES: Handle[] = ['charge', 'lull', 'drop'];

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
  moved: Partial<Record<Handle, boolean>>;
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
}

export interface AuthoredGroup {
  charge: HisMark | null;
  lull: HisMark | null;
  drop: HisMark;
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
}

// ── the display model ─────────────────────────────────────────────────────

export type SeqLook =
  | 'confident' | 'suggested' | 'confirmed' | 'edited' | 'added' | 'mine' | 'dismissed';

/** fires = his own triggers, firing as they always have (wherever the
 * room's "Scene changes" setting fires his triggers). will_fire = fires once detected
 * sequences go live (phase 5). muted = a confident detection on a song that
 * plays only his own triggers. waits = a suggestion, waiting for his
 * confirm. stands_down = a detection on one of his lone phase triggers. */
export type FireStatus = 'fires' | 'will_fire' | 'muted' | 'waits' | 'stands_down' | 'dismissed';

export interface DisplaySeq {
  /** unique across the song: the detection's key, an added id, or
   * "his:<his drop trigger id>" */
  key: string;
  look: SeqLook;
  charge: number | null;
  lull: number | null;
  drop: number;
  /** where the analysis had each MOVED (or switched-off) handle — the dotted
   * line. Only handles he changed appear here. */
  analysisHad: Partial<Record<Handle, number>>;
  off: { charge: boolean; lull: boolean };
  fire: FireStatus;
  /** 1-based, in time order, for sequences that fire or will; else null */
  number: number | null;
  /** the strip pill / review-list badge text: the number, "?", "✦" or "✕" */
  badge: string;
  /** the detection: its own, or (look `mine`) the one that matched him */
  view: DropSequenceView | null;
  his: AuthoredGroup | null;
}

const TIER_LOOK: Record<string, SeqLook> = { confident: 'confident', suggested: 'suggested' };

function lookOf(v: DropSequenceView): SeqLook {
  switch (v.state) {
    case 'confirmed': case 'edited': case 'added': case 'dismissed': return v.state;
    case 'confident': case 'suggested': return v.state;
    default: return TIER_LOOK[v.tier ?? 'suggested'] ?? 'suggested';
  }
}

function fireOf(look: SeqLook, analysedApplies: boolean): FireStatus {
  switch (look) {
    case 'mine': return 'fires';
    case 'confirmed': case 'edited': case 'added': return 'will_fire';
    case 'confident': return analysedApplies ? 'will_fire' : 'muted';
    case 'suggested': return 'waits';
    default: return 'dismissed';
  }
}

export function sequenceFires(s: Pick<DisplaySeq, 'fire'>): boolean {
  return s.fire === 'fires' || s.fire === 'will_fire';
}

function analysisHad(v: DropSequenceView): Partial<Record<Handle, number>> {
  const out: Partial<Record<Handle, number>> = {};
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
  return {
    key: v.key, look,
    charge: v.charge_ms, lull: v.lull_ms, drop: v.drop_ms,
    analysisHad: analysisHad(v),
    off: { charge: !!v.charge_off, lull: !!v.lull_off },
    fire: fireOf(look, analysedApplies),
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
    out.push({
      key: `his:${g.drop.id}`, look: 'mine',
      charge: g.charge?.timestamp_ms ?? null, lull: g.lull?.timestamp_ms ?? null,
      drop: g.drop.timestamp_ms, analysisHad: {}, off: { charge: false, lull: false },
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

export function firstHandleMs(s: Pick<DisplaySeq, 'charge' | 'lull' | 'drop'>): number {
  return s.charge ?? s.lull ?? s.drop;
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
  s: Pick<DisplaySeq, 'charge' | 'lull' | 'drop'>, beatMs: number | null | undefined,
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
  if (s.look === 'confirmed') return `confirmed by you${flag}`;
  if (s.look === 'edited') return `edited by you${flag}`;
  if (s.look === 'added') return 'added by you';
  if (s.look === 'dismissed') return 'dismissed · not a drop';
  const near = v?.his_marks_near ?? [];
  if (near.length) return `you have a ${markName(near[0].kind)} here`;
  if (s.look === 'confident') {
    return s.fire === 'muted'
      ? 'detected · this song plays only your own triggers'
      : 'detected · fires with the analysed show';
  }
  return 'suggested · waits for your confirm';
}

/** One line on what firing this sequence means — the honest version for a
 * read-only phase: nothing detected fires yet. */
export function fireLine(s: DisplaySeq): string {
  switch (s.fire) {
    case 'fires': return 'Your own triggers — they fire wherever your triggers fire (your "Scene changes" setting decides that), exactly as they always have.';
    case 'will_fire': return s.look === 'confident'
      ? 'Confident: once detected drops go live it fires on its own, because this song plays the analysed show. It does not fire yet.'
      : 'Yours: once detected drops go live it fires wherever your triggers fire. It does not fire yet.';
    case 'muted': return 'Confident, but this song plays only your own triggers, so it would not fire here. It does not fire yet in any case.';
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

/** The strip's hover text for one sequence. */
export function stripTitle(s: DisplaySeq): string {
  const head = s.number != null ? `${s.number} · ` : '';
  return `${head}${fmtTenths(s.drop)} · ${LOOK_CHIP[s.look]} · ${reviewStatus(s)}`;
}
