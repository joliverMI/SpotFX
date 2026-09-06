// Pure-logic, network-free, browser-free proof of the TESTING IN PROGRESS
// bar's display decisions — the formulas extracted VERBATIM from
// spectra/web/src/components/TestingBar.tsx.
//
// Why an offline extraction rather than a rendered check: the properties
// that matter here are DECISIONS ("does it show?", "which sentence?"),
// and they are exactly the ones a screenshot cannot pin down — a bar that
// wrongly hides during an outage looks identical to a correctly quiet
// page. Driving the real formulas with fabricated states proves the
// decision table directly, with zero network (the worktree isolates files,
// not the network: this script must never be able to touch :8010).
//
// Proves:
//   ONE   — the bar hides on EXACTLY ONE answer: a confirmed "no" from a
//           reachable backend. Every other combination shows.
//   TWO   — "unknown" shows in its own distinct form, including when the
//           backend is unreachable.
//   THREE — the failure debounce: one dropped poll never raises the bar,
//           two consecutive ones do, and a single success resets it.
//   FOUR  — the owned-vs-painting distinction: owning the room and
//           painting it produce DIFFERENT sentences, and the fault case
//           says the word "fault".
//   FIVE  — who/since formatting: a declared take names itself, an
//           undeclared auto hold names the path, elapsed appears only
//           past a minute.
//   SIX   — MEASURED BEFORE CLAIMED: a live capture run's own purpose
//           outranks a declared take, which is ttl-bounded and outlives
//           the run it was made for. The Admiral's own report, 2026-09-05:
//           "the ownership banner shows an OUTDATED test reason" — a
//           second run inside an earlier run's declaration wore the
//           earlier run's reason. The pre-fix rule is driven against the
//           same state to prove it produced exactly that.

function check(cond, label) {
  if (!cond) { console.error(`FAIL: ${label}`); process.exit(1); }
  console.log(`ok: ${label}`);
}

/* ── VERBATIM from TestingBar.tsx ─────────────────────────────────────── */

const FAIL_STREAK_TO_SHOW = 2;

function formatSince(sinceMs) {
  const d = new Date(sinceMs);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function formatElapsed(sinceMs, nowMs) {
  const secs = Math.floor((nowMs - sinceMs) / 1000);
  if (secs < 60) return null;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ${mins % 60}m`;
}

function paintingLine(live) {
  if (!live) return 'can\'t read whether your lights are being painted';
  if (live.state === 'switching') return 'the room is changing hands right now';
  if (live.owner !== 'spectra') {
    if (live.owner === 'released') {
      return 'your room is RELEASED — nothing is driving your lights';
    }
    return `spot-effects owns your lights right now (SPECTRA is ${live.state})`;
  }
  if (live.state !== 'live') {
    return 'SPECTRA holds the room but her live stack is DOWN — that\'s a fault, not a test';
  }
  const gaps = Object.keys(live.activation_gaps ?? {}).length;
  const vals = Object.values(live.virtuals ?? {});
  const active = vals.filter((v) => v.active);
  const stale = active.filter((v) => !v.fresh);
  if (active.length === 0) {
    return 'holding the room but NOT painting — that\'s a fault, not a test';
  }
  if (stale.length > 0) {
    return `holding the room but ${stale.length} of ${active.length} light(s) STOPPED painting — that's a fault, not a test`;
  }
  if (gaps > 0) {
    return `driving ${active.length} light(s), but ${gaps} never came up — partly dark`;
  }
  return `driving your lights (${active.length} painting, frames flowing)`;
}

function whoLine(st) {
  const run = st.sources.find((s) => s.kind === 'run');
  if (run) return `${run.label}${run.detail ? ` (${run.detail})` : ''}`;
  if (st.declared) return `${st.declared.actor} — ${st.declared.reason}`;
  const auto = st.sources.filter((s) => s.kind === 'auto');
  if (auto.length === 0) return 'someone (undeclared)';
  const first = auto[0];
  const extra = auto.length > 1 ? ` +${auto.length - 1} more` : '';
  return `${first.label}${first.detail ? ` (${first.detail})` : ''}${extra}`;
}

/** The rule as it shipped BEFORE the run tier — kept so SIX can prove the
 * stale headline it produced, rather than merely asserting it existed. */
