# SPECTRA timing & offset-direction conventions — READ FIRST

**If you are about to read, write, measure, or reason about anything that
fires early/late/on-time — a lead, an offset, a delay, a ramp, a sync
correction — start here.** This document exists because the knowledge below
was already scattered across this repo's own docstrings, already correct,
and was not consulted before five real mistakes were made in one week (see
[Failure case studies](#failure-case-studies)). The fix is not more
knowledge — it's this: one place that collects it, states which engine each
quantity belongs to, and says loudly which quantities disagree with each
other in sign. Every claim below cites the file and line it was verified
against on 2026-08-21; if the code has moved since, that drift is itself the
kind of thing this document exists to catch — re-verify, don't trust the
table.

## The one thing to internalize before anything else

**Two families of timing quantity coexist in this codebase, and they use
OPPOSITE sign conventions for "earlier."** Nothing enforces this at a type
level — they're both plain `int` fields in milliseconds. The only guard is
whoever is reading this.

| Family | Positive means | Negative means | Composed as | Members |
|---|---|---|---|---|
| **LEAD** ("how early to start so the payoff lands on the mark") | **EARLIER** | later | `fire_at = target − lead` (subtracted from the target, or equivalently added to the running clock: `effective_now = now + offset`) | `lead_ms` (SPECTRA, all variants below), `RoomControlState.av_sync_lead_ms` (the room's own measured A/V calibration — the only AUTHORED member of this family), legacy's `ledfx_trigger_buffer_ms` + `effective_offset_ms` + `shape_offset_ms` |
| **OFFSET** ("where the owner dragged the mark / authored the moment") | **LATER** | earlier | `target = timestamp + offset` (added directly to the stored moment; two OFFSET terms may be SUMMED — see below) | `FlareKind.trigger_offset_ms`, `SceneV2.trigger_offset_ms`, `SpectraTrigger.trigger_offset_ms`, `DeviceSettings.timing_offset_ms` (SPECTRA); `MusicEvent.event_offset_ms`, `MorphLane.offset_ms`, `ParallelChild.offset_ms` (predecessor, currently dark) |

Both families are live simultaneously in SPECTRA's own trigger engine and
**compose in the same function**
(`spectra/services/trigger_engine.py` `tick()`, verified at
[lines 630–729](#collision-1-lead_ms-vs-trigger_offset_ms-the-live-collision)).
Adding or subtracting the two without tracking which side each is on
inverts one of them — the code's own comment calls this out as something
that "has cost hours twice." Anywhere you see a bare `+`/`-` between a lead
and an offset, stop and check which family each operand is from before
trusting it.

---

## Master table

Every timing quantity found in this codebase as of 2026-08-21, one row
each. **Live** = currently reachable from the running SPECTRA process on an
ordinary fire. **Dark** = the code path exists, the field can still be
authored/stored, but nothing in the SPECTRA engine reads it today (usually
because it belongs to the legacy engine, `legacy_trigger_engine_enabled`
defaults `False`, `config.py:652`). **Predecessor-only** = the field lives
in root `spotfx` code and was never ported to `spectra/` at all.

| Quantity | Unit | Sign convention | Owning engine | Status | Source |
|---|---|---|---|---|---|
| `SpectraTrigger.trigger_offset_ms` | ms | OFFSET: negative=earlier, positive=later, 0=unchanged | SPECTRA trigger engine — **every action kind** since 2026-08-27 (was `fire_scene` only) | **Live** | `spectra/models/trigger.py` (the field), `spectra/services/trigger_engine.py::tick()` |
| `FlareKind.trigger_offset_ms` | ms | OFFSET: negative=earlier, positive=later, 0=coincident with the trigger mark | SPECTRA response engine / flare preview | **Live** | `spectra/models/scene.py:307-338,345` |
| `SceneV2.trigger_offset_ms` | ms | OFFSET: negative=earlier, positive=later, 0=on the mark | SPECTRA trigger engine (`fire_scene`) / transition preview | **Live** (2026-08-27) | `spectra/models/scene.py` (`SceneV2.trigger_offset_ms`), read by `spectra/services/trigger_engine.py::_scene_offset_ms` |
| `DeviceSettings.timing_offset_ms` (per-device timing equalization) | ms | **OFFSET: negative = this DEVICE fires EARLIER, positive later, 0 unchanged** (his own words: "stick with the convention that negative is that it fires earlier"). **RELATIVE ONLY — it can never move the room.** A fixture can only be made to WAIT, so "earlier" is implemented as delay for everyone else: `delay_i = offset_i - min_j(offset_j)`, always >= 0, so the earliest device is delayed by exactly nothing and the rest are held back to meet it. All-offsets-equal (including the shipped all-zero default) is therefore byte-identical pacing to before the field existed, asserted at the transport. Applied at exactly ONE place — the DEVICE FLUSH LAYER (`fx/devices/__init__.py::_flush_timed`, reached by every vendored driver's `flush()`: Hue's entertainment stream, WLED via its DDP/UDP subdevice, e131, ddp, udp, dummy) — never at the trigger poll, never composed with a lead. **Absolute alignment of the whole room against the sound remains `av_sync_lead_ms`'s job (LEAD family, positive = earlier) and this field does not touch it**; measure per device with `/avsync`'s per-device mode, equalize the fixtures with this, then re-measure and re-apply the room lead to absorb the global shift | SPECTRA device layer (`fx/device_timing.py` holds the arithmetic; `spectra/services/device_settings.py` owns the store and is the only thing that pushes into it) | **Live** (default 0 for every device = inert until he authors one) | `spectra/models/device_settings.py` (the field + sign law), `fx/device_timing.py` (module docstring: the arithmetic), `fx/devices/__init__.py::_flush_timed` (the one application point), `tests/test_device_timing_landing.py` (both light edges measured at the transport moving by exactly the amount authored, both directions, with a byte-identity negative control) |
| `transition_preview.build_timeline`'s `trigger_mark_s` / `fire_at_s` | s | Same two formulas as the flare preview's — `flare_preview.trigger_mark_s` / `fire_at_s`, CALLED not copied | SPECTRA transition scrubbing-preview | **Live** (2026-08-27) | `spectra/services/transition_preview.py` |
| `phase_preview` marks' `mark_ms` / `fire_at_s` | ms / s | `mark = slot + band_trigger_offset_ms` (OFFSET), then `fire_at = mark − lead` (LEAD) — the same two-sign composition `tick()` makes | SPECTRA drop-sequence scrubbing-preview | **Live** (2026-08-27) | `spectra/services/phase_preview.py` |
| `scene_transition_lead.{crossfade_ms_for,anchor_frac_for,lead_ms_for}` | ms / fraction / ms | LEAD: `lead = anchor_frac × crossfade`, capped at `MAX_LEAD_MS`. The ONE definition, called by both `trigger_engine._scene_transition_lead_ms_for` and the transition preview | SPECTRA (shared) | **Live** (2026-08-27) | `spectra/services/scene_transition_lead.py` |
| `phase_preview.DEFAULT_GAP_MS` (charge 4444, lull 2778) | ms | Not signed — DERIVED, not tuned: `PHASE_RAMP_MS[cls] / (1 − PHASE_RAMP_HANG_FRACTION)`, i.e. the gap that reproduces the class's own unknown-gap fallback ramp exactly. A preview opens showing the shape the show falls back to. | SPECTRA drop-sequence preview | **Live** (2026-08-27) | `spectra/services/phase_preview.py` |
| `flare_preview.trigger_mark_s(anchor, offset, duration)` | s | `T = anchor − offset_ms/1000` — same OFFSET convention, expressed as a draw position | SPECTRA flare scrubbing-preview | **Live** | `spectra/services/flare_preview.py:127-138` |
| Flare-preview drag handler (`onTriggerOffsetChange`) | ms | `offset = round((animAnchorS − markS) × 1000)` — dragging the mark RIGHT → more negative | SPECTRA flare-preview UI | **Live** | `spectra/web/src/scenes/tabs/FlarePreviewOverlay.tsx:280-299` |
| `band_trigger_offset_ms(scene, class, intensity)` | ms | Same OFFSET convention; aggregates a band's attached kinds as `min()` over the nonzero values (earliest ask wins, untouched-default kinds never veto) | SPECTRA response engine, read by `tick()` for `fire_response` | **Live** | `spectra/services/scene_response.py:460-504` |
| `tick()`'s `target_ms = trig.timestamp_ms + trig.trigger_offset_ms` (fire_scene) / `+ self._response_offset_ms(...)` (fire_response) | ms | OFFSET family, applied first, before any lead | SPECTRA trigger engine | **Live** | `spectra/services/trigger_engine.py:630-696` |
| `_lead_ms` / `_default_lead_ms` (dispatches by action kind) | ms | LEAD: positive=earlier | SPECTRA trigger engine | **Live** | `spectra/services/trigger_engine.py:1036-1055` |
| `_scene_transition_lead_ms` / `_scene_transition_lead_ms_for` | ms | LEAD; `anchor_frac × crossfade_ms`, max across affected virtuals | SPECTRA trigger engine, scene transitions | **Live** | `spectra/services/trigger_engine.py:1058-1132` |
| `_response_switch_lead_ms` | ms | LEAD, with a hard exception: `event_class=="drop"` **always** returns 0 (a drop anchors its START to the mark, never before it) — checked ahead of the momentary-glide branch | SPECTRA trigger engine, flare/charge/lull/drop | **Live** | `spectra/services/trigger_engine.py:1189-1240` |
| `kind_lead_ms(kind, intensity, virtuals)` | ms | LEAD, per-kind extraction reused verbatim by the flare-preview's live loop so preview and production can't silently diverge | SPECTRA response engine / flare preview | **Live** | `spectra/services/scene_response.py:507-526` |
| `color_rotate_lead_ms` | ms | LEAD, intensity-scaled ramp-in duration (max over attached/pooled `color_rotate` kinds) | SPECTRA response engine | **Live** (declared; not yet attached to any real band) | `spectra/services/scene_response.py:258-296` |
| `momentary_switch_would_glide` / `_kind_would_glide` | bool | Gate: true only if a momentary kind's param targets a registry-`smooth` numeric — decides whether `DICE_REROLL_GLIDE_MS` lead applies at all | SPECTRA response engine | **Live** | `spectra/services/scene_response.py:413-457` |
| `DICE_REROLL_GLIDE_MS` | ms (=220) | Fixed lead magnitude for a glide-capable momentary switch | SPECTRA response engine | **Live** | `spectra/services/scene_response.py:187` |
| `transition_phases.anchor_frac` / `lead_ms(from,to,crossfade_ms)` / `MAX_LEAD_MS` (=5000) | fraction / ms | LEAD; `lead_ms = min(anchor_frac × crossfade_ms, MAX_LEAD_MS)` | SPECTRA, ported near-verbatim from legacy | **Live** | `spectra/services/transition_phases.py:98,111,119,125` |
| `flare_preview.fire_at_s(anchor, lead_ms)` | s | `fire_at = anchor − lead_ms/1000` — LEAD applied on top of an OFFSET already baked into `anchor` | SPECTRA flare-preview live fire loop | **Live** | `spectra/services/flare_preview.py:141-153` |
| `services/trigger_engine.py::_effective_offset_ms()` = `ledfx_trigger_buffer_ms + ledfx_rtt_ms + shape_offset_ms` | ms | LEAD: "positive result means we fire triggers earlier" (own docstring) | **Predecessor** trigger engine | **Dark by default** — gated by `legacy_trigger_engine_enabled=False`; still computed and broadcast every tick regardless (see [Collision 3](#collision-3-two-different-effective-offsets-broadcast-under-one-name)) | `services/trigger_engine.py:1077-1086` |
| `settings.ledfx_trigger_buffer_ms` (default 250) | ms | LEAD: "Positive = trigger earlier, negative = trigger later" (inline comment) | Predecessor, LedFX-HTTP write-transport compensation | **Predecessor-only, not ported** — SPECTRA's executor doesn't share that transport | `config.py:112-113` |
| `state.ledfx_rtt_ms` | ms | LEAD-family additive term; measured LedFX HTTP round-trip time | Predecessor, LedFX-HTTP write-transport compensation | **Predecessor-only, not ported** | `models/state.py:97` |
| `effective_now = now_ms + offset` (legacy tick loop) | ms | LEAD family expressed as a clock shift — algebraically identical to subtracting the same offset from every target (`now+offset ≥ target ⇔ now ≥ target−offset`) | Predecessor trigger engine | **Dark by default** | `services/trigger_engine.py:6805-6806` |
| `_resolve_shape_offset` / `apply_save` (xcorr-learned per-song offset) | ms | Feeds the LEAD family (see `_shape_offset_ms` below); **wanders live**, mid-song, via `apply_save` re-snapping to fresh cross-correlation reads | Predecessor xcorr engine | **Computed live regardless of the flag** (see below) | `services/trigger_engine.py:191-229,979-1049` |
| `state.timing["shape_offset_ms"]` | ms | Same as above; the raw xcorr correction, mirrored onto shared state every tick | Predecessor xcorr engine, broadcast over `/ws` | **Live data, but only its narrow slice is consumed by SPECTRA** — see below | `services/trigger_engine.py:6846-6854` |
| `bridge.shape_offset_ms()` / `bridge.effective_position_ms()` | ms | LEAD family: `effective_position_ms = position + shape_offset_ms`; positive `shape_offset_ms` ⇒ position reads further along ⇒ SPECTRA reaches future trigger marks sooner ⇒ fires earlier | **SPECTRA** bridge — reads ONLY the raw `shape_offset_ms` term, explicitly excludes `ledfx_trigger_buffer_ms`/`ledfx_rtt_ms` | **Live** | `spectra/services/bridge.py:1-42,195-217` |
| `perception_trim_ms` | ms | Same LEAD family; user-authored nudge layered additively onto `shape_offset_ms`'s base (`timestamp_offset_ms + trim`) | Predecessor, per-(song, Set List) manual correction | **Predecessor-only, not ported** — no equivalent field in `spectra/models`/`spectra/config.py` | `models/audio_shape.py:72-74`, `routers/audio_shape_router.py:243-299` |
| `audio_latency_ms` (default 1000) | ms | Not a fire-time offset at all — a fixed guess for how long the audio pipeline takes to deliver sound after Spotify reports a timestamp, used ONLY to align WAV capture boundaries when building the xcorr training corpus | Predecessor, capture alignment (`services/audio_shape_service.py`, `api/audio_capture.py`) | **Predecessor-only, not ported** — grep-confirmed no timing/latency/offset/delay/lead field exists anywhere in `spectra/config.py` | `config.py:110-111` |
| `MusicEvent.event_offset_ms` | ms | OFFSET: negative=earlier, positive=later (own inline comment) | Predecessor plan-timeline builder | **Dark by default** — only fires if `legacy_trigger_engine_enabled=True`; authoring UI still exists (ported Timeline Builder) | `models/music_event.py:819-820` |
| `MorphLane.offset_ms` | ms | OFFSET: negative=earlier, positive=later (own docstring, identical wording to `event_offset_ms`) | Predecessor plan-timeline builder | **Dark by default**, same gate | `models/music_event.py:642-655` |
| `ParallelChild.offset_ms` | ms | OFFSET: negative=earlier (own docstring) | Predecessor plan-timeline builder | **Dark by default**, same gate | `models/music_event.py:533-537` |
| `SequenceChild.delay_ms` / `SequenceStep.delay_ms` | ms | **Not a signed offset at all** — always a forward hold before a step fires; magnitude only, no "earlier" direction exists for it. Don't read `delay_ms` as a variant of `offset_ms`; they're different animals despite the naming similarity. | Predecessor plan-timeline builder | **Dark by default**, same gate | `models/music_event.py:481,498,664,678` |
| `librosa_offset_ms` | ms | Documented in this repo's own `AGENTS.md` as **unreliable** — nonzero on ~74% of analyses, outliers into the tens of thousands of seconds; do not use it to shift section/beat times. Both SPECTRA and legacy consumers read section/beat timestamps **raw**, deliberately ignoring this field. | Predecessor librosa analysis | **Live in storage, deliberately unread by every consumer** | `models/librosa_analysis.py:55`; consumers: `spectra/services/analysis_reader.py:14`, `services/scene_sequencer.py:28` |
| `dwell_seconds(scene, intensity)` | **seconds** (not ms — the one quantity in this table that isn't) | Not signed — a minimum HOLD duration, latched once at scene entry from the intensity the scene fired at | SPECTRA sequencer / dwell | **Live** | `spectra/services/dwell.py:109-148` |
| `room_controls.scene_transition_ms(state, intensity)`, `scene_transition_ms_gentle`/`_hard` | ms | Not signed — a crossfade DURATION, intensity-interpolated between 300ms (gentle) and 200ms (hard) | SPECTRA room controls | **Live** | `spectra/services/room_controls.py:574-587` (fields: `spectra/services/room_controls.py:498-499`) |
| `SceneV2.entry_ramp_ms` / `global_transition_ms` | ms | Not signed — scene-fire blend-in duration; explicit flat override beats the intensity-scaled default above | SPECTRA scene compiler | **Live** | `spectra/services/room_controls.py:147-184,494` |
| `color_rotate_{degrees,ramp_ms,dwell_ms,fade_ms}` | deg / ms | Not signed — all four intensity-scaled from the owner's exact numbers (60°→180°, 1000ms→250ms ramp, 1000ms→400ms dwell, fade=1.5×ramp) | SPECTRA response engine | **Live** (kind declared, not yet attached to a band) | `spectra/services/scene_response.py:222-256` |
| `PULSE_HOLD_S` (0.25) / `PULSE_RELEASE_S` (1.5) | s | Not signed — fixed momentary-kind hold/release durations (overridable per-kind by `hold_ms`) | SPECTRA response engine | **Live** | `spectra/services/scene_response.py:175-176` |
| `PendingRelease.armed_at` / `due_at` (= armed_at + hold_s) / `ReleaseGroup.due_at` | s (responder clock, `time.monotonic` in production) | Not signed — ABSOLUTE times: a momentary spike's hold clock starts when ITS OWN write lands (armed right after each virtual's spike write), and the engine's release task sleeps until `due_at` (`responses.seconds_until`) — never "hold_s after on_event returns" (that shape, the end of the fire's serial write burst, was the 967-1905ms "500ms" reverse hold measured live 2026-08-21). `flush_releases(hold_s, fire_seq=, due_by=)` drains only entries due by that time; a toggle's release is an instant jump, every other release still glides `PULSE_RELEASE_S` | SPECTRA response engine | **Live** | `spectra/services/scene_response.py` (`PendingRelease`, `_arm_pending`, `take_release_schedule`, `flush_releases`), `spectra/services/engine.py::_release_group` |
| `PHASE_RAMP_MS` (charge=4000, lull=2500, drop=400) / `_phase_ramp_ms()` dynamic stretch | ms | Not signed — charge/lull now stretch dynamically to ~90% of the live gap to the next trigger (`_next_trigger_gap_ms`); drop is never stretched; the static constants are now only the unknown-gap fallback | SPECTRA response engine | **Live** | `spectra/services/scene_response.py:298-334` |
| `flare_preview_hold.HEARTBEAT_TIMEOUT_S` (15) / `SWEEP_INTERVAL_S` (2) / `MAX_HOLD_DURATION_S` (180) | s | Not signed — abandonment/ceiling durations for the live flare-preview hold | SPECTRA flare preview | **Live** | `spectra/services/flare_preview_hold.py:191,197,203` |
| `param_watchdog.SWEEP_INTERVAL_S` (10) / `ORPHAN_GRACE_S` (30) / `RESTORE_GLIDE_MS` (= `PULSE_RELEASE_S`×1000 = 1500) | s / s / ms | Not signed — the param orphan watchdog's sweep cadence, the continuous away-from-baseline-with-nothing-holding-it age before it restores (margin over the worst legitimate hold+release ≈ 3.5 s — justified in the module docstring), and the restore glide (deliberately the same duration a momentary release uses, so a restore looks like the release that never came) | SPECTRA param orphan watchdog | **Live** | `spectra/services/param_watchdog.py` (constants near the top of the module) |
| `activation_report.RECHECK_INTERVAL_S` (30) / `RECHECK_PROBE_TIMEOUT_S` (3 = `live_host.DEVICE_VERIFY_TIMEOUT_S`) | s | Not signed — how often a light the last take-back/resume had to SKIP (unreachable/slow/not receiving) is re-asked after commit, and the per-device json/info read bound for that re-ask (the same probe `device_gaps()` polls at activation — `live_host.probe_device_live`, one definition of "confirmed driving"). Cadence matches the reconciler/frame watchdog's 30 s tick. A take-back from `released` itself still waits the activation probes' own `DEVICE_LIVE_DEADLINE_S` (25) before deciding a device is skipped — this recheck is what keeps that verdict honest afterwards. | SPECTRA activation report (the tolerant take-back, owner ruling 2026-08-21) | **Live** | `spectra/services/activation_report.py` (constants near the top of the module) |
| `av_offset_ms` (phone A/V-sync instrument: `light_lag_ms − audio_lag_ms`) | ms | **MEASURED, neither family**: positive = the LIGHT reached the phone LATER than the sound it was meant to land with (lights behind/lag); negative = lights EARLIER (ahead/lead). `light_lag_ms` = (phone sees a light edge) − (server wrote it); `audio_lag_ms` = (phone hears a sound onset) − (SPECTRA's own audio hub heard it); the phone↔server clock offset cancels in the difference. A measurement of his room from where the phone stood — NOT authored, NOT applied anywhere by the build that introduced it (the number is presented for him to accept; no setting is written). To close a measured offset the engine fires lights EARLIER by `+av_offset_ms` (a LEAD-family quantity, positive=earlier) — **that translation was built 2026-08-28 and is the `av_sync_lead_ms` row immediately below**, as this row asked. The measurement itself is unchanged by it: still measure-only, still never applied without his press | SPECTRA AV-sync instrument (`spectra/services/av_sync_session.py`, `av_sync_correlate.py`, UI `/avsync`) | **Live** (measure-only; pattern mode flashes the room over fx_seam and reverts) | `spectra/services/av_sync_correlate.py` (module docstring: the algebra), `spectra/services/av_sync_session.py` (module docstring: sign + privacy), `scripts/check_av_sync.py` (simulated rooms, the number vs truth) |
| `RoomControlState.av_sync_lead_ms` (**the apply translation the row above promised**) | ms | **LEAD family: positive = fire EARLIER, negative = fire LATER.** The one AUTHORED term in SPECTRA's fire clock, and the only setting the `/avsync` Apply button writes. Applied as a clock shift at exactly ONE place — `spectra/services/engine.py`'s trigger poll, via `av_sync_lead.show_clock_ms(position, lead)` — layered on top of the `shape_offset_ms` correction the bridge already applied: `show_clock = effective_position_ms + av_sync_lead_ms`, so a positive lead makes the song read further along, trigger marks are reached sooner, lights fire earlier. **`None` (the default) means NEVER CALIBRATED, deliberately not `0`** — both shift nothing at the clock; they differ only in what the dialogue says ("none yet" vs "0 ms"). **TRANSLATION FROM THE MEASUREMENT — ADDED, never assigned**: `proposed = current + round(av_offset_ms)`, because the measurement is taken WITH the current lead already running; assigning would silently undo an earlier calibration on every re-measure. Worked, both directions: *current `None`, measured `+120`* (lights BEHIND) → proposed `+120`, delta `+120`, stated as "lights will fire 120 ms EARLIER than they do now"; *current `+120`, measured `−45`* (lights AHEAD) → proposed `+75`, delta `−45`, stated as "lights will fire 45 ms LATER than they do now". The delta always equals the measurement and is always rendered as that direction SENTENCE, never a bare signed number. **Not** `settings.audio_latency_ms` (capture alignment for the xcorr corpus — a different job, and the number he remembers as "150") and **not** `settings.ledfx_trigger_buffer_ms` (retired-engine write-transport compensation, an inert −800 on his box); neither is an earlier value of this one and nothing in the apply path reads either | SPECTRA — the show clock (`spectra/services/av_sync_lead.py` owns the sign law; `spectra/services/engine.py` is the sole application point) | **Live** (default `None` = inert until his first apply) | `spectra/services/av_sync_lead.py` (module docstring: the whole law), `spectra/services/room_controls.py` (the field), `tests/test_av_sync_lead_landing.py` (the light edge measured moving by exactly the amount set, both directions, with a negative control), `tests/test_av_sync_apply.py` |
| Black Hole charge/lull effect-side shape: `LULL_FILL_PROGRESS` (0.5), `REVERSE_FALLBACK_TURN_S` (0.5 s) | phase-progress fraction / s | Not signed. `LULL_FILL_PROGRESS` is a position on the SpotFX-ramped `phase_progress` axis, NOT a wall-clock fraction: the ramp covers ~90% of the real gap and then hangs at 1.0 (row above), so p=0.5 lands at **~45% of the lull's true duration** — the closest an effect can get to his "half way through the duration of the lull" without being told the duration. `REVERSE_FALLBACK_TURN_S` is how long an ejected blob takes to turn around after a reverse flare releases (expressed relative to the effect's own speed curve, so it holds regardless of `base_speed`/radius/audio boost) | `fx/effects/blackhole.py` + `blackhole1d.py` (effect-side; SPECTRA only writes `phase`/`phase_progress`) | **Live** | `fx/effects/blackhole.py` (constants near the top of the module), `fx/VENDOR.md` #18/#20 |
| `LOOKAHEAD_HORIZON_MS` (= `transition_phases.MAX_LEAD_MS` = 5000) / `RESPONSE_OFFSET_HORIZON_MS` (= 60000+horizon) | ms | Not signed — cost-gate windows bounding how far ahead `tick()` bothers computing a lead/offset, not timing conventions themselves | SPECTRA trigger engine | **Live** | `spectra/services/trigger_engine.py:279-359` |

---

## The collisions, stated side by side

### Collision 1: `lead_ms` vs `trigger_offset_ms`, the live collision

Both families are active in the same function today. `spectra/services/
trigger_engine.py` `tick()` composes them explicitly (module docstring at
`spectra/services/trigger_engine.py:219-258`, code at
`spectra/services/trigger_engine.py:663-729`):

```
target_ms = trig.timestamp_ms + trig.trigger_offset_ms     # OFFSET: his sign, applied first
fire_at   = target_ms - lead_ms                             # LEAD: opposite sign, applied second
```

- `trigger_offset_ms` (**negative = earlier**) relocates the nominal moment.
- `lead_ms` (**positive = earlier**) then pulls the relocated moment
  earlier still, if the fire needs a head start to land its payoff on the
  mark.

**Since 2026-08-27 the OFFSET half of that composition is a SUM of two
same-family terms, and the LEAD half is unchanged:**

```
target_ms = trig.timestamp_ms                # the stored mark
          + trig.trigger_offset_ms           # OFFSET: THIS MARK IN THIS SONG
          + <the fired CONTENT's own offset> # OFFSET: THE SCENE / THE FLARE
fire_at   = target_ms - lead_ms              # LEAD: opposite sign, applied last
```

The content term is `SceneV2.trigger_offset_ms` for a `fire_scene` trigger
and `scene_response.band_trigger_offset_ms` (the fired band's flare kinds)
for a `fire_response` one; both default 0. **Adding two OFFSET-family
terms is legal — same unit, same sign, same meaning of "later"; adding a
LEAD to either is the thing that must never happen.** The trigger's own
field is honoured on every action kind now, instruments included: an
offset only relocates a moment, so it composes with an instant apply
(`select_color_set`, `fire_scene_update`) exactly as with a crossfade,
where a LEAD could not (a lead has to know what payoff it aligns and how
long that payoff takes to arrive).

The code's own comment states the danger plainly: *"a wrong sign here is
invisible to a naive test and has cost hours twice... must never be added
or subtracted from each other directly — doing so would silently invert
one of them."* At `trigger_offset_ms = 0` this collapses to the pre-offset
formula (`fire_at = trig.timestamp_ms - lead_ms`), which is why every one
of the owner's ~22,000 real `fire_scene` triggers was unaffected when this
shipped — the collision is currently latent everywhere he hasn't dragged a
preview marker, not absent.

### Collision 2: the OFFSET family independently agrees with itself

`FlareKind.trigger_offset_ms` / `SpectraTrigger.trigger_offset_ms` (SPECTRA,
live) and `MusicEvent.event_offset_ms` / `MorphLane.offset_ms` /
`ParallelChild.offset_ms` (predecessor, dark) all use the **identical**
convention — negative = earlier, positive = later — despite being
unrelated code written years apart. This is not a collision; it's the one
place in this table where two independently-evolved systems happen to
agree, and it's worth knowing so you don't go looking for a mismatch that
isn't there.

### Collision 3: two different "effective offsets" broadcast under one name

This is the exact shape of [Failure 3](#failure-case-studies) below, and
it deserves its own callout because nothing about the two fields' *names*
warns you they mean different things.

- **Predecessor's `effective_offset_ms`** (`services/trigger_engine.py:
  1077-1086,6805-6806,6846-6854`) = `ledfx_trigger_buffer_ms + ledfx_rtt_ms
  + shape_offset_ms`. This is written into `state.timing` and broadcast
  over `/ws` on **every tick of the legacy engine's loop, regardless of
  whether `legacy_trigger_engine_enabled` is on** — the assignment at
  `services/trigger_engine.py:6846` happens *before* the
  `if not settings.legacy_trigger_engine_enabled:` gate at line 6856, by
  design (so SPECTRA's own xcorr read below keeps getting fed). Reading
  this field tells you what the **retired** engine would have done, not
  what the owner's room is actually doing.
- **SPECTRA's own `bridge.effective_position_ms()`**
  (`spectra/services/bridge.py:205-217`) = `position + shape_offset_ms`
  only — it deliberately never reads `ledfx_trigger_buffer_ms` or
  `ledfx_rtt_ms` (module docstring, `spectra/services/bridge.py:33-39`:
  *"a genuine mechanism-differs-in-kind case, not a value worth guessing
  at"* — SPECTRA's executor has no LedFX-HTTP hop to compensate for). This
  is the number that actually governs when SPECTRA fires a trigger.

**Before reading any "effective offset" figure — from a log line, a status
endpoint, a diagnostic page — confirm which of these two formulas produced
it.** They share an underlying term (`shape_offset_ms`) and diverge by
exactly `ledfx_trigger_buffer_ms + ledfx_rtt_ms`, which is not a fixed
constant you can mentally subtract — `ledfx_rtt_ms` is a live, wandering
measurement.

---

## `shape_offset_ms` is not a measurement you can freeze and reuse

`shape_offset_ms` is the one term both families share, and it is **not
stable**. The predecessor's xcorr engine (`services/trigger_engine.py::
apply_save`, `services/trigger_engine.py:979-1049`) re-snaps it live,
mid-song, whenever a fresh cross-correlation read beats the current
play's best quality — by design, not by defect. It is fed into SPECTRA's
own clock via `bridge.shape_offset_ms()` (`spectra/services/bridge.py:
195-203`), read off the `timing` sibling field on every `/ws` "state"
broadcast (`spectra/services/bridge.py:1-42`).

**Consequence for anyone tempted to measure a "before/after" timing
improvement by diffing two readings of this value: don't.** A wandering
number read twice, seconds apart, with nothing else changed, produces a
delta that looks like a measurement and is noise. See
[Failure 2](#failure-case-studies).

---

## Which engine is actually timing his room right now

The predecessor's full trigger-firing loop is **retired** —
`settings.legacy_trigger_engine_enabled` defaults `False`
(`config.py:652`), gating the back half of `services/trigger_engine.py`'s
`run()` (firing from `storage/profiles/` data, `trigger_fired` broadcasts,
preview, pre-ramp, scene-override prep — `services/trigger_engine.py:
6856` onward). **The front half — the xcorr correlation loop that computes
`shape_offset_ms`, and the `state.timing` broadcast that carries it — keeps
running regardless of the flag**, because SPECTRA's own bridge depends on
that broadcast (see [Collision 3](#collision-3-two-different-effective-offsets-broadcast-under-one-name)).

So: **the predecessor process is still alive, still computing, still
broadcasting timing data — it just isn't firing anything anymore.** A
diagnostic surface that predates the S3 process split (`routers/
timing_viz_router.py`, ported verbatim into `spectra/web/src/timingviz/`
per `AGENTS.md`'s xcorr-sync section) can show you fields from either
engine on one page with no visual distinction between them. **Before
trusting any timing number, confirm which process/engine actually produced
it — a field's presence on a page is not proof it drives the room.**

---

## Failure case studies

Each of these is a real failure this project made in the week before this
document was written. Each is mapped to the specific quantity/quantities
involved and the specific row in this document that would have prevented
it, had it been read.

### 1. The audio delay was argued in the wrong direction

An audio-delay value was moved (1650 → worse, per the owner) and then
corrected twice by his own ears (→ 650 → 150). **Located 2026-08-22 (PR
fm/phone-audio-video-capture-for-measured-a-7b), strong circumstantial,
not a logged diff**: the number is SpotFX's `settings.audio_latency_ms` —
code default `1000` (`config.py:110-111`, "Milliseconds between audio
playback and Spotify timestamp"), typed into the Settings page's
"Latency & Timing" card (`web/src/settings/SettingsPage.tsx:146-149`,
`step={50}` — 1650/650/150 are all on that stepper), and sitting at `150`
in the live, **gitignored** `storage/settings.json` (file mtime
2026-08-20 21:21) — which is exactly why the earlier pickaxe search of
this repo's history came up empty: the value was never a commit. The
earlier guess at `perception_trim_ms` is withdrawn. **And the sting:
`audio_latency_ms` is not a fire-time offset at all** (see its own row
above) — it labels WAV-capture timestamps for the xcorr corpus and moves
the DRAWN playhead (`spectra/web/src/help/helpContent.ts`'s own words:
"audio latency shifts where the playhead is drawn, not when triggers
fire"); nothing in the engine that runs his room reads it. The week was
spent tuning, against his ears, a number that only reaches his lights
second-hand (via a corrupted xcorr corpus → `shape_offset_ms`). The
instrument that would have settled this by measurement now exists:
`/avsync` (the `av_offset_ms` row above).

### 2. The "proof" was noise

`shape_offset_ms` was measured before and after a change and the delta was
reported as a 1290ms improvement. The value itself swings over a second
unprompted — measured on the live room, nothing touched, values like
`3066 → 2054` and `2054 → 1442 → 345 → 350 → 1771 → 1074` within a single
session. See [`shape_offset_ms` is not a measurement you can freeze and
reuse](#shape_offset_ms-is-not-a-measurement-you-can-freeze-and-reuse)
above — `apply_save` (`services/trigger_engine.py:979-1049`) explains
exactly why: it re-snaps live, mid-song, on every improved cross-
correlation read. **The record this document keeps: never measure a
timing change via a raw `shape_offset_ms`/`effective_offset_ms` delta.**
Corroborate against the owner's own ears, or against a genuine measurement
instrument — the phone A/V capture at `/avsync` (`av_offset_ms` row above),
built 2026-08-22 for exactly this.

### 3. One engine's timing was read while his show ran on another

The value being read as "the" timing offset was the **predecessor's**
composite `effective_offset_ms` (`ledfx_trigger_buffer_ms + ledfx_rtt_ms +
shape_offset_ms`) — broadcast every tick regardless of the retirement flag
— while the room was actually being timed by **SPECTRA's** own
`bridge.effective_position_ms()`, which excludes the buffer/RTT terms
entirely. This is [Collision 3](#collision-3-two-different-effective-offsets-broadcast-under-one-name)
above, stated as its own callout specifically because this failure is the
whole reason this document exists in this shape (per the task brief: *"That
last column [live-in-SPECTRA-or-not] is what would have prevented failure
3 outright"*). The master table's **Status** column exists to make this
class of mistake structurally harder — every predecessor-only row is
marked so before you build on it.

### 4. Trigger-store divergence diagnosed by inference

Two trigger stores exist: the predecessor's per-song `storage/profiles/
*.json` (`MusicTrigger`, `models/song_profile.py:14-17`, `timestamp_ms:
int` — raw song ms) and SPECTRA's own `storage/spectra/triggers.json`
(`SpectraTrigger`, `spectra/services/trigger_store.py:1-6`, keyed by
`spotify_uri`). Both stores use the same raw-ms convention for
`timestamp_ms` (verified — no unit mismatch between them), so this was not
a sign/unit collision; it was a **divergence in which triggers exist in
each store**, diagnosed by inference rather than by reading both files
directly (per the task brief). The lesson this document draws is a process
one, stated plainly because it doesn't fit the sign-convention table above:
**when two stores can diverge, read both stores before diagnosing — do not
infer the state of one from the other, however confident the inference
feels.**

### 5. The preview/firing-path split

For a period, `FlareKind.trigger_offset_ms` was consulted only by the
flare scrubbing-preview (`spectra/services/flare_preview.py`); nothing in
the real firing path (`spectra/services/trigger_engine.py::tick()`) read
it at all, despite the field affecting the preview's own drawn marker and
schedule. This was established by reading the firing-path code directly
(commit `80ad5d6` / PR #174, "the firing path reads a flare kind's
trigger_offset_ms"), **after** having been asserted otherwise. The fix
landed the same day the split was found — `tick()` now reads
`band_trigger_offset_ms` for `fire_response` triggers
(`spectra/services/trigger_engine.py:630-696`, `spectra/services/
scene_response.py:460-504`), so the preview and the real show now compose
the offset identically (`spectra/services/flare_preview.py:67-93` states
the algebraic proof that they can't diverge). **The general lesson: "does
X consult this value" is a grep-and-read claim, not an assumption to carry
forward from an earlier state of the code — verify it fresh each time,
the same way this document had to.**

---

## How to check a live timing number right now

This document records **conventions and code locations**, not current live
values — several of the quantities above wander (`shape_offset_ms`) or are
tuned by the owner over time (`perception_trim_ms`,
`scene_transition_ms_gentle`/`_hard`, room-control fields). To get a
current value:

1. Read it from the live process directly (`GET /spectra/api/engine/status`,
   `GET /api/settings`, or the relevant router), never from a memory of a
   past reading or from this document.
2. If it's `shape_offset_ms`/`effective_offset_ms`, sample it more than
   once before drawing any conclusion — a single reading cannot distinguish
   a stable value from mid-wander noise (see Failure 2).
3. Confirm which engine/process actually produced the number before
   trusting it governs anything (see [Which engine is actually timing his
   room right now](#which-engine-is-actually-timing-his-room-right-now)).
4. If the owner's ears and an instrument disagree, the ears win pending a
   real measurement — this project has been wrong the other way twice.

---

## Maintaining this document

This document is itself timing-adjacent knowledge, and the whole point of
its existence is that unread knowledge is as good as absent. When you:

- Add a new signed timing field, add its row to the master table in the
  same change — state its family (LEAD or OFFSET) explicitly, don't just
  copy the field name.
- Change which engine reads a quantity (port something from predecessor to
  SPECTRA, retire a SPECTRA path back to dark), update its **Status**
  column in the same change — this is the exact fact Failure 3 shows costs
  the most when it's stale.
- Discover a new sign-convention collision, add it to
  [The collisions](#the-collisions-stated-side-by-side) rather than
  leaving it implicit in a docstring only one file will ever show.

Prefer citing the authoritative code (file:line, and quote its own
docstring where one exists) over restating logic here in different words —
this document is a map to the knowledge, not a second copy of it that can
drift out of sync with the first.
