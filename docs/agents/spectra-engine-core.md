# The SPECTRA app and its S2 evolution engine

Moved from AGENTS.md during the 2026-11-09 trim (PR fm/spotfx-trim-agents-md).
Content below is verbatim from the prior AGENTS.md; see AGENTS.md's routing table
for when to read this file.

---

## SPECTRA app (her OWN process since the S3 split)

`spectra/` is the SPECTRA app (purple-on-black UI at `/spectra/`), running
as its OWN process: `python -m spectra` under `spectra.service`, port
`SPECTRA_PORT` (8010). The spot-effects app imports NOTHING under spectra/
(spec-enforced) and serves `/spectra/*` through a transparent reverse
proxy (`services/spectra_proxy.py`, target `settings.spectra_port`) so
every port-8000 address survives. Why: one shared interpreter let
spot-effects' 90 ms–5 s GIL bursts freeze the render threads (2026-08-13
frame-rate diagnosis); the standalone entry also applies
`sys.setswitchinterval(0.001)` (Stage-1 mitigation). Split spec:
`.venv/bin/python scripts/check_process_split.py` +
`tests/test_process_split.py` (frame-rate proof under a foreign GIL
burst). Deploy pair + one-pass apply: `docs/SPECTRA_PROCESS_SPLIT.md`.
Import discipline is load-bearing: nothing under
`spectra/` imports spot-effects runtime internals — only `fx/` (shared
library, incl. `fx/device_model.py`) and stdlib/third-party; music/state
inputs arrive via the S2 read-only bridge (below), which degrades to 0.5
neutral intensity when down (stated). Its scene model (`spectra/models/scene.py`) grows SceneV2
with value bindings (+`dice` correlation), intensity-stepped effect
selection (`effect_steps`: a device entry resolves to a DIFFERENT effect
at/above ⚡ thresholds, fire-time only, base = fallback — decision:
star-fold-entry-growth; deploy migration for STAR's strips was
`scripts/seed_star_strips.py --apply`, NEVER the v2 seeder — but that one is
SUPERSEDED as of 2026-08-25 and must not be re-run: his ruling "always do
melt" removed STAR's Strips power step via
`scripts/star_strips_always_melt.py`, and the seeder would silently put it
back. The mechanism itself is unchanged and still used elsewhere).
An effect's "accent" param (`sparks_color` on power — `"accent": true` in
`config/effect_params.json`, looked up via `fx/device_model.
accent_param_for`) is force-written black by `scene_compiler._entry_config`
on every compile unless the scene entry itself authored a value — ported
from spot-effects' `services/trigger_engine.py` accent-defaults-to-black
rule (`services/morph_aspects.accent_param_for`); the un-ported gap (fixed
2026-08-15, STAR/Singles/power showed white sparks) is that
`services/scene_v2_compiler.py`'s own docstring already flags accent as
NOT YET carried by the fixed colour vocabulary — SPECTRA's descendant
compiler silently inherited that same gap with nothing downstream to catch
it, since only `gradient`/`background_color`/`brightness`/
`background_brightness` were ever written. Any future accent-capable
effect just needs `"accent": true` on its param in the registry — no
compiler change required.
NAMED FLARE KINDS (`FlareKind`: drift-jump / momentary spike-and-return /
permanent re-baseline; bands select+scale them; ALL legacy response fields —
flare_bands, param_patch, gain, reroll/colour flags — load unchanged as
auto-named kinds, spec-asserted). A momentary/permanent kind's params are
`ParamTarget` expressions, not bare floats (a bare number still coerces to
`mode="absolute"` on load — every pre-existing kind is untouched): absolute
(declared value verbatim) / offset (signed delta from the CARRIED baseline
at fire time — a creep's live wander position, not its static start) /
random (uniform draw in `[lo, hi]`, rolled once per kind execution and
broadcast like an absolute value). Intensity-driven strength stays the
band's own `×scale`, orthogonal to the target mode — it steers whichever
mode resolves. A momentary kind also carries an optional `hold_ms` (the
CHOSEN HOLD before release; `None` = the fixed `PULSE_HOLD_S` default,
250 ms) — `ResponseEngine.pending_hold_groups()` lets kinds with different
holds in the same fire release on independent schedules
(`services/engine.py`'s `fire_response_event` spawns one release task per
group); every release still glides to `_carried_value` AS CARRIED AT
RELEASE TIME regardless of hold length, so a creep that kept wandering
during the hold is honoured, never a stale spike-time snapshot. Drift
declarations, and
the colour journey (room-level walk, per-scene OVERRIDE with custody
semantics — `spectra/services/color_journey.py` docstring is the binding
statement). Storage: `storage/spectra/` (own scenes/sequencer/drift/room
files; seeder `scripts/seed_spectra_from_v2.py --apply`, idempotent, reads
spot-effects storage READ-ONLY). **A worktree's own `storage/spectra/*.json`
is gitignored and untracked — it is whatever was copied in when the
worktree was created, not proof of current live scene/room state** (found
2026-08-17: a stale Aug-13 copy of `scenes.json` in a task worktree made an
already-shipped fix look regressed). The worktree isolates the filesystem,
not the network — read `GET /spectra/api/scenes`/`.../engine/status` on the
live `:8010` process for ground truth, or copy fresh read-only from the
live app dir's `storage/spectra/` (never `storage/scenes_v2.json` — that
one is the S1 seeder's own built-in-fixture offline path, not a live
snapshot to copy in) before trusting a local snapshot for anything dated.
Executable spec:
`.venv/bin/python scripts/check_spectra.py`. Frontend: `spectra/web/`
(own vite app — `cd spectra/web && npx vite build`), help content in
`spectra/web/src/help/helpContent.ts` (same keep-it-current rule as the
spot-effects help). The spot-effects Scenes page stays as-is until
superseded; never point `fx/` at live hardware before the S3 handover.

`TopBarStrip.tsx` (`spectra/web/src/components/`, mounted once in
`App.tsx` next to `RoomControlsBar`) is the shared always-visible strip
for widgets that belong on every SPECTRA route, not just one page —
first occupant is `LiveEnergyReadout.tsx`, showing `bridge.intensity()`
— at the time, raw librosa section energy at the live playback position,
no smoothing; since the 2026-10-28 Energy build (see "ENERGY" above)
`bridge.intensity()` delegates to `engine.current_energy()`, so this is
now Energy, the Mark math included — exactly as read from
`GET /api/engine/status`'s `bridge.intensity` field, already the
callable wired into the drift conductor, the sequencer's default scene
pick, and automatic transition fires — the one number this build found
feeding every automatic (non-authored) decision path. The planned
device-preview strip (`data/spectra-device-preview-plan/report.md`) is
designed to mount here too, as a sibling, when authorised — don't build
a second one-off top-of-app mount point for it.

## SPECTRA S2 evolution engine

The engine (`spectra/services/engine.py` wires it; start/stop is owned by
`spectra/app.py::_standalone_lifespan` — the SPECTRA process's own
lifespan, which also runs the frame watchdog and the startup resume):
drift conductor (`drift_conductor.py` — creep/follow legs +
the DESTINATION-DRIVEN room colour journey, ~20 s legs: the room always
heads for a destination set picked by the shipped selector, the
destination fixes its own pace from distance, arrival reselects — the
binding model is `spectra/services/color_journey.py`'s docstring; a room
is never set-less: bootstrap + `POST /spectra/api/room-color/apply`, and
fires with no explicit set wear the room's active set), response engine
(`scene_response.py` — the four classes execute each band's NAMED KINDS
at their scales: dice re-rolls, param moves, gain envelopes, flare colour
jump via the shipped selector with an intensity-scaled ramp-in (gentle
2500 ms → hard 150 ms, `color_jump_ramp_ms`); permanent kinds and drift
jumps CARRY — baselines move; momentary kinds return exactly to the
carried-now baseline; charge/lull/drop ALSO drive
the vendored phase machinery band-or-no-band — per-family grammar in
`docs/SPECTRA_RESPONSES.md`. A dice re-roll (`_reroll`, the "Dice
Re-roll" kind) lands via `executor.glide(..., DICE_REROLL_GLIDE_MS=220)`
when the re-rolled param is registry `"smooth": true` (a genuine
continuous numeric — STAR's `star`), else `executor.jump()` as before
(toggle/string/integer, e.g. STAR's `edges` — can't be meaningfully
interpolated); an explicit param-patch kind (a permanent/momentary
`FlareKind`'s own `params`, executed via `_move_params`/
`_compute_param_moves`) on the same event still wins over a same-event
dice re-roll, and — since a 2026-08-17 follow-up fix — glides too when
its target is registry-smooth, not an unconditional jump; the two paths
share one smooth-gate now, so precedence (patch wins) falls out of plain
dict-update ordering rather than an explicit jump/glide split. Fixed
2026-08-17: his STAR scene re-rolls `star` on every ordinary flare (its
flare bands carry Dice Re-roll end to end), measured live at ~0.6–1.2s
apart, each landing as an instant jump — read as a strobe, not a defect
in `star`'s own binding. `config/effect_params.json`'s per-param
`"smooth"` flag existed before this and was previously dead metadata
(grep-confirmed unread anywhere in `spectra/`/`fx/` Python) — it is now
load-bearing for BOTH gates (`_reroll`'s dice glide and `_move_params`'s
patch glide, added in the follow-up below); check it before assuming a
param's smoothness is unhandled elsewhere. **Follow-up, same STAR scene,
2026-08-17**: he reported it "still snaps" after the fix above — real,
because `_move_params` never checked `smooth` at all, so STAR's own
"Flare/Drop patch 0.7–1" kinds (permanent, pin `star` to `0.0` on every
high-intensity flare) kept jumping regardless of the tag; `check_spectra.py`'s
own prior assertion had documented this exact gap as "unchanged by the
smoothing fix" rather than missing it. Fixed by extending the same
smooth-gate into `_move_params`. Radial's `spin` (direction+speed,
signed, `[-1,1]` in the real vendored `CONFIG_SCHEMA` though the registry
still declares `[0,1]`) was separately retagged `smooth: true` in the
same pass — verified from source (`fx/utils.py::nonlinear_log` is
continuous through a sign change), not from his ask alone, and provably
inert against `_reroll` since no live scene binds `spin` via
`signal="random"`. **`spin_sign` ("Flip", `maps_to: spin`,
`sign_control: true`) — INERT under SPECTRA until 2026-08-20, PORTED
since**: originally that translation existed only in legacy
`services/morph_compiler.py::_sign_control_patch`, never ported to
`spectra/`/`fx/`, and `fx/effects/radial.py`'s real schema has no
`spin_sign` key at all — a raw write targeting it would land as an inert,
unread key (voluptuous `extra=ALLOW_EXTRA`). Two new named kinds on STAR
built that same pass, declared but not band-attached (matching Fireworks
V2's own "Reverse Direction" precedent — a human attaches via the Scenes
page's band-strip chip, not an agent): "Reverse Direction" (permanent)
and "Reverse Momentarily (500ms)" (momentary, `hold_ms: 500`) both then
targeted `spin` directly with a signed absolute value (`-0.55`, negating
his own already-authored spin-patch magnitude) — which worked, but
GLIDED (spin is registry smooth=true) from +0.55 to -0.55, visibly
crossing a real zero-speed moment: his report, precisely, "star is
freezing on every flare... but then it continues smoothly."

**PR fm/star-reverse-flare-use-flip (2026-08-20), his ask: "use the flip
control for star"** — told the trade and taking it knowingly (no pause,
but the turn is instant and more jarring) — is what actually ports
`spin_sign`, rather than routing around its inertness: both kinds now
target `spin_sign` (value 0/1), and `scene_response._compute_param_moves`
gained a `sign_control` branch that redirects the write onto the REAL
param (`meta["maps_to"]`, i.e. `spin`) with only its sign flipped,
MAGNITUDE PRESERVED from `spin`'s own current carried value (never a
fixed `-0.55` — proven against a 0.2 baseline too, not just this scene's
coincidental 0.55) — and, critically, forces that write through
`executor.jump()`, never `.glide()`, on BOTH the departure and the
momentary kind's release (`_pending_releases` grew a 4th `instant: bool`
field; `flush_releases` now splits jump/glide by it, same shape
`_move_params` already used for the departure split). A sign flip can
never be allowed to glide regardless of the real param's own `smooth`
tag — that's the whole point: no continuous crossing, either direction.
**The collision question this required answering before shipping**: a
sign-control write and a plain absolute `spin` write (e.g. STAR's own
untouched "Flare/Drop patch" kinds) land in the exact SAME `(vid,
"spin")` carry slot — there is no second, independently-tracked "flip
bit" anywhere that could disagree with `spin`'s own value and strand
STAR reversed; the two compose by ordinary last-write-wins carry
semantics, the same as any other two permanent kinds sharing a target
param (`scripts/check_spectra.py`'s own collision section proves this
directly). `config/effect_params.json`'s notes on both `spin`/`spin_sign`
are updated in the same PR — check those, not this paragraph, for the
current mechanism detail. Migration:
`scripts/switch_star_reverse_flares_to_flip.py` (raw-dict patch — NOT
`scene_console.apply_flare_kind`'s model round-trip, since this is a
single-field edit on two ALREADY-EXISTING kinds, and a round-trip write
of that shape silently added unwanted flare kinds to Squiggles the same
night this PR was built; dry-run default, `--apply`, `--revert` for the
exact one-field-back inverse). Original migration (creating the two
kinds in the first place, still accurate for that history):
`scripts/add_star_reverse_flares.py` (dry-run default, `--apply`,
idempotent, goes through `scene_console.apply_flare_kind` — Sonic's own
write path, backed up automatically — not a raw-JSON patch, since adding
a FlareKind is exactly what that function is for). Full writeup:
`docs/SPECTRA_SPEC.md` §78. **"The Scenes page's band-strip chip" above is
now the LANE RACK** (`spectra/web/src/components/FlareLaneRack.tsx`, §81,
PR fm/spectra-flare-lanes-and-edit): a band attaches kinds by drag, not a
click-toggle chip row. **Since 2026-08-21 (§88, PR fm/flare-lanes-pick-one
— his own reversal of the §81-addendum decision that declined this) a lane
is a stored PICK-ONE POOL, not just a position**: `FlareBand.kind_lanes`
(kind name → lane name; empty default) pools attached kinds, and
`scene_response.resolve_lane_picks` rolls ONE member per pool per fire
(even weights — curve weighting deliberately deferred, his words), every
lane's pick firing together, the legacy MorphLane shape. A kind with no
entry is its own one-member lane, so every pre-§88 band fires all of its
kinds unchanged — the empty default is the whole safety of that change;
zero scene files were rewritten. Execution order stays `FlareBand.kinds`'
own insertion order regardless of pooling — the engine reads it as a
tie-break when two same-type kinds (e.g. two permanent param moves) target
the same param: the later one in that order wins (`scene_response.py`'s
fixed dice→permanent→momentary→gain→colour execution order, generalized —
see that module's own docstring before assuming "combine" means additive;
dice re-rolls and colour jumps are each a SINGLETON pick per batch —
per fire unless PER-FLARE TRIGGER MOMENT below staggers it — regardless of
how many actually fire, only param moves/gains compose). The
lead/offset forward peeks (`band_trigger_offset_ms` etc.) aggregate over
ALL pool members — the possibility-set bound, documented in each
docstring, since the fire-time pick can't be known early. Rename/
delete/copy got a direct edit box (`FlareKindEditDialog.tsx`, tap or
double-click) — deliberately narrower than the no-settings-forms rule
above, since those three are identity ops on the kind's NAME, not its
type/params/gain/hold (still agent-only). A flare kind is scoped to ONE
scene's `flare_kinds` list — no cross-scene id — so paste
(`lib/flareClipboard.ts`) is a genuine PORT (a fresh, deduped-by-name
entry, never attached to a band), not a live link back to the original.
Full writeup, including the intensity-bucket-management proposal (options,
not built): `docs/SPECTRA_SPEC.md` §81, OQ-13.), read-only bridge
(`bridge.py` — WS client on spot-effects' /ws + `analysis_reader.py`;
classification: charge/lull/drop stay themselves, scene-family event
types are observations, everything else is a flare). Every glide/jump
goes through the ONE executor seam (`fx_executor.py`): production =
RecordingExecutor (DARK — records and models, never writes; the engine
must never call fx_seam), headless tests = FacadeExecutor driving the
fx/ tween engine. S3 goes live by swapping the executor — nothing else
changes. Specs: `scripts/check_drift.py` (conductor + journey),
check_spectra.py (responses/bridge/Mid Group),
`tests/test_spectra_engine.py` (frame-level proof on the dummy device).

