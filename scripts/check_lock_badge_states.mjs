/**
 * Executable spec for the sync-lock badge's decision table.
 *
 * Transpiles the REAL frontend module (web/src/components/lockBadge.ts) with
 * esbuild and drives it — so this cannot drift from what ships — and reads the
 * phase vocabulary out of services/lock_state.py's own source, so a phase word
 * renamed on either side goes red here.
 *
 * Why an offline extraction and not a rendered check: the property that matters
 * is a DECISION ("which word?"), and a badge that says the wrong word looks
 * exactly as calm as one that says the right word. Driving the real function
 * over fabricated states proves the table directly, with zero network — this
 * script must never be able to touch his running :8000 app.
 *
 * Proves:
 *   ONE   — the founding defect, on the Admiral's own MAYDAY state (sweep ran,
 *           grade F, offset stored, drift monitor never engaged): the badge now
 *           says "Lock failed", and the PRE-FIX rule is driven over the same
 *           state to show it produced the literal "Lock idle".
 *   TWO   — THE INVARIANT: across the whole cross-product of inputs, "Lock idle"
 *           is reachable from EXACTLY ONE — a search that ended in a hard lock.
 *           No searching state and no failed state can ever produce it.
 *   THREE — searching is live: it carries window progress and moves with it.
 *   FOUR  — the live monitor outranks every phase, and ageing past
 *           LOCK_STALE_MS hands the badge back to the phase.
 *   FIVE  — a record for the PREVIOUS song never renders against this one.
 *   SIX   — "No lock" (nothing stored) is unchanged, and a sweep that tried
 *           and failed still outranks it — it says more.
 *   SEVEN — FORWARD COMPATIBILITY: a low-confidence result recorded while the
 *           engine keeps looking (phase still `searching`, numbers attached)
 *           stays "Searching…". The badge is keyed off "is it still looking",
 *           never off a first sweep's window exhaustion.
 *
 * Run: node scripts/check_lock_badge_states.mjs
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TS = path.join(REPO, 'web/src/components/lockBadge.ts');
const PY = path.join(REPO, 'services/lock_state.py');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};
const eq = (got, want, msg) => ok(got === want, `${msg}  (got ${JSON.stringify(got)})`);

const tmp = mkdtempSync(path.join(tmpdir(), 'lockbadge-'));
const js = path.join(tmp, 'lockBadge.mjs');
execFileSync('npx', ['esbuild', TS, '--format=esm', `--outfile=${js}`], {
  cwd: path.join(REPO, 'web'), stdio: ['ignore', 'ignore', 'inherit'],
});
const { lockBadge, lockForUri, LOCK_STALE_MS } = await import(js);

const NOW = 1_700_000_000_000;
const URI = 'spotify:track:mayday';

/** The badge for a record already scoped to the song playing. */
const badge = (lock, extra = {}) =>
  lockBadge({ monitor: null, nowMs: NOW, lock, storedOffsetMs: 1325, ...extra });

const rec = (phase, extra = {}) => ({
  uri: URI, phase, windows_total: 4, windows_done: 4,
  offset_ms: null, quality: null, reason: null, play_type: 'skip', ...extra,
});

/* ── The rule as it shipped BEFORE this fix, verbatim from TopBar.tsx ────── */
const PRE_FIX_LABEL = { ok: 'Locked', suspect: 'Suspect', recovering: 'Recovering' };
function preFixBadge({ monitor, nowMs, storedOffsetMs }) {
  const fresh = monitor && nowMs - monitor.at < 12_000;
  return fresh
    ? PRE_FIX_LABEL[monitor.state] ?? monitor.state
    : storedOffsetMs != null ? 'Lock idle' : 'No lock';
}

