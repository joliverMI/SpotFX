// Pure-logic, network-free, browser-free proof of the flare preview's
// frontend scheduling formulas — extracted VERBATIM from
// spectra/web/src/scenes/tabs/FlarePreviewOverlay.tsx and
// spectra/web/src/scenes/tabs/flareKindOps.ts, driven with a fake clock so
// there is zero risk of any network call reaching a real backend/hardware.
//
// Proves:
//   ONE  — the RAF loop's fire schedule crosses fireAtS repeatedly, once
//          per lap, for many laps in a row (not once on open).
//   FOUR — setKindTriggerOffset (the pure function onTriggerOffsetChange
//          feeds into) correctly persists a dragged offset, clamped and
//          keyed by kind name; and dragTrigger's own offset-from-drag-
//          position formula round-trips through trigger_mark_s exactly.

function check(cond, label) {
  if (!cond) { console.error(`FAIL: ${label}`); process.exit(1); }
  console.log(`ok: ${label}`);
}

// ── setKindTriggerOffset, verbatim from flareKindOps.ts ────────────────────
function setKindTriggerOffset(scene, name, ms) {
  const clamped = Math.max(-60_000, Math.min(60_000, Math.round(ms)));
  return {
    ...scene,
    flare_kinds: scene.flare_kinds.map((k) =>
      k.name === name ? { ...k, trigger_offset_ms: clamped } : k),
  };
}

// ── dragTrigger's own offset formula, verbatim from FlarePreviewOverlay.tsx
function offsetFromDragPosition(animAnchorS, draggedMarkS) {
  return Math.round((animAnchorS - draggedMarkS) * 1000);
}

// ── trigger_mark_s, verbatim from spectra/services/flare_preview.py (the
//    backend's own formula, ported here only to prove client/server agree)
function triggerMarkS(anchorS, offsetMs, durationS) {
  const t = anchorS - offsetMs / 1000.0;
  return Math.max(0.0, Math.min(durationS, t));
}

// ── FOUR: dragging persists the offset onto the right kind, clamped ───────
{
  const scene = { flare_kinds: [{ name: 'a', trigger_offset_ms: 0 }, { name: 'b', trigger_offset_ms: 0 }] };
  const dragged = setKindTriggerOffset(scene, 'a', -350);
  check(dragged.flare_kinds[0].trigger_offset_ms === -350, 'drag: offset lands on the dragged kind');
  check(dragged.flare_kinds[1].trigger_offset_ms === 0, 'drag: the OTHER kind is untouched');
  check(scene.flare_kinds[0].trigger_offset_ms === 0, 'drag: original scene object is not mutated');

  const over = setKindTriggerOffset(scene, 'a', 999_999);
  check(over.flare_kinds[0].trigger_offset_ms === 60_000, 'drag: offset clamps at +60000ms');
  const under = setKindTriggerOffset(scene, 'a', -999_999);
  check(under.flare_kinds[0].trigger_offset_ms === -60_000, 'drag: offset clamps at -60000ms');
}

// ── FOUR: drag position → offset → trigger_mark_s round-trips (his sign
//    convention: drag RIGHT [larger s] -> more negative offset -> mark
//    redraws back at the SAME dragged position, client and "server" formula
//    agreeing exactly) ───────────────────────────────────────────────────
{
  const anchorS = 2.0, durationS = 6.0;
  for (const draggedTo of [0.5, 1.0, 1.9999, 2.0, 3.5, 5.0]) {
    const offsetMs = offsetFromDragPosition(anchorS, draggedTo);
    const markBack = triggerMarkS(anchorS, offsetMs, durationS);
    check(Math.abs(markBack - draggedTo) < 1e-3,
      `drag to ${draggedTo}s round-trips through offset=${offsetMs}ms back to ${markBack.toFixed(4)}s`);
  }
  // his stated rule: drag RIGHT -> more negative offset
  const offsetAt1 = offsetFromDragPosition(anchorS, 1.0);
  const offsetAt3 = offsetFromDragPosition(anchorS, 3.0);
  check(offsetAt3 < offsetAt1, 'drag right (larger s) produces a MORE NEGATIVE offset');
}

