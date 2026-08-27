// Pure-logic, network-free, browser-free proof of the MULTI-CUE preview
// loop's frontend scheduling — the transition and drop-sequence previews'
// own half of the timing contract (2026-08-27,
// fm/flare-preview-offsets-everywhere).
//
// The single-cue flare loop is already covered by
// scripts/check_flare_preview_frontend_loop.mjs; this is that proof's
// sibling for the generalized loop, and it follows the same discipline for
// the same reason: the scheduling formulas below are copied VERBATIM from
// spectra/web/src/scenes/tabs/usePreviewLoop.ts and driven with a fake
// clock, so there is zero risk of a network call reaching a real
// backend or his fixtures, and zero risk of the proof drifting away from
// the code by paraphrasing it.
//
// Proves:
//   ONE   — every cue fires ONCE PER LAP, all of them, for many laps.
//   TWO   — each cue fires at its OWN server-computed at_s, in ruler order,
//           never bunched at the top of a lap.
//   THREE — a cue whose at_s the playhead has already passed when the loop
//           starts waits for the NEXT lap. A preview that fires the instant
//           it opens, before its own mark, is exactly what his 2026-08-21
//           correction rejected ("it should fire with the same timing as if
//           the playhead was crossing a trigger").
//   FOUR  — a backgrounded tab (one huge frame delta) never produces a
//           BURST of catch-up fires: the schedule advances by whole laps.
//   FIVE  — the loop derives NO time of its own: change nothing but the
//           server's cue times and every fire moment moves with them.

function check(cond, label) {
  if (!cond) { console.error(`FAIL: ${label}`); process.exit(1); }
  console.log(`ok: ${label}`);
}

// ── the schedule seed, verbatim from usePreviewLoop.ts's effect body ──────
function seedSchedule(cues, durationS, playheadS, now0) {
  const schedule = {};
  for (const cue of cues) {
    const atS = ((cue.at_s % durationS) + durationS) % durationS;
    const delayS = atS >= playheadS ? atS - playheadS : durationS - playheadS + atS;
    schedule[cue.step] = now0 + delayS * 1000;
  }
  return schedule;
}

// ── the per-frame advance, verbatim from usePreviewLoop.ts's step() ───────
function stepFrame(cues, durationS, schedule, now, fires) {
  for (const cue of cues) {
    const due = schedule[cue.step];
    if (due != null && now >= due) {
      fires.push({ step: cue.step, at: now });
      let next = due;
      while (next <= now) next += durationS * 1000;
      schedule[cue.step] = next;
    }
  }
}

function run(cues, durationS, { laps = 4, playheadS = 0, frameMs = 16.7, jumpAt = null } = {}) {
  const now0 = 1_000_000;
  const schedule = seedSchedule(cues, durationS, playheadS, now0);
  const fires = [];
  let now = now0;
  const end = now0 + laps * durationS * 1000;
  while (now <= end) {
    stepFrame(cues, durationS, schedule, now, fires);
    now += (jumpAt != null && now - now0 >= jumpAt) ? durationS * 3000 : frameMs;
  }
  return { fires, now0 };
}

// ── ONE + TWO: every cue, once per lap, at its own time ───────────────────
{
  const durationS = 6.0;
  const cues = [
    { step: 'rearm', at_s: 0.0 },
    { step: 'fire', at_s: 1.46 },
  ];
  const { fires, now0 } = run(cues, durationS, { laps: 4 });
  for (const c of cues) {
    const mine = fires.filter((f) => f.step === c.step);
    check(mine.length >= 4, `ONE: '${c.step}' fired every lap (${mine.length} in 4 laps)`);
    for (const f of mine) {
      const posInLap = ((f.at - now0) / 1000) % durationS;
      const expected = c.at_s % durationS;
      const off = Math.min(Math.abs(posInLap - expected),
                           Math.abs(posInLap - expected - durationS));
      check(off < 0.05,
        `TWO: '${c.step}' landed at ${posInLap.toFixed(3)}s (server said ${expected}s)`);
    }
  }
  const firstRearm = fires.find((f) => f.step === 'rearm');
  const firstFire = fires.find((f) => f.step === 'fire');
  check(firstRearm.at < firstFire.at, 'TWO: cues fire in ruler order within a lap');
}

