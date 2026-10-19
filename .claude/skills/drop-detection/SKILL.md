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
  SPECTRA triggers strip instead. `matches_yours` is mode-INDEPENDENT (it
  is a fact about proximity to his marks, not about whether those marks
  can currently fire) — see "Firing" below for what a `matches_yours`
  sequence actually does under the room's scene-change mode.

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

**A `matches_yours` sequence stands down only when his own trigger
actually fires in a mode that fires his triggers** (2026-10-07,
data/popoff-drops-not-firing/report.md: Pop Off's three detections each
sat on one of his own authored drops and stood down as `matches_yours`,
but the room's scene-change mode was "analysed", which never fires a
hand-authored trigger — so BOTH doors went silent). `drop_firing.
his_applies(effective_mode)` is true only for "full"/"triggers_only" —
NOT "analysed" — and `fires_here` consults it: standing down only when
it's true, otherwise falling back to the sequence's own tier exactly as
an unmatched one of the same kind would (confident fires as the analysed
show, suggested still waits for his confirm). `firing_sequences` stays
mode-independent (the trigger clock memoises it without the room's mode)
by flagging a matched sequence `matches_his=True` rather than excluding
it outright — `_recovered_state` is what lets `_candidates` tell a
confident/edited match apart from a bare, unconfirmed suggested one it
still must not fire.

**The same mode-aware fallback applies one level down, to a single
stood-down member, and the dedup is now unconditional (2026-10-07,
same report).** `firing_sequences` only ever FLAGS a charge/lull within
reach of a same-class authored mark (`FiringSequence.stood_down`) — it
never nulls `charge_ms`/`lull_ms`. `FiringSequence.members(effective_mode)`/
`gap_ms(cls, effective_mode)` are what actually exclude a stood-down
member, and only when `his_applies(effective_mode)` is true for the mode
they're given; with no mode, or a mode where his trigger can't fire there
("analysed"), every declared member comes back — the Pop Off shape one
level down (drop:178753's own charge/lull sat exactly on his authored
charge/lull, so the old unconditional null silenced both under "analysed"
too). `resolved_stood_down(effective_mode)` is the same rule for
`annotate()`'s own display field, so the Timeline never shows a member as
standing down in a mode where it's actually firing. `trigger_engine.
_sequence_triggers` calls `seq.members(mode)` and stores `(seq, cls, mode)`
in `_seq_meta` so `_fire` resolves the identical member set at fire time
(`seq.gap_ms(cls, fire_mode)`, the fire-history detail's own `members`
list). Separately, the "another firing sequence owns this drop" dedup in
`firing_sequences` now runs UNCONDITIONALLY — it used to skip whenever the
candidate `matches_his`, letting two independently-kept sequences both
matching the same authored mark fire on top of each other; `matches_his`
decides which of two sequences near one drop wins (his sort order), never
whether the dedup applies at all.

## Every drop fires off its mark — the drop timing offset (2026-10-12)

`spectra/services/drop_timing.py` is the binding statement. The room's
`drop_timing_offset_ms` (default -400 ms, negative = earlier; a scene's own
`SceneV2.drop_timing_offset_ms` wins when set) is summed by
`trigger_engine.tick()` into the target of every fire_response DROP — the
sequence members and his own stored drops alike — so the drop arm, the
drop-led cut on the drop, the Shockwave and the strip drop all move
together. `FiringSequence.gap_ms(..., drop_offset_ms=)` and
`_phase_partner_gap_ms` hand a build ending on a drop the gap to the
SHIFTED mark (the breath-hold ends on it); a drop never moves within
`MIN_BUILD_MS` of its lull; a Fireworks meld's `after_drop` delay counts
from the fired drop (`late_release(drop_offset_ms=)`). The member
timestamps, the protected windows and the Timeline's drop marks stay on the
music's own mark. Tests hold it at 0 unless marked `drop_timing_live`.
A scene's own value is set by dragging the drop's red line on its
drop-sequence preview (a scene-draft edit, kept by Save; −50/−10/+10/+50 ms
buttons and "Room's" beside it) or by Sonic's `set_scene_setting` key
`drop_timing_offset_ms` (null = back to the room's).

## What a LULL is TOLD about its drop — the lull hand-off hook (2026-10-08)

A drop sequence's lull can be told how many pieces to leave on the panel
for the drop and which effect the drop will land on. That is ONE hook, and
it already exists — do not build a second: `fx/effects/lull_handoff.py`
(the keys `lull_keep`/`lull_next`/`lull_s` on every lull arm,
`drop_intensity` on every drop arm, membership
`fx.device_model.LULL_HANDOFF_EFFECTS`/`DROP_INTENSITY_EFFECTS`) and
`scene_response`'s "THE LULL HAND-OFF HOOK" docstring section (the
`LullContext` -> `LullHandoff` RESOLVER). Drop-led scene switching and the
fireworks melds plug in by `scene_response.install_lull_handoff_resolver
(fn)`, once, from `spectra/services/engine.py` — process-wide on purpose so
the drop-sequence preview's scratch responders ask the same resolver the
room does. The resolver must be pure and cheap (the preview runs it per
lap), never raise into the fire (a failure falls back to keep 1, named in
the record as "default (resolver failed)"), and answer per virtual
(`next_effect` absent = the same effect). `LullContext.uri`/`position_ms`
are the live song, so a resolver can find the sequence the lull belongs to.
With nothing installed every lull keeps 1 (the Admiral's fish ask). Fish is
the first adopter: told `lull_keep = 3, lull_next = "fireworks"` it leaves
three spaced keepers whose positions are exactly what Fireworks' adopt path
reads from `_handoff_snapshot`. Proofs: `tests/test_lull_handoff.py`,
`tests/test_fish_lull_searcher.py`.

## A drop can BE the scene change — the drop-led switch (2026-10-08)

`spectra/services/drop_switch.py`'s docstring is the binding statement
(the Admiral's two rulings are quoted there). The short list:

- **Decided once per sequence** by the trigger clock at the FIRST member
  it fires (`TriggerEngine._decide_switch`), executed in the SAME `_fire`
  call as the planned member, BEFORE it (`_switch_before_member`), so the
  member's own phase arm lands on the NEW scene. Do not move the cut into
  a separate trigger — that is the one-frame-early/late defect.
- **The default is a hard cut ON the drop** (`fire_scene_by_id(origin=
  "drop", cut=True)` → `fx_seam.apply_writes(cut=True)` → `set_effect(cut=
  True)`, `fx/VENDOR.md` #63). The charge and lull run on the outgoing
  scene; the lull is told what is coming through the hook below (this
  module IS the installed resolver). A dwell is never waited on, but is
  NAMED (`overrode_dwell_for_drop`).
- **Early, at the charge start or riding the first flare inside it**, only
  when the pair has no `HANDOFF` row (outgoing Eye/Dancer/Pac-Man, or
  nothing showing) or the scene has OVERSTAYED (dwell + `drop_switch_
  stale_margin_s`). A ride that never fires cuts at the next member.
- **Stale**: repeated the previous drop without arriving on it / carried
  `drop_switch_drops_in_a_row` drops / overstayed / nothing showing.
  Targets: sequencer-entry scenes whose Matrix effect is in
  `device_model.CENTRE_BURST_EFFECTS` or `DROP_FIREWORKS_EFFECTS`, drawn
  by the kernel with a Random seeded by (song, key, showing scene).
- **The FIREWORKS MELDS (phase 3)** are rows of the same table, not a
  second mechanism: Fish/Orbits -> Fireworks is `keepers` (the lull is told
  keep `FIREWORKS_KEEP` 3; Fireworks explodes each keeper where it stands on
  the drop cut); Fireworks -> Black Hole is `swallowed` (moment
  `after_drop`: Fireworks plays its own drop, the cut lands
  `drop_switch_swallow_delay_s` after the mark); Fireworks -> Fish/Orbits/
  Squiggles/STAR is `implode_on_hit` (moment `next_hit`: armed at the drop
  — `TriggerEngine._arm_late_switch` — and released by THE NEXT BIG BASS
  HIT, `drop_switch.next_big_hit`, the first ANALYSED flare past the drop's
  own reach at least `drop_switch_hit_threshold`; its `_fire` cuts first so
  the flare lands on the new scene, the "comes in loud"; no hit by
  `hit_deadline_ms` — tail + a bar — and the deadline cuts and fires the
  flare itself). A late switch still pending when the next sequence's first
  member fires is cut then (`before_next_sequence`). On his dense FINA the
  next sequence usually arrives first. An overstayed Fireworks still
  switches early, at the charge (rule B).
- Recorded: `drop_switch.plans_for(uri)` (→ `drop_firing.annotate`'s
  `switch`, the Timeline strip's ⇄ mark), the show log
  (`drop_sequence:switch`), Sonic's `explain_drop_switch`. The sequence
  preview runs `preview_plan` and performs the cut live.

Proofs: `tests/test_drop_switch.py` (FINA + 100 MILLONES real stores),
`tests/test_drop_switch_cut.py` (the cut on the real pipeline),
`tests/test_preview_programs_live.py`, `tests/test_fireworks_melds.py`
(the three melds: decision, effects, FINA trigger clock).

## A LIGHT SHOW SET CAN BE ARMED ON A PHASE (2026-10-19)

The Admiral: "add a button for next drop, lull, and charge. make it one
button that cycles through those to reduce clutter." `show_arms.TRIGGERS`
gained `drop`/`lull`/`charge` (`PHASE_TRIGGERS`), and the moments come
from `drop_firing.phase_moments(view)` — the one pure rule: every firing
sequence's declared members plus his own authored phase triggers, his
winning a collision within two beats, SUGGESTED and DISMISSED excluded.
Three things to know before touching it:

- **It is mode-independent and sits on the MARK.** A phase cue is a
  moment in the music, like a High Trigger — never narrowed by
  `scene_change_mode`, and never relocated by `drop_timing`'s offset.
  Both are argued in that function's own docstring.
- **The trigger engine publishes it off `_drop_state`'s existing memo**
  (`TriggerEngine.phase_cue_moments`, read by `show_arms.phase_moments`),
  so the cue plan costs a tuple compare per tick rather than a
  `triggers.json` parse. `None` means "not worked out for this song yet",
  which is a different answer from `[]`.
- A sequence step and a playlist step deliberately cannot arm on a
  phase — named, with the reason, on `SEQUENCE_ARMS`/`WAIT_TRIGGERS`/
  `PLAYLIST_STEP_TIMINGS` in `spectra/models/light_show.py`.

Spec: `tests/test_light_show_arms.py` section 5 (the firing and
disarming, through the real trigger clock), `scripts/
check_phase_arm_cycle.mjs` + `scripts/check_light_show_run_icon_buttons.mjs`
section SIX (the one cycling button), both run by
`tests/test_phase_arm_cycle.py`. Help topic `show-phase-arming`,
`sonic-light-show`. See "Sonic reach" below for the CLI-backend docstring
gap this feature's sonic-ops follow-up found and fixed.

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
`drop_detection_summary`, and (2026-10-08) the read-only
`explain_drop_switch` — why a sequence did or did not change the scene
this play. The switch's six tunables (`drop_switch_enabled`,
`_after_previous_drop`, `_stale_margin_s`, `_drops_in_a_row`, and the
fireworks melds' `_swallow_delay_s`, `_hit_threshold`) are plain
settings-registry keys; the switch itself (a light-driving act) has no
write op, by the same boundary every other fire keeps. The two detection thresholds
(`drop_confident_score`/`drop_suggested_score`) AND the drop floor
(`drop_floor`, 2026-10-06, the Admiral's own ask — a candidate is only
generated where the top bar's own "⚡ Energy" number, EXACTLY AS
DISPLAYED (the adjacent "Mark" readout is separate and never factored
in), during or right after the drop reaches at least this, default 0.7
(his own fallback — 0.95 kept 0 of his 11 detector-found drops, 0.7
keeps 9 of 11); never removes a sequence he has confirmed, edited or
added) are plain
`settings_console.SETTINGS_REGISTRY` keys, not drop ops. A sequence
numbered by Sonic is the SAME numbering the Timeline review list shows
(song order among non-dismissed sequences) — never a raw store key.

`arm_show_set` (domain `"show"`, `show_console.py`) reaches the three
phases too since 2026-10-19 — its `on` enum is `show_arms.TRIGGERS`
itself, read rather than re-typed, so the API-backend's `input_schema`
and `_op_arm_show_set`'s validation, AND the CLI backend's own
`_ArmTriggerEnum` (`Literal[tuple(show_console.TRIGGER_CHOICES)]`), all
widened for free the moment `TRIGGERS` grew — `show_status` already
surfaces each armed set's `on` plus the song's own per-phase countdown
(`arms.song.phases`) too. **What did NOT widen automatically**: the two
hand-written MCP tool wrapper DOCSTRINGS in `settings_mcp_server.py`
(`arm_show_set`/`show_status` — the CLI/subscription backend's own tool
*descriptions*, which a model reads, as distinct from the enum TYPE those
same functions declare) still said only "scene change, or High/Low" after
this shipped — found live, fixed as a sonic-ops follow-up (prose updated
to name all six triggers; `tests/test_show_console.py` covers arm/read/
disarm on each phase plus a docstring regression). The enum and the
validation are generated from `TRIGGERS`; the wrapper prose is
hand-maintained and is not — check both on any future widening.

Every new `apply_edit` op name needs either a Sonic operation or a named
exclusion — `tests/test_drop_console.py::
test_every_apply_edit_op_has_a_sonic_operation_or_is_acknowledged` holds
that.

## Proofs

`tests/test_drop_detector.py`, `tests/test_drop_sequences.py`,
`tests/test_drop_console.py`, `tests/test_drop_firing.py`,
`tests/test_drop_floor.py`, `scripts/check_drop_detector.py`,
`scripts/check_drop_firing.py`.
