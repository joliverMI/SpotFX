// Pure-logic, network-free, browser-free proof of the minimum-dwell
// control's display state — extracted VERBATIM from
// spectra/web/src/scenes/tabs/SequencingTab.tsx (the dwellEntries record),
// spectra/web/src/components/CurveAttachmentEditor.tsx (the attachment
// derivation, label, and button-thumbnail points), and
// spectra/web/src/queries.ts (useAttachCurve's dwell_curve write mapping).
//
// The defect this pins down (his report, 2026-08-21: "All the scenes seem
// to have the minimum dwell setting set to Flat 1.0... I clicked on
// default curve and it didn't take"): all nine of his scenes store
// dwell_curve: null — the 16s/4s default, correct data — but the OLD
// dwellEntries mapping fabricated a {curve_ref: null, inline_points: null}
// entry for every scene, and the editor's 'none' state is keyed on
// `entries[id]` being undefined, so unset fell through to 'flat' and read
// "Flat 1.0". Clicking the Default tile then wrote null over null (a
// correct, immediate write) and the refetch rebuilt the same fabricated
// entry — the display lied before AND after, so a working control looked
// dead.
//
// Proves:
//   ONE   — OLD mapping: a null dwell_curve scene reads 'flat' / "Flat 1.0
//           (no curve)" (the reported defect, reproduced red).
//   TWO   — NEW mapping: the same scene reads 'none' / "Default (16s →
//           4s)", and the button thumbnail previews the real 16/4 default
//           shape, not a flat line.
//   THREE — round-trip coherence: clicking the Default tile writes
//           dwell_curve: null (queries.ts's verbatim mapping), and the
//           refetched state STILL reads 'none' with the Default tile
//           highlighted — the click visibly "takes" now.
//   FOUR  — a real override still displays as one: inline points read
//           'inline', a named curve_ref reads the profile's own name, and
//           a stored both-null attachment (legal per CurveAttachment,
//           resolved to the default by dwell.py) reads 'none' too.

function check(cond, label) {
  if (!cond) { console.error(`FAIL: ${label}`); process.exit(1); }
  console.log(`ok: ${label}`);
}

const DWELL_CURVE_DEFAULT = [{ x: 0, y: 16 }, { x: 1, y: 4 }]; // types.ts
const FLAT = [{ x: 0, y: 1 }]; // CurveAttachmentEditor.tsx
const NONE_LABEL = 'Default (16s → 4s)'; // SequencingTab.tsx's noneLabel prop

// ── OLD dwellEntries mapping (pre-fix SequencingTab.tsx, verbatim) ────────
function dwellEntriesOld(allScenes) {
  return Object.fromEntries(
    allScenes.map((s) => [s.id, {
      curve_ref: s.dwell_curve?.curve_ref ?? null,
      inline_points: s.dwell_curve?.inline_points ?? null,
      genre_mult: {},
    }]));
}

// ── NEW dwellEntries mapping (SequencingTab.tsx, verbatim) ────────────────
function dwellEntriesNew(allScenes) {
  return Object.fromEntries(
    allScenes
      .filter((s) => s.dwell_curve?.curve_ref != null || s.dwell_curve?.inline_points != null)
      .map((s) => [s.id, {
        curve_ref: s.dwell_curve?.curve_ref ?? null,
        inline_points: s.dwell_curve?.inline_points ?? null,
        genre_mult: {},
      }]));
}

// ── the editor's display derivation (CurveAttachmentEditor.tsx, verbatim:
//    `attachment`, `attachmentLabel`, and the button-preview `points`
//    expression with draft=null) ────────────────────────────────────────────
function editorState(entries, id, curves, { defaultPoints, noneLabel } = {}) {
  const entry = entries[id];
  const attachment = !entry ? 'none'
    : entry.curve_ref ? entry.curve_ref
    : entry.inline_points ? 'inline'
    : 'flat';
  const profile = entry?.curve_ref ? curves[entry.curve_ref] : undefined;
  const points = (profile ? profile.points : entry?.inline_points
    ?? (attachment === 'none' ? defaultPoints ?? FLAT : FLAT));
  const attachmentLabel = profile ? profile.name
    : attachment === 'inline' ? 'Inline one-off'
    : attachment === 'flat' ? 'Flat 1.0 (no curve)'
    : noneLabel ?? '— not sequenced —';
  return { attachment, points, attachmentLabel };
}