// ── THREE: a cue already passed waits for the NEXT lap, never fires now ───
{
  const durationS = 6.0;
  const cues = [{ step: 'fire', at_s: 1.5 }];
  // the playhead starts at 3.0s — PAST the cue
  const now0 = 1_000_000;
  const schedule = seedSchedule(cues, durationS, 3.0, now0);
  const waitS = (schedule.fire - now0) / 1000;
  check(waitS > 0.1, `THREE: a passed cue waits ${waitS.toFixed(2)}s, it does not fire now`);
  check(Math.abs(waitS - (durationS - 3.0 + 1.5)) < 1e-6,
    'THREE: it waits exactly until the next lap reaches its own mark');
}

// ── FOUR: a backgrounded tab produces no burst of catch-up fires ──────────
{
  const durationS = 4.0;
  const cues = [{ step: 'fire', at_s: 1.0 }];
  const { fires } = run(cues, durationS, { laps: 6, jumpAt: 5000 });
  // consecutive fires must never be closer together than one lap
  for (let i = 1; i < fires.length; i++) {
    const gapS = (fires[i].at - fires[i - 1].at) / 1000;
    check(gapS >= durationS - 0.05,
      `FOUR: consecutive fires stay ${gapS.toFixed(2)}s apart (>= one ${durationS}s lap)`);
  }
}

// ── FIVE: the loop derives no time of its own ─────────────────────────────
{
  const durationS = 8.0;
  const before = run([{ step: 'fire', at_s: 2.0 }], durationS, { laps: 2 });
  const after = run([{ step: 'fire', at_s: 5.0 }], durationS, { laps: 2 });
  const posBefore = ((before.fires[0].at - before.now0) / 1000);
  const posAfter = ((after.fires[0].at - after.now0) / 1000);
  check(Math.abs(posBefore - 2.0) < 0.05 && Math.abs(posAfter - 5.0) < 0.05,
    'FIVE: every fire moment moves with the SERVER\'s cue time and nothing else');
  check(Math.abs((posAfter - posBefore) - 3.0) < 0.1,
    'FIVE: a 3s server-side shift moves the fire by exactly 3s');
}

// ── SIX: the TRANSITION preview's drag round-trips through the SERVER's
//    own trigger_mark_s formula — the ONE formula, never re-derived. Both
//    functions are copied VERBATIM: the drag from
//    TransitionPreviewOverlay.tsx, the mark from
//    spectra/services/flare_preview.py (which transition_preview.py CALLS).
{
  // verbatim from TransitionPreviewOverlay.tsx's onTriggerDragEnd
  const offsetFromDrag = (animAnchorS, draggedMarkS) =>
    Math.round((animAnchorS - draggedMarkS) * 1000);
  // verbatim from flare_preview.trigger_mark_s
  const triggerMarkS = (anchorS, offsetMs, durationS) =>
    Math.max(0, Math.min(durationS, anchorS - offsetMs / 1000));

  const anchorS = 2.75, durationS = 9.0;
  for (const draggedTo of [0.5, 2.0, 2.75, 4.0, 8.0]) {
    const offsetMs = offsetFromDrag(anchorS, draggedTo);
    const back = triggerMarkS(anchorS, offsetMs, durationS);
    check(Math.abs(back - draggedTo) < 1e-3,
      `SIX: transition drag to ${draggedTo}s round-trips via offset=${offsetMs}ms`);
  }
  check(offsetFromDrag(anchorS, 4.0) < 0 && offsetFromDrag(anchorS, 1.0) > 0,
    'SIX: HIS sign law holds for the transition drag too — RIGHT is more '
    + 'negative (fire earlier), LEFT is positive (fire later)');
  check(offsetFromDrag(anchorS, anchorS) === 0,
    'SIX: landing on the anchor is exactly 0');
}

console.log('\nAll multi-cue preview loop checks passed '
  + '(pure logic, no network, no browser, no fixtures).');
