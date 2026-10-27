---
name: drop-detection
description: >
  Drop sequence detection, editing and firing (drop-detection plan,
  phases 1-5): spectra/services/drop_detector.py (the detector, with the
  pre-drop rules in predrop_detector.py),
  drop_sequences.py (the stored overrides/additions a song carries and
  the merged view the Timeline draws), drop_console.py (Sonic's own
  reach), drop_firing.py (what actually fires) and drop_panel.py (Home's
  Drops panel: per-part approval, Testing, his own drops). Load before
  touching any of these modules, the drop-sequence Timeline UI, Home's
  Drops panel, or a report shaped like "a drop isn't firing / fired twice
  / won't confirm / Sonic can't edit it / removed one came back."
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
confirm_all, restore, and since the Drops panel parts, approve, remove,
dismiss_for, undismiss_for, multi) goes through it, from three callers:
the Timeline's own buttons (`spectra/api/drop_sequences.py`), Sonic's drop
operations (`drop_console.py`), and Home's Drops panel through
`drop_panel.py`. A new write path here is the thing to avoid — route
through `apply_edit`.

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

## Home's Drops panel — parts, Testing, his own drops (2026-10-26)

Predrop plan step 1 (`/home/javi/fleet-spotfx/data/predrop-plan/
report.md` 3.6). Four things not visible cold:

- **PARTS HAVE TWO MODES.** Every view sequence carries `parts` (on /
  waiting / off / absent for charge, lull, pre_drop, drop). An override
  WITHOUT a `parts` dict is the legacy shape — confirmed or edited means
  the whole sequence is his — so nothing he did before changed meaning.
  The first part edit seeds the dict from that reading (`_ensure_parts`);
  from then on approval is explicit per part, and only an approved DROP
  makes it his (`_view_state`). The Timeline's legacy `member` op still
  makes a sequence "edited" (his) in legacy mode — the panel's part toggle
  never does. The pre-drop's part is real since step 4 (see "Editing a
  pre-drop" below).
- **WHAT FIRES reads parts and Testing** (`drop_firing._member_ms`,
  `_candidates(view, testing)`): a drop part off → never fires (listed,
  silent); a waiting part fires with its tier (confident) or in Testing; a
  view without `parts` fires every member, as before. Testing
  (`RoomControlState.drop_testing`) is in the trigger clock's memo key and
  read once a tick; it protects what it fires AT FIRE TIME only — the
  planner's `protected_windows` never includes it, so a toggle never
  re-plans stored cues.
- **HIS OWN DROPS ARE TWO STORES.** The view's `yours` rows group ALL his
  phase triggers, enabled or switched off (`authored` stays enabled-only
  — it feeds `matches_yours` and the firing). Their writes go through the
  root process's narrow route (`routers/profiles.py` POST
  `/api/profiles/triggers/edit`, `services/profile_trigger_edit.py`: the
  hand-placed → delete / imported → switch-off rule lives there, beside the
  profile) and ALSO dismiss the detection standing in for his drop
  (`dismissed_for` + `prior`, put back when his drop is switched on) —
  under "analysed" that detection is what plays. One undo step covers both
  stores (`drop_panel.restore`). The route's sync is the whole-song one a
  Timeline save runs, so it also lands any earlier profile edit that never
  reached the fired copy (his real Pop Off data has one); a sync that did
  not land marks each changed row `unsynced` and the panel's words say so —
  the automatic catch-up is upsert-only, so a deletion waits for his next
  Timeline save of that song. A trigger BORN ON
  SPECTRA'S TRIGGER CARD (not in the sync ledger, not held by the profile)
  has no profile row: `drop_panel._fired_edit` writes the fired copy
  directly (deleted — placed by hand), and its undo record carries `store:
  "fired"` all the way through the frontend's undo stack. His rows'
  members carry `offset_ms`: a handle sits where the trigger FIRES, so a
  drag stores the moment less the trigger's own `trigger_offset_ms`.
- **A STALE TIMELINE** is told by the root's `profile_triggers_changed`
  broadcast: a clean tab reloads (and starts a fresh undo history), one
  with an unsaved edit HOLDS its save until he chooses
  (`timeline/store.ts` `changedElsewhere`).

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

## Every drop arrives in a new colour set — the drop colour change (2026-10-26)