**A momentary/permanent kind targeting a TOGGLE-type param (e.g. `reverse`
on blackhole/orbits/squiggles) needs a real Python `bool` to reach the
effect, not the float `ParamTarget.value` naturally produces — fixed
2026-08-20, PR fm/momentary-reverse-flare-on-black-hole-orbits-squiggles.**
`ParamTarget.value` is a plain float field (`spectra/models/scene.py`), so
an authored `true`/`false` silently coerces to `1.0`/`0.0`; the real
effect's `CONFIG_SCHEMA` validates a toggle param against bare `bool`
(voluptuous, no coercion — `fx/effects/__init__.py::_apply_config`,
`validate=True` LOGS a warning and drops the whole write on mismatch,
never raises), so before this fix a toggle-targeting kind looked declared
and attached but silently did nothing on fire. `scene_response.
_compute_param_moves` now coerces a `KIND_TOGGLE` param's resolved target
to a real bool (verbatim at scale 1, else a 0.5-threshold blend against
the bool baseline). The release side needed its own fix: `drift_conductor.
VirtualState.param_baseline` and `scene_response._carried_value` used to
explicitly EXCLUDE bool values ("NUMERIC baselines" by design) — a
toggle's pre-flare state was never tracked, so a momentary release could
never resolve where to return to and silently skipped. Both now carry a
toggle baseline as a real bool alongside the numeric ones. `reverse` means
something different per effect — chain retrace (squiggles), spin
direction (orbits), infall vs. outward (blackhole, the most dramatic, and
worth a beat's thought against the charge/lull/drop implosion choreography
already on that scene — flagged, not resolved, in the migration script's
own docstring) — see `scripts/add_momentary_reverse_flares.py` for the
full trace and for why a fixed absolute target (not a true invert) is the
only expressible form given ParamTarget's float-only `value`/`offset`
fields. Proof on the real vendored pipeline: `tests/test_spectra_engine.py::
test_momentary_toggle_param_flare_lands_a_real_bool_and_releases`.