// ── ONE: the RAF loop's own fire-schedule formula, run for many laps ──────
// Verbatim extraction of the scheduling arithmetic from the play/loop
// effect: normalizedFireAtS, delayToFireS, and the "advance by whole
// periods" catch-up loop. Driven by a fake clock (no requestAnimationFrame,
// no network) — every simulated frame just advances `now` by a fixed dt and
// asks "did we cross nextFireAt".
function simulateLoop({ fireAtS, durationS, totalRealSeconds, dtMs = 16 }) {
  const normalizedFireAtS = ((fireAtS % durationS) + durationS) % durationS;
  let playhead = 0;
  let now = 0; // ms, fake performance.now()
  const delayToFireS = normalizedFireAtS >= playhead
    ? normalizedFireAtS - playhead
    : durationS - playhead + normalizedFireAtS;
  let nextFireAt = now + delayToFireS * 1000;
  const fireTimestampsMs = [];
  let lastFrame = null;
  const endAt = totalRealSeconds * 1000;
  while (now < endAt) {
    now += dtMs;
    if (lastFrame != null) {
      const dt = (now - lastFrame) / 1000;
      const next = playhead + dt;
      playhead = next >= durationS ? next % durationS : next;
    }
    lastFrame = now;
    if (nextFireAt != null && now >= nextFireAt) {
      fireTimestampsMs.push(now);
      while (nextFireAt <= now) nextFireAt += durationS * 1000;
    }
  }
  return fireTimestampsMs;
}

{
  // offset=0, no lead: fireAtS == animAnchorS == 2.0, duration 6.0s.
  const fires = simulateLoop({ fireAtS: 2.0, durationS: 6.0, totalRealSeconds: 32 });
  check(fires.length >= 5, `ONE: fires every lap, not once — got ${fires.length} fires over 32s @ 6s laps`);
  // Consecutive fires must be spaced ~durationS apart (within one frame dt).
  for (let i = 1; i < fires.length; i++) {
    const gap = fires[i] - fires[i - 1];
    check(Math.abs(gap - 6000) <= 20, `ONE: fire ${i} spaced ~6000ms after fire ${i - 1} (got ${gap}ms)`);
  }
  // First fire lands at ~fireAtS (2.0s), not at t=0 (his report: it used to
  // fire "almost as soon as the preview started").
  check(Math.abs(fires[0] - 2000) <= 20,
    `ONE: first fire waits for the mark (~2000ms), not an instant open-time fire (got ${fires[0]}ms)`);
}

{
  // TWO's frontend wiring: a kind with a 220ms lead fires 220ms EARLIER
  // every lap than the same kind with lead=0, proving fire_at_s (not
  // animation_anchor_s) genuinely drives the schedule.
  const noLead = simulateLoop({ fireAtS: 2.0, durationS: 6.0, totalRealSeconds: 20 });
  const withLead = simulateLoop({ fireAtS: 2.0 - 0.22, durationS: 6.0, totalRealSeconds: 20 });
  check(noLead.length === withLead.length, 'TWO: same number of fires either way');
  for (let i = 0; i < noLead.length; i++) {
    const diff = noLead[i] - withLead[i];
    check(Math.abs(diff - 220) <= 20,
      `TWO: lead-adjusted schedule fires 220ms earlier every lap (fire ${i}: diff=${diff}ms)`);
  }
}

{
  // ONE + FOUR combined: dragging the mark (changing fireAtS mid-session,
  // as the loop effect's own dependency array [playing, durationS, fireAtS,
  // timeline] would trigger a reschedule) changes WHEN subsequent fires
  // land, not just once but every lap after the change.
  const before = simulateLoop({ fireAtS: 2.0, durationS: 6.0, totalRealSeconds: 20 });
  const draggedRight = 3.0; // drag right -> more negative offset -> mark moves right;
  // dragging the trigger mark does not itself move fireAtS in THIS module's
  // design (fireAtS is server-derived from lead only) — this branch proves
  // the INDEPENDENT case: an intensity change (or any fresh /open) that
  // legitimately moves fireAtS reschedules every subsequent lap, not just
  // the next one.
  const after = simulateLoop({ fireAtS: 3.0, durationS: 6.0, totalRealSeconds: 20 });
  check(before.length >= 3 && after.length >= 3, 'reschedule case: both runs produce multiple fires');
  for (const f of after) {
    const posInLap = f % 6000;
    check(Math.abs(posInLap - 3000) <= 20 || Math.abs(posInLap - 3000 - 6000) <= 20,
      `reschedule: every fire after a fireAtS change lands at the NEW position (${f}ms, pos-in-lap=${posInLap}ms)`);
  }
}