// ── useAttachCurve's dwell_curve write mapping (queries.ts, verbatim) ─────
function dwellCurveWrite(attachment) {
  return attachment.kind === 'none' ? null
    : attachment.kind === 'flat' ? { curve_ref: null, inline_points: [{ x: 0, y: 1 }] }
    : attachment.kind === 'profile' ? { curve_ref: attachment.profileId, inline_points: null }
    : { curve_ref: null, inline_points: attachment.points };
}

const dwellProps = { defaultPoints: DWELL_CURVE_DEFAULT, noneLabel: NONE_LABEL };
const curves = { 'prof-1': { id: 'prof-1', name: 'Slow build', points: [{ x: 0, y: 8 }, { x: 1, y: 8 }] } };

// His real state: dwell_curve null on every scene (verified live 2026-08-21).
const unsetScene = { id: 's1', dwell_curve: null };

// ── ONE: the OLD mapping reproduces his report exactly ────────────────────
{
  const st = editorState(dwellEntriesOld([unsetScene]), 's1', curves, dwellProps);
  check(st.attachment === 'flat', 'OLD: unset dwell_curve falls through to the flat state');
  check(st.attachmentLabel === 'Flat 1.0 (no curve)', 'OLD: unset reads "Flat 1.0 (no curve)" — his report');
  check(st.points === FLAT, 'OLD: the button thumbnail draws a flat line, not the default');
}

// ── TWO: the NEW mapping shows what is actually going to happen ───────────
{
  const st = editorState(dwellEntriesNew([unsetScene]), 's1', curves, dwellProps);
  check(st.attachment === 'none', 'NEW: unset dwell_curve is the none state');
  check(st.attachmentLabel === NONE_LABEL, `NEW: unset reads "${NONE_LABEL}"`);
  check(st.points === DWELL_CURVE_DEFAULT, 'NEW: the button thumbnail previews the real 16s/4s default');
}

// ── THREE: clicking the Default tile round-trips coherently ───────────────
{
  const written = dwellCurveWrite({ kind: 'none' });
  check(written === null, 'click Default: writes dwell_curve null (his stored value — a no-op on content)');
  const refetched = { id: 's1', dwell_curve: written };
  const st = editorState(dwellEntriesNew([refetched]), 's1', curves, dwellProps);
  check(st.attachment === 'none', 'after refetch: still the none state — the click visibly took');
  // The picker highlights via `attachment === tile.value`; the Default tile's value is 'none'.
  check(st.attachment === 'none' && st.attachmentLabel === NONE_LABEL,
    'after refetch: the Default tile is the highlighted current pick');
}

// ── FOUR: real overrides still display as themselves ──────────────────────
{
  const inlineScene = { id: 's2', dwell_curve: { curve_ref: null, inline_points: [{ x: 0, y: 10 }, { x: 1, y: 2 }] } };
  const stInline = editorState(dwellEntriesNew([inlineScene]), 's2', curves, dwellProps);
  check(stInline.attachment === 'inline' && stInline.attachmentLabel === 'Inline one-off',
    'a real inline override still reads "Inline one-off"');
  check(stInline.points === inlineScene.dwell_curve.inline_points,
    'a real inline override previews ITS points, not the default');

  const refScene = { id: 's3', dwell_curve: { curve_ref: 'prof-1', inline_points: null } };
  const stRef = editorState(dwellEntriesNew([refScene]), 's3', curves, dwellProps);
  check(stRef.attachmentLabel === 'Slow build', 'a named-profile override reads the profile name');

  // Legal per CurveAttachment (both None = "no override"), resolved to the
  // default by dwell.py's resolve_dwell_curve_points — must read as such.
  const bothNull = { id: 's4', dwell_curve: { curve_ref: null, inline_points: null } };
  const stBoth = editorState(dwellEntriesNew([bothNull]), 's4', curves, dwellProps);
  check(stBoth.attachment === 'none' && stBoth.attachmentLabel === NONE_LABEL,
    'a stored both-null attachment reads as the default too');

  // Picking "Flat 1.0" stays a real, distinct, editable choice (queries.ts's
  // documented design: an inline one-point 1-second curve, never null).
  const flatWrite = dwellCurveWrite({ kind: 'flat' });
  check(flatWrite !== null && flatWrite.inline_points.length === 1 && flatWrite.inline_points[0].y === 1,
    'picking Flat 1.0 still writes a real inline 1-second curve, distinct from unset');
}

console.log('\nall dwell-curve display checks passed');
