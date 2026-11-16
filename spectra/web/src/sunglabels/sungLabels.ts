/** The Sung labels page's pure parts, so scripts/check_sung_labels_page.mjs can
 * drive them. spectra/services/sung_labels.py is the binding statement. */
import type { SungColorSet, SungEffect, SungShape, SungChip } from '../types';

export const SOURCE_WORDS: Record<SungChip['source'], string> = {
  seed: 'From its colours and name',
  claude: 'Claude drafted this',
  his: 'You added this',
};

/** A card's words, for the search box. */
function cardText(card: SungColorSet): string {
  const meanings = Object.values(card.meanings).flat();
  return [card.name, ...card.labels, ...meanings]
    .map((x) => (typeof x === 'string' ? x : x.text)).join(' ').toLowerCase();
}

export function filterCards(cards: SungColorSet[], query: string, onlyUndrafted: boolean): SungColorSet[] {
  const q = query.trim().toLowerCase();
  return cards.filter((card) => (!onlyUndrafted || isUndrafted(card))
    && (!q || cardText(card).includes(q)));
}

export function filterEffects(effects: SungEffect[], query: string): SungEffect[] {
  const q = query.trim().toLowerCase();
  if (!q) return effects;
  return effects.filter((e) => [e.name, ...e.labels.map((l) => l.text)].join(' ').toLowerCase().includes(q));
}

/** Each shape's glyph, by the id the shape library gives it
 * (fx/effects/word_shapes.py's `build(...)` calls). A shape the library grows
 * later still gets a card and a mark the moment it is added there — that is
 * what `SHAPE_FALLBACK_GLYPH` is for ("make it easy to add more shapes and
 * associations down the road"); give the new one its own glyph here when it
 * deserves better than the fallback. */
export const SHAPE_GLYPHS: Record<string, string> = {
  heart: '♥', star: '★', diamond: '◆',
};
export const SHAPE_FALLBACK_GLYPH = '◇';

export function shapeGlyph(id: string): string {
  return SHAPE_GLYPHS[id] ?? SHAPE_FALLBACK_GLYPH;
}

export function filterShapes(shapes: SungShape[], query: string): SungShape[] {
  const q = query.trim().toLowerCase();
  if (!q) return shapes;
  return shapes.filter((s) => [s.name, ...s.labels.map((l) => l.text)].join(' ').toLowerCase().includes(q));
}

/** The form two words are compared in, mirroring
 * spectra/services/colour_words.py's `word_key`: lower case, no accents, no
 * apostrophes, other punctuation as a space. So "Corazón" and "corazon" are
 * one word here exactly as they are one label there. */
export function wordKey(text: string): string {
  return (text || '').normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase()
    .replace(/['’`]/g, '').replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
}

/** The words on this shape that an effect answers to as well ("star" on the
 * Star shape and on the radial effect). Computed over EVERY effect, never the
 * search's filtered list: the note on a card must not change as he types.
 * spectra/services/sung_labels.py's PRECEDENCE is the rule it reports — the
 * shape owns a shared word, and the effect keeps it on its own card until he
 * takes it off. */
export function shapeClashWords(shape: SungShape, effects: SungEffect[]): string[] {
  const taken = new Set(effects.flatMap((e) => e.labels.map((l) => wordKey(l.text))));
  return shape.labels.map((l) => l.text).filter((text) => taken.has(wordKey(text)));
}

/** That precedence, as the one line the card prints. */
export function shapeClashNote(words: string[]): string | null {
  if (!words.length) return null;
  const quoted = words.map((w) => `“${w}”`);
  const list = quoted.length === 1 ? quoted[0]
    : `${quoted.slice(0, -1).join(', ')} and ${quoted[quoted.length - 1]}`;
  const names = words.length === 1 ? 'also names an effect' : 'also name an effect';
  return `${list} ${names} — the shape is the one the show follows.`;
}

/** A card waiting for Claude's draft. One with no colours has nothing to mean. */
export function isUndrafted(card: SungColorSet): boolean {
  return card.has_colours && card.drafted_ms == null;
}

export function undraftedIds(cards: SungColorSet[]): string[] {
  return cards.filter(isUndrafted).map((c) => c.id);
}

export function draftableIds(cards: SungColorSet[]): string[] {
  return cards.filter((c) => c.has_colours).map((c) => c.id);
}

/** Drafting goes a batch at a time, one request each, so closing the page
 * simply stops and pressing again carries on. */
export function batches<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

export function draftButtonWords(nUndrafted: number, nDraftable: number, nRetry = 0): string {
  if (nRetry > 0) return `Retry ${nRetry} colour ${nRetry === 1 ? 'set' : 'sets'} that failed`;
  if (nUndrafted > 0) return `Draft meanings for ${nUndrafted} colour ${nUndrafted === 1 ? 'set' : 'sets'}`;
  return `Draft all ${nDraftable} again`;
}

export interface DraftBatchResult { drafted: number; ids: string[]; skipped: string[] }

export interface DraftQueueOutcome {
  /** Ids a batch's response actually confirmed as drafted. */
  draftedIds: string[];
  /** Ids whose batch either rejected them (no colours, etc.) or whose
   * request itself failed (a timeout/502) and so could not be confirmed —
   * offered again on the next press, never silently retried on their own. */
  failedIds: string[];
  /** The raw errors from failed requests, most recent last — used only to
   * decide the summary's wording (see `draftFailureHint`). */
  errors: unknown[];
}

/** Drafts `ids` a batch at a time. One failed batch (a timeout, a 502) does
 * not stop the rest: it moves on to the next batch and reports the failure
 * truthfully rather than losing it. */
export async function runDraftQueue(
  ids: string[],
  batchSize: number,
  draftBatch: (ids: string[]) => Promise<DraftBatchResult>,
  onProgress?: (done: number, total: number) => void,
): Promise<DraftQueueOutcome> {
  const draftedIds: string[] = [];
  const failedIds: string[] = [];
  const errors: unknown[] = [];
  let done = 0;
  for (const batch of batches(ids, batchSize)) {
    try {
      const result = await draftBatch(batch);
      draftedIds.push(...result.ids);
      failedIds.push(...result.skipped);
    } catch (err) {
      failedIds.push(...batch);
      errors.push(err);
    }
    done += batch.length;
    onProgress?.(done, ids.length);
  }
  return { draftedIds, failedIds, errors };
}

/** True for the proxy's own 502/504 — a batch that took too long to answer,
 * not a genuine rejection. services/spectra_proxy.py's READ_TIMEOUT_S is the
 * 60s budget DRAFT_BATCH_SIZE is sized to stay under; this only fires if a
 * batch ran unusually slow anyway. */
export function isDraftTimeoutError(err: unknown): boolean {
  const status = (err as { status?: number } | null | undefined)?.status;
  return status === 502 || status === 504;
}

/** The outcome's summary toast: how many drafted, how many failed, and
 * whether the failures were the proxy giving up (the sets may still have
 * saved) rather than a real rejection. Never claims the backend process is
 * down — that is the proxy's own wording, not what happened here. */
export function draftOutcomeMessage(outcome: DraftQueueOutcome, total: number): string | null {
  if (!outcome.failedIds.length) return null;
  const hint = outcome.errors.some(isDraftTimeoutError)
    ? 'a batch took too long to answer; any sets in it may still have been saved'
    : 'some sets could not be drafted';
  return `Drafted ${outcome.draftedIds.length} of ${total} colour sets; `
    + `${outcome.failedIds.length} failed (${hint}). Press Draft to retry just those.`;
}
