/** THE WORD SHAPE PREVIEW's pure parts (Word Shapes row W2.1) — the shape
 * picker's options and the three spans its ruler draws, split out of
 * FlarePreviewOverlay so both are provable without a browser
 * (scripts/check_scenes_words_tab.mjs).
 *
 * IT COMPUTES NO TIME OF ITS OWN, the rule the whole preview system rests
 * on (PreviewRuler.tsx's own header): every second below is read straight
 * off the server's timeline — `fire_at_s` (the write, a form before the
 * word), `trigger_mark_s` (the word itself) and the three times in
 * `word_shape` (the room's own settings, Energy-paced for this intensity by
 * spectra/services/scene_response.preview_word_shape). The drawing and the
 * firing can therefore never disagree about when the shape completes.
 *
 * WHY THIS TYPE NEEDS ITS OWN SPANS AT ALL. Every other kind's ruler is
 * drawn from `animation_start_s`/`animation_end_s`, which are null when the
 * kind produced no writes — and a `word_shape` kind produces none until
 * wave 1 wires an effect into fx.device_model.WORD_SHAPE_EFFECTS. The
 * shape's timing is the ROOM's, not the fixture's, so the ruler must still
 * tell him the truth about it (flare_preview.word_shape_effect_ms's own
 * reasoning), which means reading the envelope rather than the writes. */
import type { FlarePreviewTimeline } from '../../queries';
import type { SungShape } from '../../types';

/** The shape the picker starts on — the plan's own first shape, and the
 * server's default when the picker sends nothing
 * (scene_response.PREVIEW_SHAPE). Never a list of three ids: the shape
 * LIBRARY is the one source of what exists (fx/effects/word_shapes.py, read
 * by GET /api/sung-labels' `shapes` rows), so a fourth shape added there
 * appears here with no frontend change. */
export const PREFERRED_PREVIEW_SHAPE = 'heart';

export interface ShapeOption { id: string; name: string; }

/** The picker's options, in the library's own declaration order. */
export function shapePickerOptions(shapes: SungShape[] | undefined | null): ShapeOption[] {
  return (shapes ?? [])
    .filter((s) => !!s && typeof s.id === 'string' && s.id !== '')
    .map((s) => ({ id: s.id, name: s.name || s.id }));
}

/** Which option is selected before he touches anything: heart when the
 * library has it, otherwise the first shape it does have, and null for a
 * library that answered with nothing (then the preview sends no shape and
 * the server picks its own default). */
export function pickDefaultShape(options: ShapeOption[],
                                 preferred = PREFERRED_PREVIEW_SHAPE): string | null {
  if (!options.length) return null;
  return options.some((o) => o.id === preferred) ? preferred : options[0].id;
}

export interface WordShapeSpan {
  from_s: number;
  to_s: number;
  /** His words for this stretch: "forms" / "holds" / "releases". */
  label: string;
}

export interface WordShapeMarks {
  shape: string;
  form_s: number;
  hold_s: number;
  release_s: number;
  /** The write goes out here — a form before the word. */
  start_s: number;
  /** THE WORD: the trigger mark, where the shape stands complete. */
  word_s: number;
  hold_end_s: number;
  /** The shape is gone here. */
  end_s: number;
  spans: WordShapeSpan[];
  /** The shortest ruler that shows the whole envelope with a little room
   * after it — the caller takes the larger of this and the server's own
   * duration_s, exactly as "⇥ Extend" does. */
  needed_duration_s: number;
}

/** Zero only when a shape stands for no time at all; the pad below keeps
 * the "releases" label from sitting on the ruler's own edge. */
const TAIL_PAD_S = 0.5;

/** The ruler's three spans and four moments for a `word_shape` kind, or
 * null for any other kind (the caller then draws its ordinary
 * start/end markers). `word_s` is the server's trigger mark, which for this
 * type is the animation anchor itself: the Words section fires its band
 * atomically, so a per-kind offset never moves it (flare_preview's
 * `offset_ms = 0 if kind.type == "word_shape"`). */
export function wordShapeMarks(timeline: FlarePreviewTimeline | null): WordShapeMarks | null {
  if (!timeline || timeline.kind_type !== 'word_shape') return null;
  const ws = timeline.word_shape;
  if (!ws) return null;
  const form_s = Math.max(0, ws.form_s);
  const hold_s = Math.max(0, ws.hold_s);
  const release_s = Math.max(0, ws.release_s);
  // fire_at_s IS word − form by construction for this type (the form is the
  // lead — flare_preview.fire_at_s), so the word is read from the mark and
  // the start from the write, never re-derived from one another.
  const word_s = timeline.trigger_mark_s;
  const start_s = timeline.fire_at_s;
  const hold_end_s = word_s + hold_s;
  const end_s = hold_end_s + release_s;
  const spans: WordShapeSpan[] = [];
  if (word_s > start_s) spans.push({ from_s: start_s, to_s: word_s, label: 'forms' });
  if (hold_s > 0) spans.push({ from_s: word_s, to_s: hold_end_s, label: 'holds' });
  if (release_s > 0) spans.push({ from_s: hold_end_s, to_s: end_s, label: 'releases' });
  return {
    shape: ws.shape,
    form_s, hold_s, release_s,
    start_s, word_s, hold_end_s, end_s,
    spans,
    needed_duration_s: end_s + TAIL_PAD_S,
  };
}

/** The sentence under the ruler. Reads the envelope out loud so the three
 * spans are explainable without hovering anything. */
export function wordShapeSentence(marks: WordShapeMarks, shapeName?: string): string {
  const ms = (s: number) => `${Math.round(s * 1000)} ms`;
  return `The ${shapeName || marks.shape} forms over ${ms(marks.form_s)} and stands `
    + `complete ON the word, holds ${ms(marks.hold_s)}, then releases over `
    + `${ms(marks.release_s)}.`;
}

/** The save's advisory warnings that name this kind (scene_store.
 * scene_warnings quotes a kind's name in single quotes). Pure so the card's
 * inline note is provable without a DOM. */
export function warningsForKind(warnings: string[] | undefined | null,
                                kindName: string): string[] {
  return (warnings ?? []).filter((w) => w.includes(`'${kindName}'`));
}

/** The warnings that name NO declared kind — shown once above the sections
 * rather than dropped, so a warning this editor doesn't recognise is still
 * seen. */
export function warningsNamingNoKind(warnings: string[] | undefined | null,
                                     kindNames: string[]): string[] {
  return (warnings ?? []).filter(
    (w) => !kindNames.some((name) => w.includes(`'${name}'`)));
}