Predrop plan step 2. `spectra/services/drop_colour.py` is the pick and its
binding statement; `ResponseEngine.drop_color_change` the precedence;
`engine.fire_drop_colour_event` the choke point (the drop's OWN response
gate first, then `house.scene_deferral`). Five things:

- **Where it fires**: `TriggerEngine._fire` for a drop sequence's DROP —
  after `_ensure_switch_plan` (the switch decided, NOT yet cut) and BEFORE
  `_switch_before_member` cuts, so the set comes from the scene the drop
  will show (`_incoming_scene_id`: the incoming one while a switch is
  planned and not yet cut) and the cut compiles in it — and for one of his
  own stored drop triggers, before `_fire_response`. Do not move it after
  the cut, or the cut wears the old set (a mutation-tested RED in
  `tests/test_drop_colour.py`).
- **The pick**: the automatic pool (`scene_sequencer.automatic_pool_cards`
  — the sequencer's own gate chain, factored out so both read ONE), his
  selector weight x closeness to 180 degrees, `drop_colour_spread_deg`
  either side (30 = 150-210). Rainbows count as big; nothing in the band
  takes the farthest; no other set keeps the colours. All named (the
  rung) on the drop's show-log entry (`detail.drop_colour`,
  `trigger_engine.drop_colour_brief`) and counted in fire_history's
  colour sets (`via: "drop_colour"`).
- **The landing** is `_color_jump`'s `picked_id` path, `flare=False`; a
  ramp of 0 now lands as a JUMP (never a zero-length glide).
- **One change per drop**: a landed change CLAIMS the drop
  (`_claim_drop_colour`, ramp + `DROP_COLOUR_CLAIM_S`); `on_event("drop")`
  takes it and the band's own colour-jump kind skips, named (the
  `_DROP_COLOUR_DONE` ContextVar, carried on a `PendingKindBatch`).
- **The fade across a pre-drop is LIVE since step 5** (below): only for a
  pre-drop that PLAYS — the verdict its lull reached (`PreDropTold`), so
  the colour and any pre-drop look agree; one the scene does not play
  leaves the change instant. `_tick_drop_colour_fades` starts the change
  one tick BEFORE the pre-drop's target (`PRE_DROP_COLOUR_LEAD_MS`; the
  target moved with its drop, computed when the lull fired) as a glide over
  the time left to the drop's target, so it lands on the drop whatever the
  lead or a late tick; a LANDED fade is remembered (`_drop_colour_faded`,
  keyed by the sequence or `his:<drop id>`) and its drop does not change
  again; a held one leaves the drop its own instant try.

