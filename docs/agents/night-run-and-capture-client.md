# The night run and the unattended capture client

Moved from AGENTS.md during the 2026-11-09 trim (PR fm/spotfx-trim-agents-md).
Content below is verbatim from the prior AGENTS.md; see AGENTS.md's routing table
for when to read this file.

---

## THE NIGHT RUN — HA pushes, we answer (and, ARMED, it takes the room)

His `Sleeping` helper is a better signal than a person: when it has been on
for thirty continuous minutes Home Assistant PUSHES one event and the
declared capture queue works through the night. `spectra/services/
night_run.py`'s module docstring is the binding statement; the seam contract
both captains agreed is `/home/javi/fleet-seam/river-dj-night-run-seam.md`.
`POST /api/night-run/{start,abort}` (Bearer, `SPECTRA_NIGHT_RUN_TOKEN`, read
at request time, absent-or-wrong is the same 401), `GET /api/night-run/
{would-start,fixtures,morning}` (open reads), `GET/PUT /api/night-run/queue`
(the declaration). **NO POLLING anywhere on our side, on any cadence** — he
pushes, we answer reads. Eight things, and each one has cost something
already:

- **ASK FIRST, PREPARE ONLY ON YES — `GET /api/night-run/would-start`,
  and THE ONE-PREDICATE GUARANTEE IS THE POINT OF IT** (2026-09-02, the
  seam's addenda 7-9). His house PREPARES before it starts a night (River
  fires the "Dark Music" envelope, then pushes start), so on 2026-09-01 the
  envelope fired, the start declined by name — no declared queue, the
  DESIGNED outcome — and his house sat lit while he slept. The preflight is
  a PURE READ (open, like every other read here; no writes, no state, no
  room touched) answering the exact three gates a start applies: owned?
  declared-and-parses? prices inside the 05:30 bound? — plus the two
  already-running gates. `{"would_start": true, ...}` or `{"would_start":
  false, "reason": <the start's OWN sentence>, "code": <not_owned |
  no_declared_queue | already_running | will_not_fit, or a calibration
  declaration's own refusal kind>}`, and the planned end / priced seconds /
  window ride along because the pricing already computed them.
  **`night_run.evaluate_start` IS THE ONE GATE CHAIN — `start()` calls it
  too, and neither caller keeps a gate of its own.** A preflight with its
  own copy would be worse than none: a confident wrong answer at 1am with
  nobody awake. `tests/test_night_would_start.py` holds that structurally
  (a sentinel proving both callers route through the one function, a
  yes-under-a-hostile-world proving neither kept a private veto, and a
  callgraph check that no gate NAME appears in either caller's body) and
  BOTH halves were verified RED against a re-introduced second
  implementation. The staleness window is NAMED, not closed: a yes can go
  stale, and closing that would mean reserving something — preparation
  before confirmation in disguise. Safety does not rest on the yes; River
  snapshots before preparing and restores on any start answer that is not
  `state == "running"`.

- **THE BOUNDARY: a start arriving while SPECTRA does not ALREADY hold the
  room DECLINES by name, records the declined night, and does nothing
  else.** The Admiral's word at the time — "it does not help itself to his
  room while he sleeps. That boundary is worth more than an occasional
  missed night." **HE HAS SINCE OVERRULED IT** for a RELEASED room behind
  one absent-by-default lever — see THE SELF-TAKING NIGHT below; everything
  in this bullet is still exactly what an UNARMED deploy does, and that is
  every deploy until he words the arm. The ownership record is read FIRST, before
  anything is resolved or driven, so a declined night cannot have had a side
  effect. A DECLINE IS A NORMAL RECORDED OUTCOME (200, not 4xx): "did last
  night run?" must be a read, never a silence indistinguishable from the
  seam being broken.
- **THE HARD PLANNED END IS 05:30 HOUSE TIME** (`HOUSE_TZ`,
  America/New_York, via `zoneinfo` — never a fixed number of seconds added
  to a timestamp). His HA morning routine runs the flag then and THE BLINDS
  OPEN ~05:40: daylight in the frame is a capture CONTAMINANT, so this is a
  bound, not a preference. The declared queue is PRICED at start
  (`price_items`) and refused by name if it cannot fit; the bound is then
  re-checked BEFORE EVERY ITEM through `capture_queue.run_queue`'s new
  `guard` seam (default `None`, so every existing caller is unchanged) —
  a queue that fitted at 01:00 has not necessarily got room for item six at
  05:28. A commissioning item is priced at `commissioning.NOMINAL_PASS_S`,
  a NAMED nominal used for this bound ONLY and never for the hold ceiling.
- **`morning-routine` is an ORDINARY ENDING, not an abort.** All three stop
  events (`sleep-ended`, `light-touched`, `morning-routine`) arrive at the
  one `/abort` endpoint and do the same three things to the room; the
  morning one records `ended_by_morning`. Folding it into `aborted` would
  make every ordinary night read as an incident, which is how a record stops
  being read.
- **ABORT IS THREE PIECES OF EXISTING MACHINERY IN AN ORDER THAT IS THE
  SEMANTICS**: `session.run_abort` (the run stops at its next capture
  boundary WITH ITS PARTIALS KEPT), `capture_queue.stop()`, then
  `flare_preview_hold.close_hold()` after a short bounded grace —
  REGARDLESS, because his dark room back within seconds outranks a tidy run.
  Nothing new was invented for it.
- **LIGHTS ON IF NECESSARY** — `spectra/services/night_power.py`: power
  only (`{"on": …}` keeps the fixture's own brightness, which is Home
  Assistant's — a dim fixture is a RECORDED REQUEST in the night's
  `brightness` block, never a write). Read its docstring for WHAT WAS ESTABLISHED about a
  powered-off WLED under a realtime stream **and what was not**: the answer
  for his fixtures could not be settled from here, so the run is correct
  under either — it turns on only what reads off, CONFIRMS by reading back,
  restores in a `finally`, and reports per fixture. `fx/VENDOR.md` #30 fixes
  `WLED.get_power_state`/`set_power_state`, which were dead and broken in
  three ways until this became their first caller.
- **THE HONEST EXIT** (`spectra/services/night_exit.py`) — the new standard's
  first application: at every run end, normal or aborted, every fixture is
  read back AT THE EMITTED LIGHT (WLED `json/state`+`json/info`, Hue via
  `release_fade.read_hue_light_states`) and named DARK / EMITTING / UNKNOWN.
  **A mode or setting read is not verification, and neither is the house's
  own envelope.** An unreadable fixture is UNKNOWN, never dark. An emitting
  one is attributed: `by_design` (Dark-mode shielded — those were the lit
  sets he woke to on 2026-09-01), `run_fixture` (ours, did not let go — the
  only category this seam owes anybody an explanation for), or
  `outside_run`.
- **THE EXPORT IS TWO LISTS AND THE SECOND ONE IS THE LESSON.** `fixtures`
  is what the night took; `standing_lit_under_dark` is computed LIVE from
  `dark_light._shielded_set` at request time, never hardcoded, so his
  pending shield decision reaches River's morning backstop with nothing to
  remember. Turning off both lists is a complete morning scope; the first
  alone is the gap he already fell into.

- **A CALIBRATION CAN BE WHAT THE NIGHT RUNS** (2026-09-01, §104) —
  `spectra/services/night_calibration.py` is the binding statement.
  `PUT /api/night-run/queue` takes EITHER the plain item list OR a
  `calibration_id` (+ optional `amend`), never both, validated the whole way
  down AT DECLARATION through the same `amendment.resolve_subset` /
  `capture_queue.parse_items` the routes use. The night calls
  `calibration_runs.run_calibration`/`run_amendment` — which simply gained
  `run_queue`'s own `guard`/`save` seams (default None) so the 05:30 bound
  and the per-item record reach a calibration's queue with **no night-only
  copy of the walk**. What it measures lands in that calibration's own
  lineage; the night record carries a LINK AND A VERDICT, never a copy. A
  refusal (an amendment's mixing gate, a moved camera) is
  `night_run.STATE_REFUSED` — distinct from `declined` (never started) and
  `failed` (unexpected error).
- **THE MORNING READ** — `spectra/services/morning_read.py`,
  `GET /api/night-run/morning`, also folded into `/night-run/fixtures` so
  "what did last night do to my calibrations" and "what do I turn off" are
  ONE read. His bar: which calibration ran, what it measured (and whether
  ANY of it was applied), what changed via `calibration_diff` (never a
  second arithmetic), and what waits on him — his nouns, never a log. It
  computes and judges nothing of its own.

**Run state on `GET /api/engine/status` is a TRIGGER, not a dashboard
field** — the house restores its own "Dark Music" envelope off it, so
`status_brief()` reads the live in-memory record (stamped before the network
work) and exposes ONE `active` boolean derived from `ENDED_STATES`.

**The house lights are Home Assistant's.** The "Dark Music" envelope is
fired and restored by River's side; nothing here fires a house scene, and
this app originates exactly two HA requests, both GETs (below). Nothing on
this path assumes a host either — the capture client runs on a remote Pi
near the camera.

Spec: `tests/test_night_run.py` (the boundary, the planned end, the export
tracking a shield change, abort, the morning ending),
`tests/test_night_calibration.py` (the calibration path: the boundary
re-asserted, the lineage landing, the mixing gate at 2am, a morning-cut
amendment applying nothing, the morning read),
`tests/test_night_run_api.py` (auth, the payloads, both reads),
`tests/test_night_would_start.py` (the preflight: the one-predicate drift
proof both ways, every decline's sentence asserted against the START's own
record rather than a copy, the honest yes, and byte-identical stores across
ten calls),
`tests/test_night_exit.py` (RED-WHEN-LYING against the real headless
pipeline and real `fx.utils.WLED` transport), `tests/test_night_power.py`.

### THE SELF-TAKING NIGHT — armed, it takes a RELEASED room and comes up DARK

The Admiral overruled the never-takes-the-room boundary above (2026-09-04,
of having to leave his room in a special state before bed: "no!!! i dont
want to have to turn it on. why can't you"). **`spectra/services/
night_take.py`'s module docstring is the binding statement**; the design is
the seam's addenda 10-11 and nothing departs from it. Read it before
touching anything on this path. Eight things:

- **ONE ARMING LEVER, ABSENT BY DEFAULT.** `SPECTRA_NIGHT_SELF_TAKE=1`
  (`config.night_self_take()`, read at call time). Unarmed — the shipped
  state — a start on a released room declines with
  `mapping_refusals.night_not_owned`'s own sentence BYTE FOR BYTE, asserted
  against that function's output rather than a copy of its text. It is
  deliberately NOT `SPECTRA_HANDOVER_ARMED`: that latch guards the
  interactive route, and two levers for one act is how a night silently
  fails to run for a reason nobody looks at.
- **IT ONLY EVER TAKES A `released` ROOM.** Held by the older SpotFX
  process, or mid-handover, still declines: displacing a live writer while
  he sleeps is not what he asked for. Checked twice — in the gate chain and
  again inside `take_room`, which closes the window between the preflight
  and the start.
- **THE QUIET TAKE CLOSES BOTH SOURCES OF LIGHT, and there were two.** The
  stack comes up BLACK (`fx/VENDOR.md` deviation #32: a LOAD-TIME
  substitution — `virtual_cfg` untouched, so nothing persists and every
  ordinary take-back afterwards restores his show), and `engine.go_live` is
  NEVER called, so the conductor/response/trigger engines write to the
  RecordingExecutor. `fx_seam` routes on the OWNERSHIP RECORD plus
  `facade.set_host` and never on the engine's executor — which is exactly
  why the night's own capture writes land while the show does not. A third
  thing is a SKIP, not a mode: `run_handover(quiet=True)` does not run the
  post-commit ambient reconcile, because a hold is Hue bulbs lit.
  **Do not "fix" this with `pause_all`** — pausing suppresses the flush, so
  the fixture holds its last frame instead of being driven black AND the
  VIRTUAL_UPDATE freshness the activation gate verifies goes silent.
- **NO DARK MUSIC — his sleeping house IS the envelope** (settled with
  River 2026-09-03, his-routine-outranks-our-envelope). The self-taking
  flow fires NO house scene; the quiet take darkens only SPECTRA's own
  fixtures; a stray house light is the contamination witness's business,
  per capture. `tests/test_night_self_take.py` asserts the module body
  contains no house-scene call so nobody adds it back helpfully.
- **GIVE-BACK ON EVERY EXIT, AND THE ORDER IS THE SEMANTICS**: stop,
  RELEASE, terminal state, announce — River's re-dark rides the night's
  state, so the room is his again before he is told it is. Gated on
  `night_take`'s durable snapshot and NEVER on the armed flag or the
  current owner, so **a night that ran on a room SPECTRA already held
  releases nothing**. The honest exit still reads at the light: releasing
  tears the live stack down, so `night_run.Instruments` captures the driver
  handles BEFORE the release and the report then answers the better
  question — is it dark now that we have let go.
- **A STOP ARRIVING DURING THE TAKE IS HONOURED, and it is a window only
  this build created.** `capture_queue.stop()` is a no-op with nothing
  running, and the take now spends real seconds holding the room BEFORE
  there is any night for an abort to stop — so a `sleep-ended` landing
  mid-handover used to be swallowed while the room stayed held. `night_run.
  _stop_mark`/`_stop_source` (bumped by EVERY `abort()`, including the ones
  with nothing to stop) are read either side of the take; a stop that
  landed in between hands the room straight back and declines the night by
  name, naming WHICH stop it was (his morning routine is an ordinary
  ending; a touched light is not). A touched house is his house even when
  the house was touched between two of our own statements.
- **CRASH RECOVERY RUNS BEFORE `resume_own_room()`, and that ordering is
  the whole point.** `night_run.recover_orphaned_night()` is called from
  `spectra/app.py`'s lifespan first: without it the resume would
  re-activate the stack and resume his SHOW at 2am, through a door the
  quiet take never opens. The orphan is stamped `failed` with
  `refusal="crashed"` — an ending River's `active` boolean already covers;
  inventing a state word for a frozen contract is how a seam breaks
  quietly — the room goes back, the terminal state is re-posted and the
  give-back announced. A night already stamped by a proper ending is never
  restamped.
- **THE ANNOUNCEMENT IS BOTH ENDS, TIMESTAMPED AND SILENT** (Order 22 for
  a sleeping house): durable records plus `take`/`self_take` on
  `status_brief()` and `fixtures_export()`, never a sound and never a push.
  `night_take.merge_announcement` is the ONE merge — folding a give-back's
  `as_dict()` in naively REPLACES the take's own entry, which was got wrong
  twice before it was factored out.

**The instrument gate joins the preflight for EVERY night**, self-taking or
not (`night_run._can_measure` over `capture_runs.session_view()`, the one
thing asked about the camera): a room must never be TAKEN for — nor held
dark all night by — a night that cannot measure. It sits after the
declaration (the cheaper answer when both are true) and before pricing.
Any night spec that wants a night to RUN must now say a camera is there —
`conftest.measuring_session(monkeypatch)` is the one definition.

**NOT BUILT, and it is the named follow-up**: the durable per-declaration
`may_take_room: true` consent field (addendum 10, item 2). His spoken word
covered the first night; the second gate belongs on the declaration.

Specs: `tests/test_night_self_take.py` (the unarmed byte-identity, the
gates, the give-back ordering, idempotence, the silence),
`tests/test_quiet_take_dark.py` (the emitted-light proof through
`fx.headless`, with the ordinary path as its own red-first control),
`tests/test_night_take_crash_recovery.py` (the REAL lifespan, a control
proving the resume would have re-lit the room, and a fresh interpreter),
and — the COMPOSITION of all of them —
`tests/test_selftake_dark_e2e.py` + `tests/selftake_dark_e2e_driver.py`.

**THE COMPOSITION PROOF, and what its numbers are (2026-09-05, PR
fm/spectra-selftake-dark-e2e-proof).** The two halves above each prove
their own half with the other one faked; this one runs the WHOLE armed
flow — `night_run.start` → the real `take_room` → the real `run_handover`
→ a real `SpectraSide(quiet=True)` over a real `fx.headless` host — and
records every frame that reaches a device transport. MEASURED, quiet:
232 frames, 21 non-black, ALL of them the run's own capture lamp on the
one emitter it named; zero in the take, the dark step, the show being
driven, the give-back and after it; owner back to `released`, snapshot
dropped, zero frames once it let go. The ORDINARY path through the same
driver: 154 non-black, first lit in the TAKE. Three things it settles
that neither half did — the engine's executor is still the
RecordingExecutor DURING the queue (a write pushed through
`engine.conductor.executor` reaches nothing), the run's own hold reverts
to the snapshot it took and under a quiet take that snapshot is BLACK,
and a restart on a RELEASED room drives ZERO frames while the same
restart on an OWNED room drives 102. Read the test's own docstring for
the four named substitutions (no camera, so the queue item is
representative; `engine.start()`'s bridge WS is not opened; dummies, not
his fixtures; pricing).

**A PHASE LABEL IS NOT A CLOCK — bound a drain by measurement.** Building
it, one lamp frame landed on the far side of a phase label that was
flipped before the revert was awaited, and read as a stray light in his
room. A render pipeline has latency: a frame already assembled reaches a
transport after the write that supersedes it returns, so asserting the
room is black the instant a write is ISSUED asserts something physically
false. The fix is not a looser assertion — it is `REVERT_DRAIN_S` plus
`lit_after_revert_ms`/`lit_after_drain`, which say how far past the
revert the last lit frame actually landed. Any future instrument
labelling frames by phase around an in-flight write needs the same
treatment, or it will report a race as a defect.

### THE FOUR BOUNDARY PINGS — River is told at each edge of SPECTRA holding
the room, and at each edge of THE WINDOW it runs inside

`spectra/services/pretake_ping.py`'s module docstring is the binding
statement for ALL FOUR (the module is named for the first one that existed),
and their one correctness property is PLACEMENT: each announcement must sit
at the exact instant its own statement becomes true — the PRE-TAKE before
the first act that could change a fixture, or the snapshot it exists to
trigger is a snapshot of a room SPECTRA has already begun to move; the
RELEASE after the Hue fade, or it announces a release that has not
happened.
River's snapshot watch fired on "is ambient running" — the NIGHT, not the
TAKE — so an ATTENDED take moved his lights with nothing photographed behind
them. The owner's chosen fix (option b): announce, wait a settle, then take.
Six things:

- **THE WIRE IS HERS AND CONFIRMED LIVE (2026-09-06)**: `POST
  {SPECTRA_PRETAKE_URL}` (the FULL endpoint URL — this side never appends a
  path), bearer `SPECTRA_PRETAKE_TOKEN` read by `os.getenv` at CALL TIME
  exactly as `witness.witness_token()` is, body `{event: "pre_take" |
  "released" | "window_open" | "window_close", room_id, at_ms}` — ONE
  endpoint, ONE bearer, ONE wire shape, the `event` word the only field
  that differs, which is why this is one module and not four — and **SUCCESS IS HTTP 200, her word, never "any 2xx"** —
  answering `{captured, elapsed_s, result}`. **One exception (2026-10-04): a RELEASE answered
  202** — her async accept — is told too (`RELEASE_ACCEPTED_STATUS`); the
  pre-take stays 200-only, because there she must already have captured. Her `captured`/`elapsed_s` are
  SURFACED on the take's own record rather than reduced to a boolean: a 200
  saying `captured: false` is still `sent` (inventing a verdict she has not
  defined would be renegotiating her contract) and is still LOUD, in the
  detail sentence and at ERROR. `None` means SHE DID NOT SAY and is never
  rendered as "she said no" — `witness_unavailable`'s own discipline.
- **THE ADDRESS IS NEVER IN THE REPOSITORY.** `config.pretake_url()` has NO
  default (unlike `whisper_bridge_url()`); her endpoint sits at a
  DHCP-reachable house address and a baked-in default is the
  pinned-by-location defect `fx/device_identity.py` exists to end one layer
  down. The deploy address is recorded in that function's docstring as prose.
- **BOTH TAKE PATHS, ONCE EACH.** `handover.run_handover` fires it for
  `to_world == SPECTRA` only (a give-back is not a take — River's own
  restore owns that end), AFTER the refusal gates (a handover that refuses
  touches nothing, so there is nothing to announce and no settle to spend)
  and BEFORE `begin_handover`/quiesce — quiesce STOPS the current writer,
  which the room can already see. `night_take.take_room` fires it as its own
  first act, ahead of its snapshot file, and passes `pretake=False` down so
  a double ping is structurally impossible. That flag exists for that reason
  alone; nothing calls it to skip the announcement.
- **AND THE RELEASE PING, 2026-09-07, THE OTHER EDGE.** River's
  bridge-direct byte-exact restore of all 17 Hue bulbs needs to fire when
  SPECTRA has actually LET GO, and her only trigger for that was the same
  ambient-mode sensor — an inference about the NIGHT, not a statement about
  the RELEASE. `pretake_ping.after_release()` posts `{"event": "released",
  ...}` from `release.release_room()`, **immediately after the Hue fade**
  (the step that actually takes his bulbs down, so the first instant the
  statement is true) and **before the live stack tears down**, so her
  restore has an uncontested room while SPECTRA finishes letting go behind
  it. Four things not to undo: it fires whether the fade SUCCEEDED OR NOT
  (a failed fade is the case where his room needs her most); it does **NOT
  settle** (the pre-take waits because River must read a room about to
  change — here the change is done, so there is no race left to lose and
  `after_release` has no `sleep` seam at all); its outcome rides
  `ReleaseResult.release_ping` and the route's response BESIDE `verified`
  and NEVER inside `problems` (whether the room let go is a question about
  his fixtures, whether River heard is a question about her watch —
  collapsing them makes a genuinely dark room read as a failed release);
  and an already-released no-op press announces NOTHING, with an EMPTY
  `release_ping` rather than a fabricated status. It rides the same env,
  so a night give-back gets it for free (`night_take.give_back` releases
  through the same function). `last()` still means "the last TAKE" —
  releases land in their own `last_release()` slot, because one shared slot
  would put a release's words on the armed handover route's own response.
- **IT CAN DELAY A TAKE; IT CAN NEVER REFUSE ONE, AND IT CAN NEVER UNDO A
  RELEASE.** `before_take()`/`after_release()` never
  raise — unconfigured, unreachable, refused, timed out and malformed all
  come back as a `PingResult` the caller REPORTS (`TakeResult.pretake` on
  the night's record, `pretake_ping.last()` folded into the armed handover
  route's response, `release_ping` on the release route's) and the take (or
  the release) proceeds. A failed PRE-TAKE ping STILL SETTLES: a
  refused or timed-out POST may have arrived, and racing the one snapshot
  this protects to save 1.5 s is the wrong trade. Only `unconfigured` skips.
- **UNSET `SPECTRA_PRETAKE_URL` IS INERT AND IS THE SHIPPED STATE** — no
  request, no sleep, no httpx import, and a take (or a release) whose
  side-call sequence is proven byte-identical to the same one with the call
  absent. **There is ONE env pair for both pings** — do not add a second.
- **A FAILED STEP SAYS WHAT ITS OWN FAILURE COSTS.** `release._best_effort`
  took a fixed sentence ("this device may still be lit until its own
  timeout"), true of a fade or a device teardown and a LIE about a POST to
  River that would send whoever read it at 2am to look at a fixture that is
  fine. It now takes the consequence as an argument, defaulting to that same
  device sentence byte-for-byte; a new non-device step there needs its own.

**IT CROSSES NO NEW BOUNDARY.** This is a POST to a RIVER SERVICE, the
witness/Whisper-bridge posture with the direction reversed; SPECTRA still
has no Home Assistant write access, no second path into his house, and THE
SCONCE MAINS RULE below is untouchable from here (asserted against the
module's own source, both modules). Specs: `tests/test_pretake_ping.py` —
the take ordering proven on both take paths, with `_first_write`'s own
control and a recorded source-level RED run behind it — and
`tests/test_release_ping.py`, the same discipline for the release: the
fade→ping→teardown ordering with its own discriminating control, and TWO
recorded source-level RED runs (the announcement removed entirely: 15 red;
the announcement moved ahead of the fade: 5 red).

**A `.pyc` CAN OUTLIVE A SOURCE EDIT THAT ONLY MOVES A BLOCK.** Running
those RED controls, restoring the file left the OLD bytecode live and the
restored code kept failing: CPython validates a cache on source mtime AND
SIZE, and moving a block changes neither. Any hand-run RED control that
edits by relocation — not just here — must clear `__pycache__` (or `touch`
the file) on the way back, or the restore silently does not happen.

### THE WINDOW — River powers the mains, SPECTRA waits for the fixtures

2026-09-08, after a night stalled because the mains-on step depended on a
human relaying the request. River added two events to the SAME endpoint,
bearer and body shape above; **`spectra/services/night_window.py` is the
binding statement** for when a night sends them and
**`spectra/services/sconce_wait.py`** for what "the fixtures came up" means.
Six things:

- **THE GATE IS THE MEASUREMENT, NEVER HER 200.** `window_open` asks her to
  power the sconce mains and hold his away automations; her answering 200
  says SHE ACTED and nothing about whether a sconce is powered. So the open
  is two acts and the night is gated on the SECOND — `sconce_wait` reads the
  run's own WLED fixtures back until they answer. `docs/SPECTRA_SPEC.md`
  §64's rule one service further out. A failed POST over sconces that are
  already lit is a night that RUNS (the wait happens on a failed POST too,
  `before_take`'s own "it may still have arrived"); a cheerful 200 over a
  sconce that never comes up is a night that REFUSES, because a room taken
  with a dark sconce measures the dark for four hours and calls it a map.
- **A FIXTURE IS FOUND BY IDENTITY, NEVER BY ITS OLD ADDRESS. A MAINS CYCLE
  IS EXACTLY WHEN A WLED TAKES A NEW DHCP LEASE**, so `sconce_wait` locates
  every fixture through `fx/device_identity.locate()` (pin → mDNS → peers →
  a bounded sweep, every rung confirmed by reading the MAC back) — polling
  the stored `ip_address` alone would abort a night whose sconces are lit
  and fine, which is that module's own founding defect arriving through this
  door. THE SWEEP RUNS ON THE LAST ROUND ONLY (254 probes), so the stated
  ceiling is the budget plus one sweep —
  every bounded retry loop's own shape. A fixture with no
  stored identity is asked at its pin and its MAC is LEARNED there; a
  relocation is written back to the fx-live config **only while the live
  stack is down**, because `fx.facade`'s own writes own that file whenever a
  host is up.
- **THREE ANSWERS AND ONLY ONE STOPS A NIGHT**: `True` (all answered, or
  there were none to watch — a run with no WLED has no mains dependency),
  `False` (the only refusal), `None` (NOTHING WAS WAITED FOR).
  `SPECTRA_WINDOW_WAIT_MS` (`config.window_wait_ms()`, default 45 s,
  clamped) **set to 0 is the documented OFF SWITCH**: the window still opens
  and closes, nothing is measured and nothing is gated, and a night behaves
  exactly as it did before this existed.
- **UNCONFIGURED IS INERT AND THAT IS CORRECTNESS, not tidiness.** With
  `SPECTRA_PRETAKE_URL` unset there is no POST, no probe, no marker and no
  gate: nobody asked for the mains to be powered on such a host, so the
  fixtures may legitimately be dark and refusing the night would turn "no
  River configured" into "your sconces are broken".
- **THE UNATTENDED NIGHT ONLY.** `night_run.start` opens it and every exit
  path closes it — which covers a COMMISSIONING pass, because a
  commissioning item runs unattended inside a night's own declared queue and
  inherits this the way it inherits the take and the 05:30 bound. NOT the
  daytime buttons (`/rooms/{id}/commission`, `/map`, `/exposure-test`) and
  NOT the armed take-back: both are acts a PERSON is present for, and a
  window HOLDS HIS AWAY AUTOMATIONS, which is the wrong thing to do to a
  house he is standing in. The human relay this removes was only ever in
  the way of the unattended path.
- **WHOEVER OPENED IT CLOSES IT, and the close comes AFTER the release** —
  she restores his bedtime baseline into a room SPECTRA has already let go
  of. `night_run._finish` (every ordinary exit, after `give_room_back`),
  `abort` (straight after the room, on the same within-seconds promise),
  the two decline paths that had already opened one, and
  `recover_orphaned_window()` at the cold start. That last one needs the
  DURABLE MARKER (`config.NIGHT_WINDOW_FILE`, `night_take.py`'s own
  restart-survival shape): a crash otherwise leaves River holding his away
  automations with nothing visibly wrong for anyone to notice. It is written
  ONLY when a `window_open` was actually SENT. A close that does not land
  still drops the marker and says so loudly — `give_back`'s own rule.
- **THE SCONCE MAINS RULE IS UNTOUCHED.** Neither module names or drives a
  Home Assistant entity; `sconce_wait` makes only `GET /json/info` and
  `GET /json/nodes`. Asserted against both modules' own code (comments and
  docstrings stripped, since their prose necessarily discusses what they do
  not do). The refusal sentence
  (`mapping_refusals.night_sconces_did_not_come_up`) leads with
  `witness.SCONCE_MAINS_FIRST_CHECK` when a sconce is among the missing, and
  deliberately does not when it is only the TV backlight.

Spec: `tests/test_window_ping.py` — the wire, the wait (incl. the relocated
case and a STRANGER answering at the old pin, which must not read as ours),
the run-flow order proven at the wire (`window_open → pre_take → released →
window_close`), the abort-on-dark-sconces path, and the inertness proof
comparing a whole unconfigured night's step sequence against a configured
one. Three source-level RED controls were run by hand: the gate removed (the
night takes the room and runs with a dark sconce), the close moved ahead of
the release, and the identity lookup replaced with a pinned-address poll (a
relocated sconce reads as dead AND a stranger reads as ours).

### The contamination witness, and THE SCONCE MAINS RULE

`spectra/services/witness.py` is a READ-ONLY client for River's deployed
house-state witness — `GET {SPECTRA_WITNESS_URL}/witness/{changes,scope}`,
bearer from `SPECTRA_WITNESS_TOKEN`, both read at call time, the
deploy-time secret living outside this repository and never entering code,
a log or a record. SPECTRA CONFORMS to her contract, it does not
renegotiate it (`transcription.py`'s own posture with the Whisper bridge).
Its docstring is the binding statement; the short list:

- **A house light coming on mid-capture is measured as the fixture's own
  light** — the same class of failure the exposure lock and the
  firmware-brightness guard each refuse, arriving by a door this instrument
  could not see through before. Every capture window is asked about
  IMMEDIATELY as it closes (`RunDeps.witness`, **no added settle — the dark
  time stays flat**), plus ONE settled whole-run sweep at the end
  (`RunDeps.witness_sweep`) so a late row still indicts the capture it
  overlaps. Both feed ONE contamination re-take pass
  (`room_mapping._retake_contaminated`), which reuses the unseen-retry
  machinery and its ONE-retry-never-a-loop rule.
- **THREE verdicts, and the third is the point.** `witness_unavailable`
  MARKS, never discards and never kills a run: the capture is KEPT, stamped,
  NO CLEAN CLAIM is made, and it is named in the exit report
  (`night_run.witness_summary`). "We could not check" and "we checked and it
  was fine" are different facts — the same distinction `night_exit` draws
  between DARK and UNKNOWN. With no witness configured every capture is
  `unclaimed`, never `clean`.
- **A COMMISSIONING PASS IS ONE MEASUREMENT, so it gets ONE question over
  its whole span and NO re-take** (`commissioning._judge_contamination`): a
  gray-code stack is read against one dark and one full reference, so a
  house light landing anywhere in it corrupts the decode rather than one row
  of it, and re-taking one IS a whole new pass — which is what `repeat`
  already is. It RECORDS and NAMES, and never touches `ok` or the five
  pre-registered tolerances: contamination is a fact about the instrument's
  conditions, like the exposure lock, not a table row.
- **Our own fixtures are subtracted** from the rows, by slugified id/name
  against the entity's object id (`own_entities`/`is_ours`) — exact, never a
  substring. The match is BIASED TO OVER-INDICT on purpose: a fixture of
  ours we fail to recognise costs a re-take; a house light we mistake for
  ours silently corrupts a footprint.
- **THE SCONCE MAINS RULE (Admiral-binding, both fleets):**
  `light.dimmer_kitchen_sconce` is the kitchen sconces' MAINS SUPPLY. **No
  run path may ever turn it off or lower it** — this side does not drive HA
  entities at all, and `tests/test_witness.py` asserts the module body
  contains no write verb. It is **BINARY, 0% or 100%, a switch with no scale
  factor**: nothing records its level per measurement and nothing is
  designed against it scaling (the Admiral's own correction, superseding an
  earlier level-recording idea); the witness treats it as an ordinary scope
  entity, so an accidental write to it indicts overlapped captures like any
  other row. At 0% BOTH sconces are dead and it looks exactly like a dead
  controller or a lost network, so `SCONCE_MAINS_FIRST_CHECK` is the NAMED
  FIRST LINE of any sconce diagnostic (`capture_refusal`,
  `activate_for_capture`'s failures, the not-rendering case) — FIRST is the
  whole point; buried three paragraphs down it is the hour this exists to
  save.

Spec: `tests/test_witness.py` (wire shape, the window cap, the three
verdicts, the mains rule), `tests/test_witness_retake.py` (the re-take on
the REAL `run_mapping`, including the no-added-settle proof and the
byte-identical unconfigured path).

## UNATTENDED CAPTURE — the client, the queue, and ONE seam for a run

His bottleneck, not a feature request: a mapping or commissioning run
needed a person at every step (open the page on a device with a camera,
grant it, wait for the lock, aim, keep the tab alive, press Start, press
the next one), so every capture experiment queued behind his availability.
**`docs/UNATTENDED_CAPTURE.md` carries the LEDGER** — what now runs with
zero human involvement, what needs a human once (aiming and choosing the
pose, camera permission, `ffmpeg`/`v4l2-ctl`, confirming that camera can
lock at all, declaring the queue), and what still needs his hands per run
(SPECTRA owning the lights, a second pose for unseen emitters, judging a
`findings` verdict, deciding what to do with a `marginal` refusal). Keep
those three categories separate whenever this area changes; blurring them
is the one way this build can become a lie.

- **`spectra/capture_client/camera.py` is the binding statement for the
  lock's honesty, and the rule is one sentence: automating the lock
  REQUEST is the point, automating the lock CONFIRMATION is forgery.**
  `apply_lock()` asks the V4L2 control and then READS IT BACK;
  `read_lock()` only ever returns what `v4l2-ctl --get-ctrl` printed; a
  driver that accepts the write and keeps its old value reports auto, and
  the run refuses by name. The `SyntheticCamera` every proof uses has NO
  locked default, so a proof cannot pass without exercising the gate.
  Nothing here may grow a flag that proceeds anyway.
- **The POSE TOKEN is minted inside `camera.open()`, and that placement is
  the whole design.** A footprint is `lit - dark` in one camera's byte
  scale, so footprints are comparable within a pose and not across two. A
  dropped WebSocket moves nothing and re-locks nothing, so the client
  re-asserts its pose on reconnect (`hello`'s `pose_hint` →
  `mapping_session._adopt_pose`) — labelling one measurement as two is the
  dangerous direction. A camera REOPEN mints a new token, and
  `capture_queue` names the change (`mapping_refusals.pose_changed_note`).
  Don't move the token's creation, and don't let the client decide a pose
  survived.
- **`spectra/services/capture_runs.py` is now the ONE seam that executes a
  capture run** — the run lock, the no-session gate and the two runs moved
  out of `spectra/api/rooms.py`, which is now the human-pressed caller of
  the same function `capture_queue` drives. A new gate goes there once.
  `RunOutcome.escaped` distinguishes a refusal the run STATED (200 with
  its record, which may hold kept footprints) from one that RAISED (409
  with the sentence) — conflating them either loses a partial map or
  claims a result that does not exist.
- **`spectra/services/capture_queue.py`**: waits for a session that is
  present AND LOCKED, walks the declared list, KEEPS partials, carries on
  past a refusal, retries ONLY a `partial` and only when the item declared
  it, and rewrites `storage/spectra/capture_queue.json` after EVERY item
  (nobody is watching; a queue killed by a reboot has still explained
  itself). It stores a SUMMARY per run — the full map is in
  `room_maps.json`, the full judged table in `commissioning.json`; copying
  either in would make the one file nobody watches the unbounded one.
  A queue is validated AT DECLARATION, so a typo is refused before the
  room goes dark.
- Three new sentences in `mapping_refusals` (no camera / session lost /
  queue stopped) plus one FACT (`pose_changed_note`), and `lock_refusal`
  reworded ONCE to speak to both client kinds rather than growing a second
  wording for the native one.
- Proofs: `scripts/check_capture_queue_e2e.py` (real server, real
  WebSocket, the REAL client, a synthetic camera — a five-item queue with
  no human action after start, a mid-queue refusal it carries on past, a
  dropped socket whose partial is kept and whose retry completes, the pose
  held across the drop and named across a reopen, the gate refusing an
  automated client, and a blind machine saying so), run from
  `tests/test_light_field_checks.py`; `tests/test_capture_queue.py`;
  `tests/test_capture_client.py`. **No live-room proof exists, and the
  V4L2 backend has never met real hardware** (the build machine has no
  `/dev/video*` and no `v4l2-ctl`) — both stated in the doc's own "What is
  proven, and what is not". Every way that backend can be wrong fails
  SAFE by the read-back rule: a missing tool, a missing control or an
  ignored write all report NOT LOCKED and refuse the run by name, so a
  wrong V4L2 detail costs a refused run, never a map that looks fine and
  is not.

### THE CAMERA HOST AS A BOOT SERVICE — and the Pi that does not exist

**`docs/CAPTURE_CLIENT_HOST.md` is the binding statement, and its LEDGER is
the deliverable**: what is proven on a dev host, what only real hardware can
settle, and what buying the board unlocks. **No Raspberry Pi exists.**
Nothing here may be reported as a working Pi deployment, and when hardware
arrives the correction is a DATED AMENDMENT, never a quiet rewrite of a
sentence that was true when written. Eight things:

- **THE UNIT SHIPS VERBATIM** (`deploy/spectra-capture-client.service`) and
  is checked by `systemd-analyze verify` — systemd's own parser, which
  rejected two real mistakes here (`StartLimitIntervalSec` belongs in
  `[Unit]`, not `[Service]`; a `Documentation=file:` relative path is
  invalid). It carries NO host path: `%h` only, `ExecStart` takes NO
  arguments, and everything that differs per machine lives in a launcher
  `scripts/install_capture_client.sh` writes. Verifying the shipped bytes
  is only meaningful because they ARE the installed bytes.
- **`systemd-analyze verify` RESOLVES A UNIT'S TYPE FROM ITS BASENAME, so
  never hand it an unsuffixed `mktemp` name.** It refuses one outright —
  "Failed to prepare filename /tmp/tmp.XXXXXXXXXX: Invalid argument" —
  BEFORE reading a byte of the contents, and at the exit status that is
  indistinguishable from a genuinely bad unit. The installer's `--system`
  path generated its unit into a bare `mktemp` file and verified THAT, so a
  perfectly valid unit refused every kiosk install (River, kiosk-0, systemd
  257, 2026-09-07; reproduced on 255 — the name never worked). A temp unit
  gets `mktemp -d` plus its own real name
  (`<tmpdir>/spectra-capture-client.service`), which is also the basename it
  lands under in /etc. The USER path never had this: it verifies
  `$UNIT_DST`, already a `.service`.
- **AND THE REASON NO PROOF SAW IT: §1b GENERATED THE BYTES ITSELF.** It
  verified a unit built the way the installer builds one, at a path IT
  chose — the same "a gate you MODEL is a gate no proof exercises" shape
  this file states about `SessionCameraDouble`. `check_capture_client_
  service.py` §3b now DRIVES the installer's own `--system` run (throwaway
  `HOME`, `sudo` shimmed to a recorder so nothing reaches `/etc`, and the
  recorded `install` line carries the exact path the installer verified).
  When a proof models a step the shipped code owns, the step it models is
  the one that will be wrong.
- **`systemd` HAS NEVER STARTED IT.** This build machine has no D-Bus
  session bus and a private `systemd --user` refuses without cgroup
  delegation, so `systemctl --user start` cannot run here at all. The unit's
  RESTART BEHAVIOUR is executed by a supervisor in
  `scripts/check_capture_client_service.py` that reads `Restart=`/
  `RestartSec=` out of the INSTALLED unit and obeys them. That proves what
  the unit tells systemd to do; it is not a proof that systemd did it, and
  it must never be reported as one. Do NOT install a probe unit into his
  live user manager to work around this.
- **ONE ENV FILE IS THE WHOLE CONFIGURATION**
  (`spectra/capture_client/config.py`, `SPECTRA_CAPTURE_*`): an explicit
  argument beats the environment beats the default, and a malformed number
  REFUSES BY NAME at startup rather than silently defaulting.
  `SPECTRA_CAPTURE_POSE` is a **LABEL** — his own words for where the camera
  stands, so a status surface can name WHICH camera is missing. It is never
  evidence of where the camera is; only `pose_fingerprint` measures that.
- **ABSENCE IS A READ — three states, not two**
  (`spectra/services/capture_health.py`, `storage/spectra/
  capture_health.json`, autouse-isolated in `tests/conftest.py`).
  `never` / `present` / `absent`, the last naming the machine, its build,
  its declared placement and how long it has been gone. It is folded into
  `capture_runs.session_view()` (so the queue and the calibration routes get
  it for free) and `mapping_session.status()`. **IT GATES NOTHING** — the
  run's refusal is still `lock_refusal`'s and `NO_SESSION`; a reporting
  surface that could refuse a run would be a second exposure gate. This
  makes `mapping_session` write ONE small row to disk (who is holding the
  camera), which is why its "persists nothing" docstring and test now say
  "no pixels" instead.
- **THE CLIENT'S DEPENDENCIES ARE TWO, AND `requirements.txt` IS THE
  SERVER'S.** `requirements-capture-client.txt` is httpx + websockets;
  installing the server's list on a camera host would drag compiled wheels
  (`aubio-ledfx`, `samplerate-ledfx`, `python-mbedtls`, `pyfastnoiselite`,
  scipy, librosa, pillow) with no guaranteed aarch64 build onto the board.
  `scripts/check_capture_client_deps.py` proves the closure by importing the
  client with 28 server-only packages BLOCKED at the meta path, asserts it
  never touches `fx/`, and audits for architecture literals
  (`platform.machine()` is REPORTED in `hello`, never branched on).
- **THE CLIENT ACQUIRES NO ROOM AUTHORITY, structurally.** Nothing under
  `spectra/capture_client/` may mention `fx_seam`, `light_ownership`,
  `handover`, a device driver or a compiler, and it imports nothing from
  `spectra.services.*` — asserted in `tests/test_capture_client_service.py`.
  Making it a boot service changed none of that.

Provisioning: `scripts/install_capture_client.sh`, idempotent, `--check`
writes nothing, every prerequisite refused BY NAME with its fix (ffmpeg,
`v4l2-ctl`, python3/venv, the video group, the configuration, linger). **It
is `pipefail`-strict** — a `grep` that legitimately finds nothing needs
`|| true` or the script dies silently mid-check (a real bug found here).

**ONE OWNER OF THE CAMERA PIPE, and the kiosk HOLDS its size** (2026-09-18,
PR fm/spotfx-capture-client-size-switch-race). A size switch reopened
ffmpeg while `newest_of`'s drain probe was still reading, and asyncio
refused the second `readexactly` mid-calibration. In `camera.V4L2Camera`
every `readexactly` now runs under `_pipe_lock` (`_require_owner` fails
loudly otherwise); `frame()` holds it per frame, and open/switch/close go
through `_exclusive()`, which CANCELS the in-flight read (the read re-queues
and returns a frame of the new pipe) — never add a pipe read outside that.
`--frame-size WxH` / `SPECTRA_CAPTURE_FRAME_SIZE` holds ffmpeg at that size
for the client's whole life and serves smaller asks by an exact stdlib area
average (`downscale_grey`), so `set_frame_size` never reopens; the kiosk's
env file sets 1920x1080 (`docs/CAPTURE_CLIENT_HOST.md`). The blocking read
bound is `frame_read_timeout_s` (device fps, pinned integration time,
capture size; 2 s floor), not a constant. Spec:
`tests/test_capture_client_size_switch.py`, whose control test proves the
race reproduces with ownership removed.

### A MACHINE MUST BE ABLE TO SAY WHAT IS WRONG WITH IT

2026-09-02, PR fm/instrument-visibility, after eight successive failures on
his laptop in one evening — every one ours, every one INVISIBLE here until
he pasted something. **The defect was not any of the eight; it was that we
had no way to know.** `spectra/capture_client/doctor.py`'s module docstring
is the binding statement. Five things, and the middle three generalize well
past this subsystem:

- **`spectra-capture-client --doctor` is the one command**, and it is
  **STDLIB-ONLY and runnable as a plain file**
  (`python3 spectra/capture_client/doctor.py`, no package import — the
  package `__init__` pulls in `websockets`). That is a requirement, not a
  preference: it is the tool you reach for when the VIRTUALENV is the broken
  thing, which two of the eight were. The installer runs it before it writes
  anything, which is how the address branch became a pre-install check.
- **ASK THE PREDICATE, NOT THE NEIGHBOURING QUESTION.** `[ -r /dev/video0 ]`
  is not `id -nG | grep -qx video`: a desktop seat's ACL grants read access
  with no group at all, so the old installer check passed on a machine whose
  service could never open the camera. This is the SAME shape as the
  `import venv` vs `ensurepip` bug (PR #241) one section over, and both cost
  an evening. When adding a precondition check, write down the thing that
  actually has to be true and check THAT.
- **A GROUP IS NOT APPLIED UNTIL THE USER MANAGER RESTARTS.** `usermod -aG`
  changes the database, not any running process; `systemd --user` takes its
  supplementary groups once at manager start and, being unprivileged, cannot
  gain one after. A user service INHERITS the manager's groups, so `id -nG`
  in a fresh shell can say `video` while the service holding the camera has
  none. The doctor reads the manager's own `/proc/<pid>/status` `Groups:`
  line — a pure read with the same answer as running a test unit, without
  writing a transient unit into his manager every time. **Say REBOOT, not
  "log out and back in"**, especially with linger enabled.
- **`SupplementaryGroups=` IN A USER UNIT CAN NEVER WORK, AND MEMBERSHIP IS
  IRRELEVANT TO THAT** (2026-09-03, PR fm/unit-group-directive-fix). An
  unprivileged manager is refused `setgroups(2)` outright — `216/GROUP`,
  "Changing group credentials failed: **Operation not permitted**" — so a
  user who IS in the group fails identically. The shipped user unit carried
  it; the owner was told to `usermod` and REBOOT, did both, twice, and it
  still died. **The boundary: the directive is legitimate ONLY under a ROOT
  manager that drops privileges — a SYSTEM unit may carry it, a USER unit
  must not.** They are two files (`deploy/spectra-capture-client.service`
  and `...-system.service.in`, the installer's `--system` mode) rather than
  one template with a conditional line, and the user unit's header NAMES the
  directive it excludes so nobody re-adds it beside `DeviceAllow=`.
- **`216/GROUP` HAS TWO CAUSES AND THE STATUS CODE CANNOT TELL THEM APART**
  — only the journal's own reason line can: "Operation not permitted" is the
  privilege cause above (fix: remove the directive, `daemon-reload`,
  restart, NO reboot); anything else is the membership-shaped one. The
  doctor's `read_216_cause()` reads it and gives them separate verdicts.
  **The general rule: an exit status is a CLASS, not a diagnosis.** Before
  translating one into advice, check whether the class has more than one
  cause — collapsing two into the more common one produces a confident wrong
  answer that sends someone to fix a thing that is not broken.
- **A CONTROL YOU DID NOT RUN IS A CONFOUND YOU DID NOT RULE OUT.** Rig A's
  original red case (`SupplementaryGroups=video` on a user NOT in the group)
  went red, proved 216, and PASSED FOR THE WRONG REASON: it never ran the
  IN-GROUP control, where the same 216 arrives for the same reason. When a
  proof attributes a failure to a variable, run the case where that variable
  has the OTHER value — `check_capture_client_fresh_host.py` rig A now runs
  A1 (in-group), A2 (out-of-group), A3 (no directive → STARTS) and A4 (the
  stale-ghost case) on real systemd, cross-checking the doctor's translation
  against each REAL journal line rather than a typed constant.
- **A LAST-ERROR VERDICT WITHOUT A CLOCK IS A GHOST** (same PR). After the
  owner's fix the doctor still headlined `last error` as a problem, quoting
  a failure from before it, while the service was up and connected. A
  journal read with no clock cannot tell a scar from a wound. It now
  compares against the unit's own `ActiveEnterTimestampMonotonic` and
  reports `IS FAILING` vs `FAILED EARLIER` as different verdicts — the
  second is UNKNOWN, visible and never counted. **Use the MONOTONIC clock,
  not `journalctl --since`**: `ActiveEnterTimestamp` is a wall-clock string
  with SECOND granularity and a `Restart=` loop fits inside a second, so the
  old failure lands in the window and reads as current;
  `ActiveEnterTimestampMonotonic` and `journalctl -b -o short-monotonic` are
  the same boot-relative clock at microsecond precision, with nothing to
  parse but a number systemd printed.
- **A MENU CONTROL HAS NO SINGLE OUTPUT FORMAT** (same PR).
  `v4l2-ctl --get-ctrl` prints `auto_exposure: 1` on some drivers and
  `auto_exposure: 1 (Manual Mode)` on others — including his. The read-back
  compared the whole string to `"1"`, so a camera GENUINELY AT MANUAL
  reported `exposure_locked=False` and every calibration-grade run refused
  by name while quoting a mode that said Manual. `camera._menu_value` parses
  the LEADING INTEGER and every menu comparison in that file goes through
  it (exposure, white balance, continuous autofocus); `_as_float` does the
  same for the four levers, which were silently reading None on the same
  drivers. Never compare a driver's printed value by string equality.
- **A REACHABLE-BUT-BROKEN CLIENT MUST NOT LOOK LIKE A HEALTHY ONE.**
  `capture_health` has a FOURTH state, `impaired` — connected and saying why
  it cannot work, in the client's own words. `present` stays a boolean about
  the socket so every earlier reader is unchanged, and NOT-YET is not
  CANNOT: only a lock that was REPORTED and did not lock counts, or every
  healthy startup would flap through it. It still gates nothing.
- **AN INSTALLER MAY NOT CLAIM WHAT IT DID NOT CHECK.** The old script ended
  by announcing "SPECTRA can now SEE this machine" — unconditionally, while
  installing a service that could not start. It now WAITS (bounded) for a
  real hello on `camera_host` and reports one of four outcomes, non-zero for
  three of them.

**`systemctl --user` DOES work from an agent shell here** — the memory that
it cannot is about the SHELL, not the machine. Export
`XDG_RUNTIME_DIR=/run/user/$(id -u)` and
`DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus` and his live user
manager answers. Without them it fails "Failed to connect to bus", which
reads exactly like "no such service" — so anything reporting on a unit must
fill those in and, when the bus is genuinely absent, say so as a property of
the shell. **This unlocks a real proof**: `systemd-run --user
--property=SupplementaryGroups=<any group> /bin/true` reproduces a genuine
`216/GROUP` in about two seconds — for ANY group, member or not — and the
same transient unit with no directive starts clean; `reset-failed` leaves
nothing behind. Do NOT install, enable or start the real unit in his manager
to test something.

**Proving a provisioner needs a host that never saw the repo.**
`scripts/check_capture_client_fresh_host.py` is the pattern: rig A drives
real systemd as above; rig B is `docker run --rm -v $REPO:/repo:ro
debian:stable-slim` with a user created seconds ago — not in `video` because
nobody put it there, and with no `ensurepip` because that is what a bare
Debian is. Shims in `check_capture_client_service.py` force both answers to
a question so a refusal is exercised deterministically; they cannot prove
the QUESTION is right, which is exactly what the fresh host is for. Either
rig SKIPS with its reason named when the facility is missing — a named hole
beats a false clean row.

**A check script that renders through `fx.headless` must `os._exit()`.**
`fx`'s `TemporalEffect` spawns non-daemon threads the frame-stepped harness
never joins, and `FxHost.stop()` refuses ("refusing to stop the SpotFX
process"), so a plain return leaves the interpreter alive forever — which
reads as a hang, not a failure, and cost a real debugging cycle here. Wrap
`asyncio.run(main())` in try/except and `os._exit(status)`.

## "TESTING IN PROGRESS" NAMES THE RUN — measured before claimed

The loud full-width top bar (`spectra/web/src/components/TestingBar.tsx`,
served by `spectra/services/test_session.py`) is what he reads to answer
"are my lights being tested on?". Its headline has THREE source tiers and
the order is the point — `test_session.py`'s own module docstring is the
binding statement:

1. **KIND_RUN** — the app executing a NAMED capture run right now. Stamped
   at the ONE seam, `capture_runs._begin`/`_clear`, in lockstep with the
   `_running` that already existed, and read through
   `capture_runs.current_run()`. It cannot go stale: it exists for exactly
   as long as the run holds the lock, on the success path and the raising
   one.
2. **KIND_DECLARED** — `POST /api/test-session/declare`, a human's claim
   with a ttl up to an hour. It is the one source that deliberately
   OUTLIVES the work it describes.
3. **KIND_AUTO** — `preview_pause`/`flare_preview_hold`/`room_preview`,
   which say only that SOMETHING holds the room.

**Why the order matters**: a declaration outlives the run it was made
for, and a mapping run holds the room through
`flare_preview_hold.open_program_hold`, so the auto tier can only say "a
flare preview is driving your lights" about it — without tier 1 a second
run inside an earlier declaration's ttl wears the EARLIER run's reason
(the 2026-09-05 report is recorded on `capture_runs.CurrentRun`'s
docstring). `since_ms` follows whatever the headline names, off the SAME
source dict, so this run's words can never sit beside an earlier
declaration's clock.

Three things to know before touching any of it:

- **A FIFTH RUN KIND NEEDS A `RUN_PURPOSES` ENTRY** (`capture_runs.py`,
  declared beside the `KIND_*` constants). Without one it falls back to
  naming itself ("a `<kind>` run on X") rather than borrowing another
  kind's phrase — honest, but not his words.
- **ASK `current_run()` ONCE PER ANSWER.** `_auto_sources()` snapshots it
  and derives the label, the probe and the start from that one
  observation; two reads can straddle a run ending, and a headline whose
  words and whose clock came from different observations is the same class
  of lie as the stale reason.
- **THE DECLARED ACTOR IS NOT BORROWED** for a run's headline. It names
  whoever declared last, which is not provably whoever started this run.
  The declaration is not discarded — it stays in `sources` and on the
  payload — it just stops speaking for a run it was not about.

The ROOM-OWNERSHIP bar (`RoomOwnershipBar.tsx`) is a different surface and
carries no reason at all: the release button, the released banner, and the
amber `ActivationStrip`. `light_ownership.commit(detail=)` writes the
record's HISTORY, which nothing renders as a live reason. Spec:
`tests/test_testing_bar_run_purpose.py` (both halves proven RED against
the unfixed code) + `node scripts/check_testing_bar_display.mjs` (the real
`whoLine` formula, DOM-free, with the pre-fix rule driven alongside it).
Help: `testing-bar`.

## A DEVICE IS FOUND BY WHAT IT IS, NOT BY WHERE IT WAS

**`fx/device_identity.py`'s module docstring is the binding statement** for
how a WLED is located, and `spectra/services/device_relocation.py`'s is for
what SPECTRA does with the answer. Read both before touching anything that
pins, probes or gives up on a networked device. Five things:

- **A RELOCATED DEVICE IS INDISTINGUISHABLE FROM A DEAD ONE WHEN IT IS
  PINNED BY LOCATION** — twice in one evening, 2026-09-04. His kitchen
  sconce took a new DHCP lease (`192.168.40.110` -> `.112`), the probe
  reported it dark, the take-back reported "Failed to connect", and both
  were true statements about an address that no longer meant anything.
  `fx/utils.py::resolve_destination` cannot catch this: handed a literal IP
  it returns that IP **verbatim, contacting nothing**, so a stale pin still
  "resolves" perfectly and fails one layer later. Do not read a successful
  `resolve_address()` as evidence a device is where the config says.
- **THE IDENTITY IS THE MAC, and the mDNS name is DERIVED from it.** WLED
  reports `mac` on every `json/info`; its own default mDNS name is
  `wled-<last six>.local`. Storing the MAC therefore gives the hostname for
  free rather than a second field that can disagree. The ladder is pinned
  -> mDNS -> a reachable sibling's `json/nodes` -> a bounded /24 sweep of
  the old pin (nearest-first), and **every rung is confirmed by reading the
  MAC back** — a name that resolves is a CANDIDATE, never an answer, because
  avahi caches and a stale cache pointing at a neighbour is precisely the
  confident-wrong-answer this exists to end. Measured on his host: nsswitch
  carries `mdns4_minimal`, avahi is active, and two of his own devices are
  ALREADY pinned by `.local` names and work — which is why mDNS is primary.
- **BACKWARD COMPATIBLE BY CONSTRUCTION, and that is load-bearing.** No
  `hardware_id` on a device means no lookup and the original error re-raised
  **verbatim** (a genuinely-off fixture must not start reporting something
  different); a device whose pin is still right is confirmed `via="pinned"`
  and changed in no way. His config was never mass-rewritten: the field is
  learned on first contact (`WLEDDevice.learn_identity`, the same lazy
  stamping `name`/`pixel_count` already get) and persisted only for a device
  that actually learned or actually moved.
- **PERSISTENCE IS THE HALF THAT MATTERS MOST, and it is not obvious.**
  Learning a MAC on the live object drives the fixture tonight and is
  useless after a restart — a process coming up against a stale pin has
  nothing to contact and therefore **nothing to learn an identity from**.
  `device_relocation.learn_from_live` (wired into `live_host.activate`) is
  what closes that, through the vendored `save_config` — one write path, not
  a second racing it. `scripts/seed_wled_hardware_ids.py` (dry-run default,
  `--apply`, `--mac id=MAC`) is the bootstrap for a device that has ALREADY
  moved and so can never learn on its own; its peer/name-match pass is a
  proposal for a human to confirm, which is why the dry run is the default.
- **THE RECOVERY PLACEMENT WAS THE OTHER HALF.** `activation_report.recheck`
  only re-inited a driver with NO destination — and a relocated device HAS
  one, so it was never re-inited and stayed dark forever. It now asks the
  identity FIRST and re-inits a device that moved (its sender was built
  against the old address). The /24 sweep is rate-limited per device
  (`SWEEP_COOLDOWN_S`) because that recheck runs every 30 s; the cheap rungs
  are not.

**Camera-by-`/dev/videoN` is the SAME SHAPE ONE LAYER DOWN and is NOT fixed
by this** — his camera also came back at a different node after a re-plug.
The principle transfers (a camera has a stable USB identity; Linux already
publishes it as `/dev/v4l/by-id/usb-<vendor>_<product>_<serial>-video-index0`)
but nothing here does: no HTTP, no MAC, no mDNS, a different process on a
different machine, a stdlib-only client that must be pulled separately, and
no way to prove it without hardware. Carded separately; do not report the
WLED fix as covering it.

Spec: `tests/test_device_identity.py`, `tests/test_device_relocation.py`,
`tests/test_seed_wled_hardware_ids.py`, `scripts/check_device_relocation.py`
(his own failure reproduced against real loopback HTTP, then fixed with one
field added). `fx/VENDOR.md` deviation #33.