console.log('\nONE — the founding defect (MAYDAY, 2026-09-08 21:15)');
{
  // spotfx.service log: sweep ran once (4 windows, play_type=skip), produced
  // `final offset=+1325ms Q=0.39`, then `lock_history: no hard lock grade=F`;
  // the drift monitor never engaged.
  const mayday = rec('unlocked', { offset_ms: 1325, quality: 0.39 });
  const state = { monitor: null, nowMs: NOW, storedOffsetMs: 1325 };
  eq(preFixBadge(state), 'Lock idle', 'PRE-FIX: the shipped rule called that play "Lock idle"');
  eq(badge(mayday).label, 'Lock failed', 'FIXED: the same play now reads "Lock failed"');
  ok(badge(mayday).title.includes('without reaching a lock'),
     'FIXED: the tooltip says it finished searching without a lock');
  ok(badge(mayday).title.includes('+1325ms'),
     'FIXED: the tooltip carries the best offset it did find');
}

console.log('\nTWO — THE INVARIANT: exactly one input may say "Lock idle"');
{
  const phases = ['searching', 'locked', 'unlocked', 'skipped', undefined];
  const offsets = [null, 0, 1325];
  const monitors = [null, { state: 'ok', at: NOW - LOCK_STALE_MS - 1 }];
  const idle = [];
  for (const phase of phases) {
    for (const storedOffsetMs of offsets) {
      for (const monitor of monitors) {
        for (const present of [true, false]) {
          const lock = present && phase ? rec(phase) : null;
          const label = lockBadge({ monitor, nowMs: NOW, lock, storedOffsetMs }).label;
          if (label === 'Lock idle') idle.push({ phase, storedOffsetMs, present });
        }
      }
    }
  }
  ok(idle.length > 0, 'the idle state is still reachable at all');
  ok(idle.every((c) => c.phase === 'locked' && c.present),
     `every "Lock idle" came from a search that ENDED IN A HARD LOCK (${idle.length} case(s))`);
  ok(!idle.some((c) => c.phase === 'searching' || c.phase === 'unlocked'),
     'no searching or failed input can produce "Lock idle"');
  eq(badge(rec('locked', { offset_ms: -420, quality: 0.81 })).label, 'Lock idle',
     'a hard lock whose monitor has gone quiet IS idle');
}

console.log('\nTHREE — searching is live, and carries its progress');
{
  eq(badge(rec('searching', { windows_done: 0 })).label, 'Searching… 0/4',
     'a sweep that has just started');
  eq(badge(rec('searching', { windows_done: 2 })).label, 'Searching… 2/4',
     'progress moves with the windows measured');
  eq(badge(rec('searching', { windows_done: 7, windows_total: 4 })).label, 'Searching… 4/4',
     'a dynamic recovery window past the plan never prints 7/4');
  eq(badge(rec('searching', { windows_total: 0, windows_done: 0 })).label, 'Searching…',
     'no planned count, no fake progress');
  ok(badge(rec('searching')).color !== badge(rec('unlocked')).color,
     'searching and failed are different colours, not just different words');
}

console.log('\nFOUR — the live monitor outranks every phase, and ages out');
{
  const fresh = { state: 'ok', at: NOW - 1_000 };
  const stale = { state: 'ok', at: NOW - LOCK_STALE_MS - 1 };
  for (const phase of ['searching', 'unlocked', 'locked', 'skipped']) {
    eq(lockBadge({ monitor: fresh, nowMs: NOW, lock: rec(phase), storedOffsetMs: 1325 }).label,
       'Locked', `a fresh monitor outranks phase=${phase}`);
  }
  eq(lockBadge({ monitor: { state: 'suspect', at: NOW }, nowMs: NOW, lock: null, storedOffsetMs: 1 }).label,
     'Suspect', 'suspect still reads Suspect');
  eq(lockBadge({ monitor: { state: 'recovering', at: NOW }, nowMs: NOW, lock: null, storedOffsetMs: 1 }).label,
     'Recovering', 'recovering still reads Recovering');
  eq(lockBadge({ monitor: stale, nowMs: NOW, lock: rec('unlocked'), storedOffsetMs: 1325 }).label,
     'Lock failed', 'once it ages out the phase speaks again');
  eq(lockBadge({ monitor: stale, nowMs: NOW, lock: null, storedOffsetMs: 1325 }).label,
     'Lock unknown', 'nothing heard about this song yet is said, not guessed');
}