Holds, each named: the setting off, a room hold (`conductor._deferral`),
Force Colour (a set pin stays; a group pin rolls its next member), a 2D
gradient (its own `on_drop_event` kick is the drop's change), a house mode
that keeps its look, and every gate the drop's own response has. Known
limit: Star's drop pieces keep the colours they sampled at the lull's start
(the plan's step 7 re-samples them). Help topic `drop-colour-change`.
Proofs: `tests/test_drop_colour.py` (the pick over his 46 single-hue sets,
the precedence, and the show-side sweep with a red control).

## Pre-drops — the spike and the vocal intro (2026-10-26)

Predrop plan step 3 (detection; what plays from one is step 5's engine,
below). `spectra/services/predrop_detector.py` is
the binding statement for both rules. Six things:

- **TWO RULES, PORTED LINE FOR LINE FROM THE STUDY** (pd_detect3 and
  pd_intro, plan evidence/tools): a SPIKE (one loud short hit in the high
  band, five tests / seven margins) and a VOCAL INTRO (a mid-band line
  entering out of a hush and holding, six tests). Score = the weakest
  margin, found at >= 1.0. The arithmetic is the measured thing:
  `scripts/check_predrop_detector.py` holds the report's numbers (spike 11
  of 330 / 7 of 498 / 15 of 6,131, intro 8 / 18 / 2) over the moments
  frozen in `tests/fixtures/predrop/study_moments.json`. Change a bar and
  that script tells you what moved; bump `PREDROP_VERSION` (part of every
  detection's stamp) whenever an unchanged song would find differently.
- **SEARCH WIDE, PLAY NARROW**: each kind searches the scene bounds'
  extremes (spike 250-3000 ms, intro 350-4500); a scene's own window is
  applied at play time (step 5). At most one pre-drop per drop: the higher
  score names the kind, a spike on an exact tie. Tiers: a spike is
  confident at 1.07, an intro at 1.18 AND entering within 3.5 s.
- **THE RE-ANCHOR** (in `drop_detector.detect`, after the first-spike
  rule): a drop sitting ON its own pre-drop hit moves to the sustained bass
  return 0.5-2 s later — only when that hit passes the spike test against
  the return (within `SAME_HIT_MS`). The blanket rule ("a short bass hit,
  then a sustained return") would move 26 of 613 detections, seven of them
  drops he had confirmed in place; restricted, it moves exactly Eyes Cut
  Deeper drop 1, to exactly where he moved it (70,350). Its lull and charge
  stay placed against the HIT (`place_sequence(p, found_ms)`) — the break
  leads into the pre-drop — or they land in the gap after the clap.
  `reanchored_from` keeps where it was found, and `_det_distance` pairs an
  override made against the old place with the new one (view pairing AND
  `_resolve_detected_key`, or an edit on the moved drop would mint a second
  override). A confirmed/edited drop does not ask for review when the
  analysis moved TO his own drop.
- **THE VIEW** names it (`pre_drop_ms`, `_kind`, `_auto`, `_tier`,
  `_score`; an automatic pre-drop his drop has moved past is left out, as
  an automatic lull is). Its part, button, handle and drag are step 4,
  below.
- **HIS OWN DROPS' PRE-DROPS** (`authored[].pre_drop`) are computed against
  his drop's moment and memoised per (song, detection stamp, drop ms) —
  ONLY on the read-through path (`view_with_detection`, a worker thread).
  A plain `view()` is the trigger clock's own read and must never analyse:
  it shows what is memoised and leaves the key OUT where nothing is (absent
  = not worked out, `None` = none). Step 5, which needs them on the tick
  path, must fill the memo off the loop (e.g. on the song-change edge).
- **A CUT WINDOW IS A FAITHFUL FIXTURE, EXCEPT ACROSS JITTERED FRAMES.**
  The capture's frame times sometimes step back (~30 ms); np.searchsorted
  over such a stretch can land a frame apart in a cut from where it lands
  over the whole song, so a WEAK verdict's score can differ there (70 of
  6,960 moments; 0 with the timestamps made monotonic; never a found
  verdict, a status or a pre-drop). The check names that class and fails
  on any other. The rules keep the study's raw searchsorted on purpose:
  "fixing" it changes the measured arithmetic.

The test bed's Pre-drops lane (`testbed_engines.ENGINE_PREDROPS`, kinds
`pre_drop` / `spike` / `intro`, every mark carrying `glyph` and `tier`) runs
the rules before every detected drop (the drop sliders' thresholds) and
before each of his drop triggers no detection sits within two beats of. Help
topic `testbed-predrops`. Proofs: `tests/test_predrop_detector.py`
(synthetic envelopes for every test of both rules, the re-anchor, the
committed cut cases, Eyes Cut Deeper whole), `tests/test_predrop_view.py`,
`scripts/check_predrop_detector.py`.

## Editing a pre-drop (2026-10-26)

Predrop plan step 4. `drop_sequences.py`'s "EDITING A PRE-DROP" and "HIS OWN DROPS' PRE-DROPS"
docstring sections are the binding statement. Six things:

- **`pre_drop` IS A HANDLE, NOT A NEW MECHANISM.** It rides the existing
  ops: `handles {pre_drop: ms | None}` (a drag keeps its kind; None = back
  to the detector's place and kind, or gone on a drop he added), `member
  handle=pre_drop` (off keeps where it comes back, `pre_drop_was`), `fill
  handle=pre_drop` (＋ Pre-drop: `predrop_detector.place` — `detect`'s
  answer, else the best weak candidate), `parts {pre_drop}`, the double
  tick and Confirm. One new op, `pre_drop_kind`, switches its kind.
  Undo/redo is the existing before/after pair.
- **TWO RULES, DIFFERENT SCOPES.** Its lead must fit its kind's range
  (`predrop_detector.lead_range`: spike 250-3000, intro 350-4500) — checked
  on the pre-drop's OWN edits (drag, kind switch, fill), never on a drop
  drag, which may therefore leave a placed pre-drop outside it. The order
  rule (one he placed stays 200 ms before its drop) holds a drop move back;
  a move carrying the pre-drop too is checked against where it is GOING
  (`_set_phase_handles(pre=)`). An automatic one a move leaves behind is
  left out with a note.
- **WHAT COUNTS AS HIS.** A drag or a switch-off makes the sequence
  "edited" in the legacy reading (the whole drop his, as a lull drag does);
  a kind switch alone does not. The detector's tier and score show only
  while he has not placed it. A pre-drop found after he confirmed a drop
  WAITS for his tick in the legacy reading; one he placed is on.
- **HIS OWN DROPS' PRE-DROPS LIVE IN THE DROP STORE**, never his song
  profile: `overrides["mine:<drop trigger id>"]`, through
  `apply_edit("mine_pre_drop", drop_ms, pre, step)`. `drop_panel` maps a
  "his:" key onto it (`his_pre_drop_ctx` works the rules' pre-drop out off
  the loop), so every pre-drop route accepts his keys and his profile and
  fired copy are byte-identical afterwards. A combined his-row move writes
  his profile first, then the pre-drop, as one undo step. His row's double
  tick approves its waiting pre-drop (`his_pre_drop_now`), and switching
  it off asks nothing — no trigger of his is touched.
- **THE RAILS**: `snap_rails` adds `hits` (every high-band attack, a
  dragged spike's rail) and `entries` (every mid-band entry passing the
  intro's tests 1-3), `predrop_detector.rails`.
- **THE UI** is two places over the same edits: the Timeline's orange
  pre-drop handle with its kind's glyph (drag-snap to its kind's rail, the
  strip tick, the review card's row; help topic `pre-drop`) and the Home
  Drops panel's pre-drop button plus the editor's fourth handle
  (`home/dropsPanel.ts` holds its snap/step/lead helpers). Both send only
  the calls above.

## The pre-drop engine — what a pre-drop does (2026-10-26)

Predrop plan step 5. `fx/effects/pre_drop.py` (the told keys, the looks,
`phase_clock`) and `spectra/services/pre_drop_play.py` (the one rule) are
the binding statements. Seven things, the first one the most important:

- **NOTHING LIGHTS A PRE-DROP YET.** `fx.device_model.PRE_DROP_EFFECTS` is
  EMPTY: every arm write equals the pre-engine golden over his 14 scenes
  (`tests/test_pre_drop_arm_identity.py`). The only visible change is the
  drop colour fade across a pre-drop that plays. Step 6 (Fireworks, Pulse,
  Orbits) joins the set — each behind his tuning gate — and declares
  `pre_drop_looks` in `config/effect_params.json`.
- **THE DECISION IS AT THE LULL, ON THE SCENE SHOWING.** Rules in order:
  a playable part (a sequence's via `drop_firing._pre_drop_fields` — its
  OWN `pre_drop_tier` for "waiting", never the drop's tier; his own via
  `his_pre_drops`), a lull that fires (`FiringSequence.pre_drop_for` — a
  lull-less sequence has none), a scene showing, that kind on, the gap in
  its window (`SceneV2.pre_drop_spike`: 350-2000 in 250-3000; `pre_drop_
  intro`: 350-4000 in 350-4500), and at least `MIN_AFTER_LULL_MS` (200)
  after the lull actually fired. A drop-led switch cutting at the drop
  leaves the lull (and its pre-drop) on the scene showing; the fade then
  picks from the INCOMING scene's pool.
- **THE TIMING**: target = mark + the drop's own fire shift (moved with
  its drop; for his own drop his trigger's offset too), `pre_drop_at_s` =
  target − the TICK's position (a late lull still lands it on its mark),
  `pre_drop_s` = the music's gap. The colour fade fires one tick early.
- **THE VERDICT COMES BACK**: `engine.fire_response_event` returns the
  response record; the trigger clock reads `phase.pre_drop` into
  `PreDropTold` (`status()["pre_drops"]`) and the show log's lull entry
  carries it as `pre_drop`. A fake `fire_sequence`/`fire_response` in a
  test must accept `pre_drop=` (it is passed only when there is one) and
  return the record if the test wants the fade.
- **A MEMBER'S LULL IS MEASURED TO THE PRE-DROP**: ramp, dark point (if a
  LULL_DARK member) and breath (always, for a member — zeros when it is no
  breath-hold effect and its pre-drop does not play), the breath ending on
  `pre_drop_at_s` with no overrun. Non-members on the same arm are
  untouched. The hand-off's `lull_s` stays the drop's gap (it is about what
  the drop lands on); the keepers meld's `lull_keep` rides alongside.
- **HIS OWN DROPS' PRE-DROPS** are worked out on the song-change edge
  (`drop_sequences.work_out_his_pre_drops`, `on_song_played`'s worker
  thread); a newly memoised answer moves `drop_sequences.revision()` so
  the trigger clock's memo sees it.
- **THE PREVIEW AND THE EDITORS**: the drop-sequence preview's kind switch
  and gap slider (`phase_preview.pre_drop_for_ruler`, the live lull step
  carrying the same candidate; drafted windows and looks travel on the
  request), the Phase tab's Pre-drops card (`scenes/tabs/
  PreDropControls.tsx`, help `pre-drop-scene-window`).

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

The Drops panel's three (2026-10-26): `approve_drop_sequence` (the double
tick), `set_drop_part` (one part on/off, the drop itself included) and
`remove_drop_sequence`. His OWN drops are named by `your_drop_s` or by the
number of the detection standing in for one; because a removal (or a part
switched off on one of his drops) can DELETE triggers he placed by hand,
those ASK FIRST — `needs_confirmation` with the question and a single-use
`confirm_id` bound to the op, its arguments and his row's triggers as they
were (absorb_console's two-call protocol). `undo_drop_edit` puts back his
song-profile rows too. Testing is the ordinary `drop_testing` setting.

The pre-drop (2026-10-26, step 4): `set_pre_drop` (exactly one of
`at_seconds`, `before_drop_ms`, or `place` = detected / rules / off / on)
and `switch_pre_drop` (spike / intro), plus `set_drop_part part=pre_drop`
— none of them asks first, because no trigger of his is touched; each is
undone by `undo_drop_edit`. `list_drop_sequences` shows each drop's
`pre_drop` (time, kind, off, placed by him, tier) and each of his rows'.
Whether one PLAYS on a scene (step 5) is the scene's: six scene-domain
settings through `set_scene_setting` (`pre_drop_spike_enabled` /
`_min_ms` / `_max_ms` and the `pre_drop_intro_*` trio) and, per entry,
`get_pre_drop_looks` / `set_pre_drop_look` (`spectra/services/
scene_console.py` — "auto", "same" for the intro, or a look the entry's
effect declares; anything else is refused with the allowed names).

The drop colour change (2026-10-26) is two ordinary settings-registry keys,
`drop_colour_change` and `drop_colour_spread_deg`; the change itself (a
light-driving act) has no write op, the same boundary every fire keeps.

Every new `apply_edit` op name needs either a Sonic operation or a named
exclusion — `tests/test_drop_console.py::
test_every_apply_edit_op_has_a_sonic_operation_or_is_acknowledged` holds
that, reading the op names out of `_apply_edit`'s own source.

## Proofs

`tests/test_drop_detector.py`, `tests/test_drop_sequences.py`,
`tests/test_drop_console.py`, `tests/test_drop_firing.py`,
`tests/test_drop_floor.py`, `scripts/check_drop_detector.py`,
`scripts/check_drop_firing.py`; the Drops panel's: `tests/
test_drop_parts.py` (parts, Testing, and the show-side sweep on 100
Millones' real detection), `tests/test_drop_panel_his_rows.py` (his own
drops across both stores, on copies of his real Pop Off and Dopamine),
`scripts/check_home_drops_panel.mjs`, `scripts/
check_timeline_changed_elsewhere.mjs`, `scripts/check_home_drops_layout.py`.
The drop colour change's: `tests/test_drop_colour.py`. Pre-drops':
`tests/test_predrop_detector.py`, `tests/test_predrop_view.py`,
`scripts/check_predrop_detector.py`; editing them: `tests/
test_predrop_edits.py` (every edit, the two rules, the rails, his own
drops on his Eyes Cut Deeper shape, the routes, Sonic),
`scripts/check_drop_sequence_view.mjs`, `scripts/
check_drop_sequence_edit.mjs`, `scripts/check_home_drops_panel.mjs`. The
pre-drop engine's: `tests/test_pre_drop_arm_identity.py` (byte-identity
over his scenes), `tests/test_pre_drop_engine.py` (the keys, the rule, stub
members, the hand-off), `tests/test_pre_drop_show_clock.py` (the late
lull, the fade, his own drops), `tests/test_pre_drop_watchdog.py`,
`tests/test_pre_drop_preview.py`, `tests/test_pre_drop_sonic.py`,
`scripts/check_pre_drop_phase_tab.mjs`, and `scripts/check_drop_firing.py`
(its offline show run lists, per song, the lulls that carried a pre-drop
to the response engine).