// ── FIVE: an INTENSITY CHANGE mid-loop (the colour rotate-and-back case —
// the ONLY kind whose lead, and therefore fireAtS, moves with intensity).
// Models the component's actual transition, verbatim from the timeline-
// refetch .then + the loop effect's restart: the .then resets the playhead
// to 0 and keeps durationS = max(prev, new) (so an Extend-grown or
// longer-previous ruler never shrinks under him), the effect restarts and
// derives the next-fire deadline fresh from the CURRENT playhead. The
// question this answers (2026-08-21, his report "after I change intensity
// it no longer runs as the playhead crosses the trigger"): does the kept
// stale-longer duration strand the fire schedule away from the drawn
// marks? It cannot — proven here — because playhead wrap, fire cadence,
// and every drawn mark all share the SAME durationS, and the anchor
// geometry is pinned (see SIX below). The real defect was server-side
// (flare_preview_hold.open_hold never scheduled the rotate's fade-back
// release queue — tests/test_flare_preview_hold.py), not this arithmetic.
function simulateIntensityChange({ fire1, dur1, fire2, dur2server, changeAtS, totalRealSeconds, dtMs = 16 }) {
  // durationS transition, verbatim: setDurationS((prev) => Math.max(prev, tl.duration_s))
  const dur2 = Math.max(dur1, dur2server);
  let playhead = 0;
  let now = 0;
  let durationS = dur1;
  let fireAtS = fire1;
  const startSchedule = () => {
    const normalizedFireAtS = ((fireAtS % durationS) + durationS) % durationS;
    const delayToFireS = normalizedFireAtS >= playhead
      ? normalizedFireAtS - playhead
      : durationS - playhead + normalizedFireAtS;
    return now + delayToFireS * 1000;
  };
  let nextFireAt = startSchedule();
  const fires = [];
  let lastFrame = null;
  let changed = false;
  while (now < totalRealSeconds * 1000) {
    now += dtMs;
    if (!changed && now >= changeAtS * 1000) {
      // the .then, verbatim: new timeline lands — playhead resets to 0,
      // duration keeps the max, fireAtS takes the server's new value, and
      // the loop effect restarts (deps: durationS/fireAtS/timeline)
      changed = true;
      durationS = dur2;
      fireAtS = fire2;
      playhead = 0;
      lastFrame = null;
      nextFireAt = startSchedule();
      continue;
    }
    if (lastFrame != null) {
      const dt = (now - lastFrame) / 1000;
      const next = playhead + dt;
      playhead = next >= durationS ? next % durationS : next;
    }
    lastFrame = now;
    if (nextFireAt != null && now >= nextFireAt) {
      fires.push({ atMs: now, playheadS: playhead, afterChange: changed });
      while (nextFireAt <= now) nextFireAt += durationS * 1000;
    }
  }
  return { fires, dur2 };
}

{
  // The rotate's REAL numbers (scene_response.py): fire_at_s = 2.0 - ramp.
  // Open at intensity 0.3 (ramp 775ms, server duration 6.758s), then RAISE
  // to 1.0 (ramp 250ms, server duration 6.0s) — the shrink direction, where
  // Math.max keeps the stale 6.758s while the server computed against 6.0.
  const { fires, dur2 } = simulateIntensityChange({
    fire1: 2.0 - 0.775, dur1: 6.758,
    fire2: 2.0 - 0.25, dur2server: 6.0,
    changeAtS: 9.0, totalRealSeconds: 40,
  });
  check(dur2 === 6.758, 'FIVE: Math.max keeps the stale longer duration (the suspected desync)');
  const after = fires.filter((f) => f.afterChange);
  check(after.length >= 4, `FIVE: the loop keeps firing after the change (${after.length} fires)`);
  for (const f of after) {
    // every post-change fire lands exactly where the ruler draws the
    // "start" line — playhead == fireAtS at the moment of fire — so the
    // fire schedule and the drawn marks still agree despite the stale max
    check(Math.abs(f.playheadS - 1.75) <= 0.04,
      `FIVE: post-change fire lands ON the drawn start line (playhead=${f.playheadS.toFixed(3)}s vs 1.75s)`);
  }
  // cadence: consecutive post-change fires are one (stale) lap apart —
  // the SAME lap length the playhead itself wraps at, so no drift ever
  // accumulates between the white playhead and the fire schedule
  for (let i = 1; i < after.length; i++) {
    const gap = after[i].atMs - after[i - 1].atMs;
    check(Math.abs(gap - 6758) <= 20, `FIVE: post-change cadence matches the shared duration (${gap}ms)`);
  }
}

// ── SIX: the structural premise that makes FIVE hold — the anchor cannot
// move. animation_anchor_s (verbatim from spectra/services/flare_preview.py)
// is min(2.0, duration_s / 3), and duration_s is never below MIN_TIMELINE_S
// (6.0) — so the anchor is pinned at exactly 2.0 for EVERY reachable
// timeline, every intensity, every kind. A stale-longer client duration
// therefore never shifts where the anchor/trigger geometry sits — only how
// long a lap takes. ──────────────────────────────────────────────────────
{
  const MIN_TIMELINE_S = 6.0;
  const animationAnchorS = (durationS) => Math.min(2.0, durationS / 3);
  for (const d of [6.0, 6.263, 6.758, 7.5, 20.0, 60.0]) {
    check(d >= MIN_TIMELINE_S && animationAnchorS(d) === 2.0,
      `SIX: anchor pinned at 2.0 for duration ${d}s`);
  }
}

console.log('\nAll flare-preview frontend loop checks passed (pure logic, no network, no browser).');