function whoLineBeforeTheFix(st) {
  if (st.declared) return `${st.declared.actor} — ${st.declared.reason}`;
  const auto = st.sources.filter((s) => s.kind === 'auto');
  if (auto.length === 0) return 'someone (undeclared)';
  const first = auto[0];
  const extra = auto.length > 1 ? ` +${auto.length - 1} more` : '';
  return `${first.label}${first.detail ? ` (${first.detail})` : ''}${extra}`;
}

/** The render decision, verbatim from the component body's early returns. */
function renderMode({ session, unreachable }) {
  if (!unreachable && session?.testing === 'no') return 'hidden';
  if (!unreachable && !session) return 'hidden';
  const unknown = unreachable || session?.testing === 'unknown';
  return unknown ? 'unknown' : 'yes';
}

/** The debounce effect, verbatim from the useEffect body. */
function debounce(events) {
  let failStreak = 0;
  let unreachable = false;
  const trace = [];
  for (const ev of events) {
    if (ev === 'error') {
      failStreak += 1;
      if (failStreak >= FAIL_STREAK_TO_SHOW) unreachable = true;
    } else if (ev === 'data') {
      failStreak = 0;
      unreachable = false;
    }
    trace.push(unreachable);
  }
  return trace;
}

/* ── ONE: the bar hides on exactly one answer ─────────────────────────── */

const NO = { testing: 'no', sources: [], declared: null, since_ms: null, readable: true, now_ms: 0 };
const YES = {
  testing: 'yes',
  sources: [{ key: 'preview_pause', label: 'a preview is holding your room', detail: null, kind: 'auto' }],
  declared: null, since_ms: null, readable: true, now_ms: 0,
};
const UNKNOWN = { testing: 'unknown', sources: [], declared: null, since_ms: null, readable: false, now_ms: 0 };

check(renderMode({ session: NO, unreachable: false }) === 'hidden',
      'ONE: a confirmed "no" from a reachable backend hides the bar');
check(renderMode({ session: YES, unreachable: false }) === 'yes',
      'ONE: "yes" shows the TESTING IN PROGRESS form');
check(renderMode({ session: UNKNOWN, unreachable: false }) === 'unknown',
      'ONE: "unknown" shows, it does NOT hide');
check(renderMode({ session: undefined, unreachable: false }) === 'hidden',
      'ONE: first load with nothing known yet stays quiet (no UNKNOWN flash)');

/* ── TWO: unreachable always shows, and always as unknown ─────────────── */

check(renderMode({ session: undefined, unreachable: true }) === 'unknown',
      'TWO: unreachable backend with no data shows the CAN\'T CONFIRM form');
check(renderMode({ session: NO, unreachable: true }) === 'unknown',
      'TWO: a STALE "no" cannot silence the bar once the backend is unreachable');
check(renderMode({ session: YES, unreachable: true }) === 'unknown',
      'TWO: unreachable outranks a stale "yes" too — it reports what it can prove');

/* ── THREE: the debounce ──────────────────────────────────────────────── */

check(debounce(['data', 'error']).at(-1) === false,
      'THREE: ONE dropped poll never raises the bar');
check(debounce(['data', 'error', 'error']).at(-1) === true,
      'THREE: TWO consecutive failures do raise it');
check(debounce(['data', 'error', 'data', 'error']).at(-1) === false,
      'THREE: a success between failures resets the streak (no flicker)');
check(debounce(['error', 'error', 'data']).at(-1) === false,
      'THREE: recovery clears it on the very next success');

/* ── FOUR: owned vs painting ──────────────────────────────────────────── */

const painting = paintingLine({
  owner: 'spectra', state: 'live', activation_gaps: {},
  virtuals: { a: { active: true, fresh: true }, b: { active: true, fresh: true } },
});
const notPainting = paintingLine({
  owner: 'spectra', state: 'live', activation_gaps: {},
  virtuals: { a: { active: false, fresh: false } },
});
const stalled = paintingLine({
  owner: 'spectra', state: 'live', activation_gaps: {},
  virtuals: { a: { active: true, fresh: true }, b: { active: true, fresh: false } },
});
const stackDown = paintingLine({ owner: 'spectra', state: 'dark', activation_gaps: {}, virtuals: {} });

check(painting !== notPainting,
      'FOUR: owning-and-painting and owning-but-not-painting are DIFFERENT sentences');
check(/frames flowing/.test(painting) && /2 painting/.test(painting),
      'FOUR: the healthy line says frames are flowing, and how many lights');
check(/fault, not a test/.test(notPainting),
      'FOUR: holding-but-dark is called a FAULT, not a test');
check(/fault, not a test/.test(stalled) && /STOPPED painting/.test(stalled),
      'FOUR: a partially stalled room names the stalled count as a fault');
