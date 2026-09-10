/** Cross-language parity proof for the music-analysis test bed's P/R/F1
 * matcher (data/spotfx-music-analysis-plan/report.md, Part 2.6's own
 * recommendation: "one battle-tested implementation, not two that can
 * silently drift"). spectra/services/testbed_metrics.py is the reference;
 * spectra/web/src/testbed/metrics.ts is a deliberate byte-for-byte TS port
 * (the frontend recomputes locally on every tolerance-slider drag).
 *
 * This script transpiles the REAL frontend module with esbuild, drives it
 * against a fixed set of vectors, drives the REAL Python module against
 * the SAME vectors via a subprocess, and asserts the two agree exactly —
 * so a change to the matching rule on either side that isn't mirrored on
 * the other goes red here.
 *
 * Run: node scripts/check_testbed_metrics.mjs
 * Interpreter: $PYTHON, else the repo's own .venv/bin/python, else
 * python3 — a disposable worktree carries no .venv (the filesystem is
 * isolated, the toolchain is not), and a parity proof that cannot run
 * there is a parity proof nobody runs.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'spectra/web/src/testbed/metrics.ts');
const VENV_PY = path.join(REPO, '.venv/bin/python');
const PYTHON = process.env.PYTHON || (existsSync(VENV_PY) ? VENV_PY : 'python3');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const out = mkdtempSync(path.join(tmpdir(), 'testbed-metrics-'));
const js = path.join(out, 'metrics.mjs');
execFileSync('npx', ['esbuild', TS, '--format=esm', `--outfile=${js}`], {
  cwd: path.join(REPO, 'spectra/web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const fe = await import(js);

const VECTORS = [
  { ref: [1000, 2000, 3000], est: [1000, 2000, 3000], tol: 100 },
  { ref: [1000, 2000], est: [50000, 60000], tol: 500 },
  { ref: [], est: [1000], tol: 500 },
  { ref: [1000], est: [], tol: 500 },
  { ref: [1000], est: [900, 950, 1050, 1100], tol: 200 },
  { ref: [1000, 2000], est: [900, 1010], tol: 150 },
  { ref: [1000, 2000], est: [1050], tol: 200 },
  { ref: [1000, 2000, 3000, 4000, 4500], est: [980, 2600, 2990, 4600], tol: 300 },
];

const pyScript = `
import json, sys
sys.path.insert(0, ${JSON.stringify(REPO)})
from spectra.services.testbed_metrics import match_marks, match_result_dict
vectors = json.loads(sys.stdin.read())
out = []
for v in vectors:
    r = match_marks(v["ref"], v["est"], v["tol"])
    out.append(match_result_dict(r))
print(json.dumps(out))
`;
const pyOutRaw = execFileSync(PYTHON, ['-c', pyScript], {
  cwd: REPO, input: JSON.stringify(VECTORS), encoding: 'utf8',
});
const pyResults = JSON.parse(pyOutRaw);

VECTORS.forEach((v, i) => {
  const tsResult = fe.matchMarks(v.ref, v.est, v.tol);
  const py = pyResults[i];
  const label = `vector ${i}: ref=${JSON.stringify(v.ref)} est=${JSON.stringify(v.est)} tol=${v.tol}`;
  ok(Math.abs(tsResult.precision - py.precision) < 1e-9, `${label} — precision matches`);
  ok(Math.abs(tsResult.recall - py.recall) < 1e-9, `${label} — recall matches`);
  ok(Math.abs(tsResult.f1 - py.f1) < 1e-9, `${label} — f1 matches`);
  ok(tsResult.n_matched === py.n_matched, `${label} — n_matched matches`);
  ok(Math.abs(tsResult.mean_abs_offset_ms - py.mean_abs_offset_ms) < 1e-9,
    `${label} — mean_abs_offset_ms matches`);
  ok(JSON.stringify(tsResult.matches.map((m) => [m.ref_index, m.est_index]))
    === JSON.stringify(py.matches.map((m) => [m.ref_index, m.est_index])),
  `${label} — matched pairs identical`);
});

console.log(failures === 0 ? '\nAll vectors agree.' : `\n${failures} mismatch(es).`);
process.exit(failures === 0 ? 0 : 1);
