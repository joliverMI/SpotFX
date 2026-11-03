/** Executable spec: sonicErrorDetail() (spectra/web/src/lib/sonicPreview.ts)
 * -- the 2026-11-02 hardening's UI half (data/sonic-jukebox-unresponsive/
 * report.md): the chat's catch block must show the SERVER's own refusal
 * sentence instead of the hard-coded, backend-wrong "is ANTHROPIC_API_KEY
 * configured?" hint.
 *
 * Transpiles the REAL pure module with esbuild and drives it directly --
 * the followWindow.ts/touchPan.ts precedent (scripts/check_timeline_
 * touch_pan.mjs). No DOM, no network.
 *
 * Run: node scripts/check_sonic_error_detail.mjs
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/lib/sonicPreview.ts');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const out = mkdtempSync(path.join(tmpdir(), 'sonic-error-detail-'));
const js = path.join(out, 'sonicPreview.mjs');
execFileSync('npx', ['esbuild', TS, '--format=esm', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const fe = await import(js);

console.log('\n§1 THE SERVER\'S OWN SENTENCE, NOT A HARD-CODED HINT');
const degraded = fe.sonicErrorDetail(new Error(
  "POST /spectra/api/settings-console/message → 503: Sonic is running in reduced mode: "
  + "SPECTRA is running older code than Sonic's tools (extra: put_on_tv). Restart SPECTRA "
  + "to bring Sonic fully back."));
ok(degraded.startsWith('Sonic is running in reduced mode'), 'strips the "METHOD url → status:" prefix, keeps the real sentence');
ok(!degraded.includes('ANTHROPIC_API_KEY'), 'never mentions the api-backend-only hint for a cli-backend refusal');
ok(degraded.endsWith('(extra: put_on_tv).'), 'takes the FIRST sentence only, not the whole multi-sentence detail');

console.log('\n§2 A ONE-SENTENCE MESSAGE (THE COMMON SHAPE) PASSES THROUGH WHOLE');
const apiKey = fe.sonicErrorDetail(new Error(
  'POST /spectra/api/settings-console/message → 503: no ANTHROPIC_API_KEY configured — Sonic has no model to talk to yet'));
ok(apiKey === 'no ANTHROPIC_API_KEY configured — Sonic has no model to talk to yet',
  'a single-sentence detail (no period) passes through whole, not truncated mid-word');

console.log('\n§3 A PLAIN ERROR WITH NO "METHOD url → status:" PREFIX STILL WORKS');
ok(fe.sonicErrorDetail(new Error('settings-agent CLI call timed out')) === 'settings-agent CLI call timed out',
  'an error with no fetch-style prefix is used as-is');

console.log('\n§4 THE FALLBACK NEVER THROWS ON SOMETHING UNEXPECTED');
ok(fe.sonicErrorDetail(new Error('')).length > 0, 'an empty message still produces a non-empty fallback sentence');
ok(fe.sonicErrorDetail(null).length > 0, 'a non-Error value never throws and still produces a sentence');
ok(fe.sonicErrorDetail(undefined).length > 0, 'undefined never throws either');

console.log('\n§5 A RUNAWAY-LONG DETAIL IS CAPPED, NEVER DUMPED');
const huge = 'x'.repeat(5000);
const capped = fe.sonicErrorDetail(new Error(`POST /x → 503: ${huge}`));
ok(capped.length < 300, `a 5000-char detail is capped to a short line (got ${capped.length} chars)`);
ok(capped.endsWith('…'), 'a capped line is marked with an ellipsis, never silently cut with no indication');

console.log(failures === 0 ? '\nPASS' : `\nFAIL (${failures})`);
process.exit(failures === 0 ? 0 : 1);
