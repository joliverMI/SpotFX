/** THE PRE-DROP WINDOWS AND LOOKS, the pure half (predrop plan step 5) —
 * what the Phase tab's Pre-drops card (PreDropControls.tsx) and the
 * drop-sequence preview (SequencePreviewOverlay.tsx) both read: one
 * definition of a scene's window per kind, of an edit to it that may be
 * written, of the looks an entry may pick, and of what the preview sends.
 *
 * Every bound and default is the server's (/api/registry `pre_drop.kinds`,
 * read off spectra/models/scene.py's own PreDropSpikeWindow /
 * PreDropIntroWindow fields); FALLBACK_KINDS mirrors them only for a server
 * too old to send them. Whether a pre-drop PLAYS is never decided here —
 * spectra/services/pre_drop_play.py is the one rule, and the preview shows
 * its answer.
 *
 * DOM-free, so scripts/check_pre_drop_phase_tab.mjs drives it directly. */
import type { IconName } from '../../components/Icon';
import type { SequencePreviewPreDrop, SequencePreviewPreDropRequest } from '../../queries';
import { PRE_DROP_KIND_NAME, type PreDropKind } from '../../timeline/dropSequences';
import type {
  PreDropKindMeta, PreDropLooks, PreDropLooksDecl, PreDropWindow, Registry, SceneDeviceConfig, SceneV2,
} from '../../types';

export const PRE_DROP_KINDS: PreDropKind[] = ['spike', 'intro'];

/** The model's own bounds and defaults per kind, for a server that does not
 * send `pre_drop` in its registry. */
export const FALLBACK_KINDS: Record<PreDropKind, PreDropKindMeta> = {
  spike: { label: 'Spike', min_bound: 250, max_bound: 3000, default_min_ms: 350, default_max_ms: 2000 },
  intro: { label: 'Vocal intro', min_bound: 350, max_bound: 4500, default_min_ms: 350, default_max_ms: 4000 },
};

/** Each kind's glyph — the one the Timeline and the Drops panel use. */
export const KIND_ICON: Record<PreDropKind, IconName> = { spike: 'preDrop', intro: 'preDropVoice' };

/** Where the preview's gap slider starts for each kind, before it is
 * clamped into the scene's window. */
export const DEFAULT_PREVIEW_GAP_MS: Record<PreDropKind, number> = { spike: 800, intro: 2000 };

export const AUTO_LOOKS: PreDropLooks = { spike: 'auto', intro: 'auto' };

export function kindMeta(registry: Registry | undefined, kind: PreDropKind): PreDropKindMeta {
  return registry?.pre_drop?.kinds?.[kind] ?? FALLBACK_KINDS[kind];
}

/** The scene's window for a kind: its own, else the kind's default. */
export function windowFor(scene: SceneV2, kind: PreDropKind, registry?: Registry): PreDropWindow {
  const own = kind === 'spike' ? scene.pre_drop_spike : scene.pre_drop_intro;
  if (own) return own;
  const m = kindMeta(registry, kind);
  return { enabled: true, min_ms: m.default_min_ms, max_ms: m.default_max_ms };
}

export function withWindow(scene: SceneV2, kind: PreDropKind, win: PreDropWindow): SceneV2 {
  return kind === 'spike' ? { ...scene, pre_drop_spike: win } : { ...scene, pre_drop_intro: win };
}

export type WindowEdit = { ok: true; window: PreDropWindow } | { ok: false; note: string };

/** One edit to a window's shortest (`min_ms`) or longest (`max_ms`) gap: a
 * number of milliseconds inside the kind's bounds that keeps the shortest
 * below the longest. Anything else is refused with the sentence the card
 * shows, and nothing is written — the model would refuse it on Save. */