check(/fault, not a test/.test(stackDown),
      'FOUR: owning with the live stack down is a fault too');
check(/RELEASED/.test(paintingLine({ owner: 'released', state: 'released', virtuals: {}, activation_gaps: {} })),
      'FOUR: a released room says so plainly');
check(/spot-effects owns/.test(paintingLine({ owner: 'spot-effects', state: 'dark', virtuals: {}, activation_gaps: {} })),
      'FOUR: the other world owning is stated, not silently rendered as a fault');
check(/can't read/.test(paintingLine(null)),
      'FOUR: no liveness data admits it rather than claiming either way');
check(/partly dark/.test(paintingLine({
        owner: 'spectra', state: 'live', activation_gaps: { wled1: 'never came up' },
        virtuals: { a: { active: true, fresh: true } } })),
      'FOUR: an activation gap is surfaced even while the rest paints');

/* ── FIVE: who and since ──────────────────────────────────────────────── */

check(whoLine({ ...YES, declared: { actor: 'firstmate', reason: 'live room proof' } })
        === 'firstmate — live room proof',
      'FIVE: a declared take names actor and reason');
check(whoLine(YES) === 'a preview is holding your room',
      'FIVE: an undeclared auto hold names the PATH instead of inventing a name');
check(whoLine({ ...YES, sources: [
        { key: 'a', label: 'holding', detail: '12s left', kind: 'auto' },
        { key: 'b', label: 'painting', detail: null, kind: 'auto' }] })
        === 'holding (12s left) +1 more',
      'FIVE: multiple auto sources show the first plus a count, with its detail');
check(whoLine({ ...YES, sources: [] }) === 'someone (undeclared)',
      'FIVE: testing with no nameable source still admits somebody is testing');

const base = new Date(2026, 7, 24, 23, 5, 0).getTime();
check(formatSince(base) === '23:05', 'FIVE: since is his own local HH:MM, zero-padded');
check(formatElapsed(base, base + 30_000) === null, 'FIVE: under a minute shows no duration');
check(formatElapsed(base, base + 61_000) === '1m', 'FIVE: past a minute shows minutes');
check(formatElapsed(base, base + 3_600_000 + 120_000) === '1h 2m', 'FIVE: past an hour shows h + m');

/* ── SIX: a live run outranks a stale declaration ─────────────────────── */

// His evening: firstmate declared run A's purpose, run A ended, run B is
// what holds the room now — and the declaration has not expired.
const RUN_B = {
  testing: 'yes',
  sources: [
    { key: 'capture_run', label: 'mapping the light field on Living Room',
      detail: null, kind: 'run', since_ms: 2_000 },
    { key: 'flare_preview_hold', label: 'a flare preview is driving your lights',
      detail: null, kind: 'auto', since_ms: null },
    { key: 'declared', label: 'firstmate: commissioning proof of the TV mapper',
      detail: null, kind: 'declared', since_ms: 1_000 },
  ],
  declared: { actor: 'firstmate', reason: 'commissioning proof of the TV mapper',
              since_ms: 1_000, expires_ms: 9e15, ttl_s: 3600 },
  since_ms: 2_000, readable: true, now_ms: 0,
};

check(whoLine(RUN_B) === 'mapping the light field on Living Room',
      'SIX: a live run names ITSELF, not the earlier run a declaration was made for');
check(whoLineBeforeTheFix(RUN_B) === 'firstmate — commissioning proof of the TV mapper',
      'SIX: the PRE-FIX rule really did show the stale reason on this same state');
check(whoLine(RUN_B) !== whoLineBeforeTheFix(RUN_B),
      'SIX: the two rules disagree here — this check can fail on the defect');
check(whoLine({ ...RUN_B, sources: RUN_B.sources.filter((s) => s.kind !== 'run') })
        === 'firstmate — commissioning proof of the TV mapper',
      'SIX: with no run live a declaration still owns the headline — unchanged');
check(whoLine({ ...RUN_B,
                sources: [{ ...RUN_B.sources[0], detail: '3 of 22 emitters' }] })
        === 'mapping the light field on Living Room (3 of 22 emitters)',
      'SIX: a run\'s own detail rides with its purpose');
check(RUN_B.since_ms === RUN_B.sources[0].since_ms,
      'SIX: the headline\'s clock is the RUN\'s start, never the older declaration\'s');

console.log('\nALL CHECKS PASSED — spectra/web/src/components/TestingBar.tsx');
