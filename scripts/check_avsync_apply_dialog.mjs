/** The apply dialogue's REFUSAL GATE, proven offline against the real TSX.
 *
 * There is no JS test tooling in this repo, so this follows the precedent
 * of scripts/check_flare_preview_frontend_loop.mjs: extract the gating
 * expressions VERBATIM from the component source and drive them, rather
 * than restating them here where they could drift.
 *
 * What it pins (hold 1 of the apply design, and the thing a real 390px
 * render caught): when the instrument did not stand behind a number, the
 * Apply control is ABSENT, not merely disabled. A disabled button still
 * paints in SPECTRA's primary accent, which reads as pressable — and a
 * control that looks pressable in exactly the state where pressing it
 * would be wrong is the defect this gate exists to prevent.
 *
 * Run: node scripts/check_avsync_apply_dialog.mjs
 */
import { readFileSync } from 'node:fs';

const SRC = 'spectra/web/src/avsync/ApplyOffsetDialog.tsx';
const src = readFileSync(SRC, 'utf8');
let failures = 0;
const check = (label, cond) => {
  console.log(`${cond ? 'ok  ' : 'FAIL'}: ${label}`);
  if (!cond) failures += 1;
};

// ── 1. The Apply control is rendered inside an `applicable` guard ────────
const guard = /\{prop\?\.applicable && \(\s*<button className="primary"/;
check('the Apply button is rendered only inside a `prop?.applicable` guard',
      guard.test(src));

// A refusal must not reach the button at all. Proven by driving the guard's
// own predicate, lifted from the source rather than retyped.
const [, predicate] = src.match(/\{(prop\?\.applicable) && \(\s*<button className="primary"/) || [];
check('the guard predicate extracted from source', predicate === 'prop?.applicable');
const renders = (prop) => new Function('prop', `return !!(${predicate});`)(prop);
for (const reason of ['weak', 'ambiguous', 'unstable', 'no_data', 'clock',
                      'audio', 'light', 'no_measurement', 'out_of_range']) {
  check(`refusal "${reason}" renders no Apply control`,
        renders({ applicable: false, reason }) === false);
}
check('a null proposal (still loading) renders no Apply control',
      renders(null) === false);
check('a measurement the instrument stood behind DOES render it',
      renders({ applicable: true, reason: '' }) === true);

// ── 2. The dialogue never re-derives the sign translation ────────────────
// Every number it shows comes from the server's proposal. A local
// recomputation here is how the flare preview's inverted-sign defect
// happened; this pins that no arithmetic on the measurement exists.
const body = src.split('export default function')[1] || '';
check('no local sign arithmetic on the measured offset',
      !/measured_av_offset_ms\s*[+\-*]/.test(body));
check('no local recomputation of the proposed value',
      !/current_lead_ms\s*\+\s*/.test(body));
check('the direction sentence is rendered, never composed here',
      /\{prop\.direction_sentence\}/.test(body)
      && !/EARLIER than they do now/.test(body));

// ── 3. The write is the established save path, with a real read-back ────
check('the write PUTs room-controls, not a bespoke endpoint',
      /apiPut\('\/room-controls'/.test(body));
check('the write GETs room-controls back afterwards (a PUT echo is not a read-back)',
      /await apiPut\('\/room-controls'[\s\S]{0,200}?await apiGet<\{ av_sync_lead_ms/.test(body));
check('success is claimed only when the read-back matches what was written',
      /const confirmed = after\.av_sync_lead_ms === value;/.test(body));
check('exactly one field is changed in the PUT body',
      /\{ \.\.\.state, av_sync_lead_ms: value \}/.test(body));

// ── 4. Nothing here reaches the two lookalike spot-effects settings ─────
for (const forbidden of ['audio_latency_ms', 'ledfx_trigger_buffer_ms']) {
  const mentions = [...body.matchAll(new RegExp(forbidden, 'g'))].length;
  check(`${forbidden} is never read or written by the dialogue`, mentions === 0);
}

console.log(failures ? `\n${failures} CHECK(S) FAILED` : '\nAPPLY DIALOGUE SPEC OK');
process.exit(failures ? 1 : 0);
