/** Pure filter/sort helpers for the test bed's song-picker search box
 * (spectra/web/src/testbed/TestbedPage.tsx — his ask, 2026-09-22: "fix the
 * testbed page so i can search for songs in a bar instead of seeing a
 * giant list"). Kept out of React so scripts/check_testbed_song_search.mjs
 * can drive them directly with esbuild, the scripts/check_testbed_metrics.ts
 * precedent for this same page.
 *
 * Matching is case- AND accent-insensitive (his own example: "apag" must
 * find "Bad Bunny - El Apagón") via Unicode NFD decomposition, which
 * splits an accented letter into its base letter plus a separate
 * combining mark — stripping the marks after that leaves the plain
 * letter, which is what makes an unaccented query find an accented
 * title. */
import type { TestbedSong } from '../types';

export function normalizeSearchText(s: string): string {
  return s
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .trim();
}

/** Same fallback SongPickerButton's own label already uses for a song
 * with no stored title, so the default alphabetical order matches what
 * he actually sees printed on the button. */
function songLabel(song: TestbedSong): string {
  if (song.title) return song.title;
  return song.uri.split(':').pop() ?? song.uri;
}

function songSearchHaystack(song: TestbedSong): string {
  return normalizeSearchText([song.title, song.artist].filter(Boolean).join(' '));
}

export function songMatchesQuery(song: TestbedSong, query: string): boolean {
  const q = normalizeSearchText(query);
  if (!q) return true;
  return songSearchHaystack(song).includes(q);
}

/** "The ones he can actually compare" (his own phrase) — a song whose
 * audio is pinned, or that already has at least one engine's marks
 * precomputed. Reads only what /api/testbed/songs already reports; never
 * a second definition of "available" (spectra/services/testbed_engines.py
 * owns that one). */
export function songHasEvidence(song: TestbedSong): boolean {
  if (song.audio?.pinned) return true;
  return Object.values(song.engines ?? {}).some((e) => e.available);
}

/** Empty-box default order: songs he can actually compare first, then
 * everything else — each group alphabetical by title. Stable within a
 * group (Array.prototype.sort is a stable sort in every engine this app
 * ships to). */
export function compareSongsDefault(a: TestbedSong, b: TestbedSong): number {
  const ea = songHasEvidence(a) ? 0 : 1;
  const eb = songHasEvidence(b) ? 0 : 1;
  if (ea !== eb) return ea - eb;
  return songLabel(a).localeCompare(songLabel(b));
}

/** The one function the page calls: filter by the search box (empty box =
 * everything), then apply the same default ordering to whatever is
 * showing — filtered or not — so a search never surfaces an
 * un-comparable song ahead of a comparable one either. */
export function filterAndSortSongs(songs: TestbedSong[], query: string): TestbedSong[] {
  const q = normalizeSearchText(query);
  const matched = q ? songs.filter((s) => songSearchHaystack(s).includes(q)) : songs.slice();
  return matched.sort(compareSongsDefault);
}