export function editWindow(
  win: PreDropWindow, field: 'min_ms' | 'max_ms', raw: string, meta: PreDropKindMeta,
): WindowEdit {
  const text = raw.trim();
  const v = Number(text);
  if (text === '' || !Number.isFinite(v)) {
    return { ok: false, note: 'That needs a number of milliseconds — not applied.' };
  }
  const ms = Math.round(v);
  if (ms < meta.min_bound || ms > meta.max_bound) {
    return { ok: false,
      note: `A ${meta.label.toLowerCase()} window runs ${meta.min_bound}-${meta.max_bound} ms, so ${ms} ms was not applied.` };
  }
  const next = { ...win, [field]: ms };
  if (next.min_ms >= next.max_ms) {
    return { ok: false, note: field === 'min_ms'
      ? `The shortest gap must stay below the longest (${win.max_ms} ms), so ${ms} ms was not applied.`
      : `The longest gap must stay above the shortest (${win.min_ms} ms), so ${ms} ms was not applied.` };
  }
  return { ok: true, window: next };
}

export function looksFor(entry: SceneDeviceConfig): PreDropLooks {
  return entry.pre_drop_looks ?? AUTO_LOOKS;
}

export function withLook(scene: SceneV2, entryId: string, kind: PreDropKind, look: string): SceneV2 {
  return {
    ...scene,
    devices: scene.devices.map((d) => (d.id === entryId
      ? { ...d, pre_drop_looks: { ...looksFor(d), [kind]: look } } : d)),
  };
}

export interface LookOption {
  value: string;
  label: string;
}

/** The looks an entry may pick for a kind: "auto" (the effect's own
 * recommendation, named when it declares one), every look the effect
 * declares for the kind, and — the vocal intro only — "same" (wear whatever
 * the spike resolves to). `current` is kept even when the effect no longer
 * declares it, so the select never silently shows another value. Null = the
 * effect declares no looks at all: its lull plays as before. */
export function lookOptions(
  decl: PreDropLooksDecl | undefined, kind: PreDropKind, current?: string,
): LookOption[] | null {
  const looks = decl?.looks ?? {};
  if (Object.keys(looks).length === 0) return null;
  const autoName = decl?.auto?.[kind];
  const autoLabel = autoName ? looks[autoName]?.label || autoName : null;
  const out: LookOption[] = [
    { value: 'auto', label: autoLabel ? `Recommended (${autoLabel})` : 'Recommended' },
  ];
  for (const [name, look] of Object.entries(looks)) {
    if ((look.kinds ?? []).includes(kind)) out.push({ value: name, label: look.label || name });
  }
  if (kind === 'intro') out.push({ value: 'same', label: 'Same as spike' });
  if (current && !out.some((o) => o.value === current)) {
    out.push({ value: current, label: `${current} (not declared by this effect)` });
  }
  return out;
}

/** The muted line for an entry whose effect declares no pre-drop look. */
export function noLooksLine(effectType: string): string {
  return `${effectType || 'This entry'} has no pre-drop look yet — its lull plays as before`;
}

export function clampGap(gapMs: number, win: PreDropWindow): number {
  return Math.min(win.max_ms, Math.max(win.min_ms, Math.round(gapMs)));
}

/** What the drop-sequence preview sends about the pre-drop: the kind to try
 * (null = none) and its gap, with the scene DRAFT's windows and every
 * entry's looks, so an unsaved edit on the card plays at once. */
export function previewPreDropRequest(
  scene: SceneV2, kind: PreDropKind | null, gapMs: number, registry?: Registry,
): SequencePreviewPreDropRequest {
  return {
    pre_drop_kind: kind,
    pre_drop_gap_ms: gapMs,
    pre_drop_spike: windowFor(scene, 'spike', registry),
    pre_drop_intro: windowFor(scene, 'intro', registry),
    pre_drop_looks: Object.fromEntries(scene.devices.map((d) => [d.id, looksFor(d)])),
  };
}

/** The preview's line about its pre-drop: the server's own sentence, else
 * one said plainly from whether this scene plays it. */
export function preDropSentence(p: SequencePreviewPreDrop): string {
  if (p.sentence) return p.sentence;
  const what = `A ${PRE_DROP_KIND_NAME[p.kind]} ${p.gap_ms} ms before the drop`;
  return p.plays
    ? `${what} plays on this scene: the drop's colour change fades across it.`
    : `${what} does not play on this scene${p.reason ? ` (${p.reason})` : ''}: the lull runs as before`
      + ' and the drop\'s colour change is instant.';
}
