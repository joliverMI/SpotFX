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
 *   NINE  — KEEP SEARCHING (2026-09-15): the engine now keeps searching past
 *           its plan. A `continued` record reads "Searching…" with no spent
 *           fraction (the PRE-CHANGE badge, transpiled from the pinned git
 *           ref, is driven over the same record and printed "Searching… 4/4"),
 *           never "Lock failed" or "Lock idle"; and each give-up reason reads
 *           "Lock failed" in words — claiming it "kept searching" only when
 *           the record says it did (`continued`), never for a give-up the
 *           moment the plan ran out. `nothing_admissible` (every recent
 *           window found something the envelope would not let it adopt)
 *           never reads as "nothing usable turned up". The records are
 *           hand-built to mirror the shape services/lock_state.py publishes.
 *
 * Run: node scripts/check_lock_badge_states.mjs
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
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
          for (const continued of [undefined, true]) {
            const lock = present && phase
              ? rec(phase, continued ? { continued, continued_windows: 3 } : {})
              : null;
            const label = lockBadge({ monitor, nowMs: NOW, lock, storedOffsetMs }).label;
            if (label === 'Lock idle') idle.push({ phase, storedOffsetMs, present });
          }
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

console.log('\nNINE — keep searching: "Searching…" while it works past the plan, failed only on give-up');
{
  // The pinned pre-change badge (PR #266), transpiled the same way.
  const BASELINE_REF = '4795fd3a69391e0577bdfc8a2bc8e597e4fd1910';
  const oldTs = path.join(tmp, 'lockBadge.baseline.ts');
  const oldJs = path.join(tmp, 'lockBadge.baseline.mjs');
  writeFileSync(oldTs, execFileSync('git', ['show', `${BASELINE_REF}:web/src/components/lockBadge.ts`],
    { cwd: REPO, encoding: 'utf8' }));
  execFileSync('npx', ['esbuild', oldTs, '--format=esm', '--log-level=warning', `--outfile=${oldJs}`], {
    cwd: path.join(REPO, 'web'), stdio: ['ignore', 'ignore', 'inherit'],
  });
  const { lockBadge: preChangeBadge } = await import(oldJs);

  // MAYDAY past its plan: 4 planned windows spent, 3 more measured, the best
  // it has is still the distrusted +1325 at Q=0.39.
  const pastPlan = rec('searching', {
    windows_total: 4, windows_done: 7, offset_ms: 1325, quality: 0.39,
    continued: true, continued_windows: 3,
  });
  const input = { monitor: null, nowMs: NOW, lock: pastPlan, storedOffsetMs: 1325 };
  eq(preChangeBadge(input).label, 'Searching… 4/4',
     'PRE-CHANGE: a search past its plan printed a finished fraction');
  eq(badge(pastPlan).label, 'Searching…', 'NOW: it reads plain "Searching…"');
  ok(badge(pastPlan).color === badge(rec('searching')).color, 'in the searching colour');
  ok(badge(pastPlan).title.includes('still searching the rest of this song'),
     'the tooltip says it is working past the plan');
  ok(badge(pastPlan).title.includes('3 more windows measured'), 'and how far it has got');
  ok(badge(pastPlan).title.includes('+1325ms'), 'and the best it has so far');
  eq(badge({ ...pastPlan, continued_windows: 1 }).title.includes('1 more window measured'), true,
     'one window is singular');
  eq(badge({ ...pastPlan, continued_windows: 0 }).label, 'Searching…',
     'the instant it goes past the plan, before a new window lands');
  ok(!badge(pastPlan).title.includes('planned windows measured.'),
     'it never claims "N of M planned windows" for a spent plan');
  eq(badge(rec('searching', { windows_done: 2 })).label, 'Searching… 2/4',
     'a search still inside its plan keeps its fraction');

  for (const [reason, words] of [
    ['nothing_to_find', 'nothing usable turned up'],
    ['no_time_left', 'last stretch of the song'],
    ['user_verified', 'user-verified'],
    ['nothing_admissible', 'nothing it found could be adopted'],
  ]) {
    const gaveUp = rec('unlocked', { continued: true, continued_windows: 9, reason });
    eq(badge(gaveUp).label, 'Lock failed', `a give-up (${reason}) reads "Lock failed"`);
    ok(badge(gaveUp).title.includes(words), `and says why: "${words}"`);
  }
  ok(!badge(rec('unlocked', { continued: true, continued_windows: 3, reason: 'nothing_admissible' }))
       .title.includes('nothing usable turned up'),
     'a search that found only what it could not adopt never says nothing usable turned up');
  ok(badge(rec('unlocked', { continued: true, continued_windows: 9, reason: 'no_time_left' }))
       .title.includes('kept searching past its planned windows'),
     'a continued search that ran into the last stretch says it kept searching');

  // A give-up the moment the plan ran out — the last planned window landed
  // inside the song's last stretch — never searched past the plan, so the
  // record carries no `continued`, and the words must not claim it did.
  for (const [reason, words] of [
    ['no_time_left', 'last stretch of the song'],
    ['nothing_to_find', 'nothing usable turned up'],
    ['user_verified', 'user-verified'],
  ]) {
    const immediate = rec('unlocked', { reason, offset_ms: 1325, quality: 0.39 });
    eq(badge(immediate).label, 'Lock failed', `an immediate give-up (${reason}) reads "Lock failed"`);
    ok(badge(immediate).title.includes(words), `and says why: "${words}"`);
    ok(!badge(immediate).title.includes('kept searching'),
       `and never claims it kept searching past its planned windows (${reason})`);
  }
  ok(badge(rec('unlocked', { reason: 'no_time_left' })).title.includes('planned windows ran out'),
     'an immediate no_time_left says its planned windows ran out');
}

