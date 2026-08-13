/** Tiny dependency-free fuzzy matcher for the Help page search.
 *
 * Strategy (per query token, against a haystack of words):
 *   1. exact substring        → best score
 *   2. word-prefix match      → strong score
 *   3. edit distance ≤ 1–2    → typo tolerance ("pallete" → "palette")
 *   4. subsequence match      → weak score ("clrset" → "color set")
 * All query tokens must match somewhere for the haystack to count as a hit
 * (AND semantics). Scores accumulate so better matches sort first.
 */

const normalize = (s: string) =>
  s
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '');

/** Damerau–Levenshtein distance, capped early at `max` for speed. */
function editDistance(a: string, b: string, max: number): number {
  if (Math.abs(a.length - b.length) > max) return max + 1;
  const m = a.length;
  const n = b.length;
  let prev2: number[] = [];
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const cur = [i];
    let rowMin = i;
    for (let j = 1; j <= n; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      let v = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
      // transposition ("teh" → "the")
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        v = Math.min(v, prev2[j - 2] + 1);
      }
      cur.push(v);
      if (v < rowMin) rowMin = v;
    }
    if (rowMin > max) return max + 1;
    prev2 = prev;
    prev = cur;
  }
  return prev[n];
}

function isSubsequence(needle: string, hay: string): boolean {
  let i = 0;
  for (let j = 0; j < hay.length && i < needle.length; j++) {
    if (hay[j] === needle[i]) i++;
  }
  return i === needle.length;
}

/** Score one query token against one haystack word. 0 = no match. */
function tokenWordScore(token: string, word: string): number {
  if (word === token) return 100;
  if (word.startsWith(token)) return 80;
  if (word.includes(token)) return 60;
  // typo tolerance: allow 1 edit for short tokens, 2 for longer ones
  if (token.length >= 3) {
    const max = token.length >= 6 ? 2 : 1;
    const d = editDistance(token, word, max);
    if (d <= max) return 50 - d * 10;
    // prefix typo: "palete" should still hit "palettes"
    if (word.length > token.length) {
      const dp = editDistance(token, word.slice(0, token.length), max);
      if (dp <= max) return 40 - dp * 10;
    }
  }
  if (token.length >= 4 && isSubsequence(token, word)) return 15;
  return 0;
}

/**
 * Score a whole query against a haystack string.
 * Returns 0 when any query token fails to match; otherwise a positive score.
 */
export function fuzzyScore(query: string, haystack: string): number {
  const tokens = normalize(query).split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return 1;
  const words = normalize(haystack).split(/[^a-z0-9+#?*<>!@/.-]+/).filter(Boolean);
  // Non-alphanumeric queries (e.g. "!" or "*") fall back to raw substring.
  const rawHay = normalize(haystack);
  let total = 0;
  for (const token of tokens) {
    let best = 0;
    for (const word of words) {
      const s = tokenWordScore(token, word);
      if (s > best) best = s;
      if (best === 100) break;
    }
    if (best === 0 && rawHay.includes(token)) best = 60;
    if (best === 0) return 0; // AND semantics
    total += best;
  }
  return total / tokens.length;
}
