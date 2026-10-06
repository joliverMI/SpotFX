---
name: drop-detection
description: >
  Drop sequence detection, editing and firing (drop-detection plan,
  phases 1-5): spectra/services/drop_detector.py (the detector),
  drop_sequences.py (the stored overrides/additions a song carries and
  the merged view the Timeline draws), drop_console.py (Sonic's own
  reach), and drop_firing.py (what actually fires). Load before touching
  any of these modules, the drop-sequence Timeline UI, or a report shaped
  like "a drop isn't firing / fired twice / won't confirm / Sonic can't
  edit it."
---

# Drop detection

A drop sequence is `charge → lull → drop`, detected per song from its
bass-energy shape (`drop_detector.py`) and stored as a cache
(`storage/spectra/drop_sequences.json`) alongside his own overrides and
additions — **the detection is disposable, his edits are not.**
`spectra/services/drop_sequences.py`'s module docstring is the binding
statement for the whole mechanism; read it before touching any of this.

## The one write choke point

`drop_sequences.apply_edit(uri, op, **kw)` is THE edit entry point —
every edit (confirm, dismiss, revert, handles, member, fill, review, add,
confirm_all, restore) goes through it, from three callers: the Timeline's
own buttons (`spectra/api/drop_sequences.py`), Sonic's drop operations
(`drop_console.py`), and nothing else. A new write path here is the thing
to avoid — route through `apply_edit`.

- **`member`** switches a lull/charge OFF (keeping its time) or back ON;
  **`fill`** ADDS one that was never there, placed by the detector's own
  rules. A caller offering "turn the lull back on" must check which case
  it is — `lull_off`/`charge_off` (switched off, time remembered) vs.
  `lull_ms is None` with `lull_off` false (never there at all).
- **`restore`** takes `edits` (an `{overrides, added}` pair) + `expect` (a
  rev fingerprint) — refuses (`EditConflict`) if the song's edits moved
  since `expect` was computed. This is what both the Timeline's undo/redo
  AND Sonic's own one-step undo (`drop_console._LAST_SONIC_EDIT`, in
  memory, keyed per uri) are built from.
- A sequence sitting on his own authored charge/lull/drop triggers reads
  `matches_yours` and is NOT editable through any of this — edit the
  SPECTRA triggers strip instead.

## Detection is cheap to re-run and never touches his edits

`ensure_detected(uri, force=False)` re-detects only when the stored
stamp is stale (detector version + the two tier thresholds + the drop
floor + the song's own analysis inputs) or `force=True`; `his overrides
and added sequences are
never touched by a re-detection` — stated in that function's own
docstring, and asserted by tests. Bump `drop_detector.DETECTOR_VERSION`
whenever the detection logic changes, or an unchanged song never
re-plans.

## Firing (phase 5) is a separate module and a separate gate

`drop_firing.py` decides whether a sequence actually fires, under which
`scene_change_mode`, and inside the PROTECTED WINDOW the drop/lull moment
holds against being picked as an ordinary scene-change candidate. Editing
a sequence here (confirming it, moving it, switching off its lull) is
what makes it count as "his" for that gate — it does not, by itself, make
anything fire differently without going through `drop_firing`'s own
rules. See AGENTS.md's "DROP DETECTION — the detector and its file" and
"PHASE 5 — FIRING" sections for the full mechanism.

## Sonic reach

`spectra/services/drop_console.py`, domain `"drops"`. The full edit set
as of 2026-10-06: `list_drop_sequences` (now also reporting
`lull_off`/`charge_off`, and `fires`/`fires_reason` via
`drop_firing.annotated_view` — the same phase-5 verdict the Timeline
shows, not just state/times), `confirm_drop_sequence`, `dismiss_drop_sequence`,
`move_drop_handle`, `add_drop_sequence`, `set_drop_member` (on/off AND
"never there — place it"), `revert_drop_sequence`, `resolve_drop_review`,
`undo_drop_edit` (Sonic's own last edit only, refused if the Timeline
edited the song since), `redetect_drop_sequences`,
`drop_detection_summary`. The two detection thresholds
(`drop_confident_score`/`drop_suggested_score`) AND the drop floor
(`drop_floor`, 2026-10-06, the Admiral's own ask — a candidate is only
generated where the containing librosa section's `energy_rms` during or
right after the drop reaches at least this, default 0.95; never removes
a sequence he has confirmed, edited or added) are plain
`settings_console.SETTINGS_REGISTRY` keys, not drop ops. A sequence
numbered by Sonic is the SAME numbering the Timeline review list shows
(song order among non-dismissed sequences) — never a raw store key.

Every new `apply_edit` op name needs either a Sonic operation or a named
exclusion — `tests/test_drop_console.py::
test_every_apply_edit_op_has_a_sonic_operation_or_is_acknowledged` holds
that.

## Proofs

`tests/test_drop_detector.py`, `tests/test_drop_sequences.py`,
`tests/test_drop_console.py`, `tests/test_drop_firing.py`,
`tests/test_drop_floor.py`, `scripts/check_drop_detector.py`,
`scripts/check_drop_firing.py`.