console.log('\nTEN — Ship 2 frame-mismatch advisory: tints "Lock idle", never replaces it');
{
  // services/frame_advisory.py, data/false-lock-continued-search/report.md §4.
  const suspectLock = rec('locked', {
    offset_ms: 4274, quality: 0.79,
    frame_suspect: true, frame_suspect_room_band_ms: -1100, frame_suspect_distance_ms: 5374,
  });
  const quietLock = rec('locked', { offset_ms: -475, quality: 0.98, frame_suspect: false });

  eq(badge(suspectLock).label, 'Lock idle',
     'a frame-suspect lock is STILL "Lock idle" — the advisory never invents a new phase');
  ok(badge(suspectLock).color !== badge(quietLock).color,
     'but it is tinted differently from an ordinary idle lock');
  ok(badge(suspectLock).title.includes('may not share a timing frame'),
     'and the tooltip explains what that means, in words');
  ok(badge(suspectLock).title.includes('5374ms'), 'carrying the measured distance');
  ok(badge(suspectLock).title.includes('-1100ms'), 'and the band it was judged against');

  eq(badge(quietLock).label, 'Lock idle', 'an ordinary lock reads exactly as before');
  ok(!badge(quietLock).title.includes('timing frame'),
     'and says nothing about frames when nothing is suspect');

  const noAdvisoryRecorded = rec('locked', { offset_ms: -475, quality: 0.98 });
  eq(badge(noAdvisoryRecorded).label, 'Lock idle',
     'a play recorded before this field existed reads exactly as before (additive field)');
  eq(badge(noAdvisoryRecorded).color, badge(quietLock).color,
     'and its colour is identical to an explicit frame_suspect=false lock');
  ok(!badge(noAdvisoryRecorded).title.includes('timing frame'), 'no stray advisory text');
}

rmSync(tmp, { recursive: true, force: true });
console.log(failures === 0 ? '\nALL PASS\n' : `\n${failures} FAILURE(S)\n`);
process.exit(failures === 0 ? 0 : 1);