**A fourth `FlareKind` type, `color_rotate` — the COLOUR ROTATE-AND-BACK
flare (owner ask, 2026-08-20, PR fm/rotate-and-back-colour-flare)**: rotates
a set-mode virtual's live foreground colour (`VirtualState.gradient`, via
the same `spectra/services/color_rotate.rotate_color_value` the room's own
colour-journey rotation already uses) by an intensity-scaled amount, ramps
in to land the full rotation ON the trigger mark, dwells, then fades back
to the exact original — his four numbers, exact:
`scene_response.color_rotate_{degrees,ramp_ms,dwell_ms,fade_ms}` (60°→180°,
1000ms→250ms ramp, 1000ms→400ms dwell, fade = 1.5× the ramp). Unlike every
other kind, it carries NO authored params/gain/hold_ms — all four
quantities are computed from the fire's own intensity, never a fifth knob
(`FlareKind._shape` rejects any). It's a genuinely new mechanism, not a
`_move_params` reuse: `gradient` is a scene colour assignment, never a
`device_model` registry param, so it can't flow through the param/gain
machinery every other momentary/permanent kind shares — this is *why* it
composes for free alongside a shape-targeting kind in the same band (his
"concur with some shape flares" requirement): it never touches the
`jumps`/`glides` dicts those kinds build. Its own release queue
(`ResponseEngine._pending_color_rotates` / `pending_color_rotate_holds` /
`flush_color_rotates`) is separate from `_pending_releases`/
`flush_releases` because its fade-back duration is itself intensity-scaled,
where every other momentary release shares one fixed `PULSE_RELEASE_S` —
wired into `engine.py`'s `fire_response_event` the same way, as a second,
parallel scheduling loop. ANCHORING (the flare rule — ramp ends on the
mark, not the drop rule): `trigger_engine._response_switch_lead_ms` now
takes `max()` of the existing dice-glide lead
(`momentary_switch_would_glide`, unchanged) and the new
`scene_response.color_rotate_lead_ms` — a separate function because this
kind's ramp has a real, intensity-scaled duration, so it can't share
`momentary_switch_would_glide`'s single fixed `DICE_REROLL_GLIDE_MS`
boolean-then-constant shape. `flare_preview.build_timeline` drains the new
release queue too, so the scrubbing preview shows a `color_rotate` kind's
full ramp/dwell/fade shape like any other. **A new ResponseEngine release
queue must be scheduled at every drain point, not just `engine.py`** —
there are four (`engine.fire_response_event`, `engine.
fire_scene_update_event`, `flare_preview.build_timeline`, and
`flare_preview_hold.open_hold`, the live preview's per-lap fire): this
queue was missed at `open_hold` when it shipped, so a live-previewed
rotation never faded back — the gradient sat parked rotated between laps
and every crossing after the first showed nothing (his 2026-08-21 report,
fixed PR fm/rotate-preview-stops-on-intensity-change; the intensity
slider was the moment he noticed, not the cause — the client's fire
schedule was proven sound, `scripts/check_flare_preview_frontend_loop.mjs`
§FIVE/SIX). Declared on every scene (not
effect-scoped like `reverse` — `gradient` exists on every set-mode virtual
regardless of effect type — `scripts/add_color_rotate_flares.py`, dry-run
default, never attaches to a band, his data is his to attach). Executable
spec + real-async-timing dwell measurement + the anchoring arithmetic
identity (`fire_at + ramp_ms == trigger mark`) + the colour/shape
concurrency proof: `scripts/check_color_rotate.py`. Fast deterministic
pytest coverage of the same mechanism (ramp/dwell/fade sequence on the
real vendored blackhole effect, the two release queues' independence, the
concurrency proof, the model's rejected-fifth-knob cases):
`tests/test_color_rotate.py`.

**A fifth `FlareKind` type, `firework_burst` (owner ask, 2026-08-21, PR
fm/fireworks-burst-flare)**: explodes an intensity-scaled count of payoff
rockets (3 at intensity 0 → 6 at 1, `scene_response.
firework_burst_rockets`) IMMEDIATELY on every live fireworks effect —
`docs/SPECTRA_SPEC.md` §89 has the full writeup. Two things worth knowing
before touching it: (1) it is deliberately NOT `beat_burst` — that param
only launches on the NEXT beat, so it can't line up with a trigger; the
engine instead jumps the effects' own `burst_rockets` key (edge-detected,
self-resetting, the phase-key pattern — `fx/VENDOR.md` deviation #15;
gated by `fx.device_model.FIREWORK_BURST_EFFECTS`, and like the phase
keys deliberately absent from the param registry). (2) unlike
`color_rotate` it has NO release queue — nothing to schedule at the four
drain points; the particles age out inside the effect. Migration
(declares AND band-attaches on Fireworks V2, his explicit placement,
run only AFTER the code deploys): `scripts/add_fireworks_burst_flare.py`.
Specs: `scripts/check_firework_burst.py`, `tests/test_firework_burst.py`.

**Fireworks "drop tail" (2026-08-21, PR fm/fireworks-drop-tail, `fx/VENDOR.md`
#17) — two facts worth knowing before touching fireworks spawn pacing:
(1) his real Fireworks V2 entries (both effects) run `spawn_rate: 0` —
beat bursts are their ONLY ordinary launch source, so any `_pspawn`-style
spawn_rate multiplier (incl. the charge's `CHARGE_SPAWN_X`) is inert on
his scene; anything that must visibly add launches there has to be a
launch RATE or touch beat bursts. (2) particles spawned past the density
cap (payoff, burst flare, tail, rockets) are flagged `p_nocap`/`f_nocap`
and don't occupy `max_blobs` — before that flag, a payoff held the cap
full for `PAYOFF_LIFE × burst_life` (~2.6 s on his crystal) and silenced
every beat burst, which was the "big burst then nothing" cliff. Measure
with `scripts/check_fireworks_drop_tail.py` (has a his-real-config
variant) before reasoning about post-drop density.

**The reverse flare's ~2x dwell overrun (967-1905ms measured live against
an authored 500ms, median 1160) — ROOT CAUSE FOUND AND FIXED 2026-08-21
(PR fm/reverse-flare-glide-and-stuck), after nine eliminations: the
release timer started at the END of the fire's own serial write burst,
not at the spike.** `engine.fire_response_event` used to create its
`asyncio.sleep(hold_s)` release tasks only AFTER `await
responses.on_event(...)` returned — and `on_event` lands every write of a
fire serially through the facade (~30ms each on his live room: seq
spacing in `executor.recent_writes`). A Black Hole V2 flare is 13 writes
(spike jumps ×5, gain jumps ×5, colour-jump glides ×5 — his live log,
seq 163-175, ~400ms), so "sleep 500ms" began ~0.4-0.5s late and the
reverse release landed 1.02s after its spike (seq 164 → seq 181, read
straight off `GET /spectra/api/engine/status`). The earlier offline
reproductions (509-638ms, one headless virtual, near-zero write cost)
were CORRECT measurements of a burst that barely existed there — the
overrun scales with the fire's write burst, which is why it only ever
showed on his live room. It was never the tween (both tween engines,
vendored `fx/` and the external fork, classify a bool target as instant —
a toggle never glided on the light), never `record_fire`, never the lead
system (toggle-only kinds compute lead=0 — still true). Fix:
`scene_response.PendingRelease` entries are ARMED (`armed_at`/`due_at`
stamped) right after each virtual's spike write lands, and
`engine._release_group` sleeps until that ABSOLUTE due time
(`responses.take_release_schedule()` / `seconds_until()`), so the hold is
measured from the spike regardless of how long the rest of the fire
takes. Measured on the real pipeline: `tests/test_reverse_flare_release.py`
(real effect: 536ms for a 500ms hold at 30ms/write; five virtuals, old
shape 806ms vs new 532-563ms; two flares 250ms apart: 773ms, i.e. the
LATER hold's full length). **Three more things that shipped with it, all
in `scene_response.py`'s "RELEASE OWNERSHIP" docstring — read that before
touching `_pending_releases`/`flush_releases`:** (1) every release is
OWNED by the fire that created it (`fire_seq`) — the old by-hold_s drain
let the FIRST of two 500ms flares release the SECOND one mid-hold — and a
later spike on the same (virtual, param) SUPERSEDES the earlier release
(holds extend, never cut short); (2) a TOGGLE param's release is forced
instant (`executor.jump`, never a PULSE_RELEASE_S glide), the rule
sign-control already had — the light never glided a bool anyway, but the
executor log and the scrubbing preview's ruler used to describe a 1.5s
glide-back that never happened (`scripts/check_flare_preview.py`'s
polygon case was updated from "no release" to "jump back at hold"); (3) a
momentary spike on a param the scene entry NEVER AUTHORED used to land and
never release — `flush_releases` skipped a `None` target — stranded until
an effect-TYPE switch rebuilt the instance: **his Orbits V2 and Squiggles
V2 both have this shape on their Strips (`orbits1d` registers `reverse`,
neither entry sets it), a genuine "stuck in Reverse" on the strips from
the FIRST flare, regardless of spacing.** Every entry now carries a
`return_to` resolved at spike time (`_resting_value`: the carried
baseline, else `fx.device_model.resting_default` — the effect's own schema
default, registry default as fallback — coerced to the registry kind),
used only when nothing carries a baseline at flush. PR #186's param
orphan watchdog (`release_target`/`pending_release_keys`, kept and adapted
to the new entry shape in the same commit) deliberately keeps no opinion
on never-authored params, so that fix is prevention-only; the two share
ONE definition of baseline (`_carried_value`). **And the "stuck in
Reverse" he most likely SEES is STAR's own data shape, reported, not
changed**: read live off `:8010`, STAR attaches the PERMANENT "Reverse
Direction" kind to its 0.35-0.7 and 0.7-1.0 flare bands and the momentary
one to 0-0.35 — a permanent kind's carry moves `param_baseline`
(`conductor.on_surge`), so after ONE mid/high flare reversed IS the
baseline and every later momentary reverse lands -|spin| and releases
back to -|spin|: stuck by construction, not by a race; the watchdog
rightly sees nothing to restore (`test_star_permanent_reverse_makes_every_
later_momentary_reverse_stick`, on the real radial effect). Fireworks V2's
"Reverse Direction" is, despite its name, MOMENTARY (hold 500) — fine.
Whether STAR's permanent attachment is intended is his call; the scene
backups (`/home/javi/SpotFX/storage/spectra/scene_backups.json`) show the
two kinds declared-but-unattached by script, so the band attachments were
a later UI save. **A ninth
elimination, 2026-08-21 (PR fm/engine-reads-flare-trigger-offset, checked
at firstmate's direction when that PR found a REAL double-fire in
`tick()`'s safety-net OR clause)**: that double-fire DOES hit
`fire_response` triggers in general (pre-fix, empirically: lead=220 → two
fires 200ms apart; lead=450 → 400ms apart — spacing = the lead, rounded
up to tick cadence), but it structurally requires lead > one 200ms tick,
and every one of the 9 real bands attaching "Reverse Momentarily (500ms)"
(Black Hole V2 / Orbits V2 / Squiggles V2 × 3 flare bands each, read from
the live process) computes lead = 0 — toggle-only, no registry-smooth
momentary param, no attached color_rotate — so `fire_at == target`, the
two OR clauses collapse to one predicate on one tick, and the pre-fix
engine fires exactly ONCE on that path (proven by running the pre-fix
module, not argued). UNRELATED to the overrun (now explained above).

Degeneracy floor/ceiling (owner defect fix, 2026-08-14): a drift declaration
is authored param-agnostic (a named profile is reused across effects), so
its lo/hi can be legal-looking but wrong for the param it lands on — e.g. a
[0,1]-ish default wandering Orbits' `blob_size` (legal [0.5, 6.0]), silently
rejected below 0.5 by the effect's own config schema while the conductor's
own position model kept wandering, stuck near the floor. `drift_conductor.
_registry_range()` intersects every creep's lo/hi (at Mechanism construction)
and every follow's resolved target (every leg) against the param's own
range in the shared `fx.device_model` registry (`config/effect_params.json`)
— a spec entirely outside that range falls back to the full registered
range rather than a zero-span window. `DriftSpec.motion` also carries
`"hold"` (parks at whichever bound it reaches and stops, no bounce-back)
alongside bounce/wrap. The Scenes → Drift tab's creep cards expose lo/hi/
motion directly (the one non-agent-edited piece of a drift card besides a
follow curve) — product judgement: limits/boundary are agent-tellable by
nature, but they're what the lights visibly do, so they get a compact
editable row instead. Spec: `scripts/check_drift.py`.

**The Timeline's follow window anchors on the DRAWN playhead, not the raw
Spotify clock (2026-10-07, his report on Pop Off: "the playhead appears to
be ahead of the scrolling view").** The playhead layer draws at the audible
clock + the song's stored `timestamp_offset_ms` (shape offset); follow mode
used to window on the raw clock, so on a song whose offset exceeds the
future buffer (Pop Off: 14,450 ms vs 10 s — 26 of his songs are over 10 s,
226 over 2 s) the line sat past the right edge all song. `spectra/web/src/
timeline/hooks/followWindow.ts` (byte-identical twin in `web/src/builder/
hooks/`) is the one definition both the hook and the layer call; the Now
Playing page always did this. Spec: `node scripts/
check_timeline_follow_playhead.mjs` (run by `tests/
test_timeline_follow_playhead.py`), red control included. A quick visual
repro needs no live app: mount the real `TimelineCanvas` + `BUILDER_LAYERS`
+ `useFollowWindow` in a throwaway vite dev harness with a frozen
`getNowMs` (the `preview-harness.html` recipe in memory) — `chrome-devtools-
axi`'s page commands fail here (pageId), raw CDP over `websockets` works.

SPECTRA frontend notes: `/spectra/timeline` is the SpotFX Profile
Builder ported whole (`spectra/web/src/timeline/`, reads/writes the
SpotFX `/api` + `/ws` same-origin via `api/spotfx.ts` + `api/ws.ts`);
phone portrait (≤720px, `lib/useIsPhone.ts`) is a first-class layout —
Scenes goes single-pane with a drawer picker. The Fire button asks no
confirm BY OWNER ORDER (deliberate asymmetry: the global colour-set
opt-out confirm stays) — don't "tidy" either side.

### SPECTRA-kept legacy equivalents (routed build, four items)

Owner decision `data/spectra-gap-inventory/decision-legacy-retirement-picks.md`
KEPT four legacy capabilities needing SPECTRA equivalents (six others RETIRED,
retire-not-delete). Built:

**`PUT /api/room-controls` IS A TRUE PARTIAL UPDATE — only the keys a
caller SENT are overlaid onto the current stored state; everything else is
byte-preserved (2026-08-30, PR fm/room-controls-partial-merge).** Before
that it bound the body to the full `RoomControlState`, so a partial body
silently reset every unnamed field to its model default and saved it — his
`av_sync_lead_ms` calibration and `force_scene_scene_id` pin were both
confirmed wiped in his real file that way. The merge, not a per-key patch,
is the fix: the reverse-proxy hop makes the caller list structurally
unknowable, so only a merge protects callers nobody has enumerated. The
contract and the retired-`ambient_mode` compatibility alias (PUT path only,
never stored; `"auto"` maps to `ambient_on_music_pause=True`, unlike the
one-time disk migration — and a body carrying both dialects lets the NEW key
win) live in `room_controls.merge_room_controls`/`AMBIENT_MODE_ALIAS`.
Reconcilers still receive `(previous, merged)`. Spec:
`tests/test_room_controls_partial_put.py`.

- **Override Blend** — `SceneV2.entry_ramp_ms` (a scene-fire blend-in ramp,
  threaded through `fx_seam.apply_writes(transition_ms=...)`, hue-arc, same
  tween shape as `fx_executor`'s glides) covers the thinner scene-entry
  facet. A read-only live-storage study found real legacy usage is 265/269
  triggers Charge/Lull phase builds, not scene selection — that dominant
  facet is `scene_response._phase_ramp_ms`'s dynamic gap-to-next-trigger
  stretch (below), not `entry_ramp_ms`.

  **The dominant Charge/Lull facet dynamically stretches to the real gap
  now (2026-08-20, `fm/spectra-lull-ramp-does-not-scale`, Admiral order
  "fix the lull ramp")** — a PORTING GAP fixed, not a design reversal:
  legacy's own dynamic ramp-to-next-trigger stretch had no analogue when
  this was first built (S2 had no forward trigger schedule to compute a
  gap against), so `models/scene.py` `PhaseBlend` shipped only the
  buildable static half — a per-scene `charge_ramp_ms`/`lull_ramp_ms`
  number, unset on every one of his real scenes. `trigger_store` now
  supplies exactly that schedule, so `PhaseBlend` is **retired** (removed
  from `SceneV2`, Sonic's `SCENE_SETTINGS_REGISTRY`, and the Scenes UI) and
  `scene_response._phase_ramp_ms` computes the real stretch instead — no
  per-scene knob was rebuilt alongside it: his own two real lull gaps on
  one song (Dopamine, `data/charge-lull-drop-timing-blends-and-a-sus-
  7fm2/report.md`: 6040ms and 900ms) prove a single constant can't fit
  both, so a hand-tuned number would just hand the problem back to him.
  His spec, verbatim: "the single blob waiting in lull should reach the
  center just and hang for just a moment, maybe 10% of the lull time,
  before the explosion" — charge/lull ramp to ~90% of the real gap
  (`TriggerEngine._phase_partner_gap_ms`, honoring the same
  `scene_change_mode` gate `tick()` itself applies), hanging the remaining
  ~10% at `phase_progress=1.0` for free (nothing writes it again before
  the next phase event); drop is never stretched. An UNKNOWABLE gap (no
  trigger-schedule context — a bridge-classified legacy flare, or a
  manual `/api/engine/event` test-fire) is a documented fallback to the
  flat tuned default, never a silent guess. Spec:
  `scripts/check_triggers.py` (gap computation, incl. a disabled/mode-
  gated trigger never counting as "next") + `scripts/check_spectra.py` +
  `tests/test_spectra_engine.py` (frame-level, his real Dopamine pair).

  **THE UI CAUGHT UP 2026-09-04 (PR fm/spectra-charge-lull-blend-graph, his
  ruling: "i want the tick box enabled, or i don't want it visible on them.
  but i do want to show the blend on the graph like other triggers with
  'override blend' enabled").** Because the stretch above is UNCONDITIONAL,
  the ported timeline's Override Blend checkbox was a control implying a
  choice that does not exist — and it was worse than cosmetic: 64 of his 338
  real charge/lull triggers carry `override_blend: false`, so the canvas drew
  19% of his charge/lull as blending nothing while the room blended them
  anyway. Both halves fixed, UI only — no engine change, no data migration,
  no trigger flag read or written on the charge/lull branch:
  - The checkbox is HIDDEN for a charge/lull event (a box he cannot untick
    still implies agency), replaced by a sentence pointing at the graph.
    `web/src/builder/`'s frozen spot-effects twin is deliberately UNTOUCHED —
    the retired legacy engine really is flag-gated there
    (`services/trigger_engine.py:1877`), so hiding it on that surface would
    remove real agency, unlike here. The `[`/`]` blend BRUSH is also
    untouched (a bulk tool over every event type).
  - `spectra/web/src/timeline/phaseBlend.ts` is the binding statement for the
    drawn span, and MIRRORS `scene_response`'s own constants (nothing serves
    them over the wire) — ramp to ~90% of the real gap to the next ENABLED
    trigger, then a lighter HANG band for the last ~10%; a charge/lull with
    NO next trigger draws its flat class default (4000/2500 ms) with no hang,
    never a span to the song's end (that is `override_blend`'s rule, not
    this one); a disabled one draws nothing; drop never draws a span.
    Rendered on BOTH surfaces: `SpectraTriggerBar.tsx` (his 338 native
    charge/lull live here) and the legacy canvas's `blendSpans` layer, which
    grew an `eventType` resolver — so `canvas/data.ts` no longer diffs
    byte-identical against `web/src/builder/canvas/data.ts`, deliberately.
  Spec: `node scripts/check_charge_lull_blend_spans.mjs` — transpiles the
  REAL frontend module with esbuild and asserts it against `_phase_ramp_ms`'s
  constants READ OUT OF the Python source, so a constant drifting on either
  side goes red. Help: `charge-lull-blend`.

  **A BUILD RUNS TO ITS OWN PARTNER (2026-10-06, drop-detection plan phase
  1, the Admiral: "a charge builds to its own lull or drop, and a lull to its
  own drop, whatever else sits between").** `spectra/services/
  phase_partner.py` is the binding statement and the ONE definition; the
  gap above is `TriggerEngine._phase_partner_gap_ms` (renamed from
  `_next_trigger_gap_ms`), mirrored by `phaseBlend.ts::phaseBuildTarget` on
  both Timeline surfaces. The next PHASE trigger is the build's end when it
  is a partner (later in charge → lull → drop) within `PARTNER_REACH_MS`
  (the effects' own 60 s cap); flares, scene changes, colour changes and
  updates in between are ignored. **A charge or lull with no partner ahead
  keeps the pre-rule gap (the next trigger of any kind), deliberately**:
  ~100 of his charges are lone or run into another charge (a RESTART, never
  a partner), and he uses them as builds into the next flare — sending them
  to the flat default would change far more than the sequences this fixes.
  `scripts/check_phase_partner_library.py` lists, per song, every build
  whose end moves (old vs new, the pre-rule engine loaded out of git at a
  pinned ref); spec `tests/test_phase_partner.py`.
- **Energy gates/tilt** — PROVEN EQUIVALENT, nothing built: sequencer
  likelihood curves already express floor/ceiling/scale gating exactly
  (`scripts/seed_sequencer_from_legacy.gate_points`, zero=veto in
  `selection_kernel.py`, spec-proven in `scripts/check_sequencer.py` against
  the legacy formula at `services/trigger_engine.py:2338`); live usage was 1
  authored option, 0 fires. See help topic `energy-gates-equivalence`.
- **Brightness multiplier** + **ambient/global-transition** — new room
  surface `spectra/services/room_controls.py` + `spectra/api/room_controls.py`
  (`GET`/`PUT /api/room-controls`), UI `RoomControlsBar.tsx` (mounted next to
  the ownership bar in `App.tsx`). `brightness_multiplier` scales
  brightness/background_brightness uniformly at the write seams
  (`fx_executor` for engine glides/jumps, `scene_compiler.fire_scene` for
  scene-fire bytes) — never the conductor's carried baseline or the
  returned/dry-run writes, so dry-run/live preview parity holds.
  `global_transition_ms` is the room default `entry_ramp_ms` falls back to.
  `ambient_enabled`/`ambient_color` drive a real live takeover
  (`spectra/services/ambient.py`, reconciled from the PUT handler whenever
  those fields change): every live Hue device in the room (Hue-only,
  matching the legacy scope — WLED keeps running its normal show) freezes
  its entertainment stream (`fx/devices/hue.py HueDevice.set_frozen`,
  in-process, no LedFX HTTP hop) and is held at `ambient_color` via direct
  bridge REST. No device-category setting (every live Hue device IS the
  target) and no legacy "wake scene" on disable — a SPECTRA-owned Hue
  virtual never goes inactive while frozen, so unfreezing alone lets the
  room's already-running scene pick the stream back up. Release is a
  TWO-PHASE bridge-side ramp, still frozen for both: a brief dim fade, then
  a second ramp toward whatever the live effect is ACTUALLY rendering right
  now — read from the literal live pixel buffer
  (`Device.assemble_frame()`, the frame `HueDevice.flush()` already
  receives and drops while frozen), not a captured scene config — before
  finally unfreezing. This is SPECTRA's analogue of legacy's own two-phase
  release (`services/ambient_mode.py`: REST fade toward a wake scene, then
  an LedFX-side effect-config tween back to a captured pre-ambient look);
  the two aren't reproducible 1:1 because legacy's driving virtual actually
  goes dark and needs a wake scene fired, while SPECTRA's never stops
  rendering, so there's no separate wake config to capture and tween away
  from — see `spectra/services/ambient.py`'s module docstring for the full
  reasoning (fixed post-#56, PR fm/spectra-ambient-release-fidelity, after
  the shipped single-fade version read as an abrupt cut against the legacy
  behaviour it was compared to). State-only (status "dark") when SPECTRA
  doesn't own the live stack. Ambient's ON path READS EVERY LIGHT BACK from
  the bridge before counting it held — a 2xx PUT only means the bridge
  accepted the write, not that the physical bulb (over zigbee, which can
  silently drop a command under a write burst) took it (live defect,
  2026-08-15, PR fm/spectra-ambient-verify-per-light: `lights_set` is now a
  CONFIRMED count, stragglers get bounded+spaced retries, and any light
  still not holding after that is named in `unconfirmed`/status "partial"
  rather than folded into the total — see the module docstring). This same
  attempted-vs-confirmed gap does NOT exist on the release path (already
  reads real state back) or the scene-fire path (writes virtual effect
  configs, fails loud on HTTP errors) — checked, not assumed. Ambient/
  Dinner-Party as a full room-MODES build is still separate. Spec: the
  room-control section of `scripts/check_spectra.py` +
  `tests/test_room_controls.py` + `tests/test_ambient.py`.

  **The bridge gives ZERO signal on a silent drop** — measured live
  2026-08-16 (`docs/SPECTRA_SPEC.md` §60): every PUT, dropped or not,
  returns a clean `HTTP 200`/`{"errors":[]}`, no `429`, no `Retry-After`,
  no rate-limit header. A retry has nothing to react to but a read-back —
  don't design one around the response. `AMBIENT_WRITE_STAGGER_MS=300`
  (raised from 50) is margin inside a confirmed-safe band, not a measured
  cliff edge — 48 controlled sustained-burst trials across both real
  bridges independently found no drops from 0.08s–0.60s; a claimed sharp
  0.12s-fails/0.45s-works cliff in an earlier report did not reproduce and
  was most likely itself a target-tracking bug in whatever script
  gathered it (the same mistake this investigation's own first attempt
  made — always self-check a burst-measurement script against an
  unambiguously-safe pace before trusting a faster result).
  `ambient.repair_stragglers()` is the fix for "detects but does not
  repair": `ambient_music_gate.py`'s periodic verifier now actually
  re-writes an ON-but-wrong-colour straggler it finds (still never a
  light that reads OFF right now — checked fresh, immediately before
  writing). `_color_matches` (on+hue only) vs `_state_matches` (on+hue+
  brightness) is a deliberate split: the former is what `verify_held()`'s
  reporting surface uses, so a bulb dimmed out of band no longer reads as
  a false "unlit" — brightness only gates confirming OUR OWN write.

**Force Scene** — the Admiral's day-one ask, separate from the four-item
gap-inventory decision above but built on the same room-control surface:
`RoomControlState.force_scene_enabled`/`force_scene_scene_id`
(`spectra/services/room_controls.py`), UI in `RoomControlsBar.tsx`. Ported
verbatim from legacy Now Playing's Force Scene (`settings.force_scene_enabled`/
`force_scene_event_id`, `services/trigger_engine.py::_forced_scene_event`):
while enabled, whatever scene id was about to fire automatically is
redirected to the pinned scene instead — an unconditional reassert, not a
pause; the caller's own resolved colour set/intensity still applies. Ported
at `scene_sequencer.fire_scene_by_id`, the single choke point every
automatic SPECTRA scene pick (sequencer rolls, `trigger_engine`'s
`fire_scene` action, its automatic transition fire) already funnels
through — one interception point covers all of them, unlike legacy's several
call sites. Manual editor test-fires (`POST /scenes/{id}/fire`) bypass that
choke point by design and are never redirected. SPECTRA has no Scene Group
concept, so legacy's group-member-rotation half has nothing to port to.
Spec: the Force Scene section of `scripts/check_spectra.py` +
`tests/test_room_controls.py::test_force_scene_redirects_every_automatic_pick`.

**The redirect above is passive — it only fires when something else was
already about to pick a scene, and enabling Force Scene also sets
`bridge.sequencer_deferral()` to defer the sequencer's own rolls; on a
song with no triggers/analysis, nothing was ever going to fire, so the
pin sat there doing nothing and looked broken (his live report,
2026-08-18).** `room_controls.reconcile_force_scene_if_changed`
(same one-choke-point PUT-triggered shape as `reconcile_ambient_if_changed`/
`reconcile_dark_light_if_changed`, called from `PUT /api/room-controls`)
fires the pin immediately on the edit that enables it or repins a
different scene while already enabled — never on an unrelated field
re-save with the pin unchanged. Always returns a stated
fired/skipped/error reason (`force_scene_result` in the PUT response,
`ForceSceneResult` in `types.ts`, surfaced as a badge in
`RoomControlsBar.tsx`) — never a silent no-op.

**Force Colour** — Force Scene's twin ONE AXIS OVER (2026-08-27, his ask:
"Add an ability to force a color set or color group, similar to force
scene, so the color does not change and stays on a specific set. Put the
tool in the top bar and focus on fucntion and we will work on UI later").
Force Scene pins WHICH SCENE plays; this pins WHICH COLOURS it wears.
`RoomControlState.force_color_enabled`/`force_color_target_id` (a colour
SET **or** GROUP card id), default off/None so its arrival changed
nothing. **`spectra/services/force_color.py`'s module docstring is the
binding statement** — every gate, both precedence rulings, and the
side-effect rule below live there; read it before touching any colour
selection path. The short list:

- **Gated at SEVEN choke points, each checked individually** (§86's
  lesson, again): `scene_sequencer.fire_scene_by_id` (replaces the
  caller's own colour set, result carries `forced_color`), its
  `_roll_color_set` (short-circuits with its own `FORCED_COLOR` rung so
  the roll never re-anchors the wheel for a pick that is about to be
  overridden), `scene_compiler.room_active_set` (the TERMINAL fallback —
  the path 100% of his real `fire_scene` triggers take), `drift_conductor.
  tick`'s journey hold + `_bootstrap_room_color` + `on_drop_event`,
  `scene_response._color_jump`, and `trigger_engine.
  _default_select_color_set` (names the redirect via
  `apply_set_directly(forced_from=...)`).
- **`active()`/`pinned_id()` are side-effect-free; `pinned_card()` is
  NOT.** Resolving a pinned GROUP advances that group's rotation cursor
  (`color_set_groups._pick_member`), so `pinned_card()` is called exactly
  ONCE per real fire, at the choke point about to use it — never from a
  per-leg hold check or a status poll, which would roll his colours on
  nothing but someone looking at the page. Proven directly in
  `tests/test_force_color.py`.
- **SET pin = static; GROUP pin = the POOL, rotation still live** (that is
  what a Group is). Stated as a reading, his to tune.
- **Precedence, named**: it WINS over an active 2D gradient (which also
  replaces the journey) — the gradient is untouched and resumes on
  release; it composes for free with Ambient (device-level, downstream —
  verified, not assumed, the same orthogonality Dark/Light already has).
  `preview_pause` still outranks everything, unchanged.
- His EXPLICIT actions still work and NAME the override
  (`overrode_force_color` on `POST /room-color/apply` and the editor
  Preview); a disabled pin APPLIES and is named (`overrode_disabled`),
  never silently refused. Sonic excluded from the registry on
  `force_scene_*`'s own opaque-id precedent.

Immediate apply on enable/repin: `room_controls.
reconcile_force_color_if_changed`, `force_color_result` in the PUT
response — the passive-redirect trap immediately above is documented, so
it is not repeated. Help topic `force-color`, linked from the top bar's
own "Colour" group button. Spec: `tests/test_force_color.py`.

**HOUSE MODES ARE AN EIGHTH CHOKE POINT AND THE ONE EXCEPTION (2026-10-05,
the Admiral's ruling: "house modes must ignore Force Colour and use their
own colour sets")** — Force Scene is UNCHANGED, he was not asked about it.
`house._apply_scene_and_colour` no longer waits for the pin to clear
before picking the mode's own card (the old `pinned_colour`/`card = None`
deferral is gone); that alone is not sufficient, because
`fire_scene_by_id` would otherwise still substitute the pin onto the
card house.py just resolved — so that function's own Force Colour
substitution is gated on `origin != "house"` (mirroring the Force
Scene/`house_mode` deferral check one function-section above it, which
already uses the same `origin` marker). Music/trigger-driven fires
(`origin="auto"`, the default) and an explicit human press are
unaffected — the pin keeps governing everything else, including a house
mode with NO colour sets of its own, which still falls through to
`scene_compiler.room_active_set()` (deliberately untouched) and so still
wears the pin.

**Two more choke points closed the same day, found by asking whether the
ask holds OUTSIDE scene-fire time too**: `room_controls.
reconcile_force_color_if_changed` (the PUT-triggered immediate apply on
enable/repin) now checks `house.journey_override() is not None` — BEFORE
`force_color.pinned_card()` is called, so a pinned GROUP's rotation
cursor never advances for an apply that is about to be skipped — and
returns `{"status": "skipped", "reason": "a house mode owns the room's
colour while it rests", ...}` rather than repainting the room out from
under a resting mode. `drift_conductor._colour_leg` now consults
`self._house_override()` BEFORE `force_color.active(controls)`: while a
house mode rests, the force_color-held branch is skipped entirely and the
leg falls through to `self._journey_leg(...)`, which already narrows the
pool/pace to the mode's own sets via that same `_house_override()` call.
The existing gradient precedence is untouched — this is only about Force
Colour. Spec: `tests/test_force_color.py`, `tests/test_house_lighting.py`.

**Force Scene/Force Colour's top-bar panels** (card
force-colour-and-forced-trigger-dialogs-p99a): each pin is a `PowerButton`
(with `ariaLabel`, since it toggles a room pin, not an item) with its result
badge directly under it; only while on, a `SearchSelect` plus
`RecentChoiceButtons.tsx` (the 6 most-recent picks, per-viewer localStorage
via `lib/useRecentChoices.ts`) — both write the same field, so they can
never disagree. **`SearchSelect`'s dropdown is `position: absolute`, NOT a
portal**: it adds no flow height and is clipped by any `overflow` ancestor.
It bounds itself only to the viewport and an enclosing `.top-bar-group-panel`
(its own measure effect), so inside any OTHER scrolling container it still
clips. In the top bar, `.top-bar-recent-choices` reserves in-flow room below
it (tokens.css carries the arithmetic) and `TopBarGroupButton` bounds each
panel from its own computed top. User-facing behaviour: help topics
`force-scene`/`force-color`.

**The Scenes/Colour buttons' own collapsed FACE shows what is actually
playing, not a setting (2026-10-07, his ask: "the scenes button the top
bar that currently shows transitions + analyzed: change that to show the
name of the current scene. Similarly, on the color button, show the
current color set (or the last chosen one if it is drifting). Show a lock
icon if it's being forced, and nothing otherwise").** `RoomControlsBar.tsx`
reads `engineStatus.conductor.active_scene.name` (Scenes) and
`engineStatus.conductor.journey.active_set_id` resolved against the
fetched colour-set list (Colour) — the scene-change-mode select and the
Force Scene/Force Colour pin panels above are unchanged, just moved out of
the button face and into its tooltip. `journey.active_set_id` already
answers "or the last chosen one if it is drifting" with no separate
drift-state branch: per `color_journey.py`'s own DESTINATION model (above),
it's the room's current destination, held steady while the journey steers
toward it and replaced only on arrival. The purple "forced" dot on these
two buttons is replaced by a dedicated padlock (`iconRegistry.ts`'s `lock`
key, `.top-bar-group-btn-lock` in tokens.css) shown only while forced,
nothing otherwise — the dot itself is untouched everywhere else (mode/
ambient). `.top-bar-group-btn-value` now truncates with an ellipsis at a
fixed max-width, since a scene/colour-set name is author-chosen and
unbounded where the old mode labels were fixed strings. Spec: `scripts/
check_topbar_scene_colour_names.mjs` (mounts the real `RoomControlsBar.tsx`
under jsdom against a fixture data layer).

**The lock icon didn't update when something OTHER THAN this browser's own
PUT flipped the pin (2026-10-08, his report: turning off Force Colour from
the Light Show "didn't seem to update the icon/button on the top bar").**
`useRoomControls()` (`spectra/web/src/queries.ts`) has no poll of its own —
only a 10s `staleTime`, refetched on mount/window-refocus/this-browser's-
own-save — so a Light Show step, Sonic, or another tab flipping
`force_scene_enabled`/`force_color_enabled` through `room_controls.
apply_patch` (the one choke point all three share) never reached a
different tab's cache. `apply_patch` now broadcasts `{"type":
"room_controls_force", ...the four force fields...}` on the SPECTRA
websocket whenever any of them actually changed — compared directly
against `previous`/`state`, NOT keyed off `reconcile_force_scene_if_
changed`/`reconcile_force_color_if_changed`'s own return value, since both
of those intentionally return `None` on a release (turning OFF is exactly
the miss this exists to close). `useRoomControlsForcePush()` is the client
half (mounted once in `RoomControlsBar.tsx`, next to `useAmbientStatusPush`,
same precedent: fold the push straight into the SAME `['spectra-room-
controls']` cache entry `useRoomControls()` reads). Spec:
`tests/test_room_controls.py` (the broadcast fires on a release, fires on
an enable/repin, and stays silent on an unrelated field) + `scripts/
check_room_controls_force_push.mjs` (the real `queries.ts` hooks under a
real `@tanstack/react-query` client, proving the push lands with no
refetch).

**Temporary scene disable** (2026-08-18, his ask: "add an ability to
disable a scene temporarily") — `SceneV2.disabled: bool` (default False),
a manual reversible toggle, no timer/expiry. STRONGER than mode
availability above (checked first, wins the reported reason when both
apply) — gated at the same three choke points: `scene_sequencer.
fire_scene_by_id` (the hard gate; `skipped="disabled"`), `SceneSequencer.
_roll`'s candidate pool (new `_scene_enabled`/`_default_scene_enabled`,
kept separate from `_scene_mode_available` rather than folded in),
and `trigger_engine._default_select_scene`'s generated-trigger draw. A
manual Fire/test-fire bypasses it, same as it already bypasses mode
availability. Force Scene still fires a disabled pinned scene (an
explicit press always wins) but NAMES the contradiction rather than
applying it silently: `fire_scene_by_id` returns `overrode_disabled=True`,
threaded through `reconcile_force_scene_if_changed` into
`force_scene_result.overrode_disabled`, surfaced as a second badge ("⚠
overriding disabled scene") on `RoomControlsBar.tsx`. Visible everywhere a
scene's status is shown, not just a detail panel: a red "⛔ disabled"
badge on the scene-list row and the phone header's compact selector
(`ScenesPage.tsx`), a `DisabledToggle.tsx` toolbar control next to Mode
availability, and the disabled marker on Force Scene's own scene picker.

Fixed 2026-08-19 (his report: "the enable/disable button gets taller and it
makes the entire row look bad"): `DisabledToggle.tsx` shipped with a fixed
pixel WIDTH but no `white-space: nowrap`, so the bold "⛔ Disabled" label
wrapped onto a second line at that width, growing the button (and the
toolbar row it sits in) 17px taller only while disabled.
`ModeAvailabilityToggle.tsx` — same row, one control over — was built with
the identical hard requirement ("must not change size as it cycles") and
had the identical gap, just never triggered because its own labels
("Hybrid"/"Light"/"Dark") happen to be short enough not to wrap. Both now
build their `style` via the shared `fixedSizeToggleStyle.ts` (fixed width +
`white-space: nowrap`), so this is closed for both, not patched once per
control. Measured via a real render of both toggles at 390×844 (isolated
instance, no live storage touched): fixed, an enabled-at-load scene and a
disabled-at-load scene render pixel-identical toolbar rows (88×31 toggle,
321×154 row); pre-fix, the disabled-at-load scene's toggle/row measured
88×48 / 321×171.
Deliberately did NOT extend the same naming treatment to Force Scene's
pre-existing SILENT bypass of mode availability (§9/§31 above) — a
different, already-shipped behaviour this task wasn't asked to touch.

**AMBIENT IS ONE BINARY TOGGLE (2026-08-30, PR fm/ambient-binary-clarity;
`docs/SPECTRA_SPEC.md` §96) — read `spectra/services/ambient_music_gate.py`'s
module docstring before touching anything here, it is the binding
statement.** His ruling: "let's only ever toggle between Off and On."
`RoomControlState.ambient_mode` (`"off"|"always"|"auto"`) is RETIRED for
`ambient_enabled: bool` + `ambient_on_music_pause: bool`. Migration on load:
`"always"` → enabled True, `"off"`/`"auto"` → enabled False, and
`ambient_on_music_pause` **False in every case** (his explicit "set it to
false for now"), every other key byte-preserved. The "auto" BEHAVIOUR is
preserved verbatim in `_desired_hold` and gated behind the new switch —
disabled, not removed. Four things ride with it, and all four have bitten
before:

- **THE PHASE CONTRACT IS FROZEN** — another captain builds Home Assistant
  against it. The `ambient` key on `GET /api/engine/status` and on the
  SPECTRA websocket (`{"type": "ambient_status", ...}`) carries
  `intent: "on"|"off"` and `phase: "on"|"off"|"turning_on"|"turning_off"|
  "unavailable"`. Do not rename or extend those value sets without going
  back to him. `phase` updates within 1s because the gate PUSHES at every
  transition start/end/cancel; the 3s poll is the backstop, not the
  mechanism (`spectra/web/src/api/spectraWs.ts` folds the push into the
  SAME react-query cache entry the poll writes — never a second source of
  truth). `phase` reports the TRANSITION's outcome, not the bulbs': a hold
  broken out of band still reads `on`, and the pre-existing `held`/`mode`/
  `verify`/`verified_age_s` keys keep carrying that honesty.
- **INTERRUPTION SNAPS, and the boundary matters.** Measured live before
  the rework: turn-OFF 22.6s, turn-ON ~15s across his 17 bulbs, and a press
  MID-transition took **38s** to win because it queued behind
  `services.ambient`'s own I/O lock. Now at most ONE generation-stamped
  transition task exists; a new intent cancels the in-flight one at its next
  safe write boundary (never mid-write to one bulb — `ambient.CancelToken`
  owns where those are, and its interruptible `sleep` is what lets a RAMP be
  abandoned instead of waited out) and applies the new end state with every
  ramp DROPPED (`snap=True`). **The 300ms write stagger STAYS — that is
  zigbee physics; the ramps are choreography.** A superseded run never
  writes again and never touches the landed-state bookkeeping (guarded on
  `_transition is tr`), or a slow cancelled turn-off would flip `_held` back
  while the room is genuinely lit. An UNINTERRUPTED turn-off keeps its full
  two-phase ease — his complaint was the interruption, not the fade.
- **The press does not block.** `reconcile_ambient_if_changed` STARTS the
  transition and returns `{"status": "turning_on"/"turning_off", intent,
  phase}`; the PUT blocking for the whole sequence is where "I don't know if
  it has started" began. Every automatic caller still uses `wait=True`.
- **A press while the room is not ours is never a silent nothing**: it
  starts no transition and records NOTHING as landed (recording it is what
  would make the take-back short-circuit and swallow his intent), returns
  `{"status": "dark", "phase": "unavailable", "stored": true}`, and applies
  on the next take-back — app.py's startup/resume, and now
  `handover.run_handover`'s own commit when SPECTRA becomes owner.

Spec: `tests/test_ambient_transition.py` (a timestamping mock bridge at his
real bulb count, pacing scaled 1/20th so a sequence still has real duration
to interrupt — the 38s shape is reproduced RED against the pre-rework call
shape before the new owner is proven green) +
`tests/test_room_controls.py::test_ambient_mode_migrates_to_the_binary_toggle`.

Everything below this paragraph is the history of the retired three-setting
gate, kept because its reasoning still governs the music-pause branch and
because the composition facts it establishes are unchanged.

Origin: found live 2026-08-15,
`ambient_enabled: true` (the old bool) + a real track playing + an active
scene + firing triggers = all 19 Hue bulbs sat frozen at ambient cream,
following none of it — a second, independent cause of his "no scene
changes" complaint on top of the `scene_change_mode` fix. First framed as
"music always wins"; the Admiral corrected that the SAME session: he
wants Hue held lit during music TOO, as a deliberate third setting, as
long as every other device keeps performing — so the fix became three
modes, not one rule. `"off"` never holds. `"always"` (mode 2, his own
request) holds Hue UNCONDITIONALLY, playback irrelevant — proven for free
to never affect other devices, since `selection_kernel.py`/
`scene_sequencer.py`/`sequencer.py`/`trigger_engine.py` have zero
functional references to ambient state (grep-confirmed) and the hold
itself lives at `fx/devices/hue.py`'s device-level `set_frozen()`, the
last step in the pipeline, strictly downstream of scene selection.
`"auto"` is the original precedence fix: holds only when playback is
CONFIRMED not-playing, releases the instant it's confirmed playing. Every
path that can change the live hold (a human PUT, every bridge state
broadcast, process startup/resume) funnels through the gate rather than
calling `services.ambient.reconcile()` directly, so the chosen mode can
never be bypassed. Under `"auto"`, a confirmed playback read always wins,
even over an existing hold; an UNKNOWN read never actively changes
anything (carries the current hold forward) — collapsing unknown onto
"release" was rejected because a transient bridge blip would otherwise
flicker-release an already-quiet held room. One-way migration: a stored
`ambient_enabled: true` maps to `"auto"`, `false` to `"off"`. Visible
always-live status (`off`/`holding`/`yielding`/`transitioning`, plus the
chosen `setting`) folds into `GET /spectra/api/engine/status`'s `ambient`
key and shows as a persistent badge on `RoomControlsBar.tsx`, separate
from the one-shot PUT-outcome badge. Full detail + room-proof status:
`docs/SPECTRA_SPEC.md` §52 and §53 (mode 2), both room-proven live
2026-08-15 — including the composition question, confirmed not just
architecturally but measured live: the drift conductor's own ~20s legs
kept firing on every non-Hue virtual across two full cycles while Hue
sat held under `"always"`, and the ease-back release re-measured at
~16.9s, unflattened against the §52 baseline. Spec: `tests/test_ambient_music_gate.py`,
`tests/test_bridge.py`.

**Ambient — Hue entertainment-area selection** (WHICH Hue devices Ambient
reaches, not just whether it holds — `docs/SPECTRA_SPEC.md` §5, ported
from legacy's own per-group picker on `web/src/nowplaying/AmbientButton.tsx`
after he asked twice): `RoomControlState.ambient_hue_group_ids` (`[]` =
every live Hue device, the unmodified default) is resolved and threaded
through `ambient.reconcile()`/`verify_held()`/`ambient_music_gate._apply()`
as an explicit `group_ids` parameter at every call site — a device outside
the resolved target is either left completely untouched (never frozen) or,
if it's frozen and just fell out of scope, released via the same
fade→catch-up→unfreeze sequence, gated on `fx/devices/hue.py`'s new
read-only `frozen` property (VENDOR.md deviation #11) specifically so an
already-unfrozen out-of-scope device never eats a spurious
`set_frozen(False)` stream reconnect. Whole-room OFF stays unconditional,
ignoring the current selection, unchanged from before this field existed.
`ambient_music_gate` tracks TWO separate group-id sets — `_held_group_ids`
(the raw selection input, compared only for the write short-circuit) and
`_held_resolved_groups` (the actual held device ids, sourced from the
reconcile result's own `devices` list, what `status()`'s `groups` reports)
— conflating the two makes `status()` report an empty hold under the
default `[]` selection even while genuinely holding everything.

**Reading real Hue bulb state — don't trust a raw CLIP light GET during a
live entertainment stream.** While a Hue entertainment session is
streaming (any active SPECTRA scene, not just Ambient), `GET
/clip/v2/resource/light` does NOT reflect the streamed colour — a bulb
being actively driven reads as static there, so a WORKING fix looks dead
and a genuinely frozen one looks fine; this nearly read as a fix failure
during §52's own live proof. To tell whether bulbs are actually following
the room, read `entertainment_configuration` status ACTIVE on each of his
bridges plus continuous glide writes for the relevant virtual in `GET
/spectra/api/engine/status`'s `executor.recent_writes` (`spectra/services/
engine.py::status`) — that combination, not the light resource, is what
"read it at the bridges" means for a streamed scene. The light resource
IS the right instrument for Ambient's own hold/release (`spectra/
services/ambient.py`) and the panic-release path (`spectra/services/
release.py`) — both write over plain REST, not the entertainment stream —
so the same GET that lies during a streamed scene is correct there — but
only once the area has actually STOPPED streaming, so `ambient.verify_held`/
`verify_looks` also read each held area's `entertainment_configuration`
status and count an `active` one as not held (re-freezing it when the
streamer is ours, `ambient_music_gate._refreeze_if_streaming`; 2026-10-07,
the dining area followed the show for ten minutes under "held, 17
confirmed"). A freeze always wins over a stream still starting
(`fx/VENDOR.md` #58). Pick the wrong instrument for the case at hand and
you get a confident wrong answer either way.

**Even for the correct instrument, a CLIP v2 light GET during an active
`dynamics`-ramped transition reports the commanded/target state, not a
live-interpolating frame.** Found live 2026-08-16 room-proving §63
(Ambient's second colour): polling `GET /clip/v2/resource/light/{id}`
every 150ms across a `dynamics.duration=1500` colour swap showed a
strictly binary jump — the OLD xy exactly, for several seconds, then the
NEW xy exactly from the next sample on, with no intermediate value ever
observed. The physical bulb almost certainly does fade smoothly (the
whole point of setting `dynamics.duration` on the PUT), but that
animation lives on the bulb/zigbee mesh, not in the bridge's REST
resource model — polling cannot see it. Proving an eased-vs-snapped
transition therefore has two honest layers, not one: the CODE-level
guarantee (confirm `dynamics.duration` is actually on the wire, e.g. by
reading the deployed source) and the STRUCTURAL guarantee (server logs /
`status()` show a single continuous hold, never a release-then-reacquire
cycle) are both provable by instrument; the third layer — does it
actually *look* smooth — needs a person's eyes on the bulb. Don't let a
binary-jump polling result read as "it snapped;" it means the instrument
can't see the answer, which is a different finding.

**A write-time confirmation is a snapshot, not a standing guarantee —
status surfaces need their own independent re-verification.** Found live
2026-08-15, overnight: `ambient_music_gate.status()` reported
`held: true, mode: "holding"` while every one of his 36 bulbs was
physically off (he'd turned them off before bed). Cause: `_apply()`
short-circuits a repeated identical `desired` (deliberate — no redundant
Hue writes), so under `ambient_mode="always"` a genuinely held room never
gets written to, and therefore never re-confirmed, again — the write's
own honest read-back (`_hold_and_confirm`, on+colour+brightness) just kept
replaying as if live. Fixed by adding a SEPARATE, GET-only periodic task
(`ambient_music_gate.run_supervised()`, `VERIFY_TICK_S=30`, wired into
`spectra/app.py`'s lifespan next to `frame_watchdog`/
`ownership_reconciler`) that re-checks reality on its own clock,
independent of whatever triggers a write — and a `status()` that reports
the CONFIRMATION's age (`verified_age_s`) alongside the result, rather
than only the result, so staleness is visible instead of implicit. The
general pattern for any future "X believes it's holding state Y" status
surface in this codebase: a write's read-back proves the moment it was
taken, not the moment someone reads the status later — either give the
status its own independent recheck loop, or make the staleness visible
(report the confirmation's age) rather than presenting a stale claim as
live. See `spectra/services/ambient.py::verify_held` (never writes — a
device found off is reported, never re-lit) and
`spectra/services/ambient_music_gate.py`'s module docstring ("Status
honesty") for the full mechanism.

**A state that is only announced on user-initiated transitions will
eventually lie about a transition the user did not initiate.** Found live
2026-08-15 in the device-preview strip (`spectra/services/
device_preview.py`): a status push only fired from the explicit
pause()/resume() API handlers, but the actual LedFX reconnect after
resume() completes asynchronously — an already-open tab could sit on
"reconnecting…" forever despite the server being fully live again, because
nothing told it once the async reconnect landed. Fixed in
`DevicePreviewRelay._set_connected` (PR #85): every `connected` transition
broadcasts, not just the ones a human click triggered. This is the same
shape as the write-time-confirmation gap above (a status that only
refreshes on the actions that usually cause a change, not on the change
itself) and is directly relevant to any future auto-triggered transition
in this codebase (the hidden-tab auto-pause built on top of this same
module is one — see `spectra/api/device_preview.py`'s WS endpoint calling
`relay.viewers_changed()` on every connect/disconnect, not just on a
pause/resume click). Broadcast state on every change of the underlying
condition, not on the actions that usually cause it.

**Device preview is now sourced from whichever world actually owns the
lights, not always LedFX** (fixed 2026-08-16, PR fm/spectra-preview-facade-
source, correcting the 2026-08-16 gap found room-proving against his real
stack — history kept below for why the fix takes this shape).
`device_preview._source_mode()` reads the SAME light-ownership record
`spectra/services/fx_seam.py` routes writes by: `owner == "spot-effects"`
→ `_consume_ledfx` (the original LedFX-websocket relay, unchanged, correct
whenever the external process really is the writer); `owner == "spectra"`
→ `_consume_facade` — no websocket at all, a direct in-process
`fx.events.Event.VIRTUAL_UPDATE` subscription on the live
`spectra.services.live_host.live.host` (the SAME event the frame-freshness
tap already listens for, fired by the real render thread after
assemble+flush — this is the literal pixel buffer being written to the
device); anything else (handing-over/released/spectra-owns-but-not-yet-
active) → `"none"`, honestly `connected: false`, nothing to relay. Pause
and the hidden-tab auto-pause are re-proven against the facade source on
its own terms (removing the `Event.VIRTUAL_UPDATE` listener from the live
host's own registry is the in-process equivalent of closing a socket —
`tests/test_device_preview.py` section 5 fires a frame directly at the
real bus while paused and proves it never reaches the relay), not assumed
to carry over from the LedFX proof. Licence position re-examined fresh for
this source (module docstring): `fx/` is already GPL-3.0-vendored and
already imported throughout spectra/, so subscribing to its own event bus
is no new incorporation; what would NOT be safe — and isn't done — is
porting `ledfx/core.py`'s dropped-from-vendoring throttle/serialize logic,
so the facade payload encoder is an independent implementation reusing
this module's own pre-existing throttle bookkeeping instead.

History (found live 2026-08-16, room-proof attempt against his real
stack, now resolved by the above): the original build always relayed
`ledfx_ws_url()` (`ws://…/api/websocket`, LEDFX_HOST/PORT from `.env`,
the pre-S3 `ledfx.service`) regardless of who owned the lights. Once
ownership moves to `"spectra"` (his live default since the S3 handover),
`ledfx.service` is intentionally stopped and the ownership reconciler
alarms if it comes back (see the S3 section above) — so the strip sat on
"reconnecting…" forever in his normal operating state: not a relay defect,
a genuine missing listener at that address. Proving live frames / genuine
pause against the ORIGINAL LedFX-only relay in that state would have
required either a real handover back to the external service (never do
this to "test" the preview) or exactly the source correction above.

**Device preview's expanded view is shape-aware, not always one flat
line** (fixed 2026-08-16, PR fm/spectra-preview-phone-matrix, his own
report after using it once: "the preview stretches out in a line super
far... I don't see any Matrix for The Matrix previews"). The backend has
always emitted the real `shape: [rows, cols]` on every frame — this was a
frontend-only defect, not a payload gap; check the payload before
assuming otherwise if this area comes up again. `DevicePreviewStrip.tsx`
branches on `shape[0]` (rows > 1 → `device-preview-matrix`, one row →
`device-preview-pixel-strip`, both sized to the container via
`aspect-ratio`/`width:100%`, no JS measurement) so a real matrix (his
`crystal-mapper` favourite, 72×37) reads as a grid and short strips (his
other favourites: 17/10/7 pixels) read as clean lines regardless of
length. Expanded devices stack vertically, so expanding always grows the
page downward. Collapsed mode's separate overflow (`.device-preview-strip`
was `white-space: nowrap` with no `flex-wrap`) wraps instead of running
off a phone's right edge.

**Device preview render path is a `<canvas>` painted imperatively, not a
`<span>`-per-pixel React grid** (fixed 2026-08-17, PR #115
fm/spectra-preview-smoothness, his own report: "not anywhere near as
smooth as ledfx version... ledfx was very good, and should be the
standard. copy as much as makes sense"). Read LedFX's real frontend first
(`/home/javi/ledfx-src/frontend/src/components/PixelGraph/*.tsx` — the
audio-visualiser `VISUALISER_CONTEXT.md` is a different feature, not the
device-pixel preview) plus `ledfx/core.py`'s `setup_visualisation_events`
and `ledfx/api/websocket.py`'s dual-path sender: LedFX ships five preview
render variants and keeps the DOM-per-pixel one only as a slower legacy
fallback (`variants: 'original'`) behind a settings toggle — `'canvas'`
(a raw WS callback writing straight to a canvas ref via
`ctx.putImageData()`, no React state in the hot path) is the shipped
default. Measured all three layers before touching code, against his
real shapes (`crystal-mapper` 72×37/2664px + 17/10/7px strips, via an
offline `fx.headless` render thread): SOURCE ~62fps and TRANSPORT
~7.66fps (matching `RELAY_TARGET_FPS=8`) were never the bottleneck for
either device size; RENDER was — a real-React harness reproducing the old
JSX (2664 `<span>`s inside one shared `frames` state object that
re-rendered the WHOLE strip on ANY favourite's frame) cost avg 6.5–8.7ms
on desktop, climbing to avg 43–47ms / max 86–98ms under a phone-class (4x)
CPU-throttle proxy — a third to most of the 125ms/8fps budget — versus
0.04–1.2ms for the canvas equivalent in both conditions. Fix:
`DevicePreviewStrip.tsx` now paints every incoming frame straight into a
per-device `canvasRefs`/`swatchRefs` ref via `putImageData`
(`imageSmoothingEnabled=false` + CSS `image-rendering:pixelated`, matching
LedFX's own default look) — a frame never touches React state, so it
never triggers a re-render at all, closing the cross-device amplification
too. Deliberately did NOT carry LedFX's `visualisation_maxlen≈81`
downsample cap: measured JSON.parse+decode cost for the full 2664-pixel
payload was <1ms even throttled (no smoothness benefit once canvas
removes the render cost), and it would conflict with his own prior
explicit ask two rows up (see immediately above) to actually see the
matrix shape — a named incompatibility, not a silent gap. Did not change
`RELAY_TARGET_FPS` (still 8) either, since SOURCE/TRANSPORT measurements
show it was never the cause. Full measured numbers and reasoning:
`docs/SPECTRA_SPEC.md` §43.

**"Still" bad 2026-08-20, over his real remote link — TRANSPORT bytes-per-
frame, ruled out above by a LOCAL-only measurement, was the actual
remaining cause** (`data/preview-frame-rate-is-still-bad-over-rem-dhvp/`,
his words: "the frame rate on the preview is still terrible... I'm always
on a remote computer, but LEDFx previews were really good"). The §43
"payload size was never load-bearing" finding measured `JSON.parse`+decode
CPU cost only, never bytes actually crossing a bandwidth-constrained link
— his stated permanent condition. Root cause: `_facade_frame_payload`
(his live default source since the S3 split) emitted pixels as a JSON
list-of-three-channel-lists ("uncompressed"); the LedFX-relay path forwards
whatever LedFX itself sent, which defaults to `transmission_mode=
"compressed"` — base64 of interleaved rgb bytes (`ledfx/config.py`'s own
default, confirmed in `/home/javi/ledfx-src`) — so LedFX being "really
good" on the exact same link was never about downsampling alone, it was
also sending far fewer bytes per point. Fix: `_facade_frame_payload` now
emits the same base64 encoding — no frontend change needed, since
`decodePixels()` (api/devicePreviewWs.ts) already parsed both shapes, just
never received the compact one from this path. Deliberately NOT
reintroducing LedFX's `visualisation_maxlen≈81` downsample cap — same
still-standing reason as before (his matrix-shape ask) — this changes only
the encoding, not the point count. Measured, not asserted:
`scripts/check_device_preview_remote_transport.py` — exact bytes/frame
from the real serialization code (crystal-mapper 36,624B → 10,758B, 3.4x)
plus a real throttled-loopback-socket delivery test at two representative
constrained-link profiles (2 Mbps/60ms: 4.76fps → 9.59fps; 768kbps/120ms:
1.96fps → 4.27fps) — labeled a remote-EQUIVALENT proxy, not his actual
connection, which this task never touched.

Verified against a static harness reproducing his real favourite shapes
at 390×844 and 360×780 (headless Chromium via chrome-devtools-axi), plus
a live isolated instance (spare port, `fx.headless` multi-virtual host
built to his real device shapes) for the canvas rewrite specifically —
his live `:8010` instance was read-only and untouched throughout both.

**Still skipping under fast motion after the bytes fix, 2026-08-20 — the
DELIVERY path, not payload size, was the remaining cause**
(`data/preview-skips-under-fast-motion/`, his second "LedFX was better"
report). Read LedFX's client fan-out (`ledfx/api/websocket.py
WebsocketConnection.send()`/`_sender()`) a second time, this time for what
happens AFTER encoding: it never queues a vis frame — a per-vis_id
single-slot mailbox unconditionally overwrites whatever hasn't been sent
yet, and exactly ONE sender task per connection drains it, one message at
a time. SPECTRA's relay did neither: the facade source fired a bare
`asyncio.create_task` per accepted frame into `WSManager.broadcast`
(`spectra/services/ws.py`), which wraps each client's send in
`asyncio.wait_for(..., timeout=SEND_DEADLINE_S=0.25s)`. Whenever one send
takes longer than a 125ms frame interval — ordinary on a real remote
link, no motion required — the next frame's task starts before the
previous one finishes, so two+ coroutines can be mid-write on the SAME
WebSocket at once (undefined behaviour); whenever a send exceeds 250ms,
the timeout fires and `broadcast()` calls `self.disconnect(ws)` — which
only removes the connection from its list, NEVER calls `ws.close()`. The
browser's socket is left fully open (`devicePreviewWs.ts`'s `onclose`,
its only reconnect trigger, never fires) while the server has silently
stopped sending it anything, forever — a permanent, invisible stall, not
jitter, and it never self-heals. Fix: `spectra/services/
device_preview.py`'s `PreviewFrameHub`/`_PreviewFrameSender` — one
single-slot mailbox + one dedicated sender task per connection, ported
from LedFX's shape, wired into the `/device-preview/ws` endpoint
alongside (not replacing) `preview_ws_manager`, which still carries only
the low-frequency status pushes. A frame send that genuinely fails now
gets a real `ws.close()` before giving up. Status messages are unaffected
and unchanged. Measured, not asserted:
`scripts/check_device_preview_frame_pacing.py` (delay-injected fake
socket bracketing the old 125ms/250ms thresholds — reproduces the OLD
path's concurrent-send overlap and its false eviction-without-close
side by side with the NEW path showing neither) + `tests/
test_device_preview.py` section 6. This is a delivery-TIMING fix, not a
second bytes fix — `_facade_frame_payload`'s encoding above is untouched.

**EXPANDED NOW DRAWS WITH THE LIVE TAB'S OWN RENDERER, NOT A PER-DEVICE
GRID/STRIP (2026-10-06, his ask: "make the expanded preview for the
devices look like the layout screen on devices").** The `device-preview-
matrix`/`device-preview-pixel-strip` CSS classes and the per-device
`canvasRefs`/`putImageData` painting the paragraphs above describe are
GONE from expanded mode — collapsed mode (the swatches, `paintSwatch`) is
unchanged and still works exactly as those paragraphs say. Expanded now
fetches `/device-preview/layout` (narrowed to his favourites), builds a
`StagePlan` with `live/positions.ts`'s `layoutPositions` and draws it with
`live/useLiveStageCanvas.ts` — the SAME hook + `LiveStage` class the
Devices page's Live tab uses, factored out of `LiveView.tsx` for exactly
this reuse. A conditionally-mounted `<canvas>` (the strip's canvas only
exists once `expanded` AND favourites have loaded) needed the hook's
`canvasRef` to become a state-backed CALLBACK ref rather than a plain
`useRef` object — a plain ref's `.current` can be null on the render
where the construction effect's dependency array happens to evaluate,
and since nothing else in that array changes once the canvas does mount,
the effect would otherwise never retry. See that hook's own docstring
before changing anything here. Both consumers (`DevicePreviewStrip.tsx`
expanded, `LiveView.tsx`'s Layout/Room map) share one renderer now, so a
future renderer fix benefits both automatically. Proof: `scripts/
preview_perf/run_preview_perf.py`'s existing gate still measures
`spectra+proxy` (the expanded strip, unaffected — its WS-level timings
don't depend on what the page draws with) and `spectra+proxy:live` (the
Live tab, now sharing the strip's code) alike.

**NO TEXT IN THE EXPANDED STAGE, AND IT NOW LANDS BELOW THE REST OF THE TOP
BAR AS ITS OWN FULL-WIDTH ROW (2026-10-06, his own words: "take all the
text out of the preview window, it is too messy. also, make it land below
the rest of the items on that horizontal bar and have it fill
horizontally. it is okay to rearange the different devices for it to fit
well on different devices")** — `DevicePreviewStrip.tsx`'s own module
docstring is the binding statement; three things worth knowing before
touching it again:

- `<DevicePreviewStrip />` renders TWO top-level siblings (a Fragment),
  not one — the controls (`.device-preview-strip`, unchanged in place) and,
  only while expanded, the stage (`.device-preview-expanded-row`,
  `flex: 1 0 100%`). Both land as DIRECT children of `TopBarStrip`'s own
  `display: flex; flex-wrap: wrap;` row, which is what forces the second
  one onto its own full-width line below every other top-bar item — no
  portal, no restructuring of where the controls sit. Every fixture label,
  the paused/idle/connecting notice, the selected-fixture name/detail and
  the "Open settings" button's own text are all gone from the stage;
  accessibility lives entirely in `aria-label`/`title` now (a new `settings`
  gear icon in `iconRegistry.ts` replaces the old text button).
- The stage's ARRANGEMENT is now MEASURED rather than a phone/not-phone
  guess: `live/positions.ts`'s new `compactPositions` (strip-only —
  `layoutPositions` itself, and the Live tab's own Layout view that calls
  it, are untouched) wraps fixtures at the row's own observed pixel width
  (a `ResizeObserver` on the wrap, via a constant stage-units-per-pixel
  scale) and reserves no row space for a label, since the strip draws none.
- **THE SAME CALLBACK-REF GOTCHA BIT A SECOND TIME, in a second ref, one
  paragraph after the first one was written down.** The measuring
  `ResizeObserver` was first wired to a plain `useRef` object
  (`stageWrapRef.current`), which silently measured nothing — a fresh
  render with `expanded` already `true` (restored from localStorage) can
  reach the measuring effect before `favoriteIds`/`stageLayout` have
  loaded, so the wrap element doesn't exist yet on the render that effect
  depends on (`[expanded]`), and nothing else in that dependency array
  changes once the wrap mounts later. Found only by comparing the real
  computed `--live-ar` against a hand-derived expectation — the stage
  rendered a plausible-looking but WRONG (narrow/tall) arrangement with no
  error of any kind. Fixed the same way the paragraph above already fixed
  `useLiveStageCanvas`'s `canvasRef`: a state-backed callback ref
  (`stageWrapEl`/`setStageWrapEl`), with the measuring effect depending on
  `[expanded, stageWrapEl]` instead of `[expanded]` alone. **Any ref on an
  element this component mounts conditionally needs this shape, not a
  plain `useRef` — check both existing instances before adding a third.**

Proof: `node scripts/check_device_preview_compact_layout.mjs` (the
transpiled real `compactPositions` against `layoutPositions` — no label
row reserved, genuine reflow against a measured width rather than a
two-preset switch, and identical per-fixture box shapes between the two).

**HIS PREVIEW REACHES SPECTRA THROUGH TWO PROXIES, AND THE SECOND ONE IS
THE SPOT-EFFECTS EVENT LOOP (2026-10-07, phase 4 of the same plan,
`data/preview-p4-live-check/report.md`).** `tailscale serve` on
`https://serenity.tailb5ca89.ts.net` sends `/` to :8000, whose
`services/spectra_proxy.py` relays the WebSocket to :8010 — so his
connections arrive as 127.0.0.1 sockets owned by tailscaled, never as
100.x peers, and a probe keyed on Tailscale addresses sees nothing.
Measured read-only under a real show with his browser on the preview
(`scripts/preview_perf/live_probe.py`, two protocol-2 viewers from the
host through :8000 and direct to :8010, exact one-way delay off the
server's own send stamp): the proxy hop is 0.3 ms at the median and the
whole cost is spot-effects' loop stalls (one 9.7 s freeze, p99 80 ms, 37
rate step-downs against 4 direct); his Tailscale leg itself had zero
retransmits. Change 7's answer is the serve route in
`docs/SPECTRA_PROCESS_SPLIT.md` ("His remote path"), a deploy step, not
code. **A newest-wins relay was ruled out on correctness**: a tick carries
only the devices changed since the viewer's previous tick was BUILT and
the next ack clears it from the window, so a tick dropped in a proxy
strands a still device's last change (the report's §3). Found alongside,
NOT change 7's and not fixed here: BOTH paths miss the 33 ms tick clock
under a live show (~150 inter-arrival gaps over 100 ms a minute, server
age p90 ~80 ms, 300-700 ms spikes on the direct path too) — that is the
Spectra process's own loop, the thing a "preview jumps" report would see
whichever route it took.

**THE PREVIEW STREAM IS PROTOCOL 2 (2026-10-05, phase 1 of
`data/preview-perf-plan/report.md`).** `spectra/services/preview_stream.py`'s
docstring is the binding statement (wire format included); the paragraphs
above describe the OLD JSON format, which a viewer that never says hello
still gets (`localStorage spectra-device-preview-legacy=1` forces it). Six
things:

- **The gap was the 8 fps cap, and raising it alone is unsafe** (2.3 s behind
  at 60 fps on 1 Mbit). The stream is a per-viewer 30 fps STEADY CLOCK (a
  "min interval since last send" test rounds 30 down to 20.7 against a 60 Hz
  source), binary, real cells only (crystal 976 of 2,664, from the device
  profile mask), paced by the browser's acks.
- **The ack window is "two frames beyond the link's own round trip"**
  (`ceil(min_rtt * rate) + 2`, capped), NOT a flat two — a flat two caps the
  rate at 2/RTT (22 fps on an 80 ms relay link) and cannot pass the gate.
- **Negotiation is a `hello` MESSAGE, never a query string**:
  `services/spectra_proxy.py` drops the query on a WebSocket.
- **uvicorn's WebSocket deflate uses a 4 kB window**, so consecutive frames
  do not compress against each other the way LedFX's (aiohttp, 32 kB) do —
  the reason Spectra's wire cost per byte is higher. Size frames to be small
  on their own.
- **The gate is `scripts/preview_perf/run_preview_perf.py --gate`** (README
  beside it): real browser, emulated links, LedFX measured in the same run.
  Rebuild `spectra/web/harness-dist` first. Two test traps it already
  handles: `singleColor` redraws on its own 100 ms loop (a flash must force a
  redraw), and evenly spaced flashes phase-lock to the sender's frame clock.
  Unit spec: `tests/test_preview_stream.py`.
- **THE STREAM IS A PASSENGER ON THE EVENT LOOP.** Anything that holds
  SPECTRA's loop holds the preview: the lights keep rendering on their own
  threads, the stream sends nothing, then sends only the newest frame — the
  preview "jumps past" whatever happened meanwhile (his 2026-10-07 flares-
  and-transitions report: an inline save of the ~1 MB fx config on every
  facade effect write, ~30 ms each, held the loop for a whole flare burst;
  effect writes now persist coalesced, `fx/VENDOR.md` #56). Before adding
  synchronous work to a write path, measure it with
  `scripts/check_preview_flare_skip.py` (the preview against the lights).

**THE LIVE VIEW (Devices → Live, pop-out `/live`; 2026-10-05, phase 2 of the
same plan).** `spectra/web/src/live/` — each file's header is the binding
statement. Five things:

- **The stream carries VIRTUALS; a person looks at FIXTURES.**
  `spectra/services/preview_layout.py` (`GET /api/device-preview/layout`)
  reads the stored fx config's segments and says, per fixture, its drawing
  kind and which stream CELL colours each pixel (`src`). A copy-mapped
  virtual's frame is its LONGEST segment (`tv-mapper` 560, `hues` ONE pixel
  for seventeen bulbs), and a masked device's cell index is the rank among
  its real cells, not the pixel index. Shapes other than the crystal's
  lattice are HINTS read off type and name — Spectra stores no positions.
- **The position table is the seam for the room map.** `positions.ts`
  returns a `StagePlan` (points, sizes, source cells, grouped by stream
  device); `layoutPositions` is one `PositionSource` and `roomMap.ts` is the
  other, for the SAME renderer — do not add a second renderer or teach
  `stage.ts` about fixtures.
- **Nothing per frame goes through React or allocates.** `stage.ts` copies a
  frame out of the message's bytes through the plan's source table into
  preallocated arrays and draws every point in ONE instanced WebGL2 call
  (MAX blend, so overlapping strip dots do not add up); 2D canvas fallback.
  Smoothing EASES each device from what is on screen to its newest frame
  over its measured arrival interval PLUS twice the arrivals' spread: an
  ease of exactly one interval ends before a late frame lands and the
  picture stands still (58.5 drawn fps on the relay profile, 59.8 after).
  About one frame of delay on an even link; switchable.
- **SCOPE**: the Live view asks the stream for `in_use` (every drawable
  virtual), the strip for `favorites`; the relay reads the extra virtuals
  only while a viewer asks (`device_preview.refresh_scope`). Pause is the
  preview's ONE sticky pause, shared with the strip.
- **The gate is a `:live` system in the perf runner** (`--pass-drawn-fps 59`,
  `:phone` = 390x844 with a 4x CPU slowdown; "drawn fps" = animation frames
  with a real draw call). `:live` rows use the machine's GPU
  (`--gpu auto`): headless Chromium otherwise rasterises WebGL in software
  and measures this box's CPU, not the view — every row records its
  `webgl_renderer`. The rig's `--room` builds his real topology on dummies
  and tells the layout endpoint their pretend types. `chrome-devtools-axi`
  was broken here (pageId error) — drive raw CDP as the runner does.
  Specs: `tests/test_preview_layout.py`, `node scripts/check_live_view.mjs`.

**A HELD HUE FIXTURE PREVIEWS ITS REAL COLOUR, NEVER THE STREAM'S
(2026-10-06, his report: Hue bulbs read yellow-green in the preview
despite being held at a white kelvin look).** `fx/devices/hue.py`: a
frozen Hue device's driving virtual "stays ACTIVE and rendering — only
this device's output is muted," so the preview (which taps that same
render via `Event.VIRTUAL_UPDATE`) always showed the room's live show on
a held bulb, never the REST colour actually on it — structural on his
`hues` virtual, which is ONE shared copy-mapped pixel across both
entertainment areas, so even a correct render could never show two held
areas at two different colours. `spectra/services/
hue_preview_colour.py` (kelvin/xy → sRGB, the SAME blackbody fit
`houseSummary.ts::kelvinToHex` already used correctly) +
`preview_layout.py`'s per-fixture/per-virtual `held` hex (from
`house.hue_directive()`'s own look, `None` = draw the live render as
before) is the fix; `positions.ts::withHeldOverlay` + `stage.ts` apply it
in the Live view, `DevicePreviewStrip.tsx` in the top strip. Specs:
`tests/test_hue_preview_colour.py`, `tests/test_preview_layout.py`,
`node scripts/check_hue_preview_colour.mjs`.

**Global Dark/Light mode** — day-one bar item, SPECTRA_SPEC.md §9 (`AGREED`,
built, room-proof pending for the Light half — see below); NOT the same
feature as the retired per-node Light Mode Chooser/§36, which shares only a
field name (`spectra/web/src/timeline/types.ts`'s per-trigger
`display_mode`, still unread by any `spectra/*.py`).
`RoomControlState.display_mode` (`"default" | "dark" | "light"`, room bar
select) is ALL THREE of legacy's states, matching `services/
display_mode.py`'s own cycle — a 2026-08-16 rebuild off the original
`dark_mode_enabled` bool, whose `False` state was found to be a mislabelled
Default (nothing forced) presented as "Light"; real Light (a configurable,
forced background) never existed until this rebuild
(`data/spectra-display-mode-three-state/report.md`). **Migration is
load-bearing**: `dark_mode_enabled: true` → `"dark"`; `false` → `"default"`,
**never** `"light"` (the old field was named light but behaved as default —
mapping false→light would have silently forced a background on deploy).
"default" is his word "hybrid" (labelled "Hybrid" in the UI, kept
`"default"` on the wire/internally). Dark toggles the SAME LedFX-side
`dark_lock` clamp legacy's `services/display_mode.py` drives — vendored
into `fx/` verbatim (`fx/virtuals.py`'s CONFIG_SCHEMA, `fx/effects/
__init__.py`'s `_apply_config` hard clamp), reached over ownership-routed
primitives on `spectra/services/fx_seam.py` (`get_virtuals`/
`set_virtual_config`/`apply_writes`, same HTTP-pre-handover/
in-process-post-handover routing). Light writes `display_light_bg_color`/
`_brightness` (new `RoomControlState` fields, legacy defaults `#201830`/
`0.3`) as `background_color`/`background_brightness` onto every
non-shielded virtual's CURRENT live effect config via `fx_seam.
get_virtuals()`+`apply_writes()` — running effect type and every other
param untouched — **unconditionally**, not gated on `bridge.is_playing()`
(unlike the default-repaint below), because a fresh forced write is
authoritative the instant it lands and gating it would defeat the point:
watching it work while music plays. `spectra/services/dark_light.py` is
the reconcile logic and carries the full fidelity reasoning — read its
docstring before touching this. Transitioning to `"default"` restores from
a live pre-dark snapshot (captured via `fx_seam.get_virtuals()`, persisted
to survive a restart, replayed via `fx_seam.apply_writes()`) rather than
legacy's "re-fire the last Color Set" (that concept belongs to the same
retired authoring world); the snapshot is cleared on every transition away
from `"dark"` (to `"light"` or `"default"` alike), since Light's own write
makes it stale. Shielding
(`dark_light_shield_categories`/`_virtuals`, default `["Singles"]` —
legacy's own default) is ported verbatim via the shared read-only category
registry (`fx/device_model.get_virtuals_for_category`). **Composes with
`ambient_mode`'s three settings, not a boolean** (the two features never
reference each other's fields — composition is architectural, not
coordinated): whenever a Hue device is ACTUALLY frozen right now —
`ambient_mode="always"` unconditionally, or `"auto"` while playback reads
confirmed-not-playing — that device is driven by direct bridge REST
(`spectra/services/ambient.py`), bypassing LedFX entirely, so `dark_lock`
has no visible effect on it; the moment that device ISN'T frozen
(`ambient_mode="off"`, or `"auto"` while confirmed playing), it's
LedFX-rendered like any other virtual and responds to `dark_lock`
normally. Dark/light never reads `ambient_mode` to decide this — the
orthogonality is a property of the write path (a frozen device never
reaches LedFX's effect config), not a rule either feature encodes about
the other, the same "compose for free by construction" shape Ambient
mode 2 found for the selection kernel. The transition-to-`"default"` repaint
is ALSO gated on `bridge.is_playing()` (`spectra/services/bridge.py`) —
while music is actively playing, the stale pre-dark snapshot is
deliberately not forced back (`dark_lock` still clears;
`repaint_skipped: "music_playing"` in the result) so the room's own live
show repaints it instead of a frozen still-frame overriding what's
currently playing — the same class of mistake `ambient_music_gate.py`'s
three-mode fix above exists to prevent, reached independently rather than
by sharing code with it. Light's own write is deliberately NOT gated this
way (see above). Measurement note, same lesson as "Reading real
Hue bulb state" above: dark/light's own mechanism is LedFX-side
(`dark_lock` + effect config on `/api/virtuals`), never the Hue CLIP
light resource — that instrument is for Ambient's own REST-held bulbs, a
different subsystem; verifying dark/light at the bridges means reading
LedFX's per-virtual `dark_lock` + effect config back
(`fx_seam.get_virtuals()`, what `dark_light.py`'s own confirm step and
`scripts/verify_dark_light_fixtures.py` both do). Spec:
`tests/test_dark_light.py` (18 tests), incl. frame-level proofs against a
real headless dummy host (`fx/headless.py`) that the vendored clamp
actually engages, the Light write forces the configured background live
even while playing, the restore repaints the exact pre-dark background, and
the music-aware gate holds both ways. Live-fixture check (read-only,
GET-only, same pattern as `scripts/verify_release_fixtures.py`):
`scripts/verify_dark_light_fixtures.py` — `--spectra-url`/`--ledfx-url`
are REQUIRED, no default target (a disposable worktree isolates the
filesystem, never the network — 127.0.0.1:8010/:8000 reach the same live
instances from inside any worktree on the host; a verification script that
defaults to them is a trap, learned live 2026-08-15).

**LEAVING LIGHT HANDS THE BACKGROUND BACK (2026-10-04, Light Show proof
D3).** Light paints `background_color`/`_brightness` and nothing used to
undo it: End show restored the display-mode setting while the TV kept
Light's colour. `dark_light` now records each virtual's own two background
fields before the FIRST Light paint (from the pre-dark snapshot when coming
from Dark, since the live config is clamped there) in
`dark_light_snapshot_pre_light.json`, and the transition to "default" puts
just those two fields back onto the CURRENT live config — only where the
background still equals what Light painted (a scene repaint since wins), and
not playback-gated (never a stale frame). Spec: `tests/test_dark_light.py`.

**THE BACKGROUND FADES, ROUND THE COLOUR WHEEL (2026-10-11).** Every live
background change — Dark's clamp, Light's paint, the way back, and any
instant background write in Hybrid — lands as a hue-path fade of the
RENDERED background (colour x brightness) at the effect layer
(`fx/background_fade.py` is the binding statement, `fx/VENDOR.md` #68).
Length = `RoomControlState.background_fade_s` (1 s, 0 = instant), PUSHED to
fx by `room_controls.push_background_fade` (every save + live stack
activate), or a Light Show Display-mode step's own `fade_s`
(`apply_patch(display_fade_s=)` → `dark_light.reconcile(fade_s=)` →
`background_fade.fading`). A tween >= `FOLLOW_MIN_S` keeps its own timing.
Two things not to undo: Light and the pre-Light/pre-dark restores write ONLY
the two background keys when the effect type is unchanged (a write naming
other colour keys RECREATES the effect on the facade and swaps the fade for
the virtual's crossfade), and a proof that reads a background pixel right
after a write must render past the fade (or set the default to 0). Spec:
`tests/test_background_fade.py`; help topic `background-fade`.

**HOUSE LIGHTING IS THE ONE EXCEPTION (2026-10-06, the Admiral's ruling,
verbatim: "house lighting modes should override dark mode") — the same
shape as Force Colour's house exception above, one axis over.** While a
house mode is actually governing the room's own look right now —
`house.house_overrides_display()`, True exactly when `layer_active()` AND
the mode is not currently handed to a music "show" phase (a "calm"/
"ignore" mode counts as driving even while music plays, same as
`scene_deferral`; standby does NOT count, deliberately differing from
`scene_deferral`/`_live_mode` there) — `dark_light.py` withholds the
dark_lock push, Light's forced background write, and the "default"-mode
stale-snapshot repaint on EVERY virtual (`dark_light._house_driving()`,
treated exactly like an extra, dynamically-computed shielded set for the
one call). The STORED `display_mode` is never touched — it simply doesn't
apply while a house mode drives. Because dark_lock is a PERSISTENT
per-virtual clamp (unlike Force Colour's per-fire substitution), a PUT
alone can't keep it in sync as the house's own driving state changes
later — `house.py`'s own `_enter`/`_hand_in`/`_go_inactive` hooks call
`dark_light.reconcile()` again, with the room's CURRENT stored
display_mode, every time that state flips, via `house.
_resync_dark_light_override()` (a no-op while stored mode is `"default"`).
This is what makes dark_lock reassert itself the instant music takes the
room back from a resting mode with no PUT required. Separately, a house
fire's own authored `#000000` must never take Light's black→light
substitution just because the room happens to be in Light mode:
`scene_compiler.fire_scene`/`compile_scene` and `drift_conductor.
apply_color_set`/`apply_set_directly` all gained an optional
`display_mode` override that REPLACES the room's stored mode for one
call, and `scene_sequencer.fire_scene_by_id`'s `origin="house"` branch
(house.py's `_default_fire_scene`/`_default_apply_set`) passes `"default"`
through it — mirroring Force Colour's own `origin != "house"` check one
line above it. UI: a gray dot + a panel note on the Mode button, and
`house.status_dict()`'s `overrides_display_mode` key
(`GET /api/engine/status`'s `lighting` key). Spec:
`tests/test_house_overrides_dark.py` (the predicate, the dynamic dark_lock/
Light-write exclusion against a real headless host, the hook wiring) +
`tests/test_light_mode_bg_clear.py`'s override-specific tests.

**An authored black `bg_color` on a colour set is LOAD-BEARING in Hybrid
mode — do not remove it as "redundant" next to a black effect colour.**
`storage/color_sets.json` has 30 such entries across 22 colour sets (Black
Hole/Orbit/`Line - *`, `docs/SPECTRA_SPEC.md` §72, `scripts/
check_redundant_black_backgrounds.py`). His own first instinct, on
learning Black Hole ignores Light mode, was to strip these as dead data —
"a redundant black background." **They are not redundant: in Hybrid mode
they're the only thing that resets a virtual's background to black on
every fire.** Remove them and a prior non-black background left by an
earlier write (another colour set's own authored colour, or a Light-mode
write not yet repainted away) bleeds through the next fire instead of
being cleared — colour bleed between scenes, proven in the harness below,
not a hypothetical. His proposed fix was investigated, found unsafe on
exactly this axis, and NOT applied (no data or code changed) — he has
since replaced the underlying idea with a different, per-scene
colour-set preference design instead.

An authored `bg_color` beats Light mode regardless of `bg_mode`, because
the stomp is gated on the value being truthy, not on additive-vs-overwrite.
`scene_compiler._apply_set_colors`/
`_entry_config` writes `config["background_color"]` whenever `entry.bg_color`
is truthy, and `fx/effects/__init__.py::Effect._apply_config` partial-MERGES
each write (`self._config = {**self._config, **config}`) — so any entry
that authors a `bg_color` re-asserts it on every fire and overwrites
whatever a previous write (e.g. Light mode's forced background) left there;
an entry that authors nothing never touches the key, so a prior write
survives. Confirmed empirically against the real vendored pipeline via
`fx.headless` (no live storage): `scripts/check_black_bg_light_mode_interaction.py`.
Separately, once `bg_color` actually is black, `Effect._refresh_bg_render_state`'s
`bg_color_use` gate (`(live_rgb*brightness > 0.5).any() or (target_rgb >
0.5).any()`) is `False` regardless of `bg_mode` or brightness — additive
and overwrite black are equally invisible on their OWN turn, but that
sameness does not carry over to the stomp question above; don't conflate
"is this a no-op once rendered" with "does this clear a previous write" —
they're gated by different code paths. Fixing this by deleting the
redundant black fields from data is not free: in Hybrid/Default mode
(where nothing else forces a background) it also removes the guarantee
that these entries reset a virtual's background to black on every fire,
so a leftover non-black background from an earlier write would persist
through their next fire instead. `scripts/check_redundant_black_backgrounds.py`
finds every affected entry (30 across 22 colour sets in his real data, not
just Black Hole).

**A sparse/black-canvas Matrix effect can opt out of `background_color`
writes entirely** — `config/effect_params.json`'s per-effect
`no_background_color` flag (`fx.device_model.bg_color_blocked()`, checked
by every colour-set-driven write path: `scene_compiler.py` ×2,
`drift_conductor.py`, `scene_response.py`) makes those paths skip writing
a fired set's `bg_color` onto that effect's config at all, regardless of
which set fires. Still set on `radial` ("a non-black background washes
the panel") and `pacman` (both paint thin/sparse content onto a canvas
that starts as `np.zeros(...)`, unlike the denser particle effects that
read their own `self._bg_color`/pre-filled `self.matrix`, e.g.
`blackhole.py`). §85 also set it on `squiggles` after a real headless
render proved a bright authored background floods ~100% of its frame —
**removed again, §87, his own ruling: "keep the backgrounds, i want to
control them with overrides."** He was told the legibility tradeoff and
chose to manage it himself with colour-group overrides (§10) instead of
having the capability suppressed — made possible once §86 proved a group
override actually reaches the wire (three choke points were silently
discarding it before that fix). If a Matrix scene's colour-set accept
list looks suspiciously narrow, check this flag before assuming the
narrowing is arbitrary or before widening it — verify from the effect's
real render output (`fx.headless`), not from set metadata; squiggles'
widened accept list (§85, `accept_all_sets=True`) itself never depended
on the flag and is untouched by its removal. `pacman` carries the
identical byte-for-byte accept list to squiggles' pre-widen state and
still carries the flag — not part of either his §85 widen ask or his §87
background ruling, deliberately left alone as his call, not tidied in
passing.

**In "light" mode, an authored `#000000` background clears to the room's
own Light background instead of literal black** (`room_controls.
resolve_authored_bg_color`, his ruling "do option three": Light paints its
forced background ONCE and never re-asserts it, so a later colour-set fire
authoring literal black — 30 entries across 22 of his real sets — cleared
it and it never came back). Threaded into all five places a colour-set/
scene-entry background reaches the wire: `scene_compiler._entry_config`/
`_apply_set_colors`, `scene_response.ResponseEngine._color_jump`,
`drift_conductor.DriftConductor.apply_color_set`/`_journey_leg`. Real-data
proof: `scripts/check_light_mode_bg_clear.py`. Tests:
`tests/test_light_mode_bg_clear.py`.

**This feature shipped once (PR #142), crashed the service on every start,
and was reverted (PR #145) — the rebuild (PR fm/spectra-light-mode-fix-
import-crash) kept the feature identical and fixed only the construction
pattern.** `DriftConductor`/`ResponseEngine` are both built as singletons
at `spectra/services/engine.py`'s MODULE IMPORT TIME (`conductor =
DriftConductor(...)`, `responses = ResponseEngine(...)`) — never inside a
function, never lazily. PR #142 gave each of them a
`room_controls_load: ... = None` constructor param whose fallback,
evaluated **inside `__init__`**, did `room_controls.load_room_controls`
— a real attribute access on the module-level `room_controls` imported at
the top of the file. That module-level name was ALSO reused as a plain
constructor **parameter** name (`room_controls: Callable[[], Any] | None
= None`, added independently by PR #144 for the drift-gradient feature,
already merged to master by the time #142 was reverted) — inside
`__init__`, any bare reference to `room_controls` binds to the parameter,
not the module import, so the fallback silently read `None.
load_room_controls` and threw `AttributeError` on every process start
(`spectra/services/drift_conductor.py:261`), a two-minute room outage
before revert. Reproduced exactly by re-applying PR #142's diff on top of
current master and running `python -c "import spectra.app"` — a plain
in-process pytest run never catches this, because pytest has already
imported `spectra.services.room_controls` via some earlier-collected test
file by the time any one test runs, which is exactly what masked it the
first time.

**The rule, going forward: nothing that can be constructed at import time
may touch `room_controls` (or any similarly singleton-adjacent service
module) eagerly — inside `__init__`, as a bare default expression, or via
a module-level `from spectra.services import ... room_controls` import in
a file whose class gets built at another module's import time.** Resolve
it lazily instead, the pattern `DriftConductor` already used correctly
before #142 (and which the rebuild copied into `ResponseEngine`): a
constructor param `room_controls: Callable[[], Any] | None = None`, stored
as `self._room_controls = room_controls or self._default_room_controls`
where `_default_room_controls` is a `@staticmethod` doing the real `from
spectra.services.room_controls import load_room_controls` **inside its own
body** — nothing is imported or called until `self._room_controls()` is
actually invoked at runtime. Every OTHER call site that needs
`resolve_authored_bg_color` imports it locally, inside the function that
uses it, for the same reason. Before adding ANY new constructor parameter
to `DriftConductor`/`ResponseEngine` (or introducing a new class
constructed at `engine.py`'s module scope), grep the class for an existing
parameter of the same name — a second, differently-scoped meaning for
one identifier inside one `__init__` is exactly how this broke, and it
will not raise at review time, only at the next process start. Regression
proof that a fresh interpreter's cold start still succeeds (the ONLY kind
of check that would have caught this — a green pytest suite says nothing
about import order): `tests/test_light_mode_cold_start.py`, which spawns
`sys.executable -c "import spectra.app"` in a genuinely new subprocess
rather than relying on whatever's already in `sys.modules` inside the test
runner.