console.log('\nFIVE — the previous song never speaks for this one');
{
  eq(lockForUri(rec('unlocked'), 'spotify:track:OTHER'), null,
     'a record for another uri is filtered out');
  eq(lockForUri(rec('unlocked'), URI).phase, 'unlocked', 'the matching record passes');
  eq(lockForUri(null, URI), null, 'no record is no record');
  eq(lockForUri(rec('unlocked'), null), null, 'nothing playing renders no phase');
  eq(badge(lockForUri(rec('locked'), 'spotify:track:OTHER')).label, 'Lock unknown',
     'the previous song having locked never makes THIS one read idle');
}

console.log('\nSIX — "No lock" is unchanged, and a real attempt outranks it');
{
  eq(badge(null, { storedOffsetMs: null }).label, 'No lock', 'nothing stored, nothing known');
  eq(badge(rec('skipped', { reason: 'no_shape' }), { storedOffsetMs: null }).label, 'No lock',
     'nothing stored still reads "No lock" even when we know why nobody looked');
  eq(badge(rec('unlocked'), { storedOffsetMs: null }).label, 'Lock failed',
     'a sweep that tried and failed says more than "No lock"');
  eq(badge(rec('skipped', { reason: 'setlist_disabled' })).label, 'Not checked',
     'a skipped sweep with a stored offset is NOT idle');
  ok(badge(rec('skipped', { reason: 'setlist_disabled' })).title.includes('Set List'),
     'and it says why in the tooltip');
}

console.log('\nSEVEN — forward compatibility: keyed off "still looking", not window exhaustion');
{
  // A weak result recorded while the engine keeps searching: lock_state's
  // note_outcome(locked=False) attaches the numbers and LEAVES the phase at
  // `searching`. The badge must stay on "still trying".
  const weak = rec('searching', { windows_done: 4, offset_ms: 1325, quality: 0.39 });
  ok(badge(weak).label.startsWith('Searching…'),
     'a low-confidence result while still looking stays "Searching…"');
  ok(badge(weak).title.includes('+1325ms'),
     'and the tooltip already shows the best it has found so far');
  ok(badge(weak).label !== 'Lock failed',
     'exhausting the planned windows is NOT by itself a failure');
}

console.log('\nEIGHT — the phase vocabulary matches services/lock_state.py');
{
  const py = readFileSync(PY, 'utf8');
  const ts = readFileSync(TS, 'utf8');
  for (const [name, word] of [
    ['PHASE_SEARCHING', 'searching'], ['PHASE_LOCKED', 'locked'],
    ['PHASE_UNLOCKED', 'unlocked'], ['PHASE_SKIPPED', 'skipped'],
  ]) {
    ok(new RegExp(`^${name}\\s*=\\s*"${word}"$`, 'm').test(py),
       `lock_state.py still spells ${name} "${word}"`);
    ok(ts.includes(`'${word}'`), `lockBadge.ts still tests for '${word}'`);
  }
  for (const reason of ['no_shape', 'capture_in_progress', 'setlist_disabled',
                        'no_windows', 'no_measurements']) {
    ok(py.includes(`"${reason}"`) || readFileSync(
         path.join(REPO, 'services/auto_offset_service.py'), 'utf8').includes(`"${reason}"`),
       `the reason "${reason}" is emitted by the backend`);
    ok(ts.includes(`'${reason}'`), `and rendered in words by the badge`);
  }
}

rmSync(tmp, { recursive: true, force: true });
console.log(failures === 0 ? '\nALL PASS\n' : `\n${failures} FAILURE(S)\n`);
process.exit(failures === 0 ? 0 : 1);
