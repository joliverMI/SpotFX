/** The Sung labels page's pure parts, so scripts/check_sung_labels_page.mjs can
 * drive them. spectra/services/sung_labels.py is the binding statement. */
import type { SungColorSet, SungEffect, SungChip } from '../types';

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

export function draftButtonWords(nUndrafted: number, nDraftable: number): string {
  if (nUndrafted > 0) return `Draft meanings for ${nUndrafted} colour ${nUndrafted === 1 ? 'set' : 'sets'}`;
  return `Draft all ${nDraftable} again`;
}
