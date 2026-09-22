/** Proof for the music-analysis test bed's song-search box (his ask,
 * 2026-09-22: "fix the testbed page so i can search for songs in a bar
 * instead of seeing a giant list"). spectra/web/src/testbed/songSearch.ts
 * is the pure filter/sort module the page calls; this script transpiles
 * the REAL module with esbuild and drives it directly — no DOM, no
 * framework, the scripts/check_testbed_metrics.mjs precedent for this
 * same page.
 *
 * Run: node scripts/check_testbed_song_search.mjs
 */
import { existsSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/testbed/songSearch.ts');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const out = mkdtempSync(path.join(tmpdir(), 'testbed-song-search-'));
const js = path.join(out, 'songSearch.mjs');
execFileSync('npx', ['esbuild', TS, '--format=esm', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const fe = await import(js);

function song(overrides) {
  return {
    uri: 'spotify:track:x', title: null, artist: null,
    n_transitions: 0, n_flares: 0, n_generated: 0, n_promoted: 0,
    provenance: { found: false, ai_generated: false, verified: false, editor_trigger_count: 0 },
    audio: { pinned: false, pinned_at: null, has_source_wav: false, has_peaks: false },
    engines: {},
    ...overrides,
  };
}

console.log('§1 accent- and case-insensitive matching');
{
  const apagon = song({ uri: 'spotify:track:1', title: 'El Apagón', artist: 'Bad Bunny' });
  const other = song({ uri: 'spotify:track:2', title: 'Otro Tema', artist: 'Nadie' });
  ok(fe.songMatchesQuery(apagon, 'apag'), 'unaccented "apag" matches accented "El Apagón"');
  ok(fe.songMatchesQuery(apagon, 'APAG'), 'uppercase "APAG" still matches');
  ok(fe.songMatchesQuery(apagon, 'ÁPAG'), 'an accented query itself still matches');
  ok(fe.songMatchesQuery(apagon, 'bad bunny'), 'matches on artist, not just title');
  ok(!fe.songMatchesQuery(other, 'apag'), 'a non-matching song is excluded');
  ok(fe.songMatchesQuery(other, ''), 'an empty query matches everything');
  ok(fe.songMatchesQuery(other, '   '), 'a whitespace-only query matches everything');
}

console.log('§2 filterAndSortSongs — filtering');
{
  const songs = [
    song({ uri: 'spotify:track:1', title: 'El Apagón', artist: 'Bad Bunny' }),
    song({ uri: 'spotify:track:2', title: 'Zebra Song', artist: 'Someone' }),
    song({ uri: 'spotify:track:3', title: 'Another Apagon Remix', artist: 'DJ X' }),
  ];
  const filtered = fe.filterAndSortSongs(songs, 'apag');
  ok(filtered.length === 2, `query "apag" narrows 3 songs to 2 (got ${filtered.length})`);
  ok(filtered.every((s) => /apag/i.test(s.title.normalize('NFD').replace(/[̀-ͯ]/g, ''))),
    'every result actually contains the query');
  const all = fe.filterAndSortSongs(songs, '');
  ok(all.length === 3, 'empty query returns every song');
}

console.log('§3 default ordering — comparable songs first, then alphabetical by title');
{
  const noEvidence = song({ uri: 'spotify:track:1', title: 'Zzz Last Alphabetically' });
  const pinned = song({
    uri: 'spotify:track:2', title: 'Aaa First Alphabetically',
    audio: { pinned: true, pinned_at: 123, has_source_wav: true, has_peaks: true },
  });
  const precomputed = song({
    uri: 'spotify:track:3', title: 'Mmm Middle',
    engines: { librosa: { label: 'Current (librosa)', kinds: ['section_boundary'], available: true, computed_at: 1, n_marks: null } },
  });
  const sorted = fe.filterAndSortSongs([noEvidence, pinned, precomputed], '');
  ok(sorted[0].uri === pinned.uri, 'a pinned song sorts ahead of one with no evidence');
  ok(sorted[1].uri === precomputed.uri, 'a precomputed-engine song sorts ahead of one with no evidence');
  ok(sorted[2].uri === noEvidence.uri, 'a song with neither pinned audio nor a precomputed engine sorts last');

  const pinnedZ = song({
    uri: 'spotify:track:4', title: 'Zed Pinned',
    audio: { pinned: true, pinned_at: 1, has_source_wav: true, has_peaks: true },
  });
  const pinnedA = song({
    uri: 'spotify:track:5', title: 'Abel Pinned',
    audio: { pinned: true, pinned_at: 1, has_source_wav: true, has_peaks: true },
  });
  const withinGroup = fe.filterAndSortSongs([pinnedZ, pinnedA], '');
  ok(withinGroup[0].uri === pinnedA.uri && withinGroup[1].uri === pinnedZ.uri,
    'within the "comparable" group, songs are alphabetical by title');
}

console.log('§4 songHasEvidence');
{
  ok(!fe.songHasEvidence(song({})), 'a bare song has no evidence');
  ok(fe.songHasEvidence(song({ audio: { pinned: true, pinned_at: 1, has_source_wav: true, has_peaks: true } })),
    'a pinned song has evidence');
  ok(fe.songHasEvidence(song({
    engines: { beat_this: { label: 'beat_this', kinds: ['beat'], available: true, computed_at: 1, n_marks: null } },
  })), 'a song with an available engine has evidence');
  ok(!fe.songHasEvidence(song({
    engines: { beat_this: { label: 'beat_this', kinds: ['beat'], available: false, computed_at: null, n_marks: null } },
  })), 'an unavailable engine alone is not evidence');
}

console.log(failures === 0 ? '\nAll checks passed.' : `\n${failures} failure(s).`);
process.exit(failures === 0 ? 0 : 1);
