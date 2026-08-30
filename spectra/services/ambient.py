"""SPECTRA's own Ambient Mode — the behaviour behind the room bar's Ambient
control (spectra.services.room_controls.RoomControlState.ambient_enabled /
ambient_color). This module is the single Hue write seam — it knows
nothing about the toggle, the music-pause switch, or the intent/phase
contract; all of that lives one layer up, in spectra/services/
ambient_music_gate.py, which is the only caller that decides WHEN to
invoke reconcile() below and owns the single cancellable transition.

The legacy world (services/ambient_mode.py) is the spec for what "ambient"
MEANS: a calm takeover of the Hue devices in the room — freeze each Hue
device's entertainment (DTLS) stream so its bridge reverts to normal
REST-controlled mode, then PUT every light in that stream to a static,
full-brightness colour directly over the bridge's own REST API. Non-Hue
devices (WLED etc.) are left running their normal reactive show, same as
legacy — the Entertainment-API brightness cap this sidesteps is a Hue-only
problem.

Two things are simpler here than in the legacy world, both because SPECTRA
drives her devices in-process (live_host.live) instead of through a remote
LedFX HTTP API:

  - No device-category setting to resolve a target from — every live Hue
    device in the room (live_host.live.host.devices, type "hue") is held.
    Matches "a calm takeover of THE ROOM" literally, and keeps this off the
    settings-form the room-controls surface deliberately avoids.
  - No "wake scene" on disable. Legacy needed one because freezing a LedFX
    virtual could leave it inactive, so re-arming the stream needed a fresh
    scene fire to put a real effect back on it. A SPECTRA-owned Hue virtual
    never goes inactive while frozen — set_frozen() only mutes this
    device's OWN flush(); the virtual keeps rendering the room's live scene
    the whole time (fx/devices/hue.py's own docstring) — so unfreezing
    alone is enough for the stream to pick back up wherever the scene
    already is.

Interruption (2026-08-30): a transition can be CANCELLED at a write
boundary and the newer end state applied with every ramp dropped — see the
"cancellation" block below `_light_cache` for the mechanics and the live
numbers that forced it. ambient_music_gate.py owns when; this module owns
where it is safe to.

Release (ambient OFF) is a TWO-PHASE bridge-side ramp, matching legacy's
own two-phase off-sequence (fade-toward-landing-colour, then ease toward
the real show) rather than the single fixed-brightness fade this module
shipped with in PR #56 — that shipped version faded to 35% and unfroze
immediately, an abrupt cut the Admiral flagged after living with it
("the spot effects version of transferring from ambient mode to releasing
was way better", 2026-08-14). Legacy's two phases are a REST fade toward
the wake scene's colour (services.ambient_mode._wake_fade_color, over
settings.ambient_transition_s) and, after the stream reconnects, an
LedFX-side effect-config tween from the wake scene's look back to a
CAPTURED pre-ambient look (settings.ambient_catchup_s) — that second phase
has no direct analogue here: SPECTRA's driving virtual never goes dark or
gets replaced by a wake scene, so there is no separate "wake config" to
capture-then-tween-away-from the way legacy's LedFX-side tween needs. What
IS reproducible, and is the same qualitative fix, is easing the HELD BULB
toward whatever the room's live effect is ACTUALLY rendering right now
before handing back control — sourced from the literal live pixel buffer
(Device.assemble_frame(), the exact per-flush frame HueDevice.flush()
already receives and drops while frozen — see fx/devices/hue.py) rather
than a captured scene config, since that buffer is a truer target than any
snapshot legacy could take (SPECTRA's render loop never stopped). Phase 1
(dim fade, AMBIENT_TRANSITION_MS) and phase 2 (catch-up ramp toward the
live look, AMBIENT_CATCHUP_MS) both run over Hue's own bridge-side
`dynamics.duration`, still frozen — the same REST-ramp primitive phase 1
already used, just re-aimed at a live-derived target instead of a fixed
dim. Only once that lands does set_frozen(False) hand back to the stream,
so the jump the stream then picks up from is small. Numbers
(AMBIENT_OFF_FADE_PCT=35, AMBIENT_CATCHUP_MS=8000) are legacy's own
shipped defaults (ambient_fade_brightness=35, ambient_catchup_s=8.0 in
config.py) — not re-guessed, matched. AMBIENT_TRANSITION_MS itself
started as legacy's own default too (ambient_transition_s=1.5) but is no
longer that value — see the constant's own comment and
docs/SPECTRA_SPEC.md §63 for the 2026-08-16 extension to 3000ms and why
it's recorded as his stated preference, not a proven one.

Light-state REST calls go over a direct httpx.AsyncClient (same pattern as
spectra/services/ledfx_release.py), not the live HueDevice's own
`_hue_request` — that vendored helper never checks response.status_code
(fx/devices/hue.py:175-186 returns response.json() unconditionally), so a
Hue CLIP v2 4xx error body would silently count as a successful write.
Legacy's own _apply_hue (services/ambient_mode.py) explicitly gates on
`status_code < 400`; raise_for_status() here is that same gate. Bridge
credentials come from the device's public `.config` property
(fx/utils.py BaseRegistry.config). Freezing itself still goes through the
device's own `set_frozen()` — the one call this module doesn't replicate.

State-only when SPECTRA doesn't own the live stack (dark, or spot-effects
owns) — reconcile() no-ops and reports "dark" rather than raising, so
saving the control never fails even when there's nothing to drive.

Read-back confirmation (fixed after a live defect, 2026-08-15): a 2xx PUT
response only means the BRIDGE accepted the write — it does not mean the
physical bulb took it. Live proof: "Ambient ON: ['dining-hues',
'hue-lights'] held at #f5da8c, 17 light(s) set" logged identically on a run
where 3 lights (Kitchen Infuse, Dining Hue SE, Dining Hue SC) stayed on
their old colour and a later run where all 17 actually changed — a burst of
17 back-to-back REST writes hitting the bridge's own zigbee mesh, which can
silently drop a command the bridge already 2xx'd (the mesh's radio, not the
bridge's HTTP stack, is the bottleneck). Toggling Ambient off/on again fixed
it, consistent with transient mesh congestion rather than a targeting bug —
the three ARE in Ambient's set. So enabling now reads every light back from
the bridge after writing it and only counts it as held once its reported
state matches; `_hold_and_confirm` retries stragglers a bounded number of
times, SPACED apart (not hammered — hammering a congested mesh makes it
worse) and also paces the initial write round itself
(AMBIENT_WRITE_STAGGER_MS) so a burst is less likely to congest the mesh in
the first place — prevention alongside recovery. `reconcile()`'s "on"
result can no longer overstate: `lights_set` is now a CONFIRMED count, and
any light still not holding after retries comes back by its own bridge name
in `unconfirmed` (status "partial") for a caller to name to the room's
owner — never silently folded into a bigger "N set" total. Checked at the
time but NOT actually fixed by this pass, corrected 2026-08-16
(spectra-audit-2xx-proof): this docstring used to claim the release path
(services/release.py) "stops the Hue entertainment stream rather than
writing individual lights, and already reads real state back" — false on
both counts. `services/release_fade.py`'s `fade_and_release_hue()` DOES
write individual lights (a dim PUT then an off PUT, direct REST, same
shape as this module's own writes), and `release.py`'s own
`_verify_released()` only ever checked process/ownership-level state
(`live.active`, external LedFX virtuals), never an individual Hue bulb —
so the release path carried the EXACT SAME attempted-vs-confirmed gap this
module's own read-back fix closed here, just never closed there. Now
fixed: `release_fade.py` reads each light back after its own off write
(see that module's docstring) and `release.py` folds a still-on light into
`ReleaseResult.verified`/`.problems`. The scene-fire path (fx_seam.
apply_writes) remains genuinely exempt, unlike the release path was
wrongly assumed to be: it writes virtual effect configs (through the
in-process facade or a hard-failing HTTP PUT) to the LOCAL render engine,
not one REST call per Hue bulb — the actual bulb colour only exists
downstream of that, driven continuously by fx/devices/hue.py's flush() at
~30fps over the entertainment stream, so a single dropped frame self-heals
on the very next one rather than needing its own confirmation.

Burst threshold measurement (2026-08-16, live against his room — measured,
not reasoned about): a paired report claimed 17 rapid REST writes ~0.12s
apart all 2xx'd with NOT ONE bulb lit, while the same 17 paced at 0.45s lit
all 17. Controlled, self-checked, repeated reproduction against BOTH real
bridges independently — sustained multi-round bursts (not a single round;
a single round found zero drops at any pace on the first pass), 0.08s
through 0.60s pacing, 3 trials per pace near the documented Zigbee
~10 cmd/s ceiling, 48 trials total — found ZERO drops anywhere in that
range on either bridge, `dining-hues` and `hue-lights` alike. This does
NOT reproduce the paired report's sharp cliff; the most likely explanation
is a target-tracking bug in whatever script gathered that original
evidence — the same class of mistake this investigation's own first
sustained-burst script made and caught only via a mandatory self-check
(confirm full success at an unambiguously safe pace before trusting any
faster result). What IS real and independently confirmed: the bridge
gives ZERO signal when a write doesn't land — every PUT during every
trial, dropped or not, returned a clean `HTTP 200` with body
`{"data":[...],"errors":[]}`, no `429`, no `Retry-After`, no rate-limit
header of any kind (captured raw for the fastest paces on both bridges).
A retry strategy therefore has nothing to react to but a read-back — this
module already only ever trusted read-backs, not response codes, and that
discipline is now the ENTIRE story, not one layer of several.
AMBIENT_WRITE_STAGGER_MS was still raised well past the old 50ms (see its
own comment) as cheap insurance against conditions this one measurement
session didn't cover, and because `_apply_hue` (the OFF-fade/catch-up
paths) had NO pacing at all before this pass — a real gap regardless of
where the ON path's own cliff does or doesn't sit.

Straggler repair (2026-08-16): the retry logic above only ever ran inside
one `reconcile()` call, immediately after a write. A SEPARATE, real defect
sat one layer up: `ambient_music_gate.py`'s periodic `verify_now()`
recheck could name an off-target straggler correctly on every 30s tick,
forever, and never once try to fix it — proven live: two bulbs (`Loft
Ceiling Uplight`, `Standing Lamp Side` in one incident) sat wrong for
hours through repeated correct detections; a plain re-apply of Ambient
didn't clear them either. `repair_stragglers()` below is the fix — reuses
`_write_and_confirm`, the exact paced/retried/read-back-confirmed engine
the initial hold already trusted, restricted to just the named stragglers,
called from `ambient_music_gate.verify_now()` the moment it finds one.
Checked fresh, immediately before writing, per straggler: a light reading
OFF right now is left alone (`left_off`), never re-lit — a bulb he turned
off himself must stay off, the one thing the periodic verifier was always
right to leave untouched, now narrowed from "the verifier writes nothing"
to "the verifier never writes to a light that reads off." Proven live
against real hardware (not just the headless suite): a forced real
colour-wrong straggler on `Standing Lamp Side` was detected by
`verify_held()`, genuinely rewritten by `repair_stragglers()`, and
confirmed by an independent read-back — see `tests/test_ambient.py`'s
`repair_stragglers` tests for the headless proofs (an on-but-wrong-colour
light gets rewritten; an off light never receives a PUT; a light that
keeps silently dropping the corrective write comes back `unconfirmed`,
never silently dropped from the report).

False-unlit fix (2026-08-16): a separate, live-reported defect — the
verifier's lit/unlit readout invented failures on genuinely-correct
bulbs, specifically ones caught at a different BRIGHTNESS than the
ambient hold's own target (then a hard-coded constant, since removed —
see "No AMBIENT_BRIGHTNESS_PCT constant" below) while still on and at
the exact ambient hue — a wall-switch or Hue-app dim, or simply his own
choice. `_state_matches`
(on+colour+brightness, used to confirm OUR OWN write landed) and
`_color_matches` (on+colour only, used by `verify_held()`/`status()`'s
reporting surface) are now two DIFFERENT checks — see each function's own
docstring for why the split is deliberate, not a loosened bug. Proven
live: forcing a real bulb (`Loft Ceiling Uplight`) to 35% brightness at
its correct hue, `verify_held()` now reports it LIT; before this fix
(re-run against the unpatched module for comparison) it reported unlit.

Status-honesty fix (found live 2026-08-15, overnight): the read-back above
proves a hold at the MOMENT it's written — it says nothing about five
minutes, or five hours, later. `ambient_music_gate.py`'s own `_apply()`
short-circuits a repeated identical `desired` (this module's docstring,
"no redundant Hue writes"), so under "always" mode, once genuinely held,
NOTHING ever re-touches the bridge again — a `status: on, lights_set:
17/17` from hours ago just keeps replaying as if live. Live proof: his room
sat at `held: true` all night while he'd turned every bulb off before bed.
`verify_held()` below is the fix's read half — GET-only, NEVER a PUT, so
it's safe to run on a short independent cadence (services/
ambient_music_gate.py's periodic verifier) without the write-burst zigbee
congestion `_hold_and_confirm` above guards against; it reuses the light
cache and `_color_matches` (on+hue only — see that function's own
docstring for why it's deliberately looser than `_state_matches`, the
write path's stricter on+colour+brightness check) rather than re-deriving
a second, looser notion of "held." What changed is not just WHO runs the
check and HOW OFTEN — previously only a state-changing write ever
triggered one; now a periodic read-only recheck does too, so a claimed
hold can't go stale for longer than that cadence — but also, since
2026-08-16, WHAT HAPPENS on a miss: `repair_stragglers()` gives the
verifier a bounded, paced, read-back-confirmed way to actually fix an
on-but-wrong-colour straggler it finds, not just name it (see that
function's own docstring — a bulb found genuinely OFF is still never
touched). The gate downgrades `held` only once repair has had its shot
and a straggler is still off-target.

Hue entertainment-area selection (2026-08-16, PR
fm/spectra-hue-entertainment-areas): he asked twice to choose which Hue
areas Ambient reaches — his dining room ("dining-hues", 7 bulbs) versus
his main Hue group ("hue-lights", 10 bulbs) — and it sat unbuilt on a hold
waiting for a word he was never told he needed to say. Ported from
legacy's own per-group picker rather than invented from the sentence:
services/ambient_mode.py held per GROUP (`state.ambient_groups`, a set of
Hue device ids — one per LedFX Hue device/entertainment config), exposed
via a long-press checkbox picker on the front-page Ambient button
(web/src/nowplaying/AmbientButton.tsx, `GET /control/ambient-groups` for
names + held state, `POST /control/ambient-mode?groups=<id>` per
checkbox). The unit of choice there is one Hue device id — exactly what
`_hue_devices()` above already enumerates one entry per (one bridge/
entertainment config per live Hue device), so SPECTRA needed no new
grouping concept: `RoomControlState.ambient_hue_group_ids` (room_controls.py)
names device ids directly, the same ids `reconcile()`'s `devices`/
`released` lists already report. `[]` (the default) means every live Hue
device — legacy's own `want=None` == "all groups" semantics, ported as
"empty list" so deploying this changes nothing until he picks a subset
(the bar: nobody's room changes when this lands).

One thing legacy had that SPECTRA doesn't: a device-CATEGORY layer above
the group picker (settings.ambient_target_category, resolved via
services/device_category_service) that first filters WHICH Hue devices
are even candidates before the per-group checkboxes appear. SPECTRA has
no LedFX device-category concept at all (module docstring, "No
device-category setting to resolve a target from") and every live Hue
device already IS a candidate group — so this build has no category tier
to port; `ambient_hue_group_ids` names devices directly, one flat list,
matching the intent (choose which Hue areas are in play) without
resurrecting a settings-form layer this surface deliberately avoids.

`reconcile()` now takes an optional `group_ids` (the resolved
`RoomControlState.ambient_hue_group_ids`, `None`/empty = every live Hue
device, preserving today's behaviour exactly). `_resolve_group_ids()`
intersects it against the room's actual live Hue devices, dropping and
logging any stale id (a group renamed/removed since it was last saved) —
mirrors legacy's own `want & set(hue_cfgs)` rather than treating an
unresolvable id as "select nothing." The hold path only touches devices
IN the resolved target; the release path additionally releases any
device that's currently FROZEN but has fallen OUT of the target (a group
he just deselected while Ambient stays engaged) — `_release_devices()`,
the same fade → catch-up-toward-the-live-look → unfreeze sequence
`reconcile(False, ...)` already used, now shared. Deliberately gated on
`dev.frozen` (fx/devices/hue.py's new read-only property, VENDOR.md
deviation #11) for this one case, unlike the whole-room OFF path below
(which still unconditionally releases every live Hue device, matching
its pre-existing behaviour byte for byte): calling `set_frozen(False)` on
a device that was NEVER frozen triggers `_trigger_reconnect()` — a real
stream teardown/reconnect on a device that's supposed to be left
completely alone. Skipping already-unfrozen, out-of-scope devices is what
makes "genuinely released... genuinely held" (the verification bar) true
for a device ambient never touched in the first place, not merely for one
it once held. `verify_held()` and therefore `repair_stragglers()`'s input
are scoped by the SAME resolved target — an out-of-scope device's bulbs
are never read back and can never be misreported as an ambient straggler
(the same false-unlit failure class "False-unlit fix" above already fixed
once for brightness; scoping avoids reintroducing its shape for scope).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Legacy defaults (services/ambient_mode.py's settings.ambient_transition_s /
# ambient_fade_brightness / ambient_catchup_s) — internal timing, not a
# room-control the Admiral tunes per song, so these stay constants rather
# than growing the settings surface.
#
# No AMBIENT_BRIGHTNESS_PCT constant here (removed 2026-08-16) — it used
# to be the ONLY source of brightness on the ON-hold path, hard-coded to
# 100 regardless of the colour, so a "darker" ambient colour could never
# actually dim anything (the hex only ever fed the bridge's xy
# chromaticity, which discards luminance), and the write's own read-back
# couldn't catch the gap because it was confirming against the exact same
# constant it had just written. Brightness is now DERIVED from whichever
# colour is in effect (`_hsv_value_pct` below) — the Admiral's own ruling
# on this fix, not a legacy port: legacy's settings.ambient_brightness was
# always an independent, separately-authored slider, never derived from
# colour either. See room_controls.py's ambient_brightness_note docstring
# entry for the full history, and `_hsv_value_pct`'s own docstring for why
# HSV Value (not relative luminance or CIE L*) is the chosen measure.
#
# AMBIENT_TRANSITION_MS: 3000, not legacy's 1500 (2026-08-16, docs/
# SPECTRA_SPEC.md §63): his stated preference, given BEFORE he had
# actually watched the live 1.5s glide (he later corrected that his
# "agreement" was courtesy about our description, not an observation) —
# so this value is unproven, not eyewitness-confirmed; see §63 for the
# full correction and don't record a future re-test as redundant.
# Governs both the ON hold's colour ramp and the OFF fade below (the same
# constant, deliberately — see _write_and_confirm's settle_ms for why
# raising it doesn't also lengthen a retry, which snaps).
AMBIENT_TRANSITION_MS = 3000
AMBIENT_OFF_FADE_PCT = 35
AMBIENT_CATCHUP_MS = 8000

# Hold-confirmation pacing (module docstring's "Read-back confirmation").
# Deliberately spaced, not hammered — the failure this defends against is
# most likely bridge/mesh congestion, and hammering a congested mesh only
# makes it worse. 300ms (2026-08-16 measurement, module docstring's "Burst
# threshold measurement" — a MARGIN inside the confirmed-safe band, not the
# fastest pace that happened to survive): 48 controlled sustained-burst
# trials against BOTH real bridges independently (dining-hues, hue-lights),
# 0.08s-0.60s pacing, found ZERO drops anywhere in that range — this constant
# does not sit at a measured cliff edge, there wasn't a clean one to find.
# Kept well above 50ms anyway because production logs show occasional
# single-bulb stragglers even at the old pacing (real zigbee mesh
# unreliability, not proven to correlate with pace specifically) — pacing is
# defense in depth, `repair_stragglers()` below is what actually recovers a
# straggler regardless of why one occurs.
AMBIENT_WRITE_STAGGER_MS = 300   # gap between successive light PUTs in one
                                 # hold pass — paces the burst from the
                                 # start rather than only recovering after
AMBIENT_CONFIRM_SETTLE_MS = 300  # extra wait after a write round's own
                                 # bridge-side ramp before reading state back
AMBIENT_HOLD_ATTEMPTS = 3        # 1 initial write + up to 2 spaced retries
AMBIENT_RETRY_SPACING_MS = 1200
_XY_TOLERANCE = 0.01
_BRIGHTNESS_TOLERANCE_PCT = 3.0

# ── cancellation: what makes an interrupted transition SNAP ────────────────
#
# The 2026-08-30 rework (his words: "let's also give spectra a clear ability
# to handle what happens if the turn on or off sequence gets interrupted.
# Interrupting should snap the state"). Measured live before the rework: a
# turn-OFF takes 22.6s end to end (AMBIENT_TRANSITION_MS dim +
# AMBIENT_CATCHUP_MS catch-up, plus 300ms-staggered confirmed writes) and a
# turn-ON ~15s across his 17 bulbs. A press mid-transition QUEUED behind
# `_lock` below and took 38s to win, because nothing could interrupt the
# sequence already inside it.
#
# Two halves, both here rather than one layer up, because only this module
# knows where a write boundary actually is:
#   - CancelToken: cooperative, checked ONLY between whole-light writes and
#     during the ramp sleeps, never mid-PUT to one bulb. A cancelled
#     sequence raises AmbientCancelled out of reconcile(), which releases
#     `_lock` on its way out so the newer intent acquires it within one
#     write slot instead of one whole sequence.
#   - snap=True: the newer intent's own run drops every RAMP — the ON hold
#     writes with no `dynamics` duration, the OFF release skips both the dim
#     fade and the catch-up ramp entirely and goes straight to unfreezing.
#     The 300ms write STAGGER stays: that is zigbee physics, not
#     choreography, and dropping it is how bulbs silently miss a write
#     (module docstring, "Read-back confirmation"). So a snapped turn-on is
#     bounded by bulb count (~5s at 17 bulbs), not by a fade nobody is
#     watching any more.
#
# ambient_music_gate.py owns WHEN to cancel (its generation counter and the
# single transition task); this module owns WHERE it is safe to.


class AmbientCancelled(Exception):
    """A newer ambient intent superseded this sequence at a write boundary.
    Deliberately NOT swallowed by the best-effort `except Exception` guards
    around individual device/light writes — every one of those re-raises it
    first, or a cancel would be silently absorbed and the old sequence would
    keep painting the room toward the state he just changed his mind
    about."""


class CancelToken:
    """One transition's cancel signal. `check()` at a write boundary and
    `sleep()` instead of `asyncio.sleep` inside a sequence, so a ramp can be
    abandoned the instant a newer intent arrives rather than being waited
    out."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise AmbientCancelled()

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            self.check()
            return
        try:
            await asyncio.wait_for(self._event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return
        raise AmbientCancelled()


def _check(token: Optional[CancelToken]) -> None:
    if token is not None:
        token.check()


async def _sleep(token: Optional[CancelToken], seconds: float) -> None:
    """Interruptible when a token is supplied, a plain sleep when not — so
    every pre-rework caller (and every test that never passes one) keeps
    exactly today's timing."""
    if token is not None:
        await token.sleep(seconds)
    elif seconds > 0:
        await asyncio.sleep(seconds)


def room_available() -> bool:
    """Can a press act on the room at all right now — i.e. is SPECTRA
    driving the live stack. False is the phase contract's "unavailable"
    (room released, or spot-effects owns): the intent is still stored and
    still applies on the next take-back, but nothing physical can move on
    this press. A room that IS ours but happens to have no live Hue device
    reads available here on purpose — a press genuinely acts, there is just
    nothing to drive, and reconcile()'s own "no-hue-devices" status plus
    the gate's `held`/`mode` keys already say so honestly."""
    from spectra.services.live_host import live

    return bool(live.active and live.host is not None)


_lock: Optional[asyncio.Lock] = None
# {(ip_address, entertainment_id): [(light resource id, friendly name), ...]}
_light_cache: dict[tuple[str, str], list[tuple[str, str]]] = {}


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


# ── colour math (Philips Wide-gamut D65 matrix — ported from
#    services/ambient_mode.py, unchanged) ────────────────────────────────────

def _gamma(c: float) -> float:
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def _hex_to_xy(hex_color: str) -> tuple[float, float]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
    except (ValueError, IndexError):
        return 0.3127, 0.3290  # fall back to D65 white
    r, g, b = _gamma(r), _gamma(g), _gamma(b)
    X = r * 0.664511 + g * 0.154324 + b * 0.162028
    Y = r * 0.283881 + g * 0.668433 + b * 0.047685
    Z = r * 0.000088 + g * 0.072310 + b * 0.986039
    total = X + Y + Z
    if total == 0:
        return 0.3127, 0.3290
    return X / total, Y / total


def _hsv_value_pct(hex_color: str) -> int:
    """HSV Value — the max RGB channel, scaled 1..100% — the Admiral's own
    choice (2026-08-16 ruling, fixing 'Ambient throws away the brightness
    of the colour he picks') for deriving Ambient's brightness from
    whichever colour is in effect: "I want the brightness of the color
    that I choose for both ambient modes to be applied to the lights."

    Chosen over relative luminance and CIE L* after comparing all three on
    his own colours: `_hex_to_xy` above already hands the bridge a hue's
    full chromaticity (saturation AND lightness, via the Wide-gamut D65
    matrix), so a brightness measure that ALSO discounts for a hue's
    intrinsic dimness double-counts it — relative luminance computes a
    saturated #0000ff at ~7%, so authoring a vivid blue would leave the
    bulb effectively off, exactly the "fights the picker" failure this fix
    exists to prevent. HSV Value keeps pure white and any fully-saturated
    colour at 100% (a colour picked at full intensity reads as authored at
    full intensity) and only drops as the colour is genuinely lightened or
    darkened — his cream (#f5da8c) lands at 96% (an imperceptible ~4%
    dimmer than today's hard-coded 100, not the ~29% drop relative
    luminance would have made to his everyday resting ambient, which he
    never asked for and would notice), his darker cream (#8b7e53) at 55%.

    Same formula `_live_look` below already uses for its own brightness
    proxy off the live rendered frame (max(r,g,b)/255) — one measure, not
    two independent reimplementations. Legacy (services/ambient_mode.py)
    never derived brightness from colour at all — settings.ambient_brightness
    was a wholly separate, independently-authored slider — so this
    derivation is a SPECTRA-specific behaviour the Admiral asked for on
    this fix, not a legacy port; see room_controls.py's
    ambient_brightness_note docstring entry for the full history. Invalid
    hex falls back to 100 — matching `_hex_to_xy`'s own D65-white fallback
    (full brightness), not a guessed dim value for malformed input."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
    except (ValueError, IndexError):
        return 100
    return max(1, min(100, round(max(r, g, b) / 255 * 100)))


def _light_payload(color_hex: str, ramp_ms: Optional[int] = None,
                   brightness_pct: Optional[int] = None) -> dict:
    """Brightness defaults to the HSV Value derived from `color_hex` itself
    (`_hsv_value_pct`) — see that function's docstring for why. An explicit
    `brightness_pct` is still accepted for the one caller that derives
    brightness from a DIFFERENT source: the release catch-up ramp, which
    targets the live rendered frame's own colour AND brightness together
    (`_live_look`), not an authored ambient hex."""
    if brightness_pct is None:
        brightness_pct = _hsv_value_pct(color_hex)
    x, y = _hex_to_xy(color_hex)
    body: dict = {
        "on": {"on": True},
        "dimming": {"brightness": float(max(1, min(100, brightness_pct)))},
        "color": {"xy": {"x": round(x, 4), "y": round(y, 4)}},
    }
    if ramp_ms and ramp_ms > 0:
        body["dynamics"] = {"duration": int(ramp_ms)}
    return body


def _fade_dim_payload(brightness_pct: int, ramp_ms: int) -> dict:
    """Brightness-only fade (no colour target — see module docstring on why
    disable has no 'wake colour' to fade toward)."""
    return {
        "on": {"on": True},
        "dimming": {"brightness": float(max(1, min(100, brightness_pct)))},
        "dynamics": {"duration": int(ramp_ms)},
    }


# ── bridge REST, direct to the bridge (not through LedFX) ──────────────────

_REST_TIMEOUT = httpx.Timeout(connect=3.0, read=4.0, write=4.0, pool=1.0)


def _bridge_client(cfg: dict) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"https://{cfg['ip_address']}",
        headers={"hue-application-key": cfg["username"]},
        verify=False,  # the bridge uses a self-signed cert
        timeout=_REST_TIMEOUT,
    )


async def _hue_get(client: httpx.AsyncClient, endpoint: str) -> dict:
    resp = await client.get(endpoint)
    resp.raise_for_status()
    return resp.json()


async def _hue_put(client: httpx.AsyncClient, endpoint: str, body: dict) -> None:
    resp = await client.put(endpoint, json=body)
    resp.raise_for_status()


async def _resolve_lights_named(client: httpx.AsyncClient, cfg: dict) -> list[tuple[str, str]]:
    """Map the device's entertainment stream to individual Hue `light`
    resource ids AND their bridge-configured friendly names (his own light
    names — "Kitchen Infuse", "Dining Hue SE" — the ones a partial hold
    needs to name back to him), so ambient can PUT/confirm each one
    directly over REST — cached per bridge, same as legacy (topology is
    stable). A light with no metadata.name (shouldn't happen on a real
    bridge) falls back to its resource id rather than dropping it."""
    cache_key = (cfg["ip_address"], cfg["entertainment_id"])
    if cache_key in _light_cache:
        return _light_cache[cache_key]
    try:
        ent = (await _hue_get(client, "/clip/v2/resource/entertainment"))["data"]
        ent_owner = {e["id"]: e["owner"]["rid"] for e in ent}
        lights = (await _hue_get(client, "/clip/v2/resource/light"))["data"]
        dev_light = {l["owner"]["rid"]: l["id"] for l in lights}
        light_name = {l["id"]: (l.get("metadata") or {}).get("name") or l["id"]
                     for l in lights}
        ec = (await _hue_get(
            client, f"/clip/v2/resource/entertainment_configuration/{cfg['entertainment_id']}",
        ))["data"][0]
        rids: list[tuple[str, str]] = []
        seen: set[str] = set()
        for channel in ec.get("channels", []):
            for member in channel.get("members", []):
                svc = member.get("service", {})
                if svc.get("rtype") == "entertainment":
                    lr = dev_light.get(ent_owner.get(svc.get("rid")))
                    if lr and lr not in seen:
                        seen.add(lr)
                        rids.append((lr, light_name.get(lr, lr)))
                    break
    except Exception:
        logger.exception("Ambient: failed to resolve Hue lights for %s",
                         cfg.get("ip_address"))
        return []
    _light_cache[cache_key] = rids
    return rids


async def _resolve_lights(client: httpx.AsyncClient, cfg: dict) -> list[str]:
    """Light resource ids only — the OFF/fade/catch-up path doesn't need
    names, it never reports a per-light outcome."""
    return [rid for rid, _name in await _resolve_lights_named(client, cfg)]


def _color_matches(state: dict, target_xy: tuple[float, float]) -> bool:
    """Is this light ON and showing the ambient HUE — the visually
    meaningful definition of "holding the ambient colour", used for
    status REPORTING (verify_held), deliberately looser than
    _state_matches below. Brightness is left out on purpose: a bulb he's
    dimmed via a wall switch or the Hue app is still legitimately showing
    ambient's colour, just at his own chosen intensity — the same "don't
    fight him for control" principle ambient_music_gate.py already applies
    to a bulb he turned fully off. Found live 2026-08-15/16: the verifier
    reported genuinely-on, genuinely-correct-hue bulbs as "unlit" solely
    because they read at a different brightness than the hold's own
    target — inventing a failure erodes trust in the honest reporting
    this project exists to provide."""
    if not (state.get("on") or {}).get("on"):
        return False
    xy = (state.get("color") or {}).get("xy") or {}
    x, y = xy.get("x"), xy.get("y")
    if x is None or y is None:
        return False
    return abs(x - target_xy[0]) <= _XY_TOLERANCE and abs(y - target_xy[1]) <= _XY_TOLERANCE


def _state_matches(state: dict, target_xy: tuple[float, float],
                   target_brightness_pct: float) -> bool:
    """Did THIS WRITE land — on, hue, AND the specific brightness we just
    asked for. Strict on purpose, unlike _color_matches above: confirming a
    write means confirming what we told the bulb to do, not merely that
    it's plausibly showing ambient's colour. Tolerances cover the bridge's
    own xy rounding/gamut clamping and brightness quantization, not a light
    still mid-ramp (the caller waits out the ramp before calling this)."""
    if not _color_matches(state, target_xy):
        return False
    brightness = (state.get("dimming") or {}).get("brightness")
    return brightness is not None and abs(brightness - target_brightness_pct) <= _BRIGHTNESS_TOLERANCE_PCT


async def _apply_hue(dev: Any, body: dict,
                     token: Optional[CancelToken] = None) -> int:
    """PUT `body` to every light this device's entertainment stream covers,
    over ONE connection to its bridge (a device can carry ten-plus lights —
    a fresh TLS handshake per light would make every toggle noticeably
    slow), PACED the same as _hold_and_confirm below (AMBIENT_WRITE_STAGGER_MS
    — see that constant's own comment and the module docstring's "Burst
    threshold measurement" for what 2026-08-16's live measurement actually
    found; this path — the OFF-fade and catch-up-ramp bursts — had NO
    pacing at all before this fix, same exposure as the ON path had before
    PR #69). Best-effort per light — one unreachable/rejecting bulb must not
    stop the rest, but a non-2xx response (raise_for_status) still doesn't
    count toward the returned total — a rejected write is not a write."""
    cfg = dev.config
    count = 0
    async with _bridge_client(cfg) as client:
        rids = await _resolve_lights(client, cfg)
        for i, rid in enumerate(rids):
            # BETWEEN lights, never mid-PUT — a cancel must not leave one
            # bulb half-written.
            _check(token)
            try:
                await _hue_put(client, f"/clip/v2/resource/light/{rid}", body)
                count += 1
            except Exception:
                logger.exception("Ambient: failed to set light %s on %s",
                                 rid, cfg.get("ip_address"))
            if i < len(rids) - 1:
                await _sleep(token, AMBIENT_WRITE_STAGGER_MS / 1000)
    return count


async def _write_and_confirm(client: httpx.AsyncClient, cfg: dict,
                             pending: list[tuple[str, str]], body: dict,
                             target_xy: tuple[float, float],
                             target_brightness_pct: float,
                             token: Optional[CancelToken] = None) -> tuple[list[str], list[str]]:
    """The shared paced-write-then-read-back-confirm engine behind both the
    initial hold (_hold_and_confirm, every light in the entertainment set)
    and the standalone straggler repair (repair_stragglers, just the
    lights verify_held() named as off-target). PUTs `body` to every
    (rid, name) in `pending` over the given already-open connection, THEN
    READS EACH ONE BACK — a 2xx PUT only proves the bridge accepted the
    write, not that the bulb (over zigbee, which silently drops commands
    under sustained load with NO error, no 4xx, no rate-limit header —
    module docstring) carries it. Retries stragglers, spaced apart rather
    than hammered. Retries drop the bridge-side ramp (`dynamics`) — a
    stubborn light should snap, not take another AMBIENT_TRANSITION_MS to
    maybe land.

    settle_ms below keys off whether THIS write_body actually carries a
    `dynamics` ramp, not off the attempt index (2026-08-16, extending
    AMBIENT_TRANSITION_MS to 3000ms surfaced why the two aren't the same
    thing): a retry's snap write never has one, so it already only ever
    waits AMBIENT_CONFIRM_SETTLE_MS — unaffected by AMBIENT_TRANSITION_MS
    either way. But repair_stragglers() below calls in with a `body` that
    has NO ramp at all (`_light_payload(color_hex)`, no ramp_ms — "a
    stubborn light should snap" applies to the FIRST repair write too, not
    just its retries) — under the old `attempt == 0` test, repair's own
    attempt 0 was waiting the full AMBIENT_TRANSITION_MS before reading
    back an instant write for no reason, and that wasted wait would have
    doubled right along with the constant. Keying off the body itself gets
    every caller the wait it actually needs: the ON-hold's ramped attempt 0
    still waits out the real glide, repair's un-ramped attempt 0 no longer
    waits for a glide that was never sent.
    Returns (confirmed light names, still-unconfirmed light names) —
    best-effort per light, but the unconfirmed half must reach the caller,
    never get folded into a bigger "N set" count."""
    snap_body = {k: v for k, v in body.items() if k != "dynamics"}
    confirmed: dict[str, str] = {}
    for attempt in range(AMBIENT_HOLD_ATTEMPTS):
        write_body = body if attempt == 0 else snap_body
        for i, (rid, name) in enumerate(pending):
            _check(token)   # between lights only — never mid-PUT
            try:
                await _hue_put(client, f"/clip/v2/resource/light/{rid}", write_body)
            except Exception:
                logger.exception("Ambient: failed to write %s (%s) on %s",
                                 name, rid, cfg.get("ip_address"))
            if i < len(pending) - 1:
                await _sleep(token, AMBIENT_WRITE_STAGGER_MS / 1000)
        settle_ms = (AMBIENT_TRANSITION_MS if "dynamics" in write_body else 0) + AMBIENT_CONFIRM_SETTLE_MS
        await _sleep(token, settle_ms / 1000)
        still_pending: list[tuple[str, str]] = []
        for rid, name in pending:
            try:
                state = (await _hue_get(
                    client, f"/clip/v2/resource/light/{rid}"))["data"][0]
            except Exception:
                logger.exception("Ambient: could not read back %s (%s) on %s",
                                 name, rid, cfg.get("ip_address"))
                still_pending.append((rid, name))
                continue
            if _state_matches(state, target_xy, target_brightness_pct):
                confirmed[rid] = name
            else:
                still_pending.append((rid, name))
        pending = still_pending
        if not pending:
            break
        if attempt < AMBIENT_HOLD_ATTEMPTS - 1:
            logger.warning(
                "Ambient: %d light(s) not yet confirmed at the ambient "
                "colour, retrying: %s", len(pending), [n for _, n in pending])
            await _sleep(token, AMBIENT_RETRY_SPACING_MS / 1000)
    return sorted(confirmed.values()), sorted(name for _, name in pending)


async def _hold_and_confirm(dev: Any, body: dict, target_xy: tuple[float, float],
                            target_brightness_pct: float,
                            token: Optional[CancelToken] = None) -> tuple[list[str], list[str]]:
    """Resolve every light this device's entertainment stream covers, then
    run them through _write_and_confirm. See that function for the actual
    write/confirm/retry mechanics."""
    cfg = dev.config
    async with _bridge_client(cfg) as client:
        pending = await _resolve_lights_named(client, cfg)
        if not pending:
            return [], []
        return await _write_and_confirm(client, cfg, pending, body, target_xy,
                                        target_brightness_pct, token)


async def repair_stragglers(names: list[str], color: Optional[str]) -> dict:
    """Actively re-assert the ambient colour on named stragglers
    verify_held() found off-target — the write half the periodic verifier
    (spectra/services/ambient_music_gate.py's verify_now()) was missing:
    it could DETECT a straggler on every tick and never once fix it (found
    live 2026-08-15/16 — two bulbs sat wrong for hours through repeated
    verify cycles; a direct bridge write fixed both instantly). Paced and
    read-back confirmed through the SAME engine (_write_and_confirm) as the
    initial hold — no second, looser notion of "did it land".

    NEVER touches a light that reads OFF right now, checked fresh
    immediately before writing — a bulb he turned off himself must stay
    off (ambient_music_gate.py's own "never fight him for control" rule);
    only an ON-but-wrong-colour straggler (the burst-drop/drift shape this
    exists to fix) gets rewritten. Best-effort per bridge — one
    unreachable bridge must not stop repair on the other. Returns
    {"repaired": [...], "left_off": [...], "unconfirmed": [...]} — every
    name from `names` lands in exactly one of the three."""
    from spectra.services.live_host import live

    empty = {"repaired": [], "left_off": [], "unconfirmed": []}
    if not names or not live.active or live.host is None:
        return empty
    hue_devices = _hue_devices(live.host)
    if not hue_devices:
        return empty

    async with _get_lock():
        return await _repair_stragglers_impl(hue_devices, set(names), color)


async def _repair_stragglers_impl(hue_devices: dict[str, Any], wanted: set[str],
                                  color: Optional[str]) -> dict:
    color_hex = color or "#ffffff"
    target_xy = _hex_to_xy(color_hex)
    brightness_pct = _hsv_value_pct(color_hex)
    # no ramp_ms — a stubborn light should snap
    body = _light_payload(color_hex, brightness_pct=brightness_pct)
    repaired: list[str] = []
    left_off: list[str] = []
    unconfirmed: list[str] = []

    for did, dev in sorted(hue_devices.items()):
        cfg = dev.config
        try:
            async with _bridge_client(cfg) as client:
                named = [(rid, name) for rid, name in
                        await _resolve_lights_named(client, cfg) if name in wanted]
                if not named:
                    continue
                on_now: list[tuple[str, str]] = []
                for rid, name in named:
                    try:
                        state = (await _hue_get(
                            client, f"/clip/v2/resource/light/{rid}"))["data"][0]
                    except Exception:
                        logger.exception(
                            "Ambient repair: could not read %s (%s) on %s",
                            name, rid, cfg.get("ip_address"))
                        unconfirmed.append(name)
                        continue
                    if (state.get("on") or {}).get("on"):
                        on_now.append((rid, name))
                    else:
                        left_off.append(name)
                if not on_now:
                    continue
                confirmed_names, straggler_names = await _write_and_confirm(
                    client, cfg, on_now, body, target_xy, brightness_pct)
                repaired.extend(confirmed_names)
                unconfirmed.extend(straggler_names)
        except Exception:
            logger.exception("Ambient repair: failed to reach %s", did)

    if repaired:
        logger.warning(
            "Ambient repair: re-asserted the ambient colour on %d straggler(s): %s",
            len(repaired), sorted(repaired))
    if unconfirmed:
        logger.error(
            "Ambient repair: %d straggler(s) still not confirmed after repair: %s",
            len(unconfirmed), sorted(unconfirmed))
    if left_off:
        logger.info(
            "Ambient repair: leaving %d straggler(s) alone — off, not ambient's "
            "to relight: %s", len(left_off), sorted(left_off))
    return {"repaired": sorted(repaired), "left_off": sorted(left_off),
            "unconfirmed": sorted(unconfirmed)}


async def verify_held(color: Optional[str],
                      group_ids: Optional[frozenset[str]] = None) -> dict:
    """Read-only recheck of whatever this module is CURRENTLY claiming to
    hold — never a PUT, ever (module docstring, "status-honesty fix").
    Reuses `_resolve_lights_named`'s cache and `_color_matches` (on+hue
    only, deliberately NOT the stricter write-confirmation check — module
    docstring on why brightness doesn't gate "is the room lit"), so a bulb
    he's dimmed out of band still reads as holding the ambient colour.
    Same no-live-stack/no-Hue-devices no-ops as reconcile() — there's
    nothing to verify either way, and the caller (services/
    ambient_music_gate.py) treats those the same as "not actually held"
    rather than as an error.

    `group_ids` (module docstring, "Hue entertainment-area selection")
    scopes the check to the SAME resolved target reconcile() last held —
    an out-of-scope device's bulbs are never read back here, so they can
    never be misreported as an ambient straggler."""
    from spectra.services.live_host import live

    if not live.active or live.host is None:
        return {"status": "dark"}
    all_hue_devices = _hue_devices(live.host)
    if not all_hue_devices:
        return {"status": "no-hue-devices"}
    target_ids = _resolve_group_ids(set(all_hue_devices), group_ids)
    hue_devices = {did: dev for did, dev in all_hue_devices.items() if did in target_ids}
    if not hue_devices:
        return {"status": "no-hue-devices"}

    color_hex = color or "#ffffff"
    target_xy = _hex_to_xy(color_hex)
    lit: list[str] = []
    unlit: list[str] = []
    for did, dev in sorted(hue_devices.items()):
        cfg = dev.config
        try:
            async with _bridge_client(cfg) as client:
                for rid, name in await _resolve_lights_named(client, cfg):
                    try:
                        state = (await _hue_get(
                            client, f"/clip/v2/resource/light/{rid}"))["data"][0]
                    except Exception:
                        logger.exception(
                            "Ambient verify: could not read %s (%s) on %s",
                            name, rid, cfg.get("ip_address"))
                        unlit.append(name)
                        continue
                    if _color_matches(state, target_xy):
                        lit.append(name)
                    else:
                        unlit.append(name)
        except Exception:
            logger.exception("Ambient verify: could not reach the bridge for %s", did)

    total = len(lit) + len(unlit)
    if total == 0:
        return {"status": "no-hue-devices"}
    return {"status": "verified", "lights_lit": len(lit), "lights_total": total,
            "unlit": sorted(unlit)}


# ── device discovery ─────────────────────────────────────────────────────────

def _hue_devices(host: Any) -> dict[str, Any]:
    return {did: host.devices.get(did) for did in host.devices
            if getattr(host.devices.get(did), "type", None) == "hue"}


async def list_groups() -> list[dict]:
    """[{id, name}] for every live Hue entertainment area SPECTRA currently
    drives — the group picker's data source (module docstring, "Hue
    entertainment-area selection"), the direct analogue of legacy's
    services/ambient_mode.resolve_groups(). No cache (unlike legacy, which
    round-tripped an HTTP call to LedFX) — reading live_host.live.host.devices
    is a free in-process dict lookup, not worth caching. Empty when SPECTRA
    doesn't currently own the live stack or the room has no live Hue device
    — a UI picker with nothing to show, not an error."""
    from spectra.services.live_host import live

    if not live.active or live.host is None:
        return []
    return [{"id": did, "name": getattr(dev, "name", None) or did}
            for did, dev in sorted(_hue_devices(live.host).items())]


def _resolve_group_ids(available: set[str], group_ids: Optional[frozenset[str]]) -> set[str]:
    """None/empty `group_ids` = every live Hue device — preserves today's
    default (module docstring). A non-empty selection is intersected
    against `available`; any id that doesn't resolve (a group renamed or
    removed since it was last saved) is dropped and logged rather than
    treated as "select nothing" — mirrors legacy's own
    `want & set(hue_cfgs)` (services/ambient_mode._set_groups_impl)."""
    if not group_ids:
        return set(available)
    unknown = group_ids - available
    if unknown:
        logger.warning(
            "Ambient: ignoring unknown Hue group id(s) %s (known: %s)",
            sorted(unknown), sorted(available))
    return set(group_ids) & available


def _live_look(dev: Any) -> Optional[tuple[str, int]]:
    """Best-effort (hex colour, brightness %) snapshot of what this
    device's driving virtual is CURRENTLY rendering, for the release
    catch-up ramp (see module docstring). assemble_frame() is the exact
    per-flush frame HueDevice.flush() receives and drops while frozen
    (fx/devices/hue.py) — the render loop never stopped computing it, so
    this is a live read, not a stale capture. Mean RGB across the frame
    gives both a representative hue (for the bridge's xy chromaticity) and
    a brightness proxy (the max channel, standard HSV "value"). None when
    there's nothing to read (device not yet activated, or the read itself
    failed) — the caller skips the catch-up ramp for that device rather
    than aiming it at a fabricated colour."""
    try:
        frame = dev.assemble_frame()
    except Exception:
        logger.exception("Ambient catch-up: could not read the live frame for %s",
                         getattr(dev, "name", dev))
        return None
    if frame is None or len(frame) == 0:
        return None
    n = len(frame)
    r = sum(px[0] for px in frame) / n
    g = sum(px[1] for px in frame) / n
    b = sum(px[2] for px in frame) / n
    brightness_pct = max(1, min(100, round(max(r, g, b) / 255 * 100)))
    color_hex = "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, round(r))), max(0, min(255, round(g))), max(0, min(255, round(b))))
    return color_hex, brightness_pct


# ── public entry point ──────────────────────────────────────────────────────

async def reconcile(enabled: bool, color: Optional[str],
                    group_ids: Optional[frozenset[str]] = None,
                    token: Optional[CancelToken] = None,
                    snap: bool = False) -> dict:
    """Drive the room's live Hue devices toward `enabled` (held at `color`,
    default white, at the brightness `_hsv_value_pct(color)` derives from
    that same hex — see that function's docstring for why brightness is
    DERIVED, not a separate knob) or released. Locked so rapid toggles
    can't overlap and fight each other over a device's stream state.
    No-ops (status "dark") when SPECTRA doesn't currently own the live
    stack — the room-control save must never fail just because there's
    nothing to drive right now.

    `group_ids` (module docstring, "Hue entertainment-area selection") is
    the resolved `RoomControlState.ambient_hue_group_ids` — `None`/empty
    means every live Hue device, preserving today's behaviour exactly.
    When `enabled` and a non-empty selection excludes a device that's
    currently frozen (he deselected a group while Ambient stays engaged),
    that device is released in the SAME call — see `_release_devices`.

    `token`/`snap` are the 2026-08-30 interruption mechanics (see the
    "cancellation" block above): a supplied token lets a newer intent
    abandon this sequence at its next write boundary (raising
    AmbientCancelled, which releases the lock on the way out so the newer
    intent waits one write slot, not one whole sequence), and `snap` drops
    every RAMP — no colour glide on the hold, no dim fade and no catch-up
    on the release — so the newer end state lands as fast as the staggered
    confirmed writes allow. Neither is used by the automatic paths; both
    are set by ambient_music_gate when a transition supersedes another."""
    async with _get_lock():
        return await _reconcile_impl(enabled, color, group_ids, token, snap)


async def _release_devices(devices: dict[str, Any],
                           token: Optional[CancelToken] = None,
                           snap: bool = False) -> list[str]:
    """The OFF sequence — bridge-side fade, ease toward each device's live
    look, then unfreeze (module docstring's release two-phase ramp) —
    shared by the whole-room OFF path and the group-shrink-while-still-on
    path in `_reconcile_impl` below. `devices` is exactly the set to
    release; deciding WHICH devices belong in it is the caller's job (see
    that function). Best-effort per device. Returns the device ids that
    confirmed `set_frozen(False)`."""
    if not devices:
        return []
    caught_up = False
    if snap:
        # A SNAPPED release skips BOTH ramps outright — this is the "if is
        # gradually turning ambient off, and I turn it back on, it should
        # just snap" case seen from the other side: he changed his mind, so
        # the ~11s of choreography he is no longer watching is exactly what
        # must not be waited out. Nothing is written to the bulbs at all;
        # unfreezing hands each device straight back to the live stream,
        # which is already rendering the room's real scene (fx/devices/
        # hue.py — a frozen device's virtual never stopped).
        logger.info("Ambient: snapping the release (interrupted) — no fade, "
                    "no catch-up, straight back to the stream")
    else:
        fade = _fade_dim_payload(AMBIENT_OFF_FADE_PCT, AMBIENT_TRANSITION_MS)
        for did, dev in sorted(devices.items()):
            try:
                await _apply_hue(dev, fade, token)
            except AmbientCancelled:
                raise
            except Exception:
                logger.exception("Ambient: off-fade failed for %s", did)
        await _sleep(token, AMBIENT_TRANSITION_MS / 1000)

        # Catch-up: ease the still-frozen bulbs toward whatever the room's
        # live effect is actually showing right now, over the SAME
        # bridge-side ramp phase 1 used — before handing back to the
        # stream, not after (module docstring). Best-effort per device; a
        # device with nothing to read (not yet activated) just releases
        # straight from the phase-1 fade.
        for did, dev in sorted(devices.items()):
            look = _live_look(dev)
            if look is None:
                continue
            color_hex, brightness_pct = look
            try:
                await _apply_hue(dev, _light_payload(
                    color_hex, AMBIENT_CATCHUP_MS, brightness_pct=brightness_pct), token)
                caught_up = True
            except AmbientCancelled:
                raise
            except Exception:
                logger.exception("Ambient: catch-up ramp failed for %s", did)
        if caught_up:
            await _sleep(token, AMBIENT_CATCHUP_MS / 1000)

    # Deliberately NOT cancellable: once the ramps are done (or skipped),
    # unfreezing must finish. Abandoning here would leave a device frozen
    # with nothing holding it — the one state neither intent describes.
    released: list[str] = []
    for did, dev in sorted(devices.items()):
        try:
            await dev.set_frozen(False)  # re-engages the stream; the room's
                                          # live scene resumes on its own
            released.append(did)
        except Exception:
            logger.exception("Ambient: failed to release %s", did)
    logger.info("Ambient release: %s released (caught up: %s)", released, caught_up)
    return released


async def _reconcile_impl(enabled: bool, color: Optional[str],
                          group_ids: Optional[frozenset[str]],
                          token: Optional[CancelToken] = None,
                          snap: bool = False) -> dict:
    from spectra.services.live_host import live

    if not live.active or live.host is None:
        logger.warning("Ambient: SPECTRA does not own the live stack — "
                       "state saved, no lights touched")
        return {"status": "dark"}

    hue_devices = _hue_devices(live.host)
    if not hue_devices:
        logger.warning("Ambient: no live Hue devices in the room")
        return {"status": "no-hue-devices"}

    if enabled:
        target_ids = _resolve_group_ids(set(hue_devices), group_ids)
        hold_devices = {did: hue_devices[did] for did in target_ids}
        # A group he just deselected while Ambient stays engaged: release
        # it here too — but ONLY if it's actually frozen. An out-of-scope
        # device ambient never touched must stay untouched (module
        # docstring — set_frozen(False) on an unfrozen device forces a real
        # stream reconnect it never needed).
        shrink_devices = {did: dev for did, dev in hue_devices.items()
                          if did not in target_ids and getattr(dev, "frozen", False)}
    else:
        # Whole-room OFF: unconditional, every live Hue device — unchanged
        # from before group selection existed, regardless of the current
        # ambient_hue_group_ids selection (turning Ambient off releases
        # everyone, not just the currently-selected groups).
        hold_devices = {}
        shrink_devices = dict(hue_devices)

    released = await _release_devices(shrink_devices, token, snap)

    if not hold_devices:
        if enabled:
            # A non-empty selection resolved to nothing known (every
            # selected id is stale) — the same "nothing to hold" shape as
            # no live Hue devices at all, logged so it's traceable.
            logger.warning("Ambient: no known Hue group selected — nothing held")
            result: dict = {"status": "no-hue-devices"}
            if released:
                result["released"] = released
            return result
        if released:
            return {"status": "off", "devices": released}
        logger.error("Ambient: OFF requested but every Hue device failed to "
                     "release — the room may still be held on the ambient colour")
        return {"status": "failed", "devices": []}

    color_hex = color or "#ffffff"
    brightness_pct = _hsv_value_pct(color_hex)
    # snap: no `dynamics` ramp at all — the write lands the end state on the
    # bulb as fast as it can be confirmed. _write_and_confirm already keys
    # its settle wait off whether the body carries a ramp, so a snapped hold
    # also stops waiting out a glide that was never sent.
    body = _light_payload(color_hex, None if snap else AMBIENT_TRANSITION_MS,
                          brightness_pct=brightness_pct)
    target_xy = _hex_to_xy(color_hex)
    touched: list[str] = []
    held: list[str] = []
    unconfirmed: list[str] = []
    for did, dev in sorted(hold_devices.items()):
        try:
            await dev.set_frozen(True)   # must land before the REST write
            confirmed_names, straggler_names = await _hold_and_confirm(
                dev, body, target_xy, brightness_pct, token)
            held.extend(confirmed_names)
            unconfirmed.extend(straggler_names)
            touched.append(did)
        except AmbientCancelled:
            raise
        except Exception:
            logger.exception("Ambient: failed to hold %s at the ambient colour", did)
    if not touched:
        # Every targeted Hue device failed — the switch must NOT report
        # success with nothing held (the exact failure shape this feature
        # exists to stop reporting: a control that says "on" while the
        # room didn't change).
        logger.error("Ambient: ON requested but every Hue device failed "
                     "— the room is NOT held")
        result = {"status": "failed", "devices": [], "lights_set": 0}
        if released:
            result["released"] = released
        return result
    lights_set = len(held)
    lights_total = lights_set + len(unconfirmed)
    if unconfirmed:
        # This is the log line the live defect made lie: it must not be
        # able to say more lights were set than were actually confirmed.
        logger.error(
            "Ambient ON: %s held at %s @ %d%%, %d/%d light(s) confirmed — "
            "still NOT holding it: %s", touched, color_hex, brightness_pct,
            lights_set, lights_total, unconfirmed)
        result = {"status": "partial", "devices": touched, "lights_set": lights_set,
                "lights_total": lights_total, "unconfirmed": unconfirmed}
    else:
        logger.info("Ambient ON: %s held at %s @ %d%%, %d light(s) confirmed",
                    touched, color_hex, brightness_pct, lights_set)
        result = {"status": "on", "devices": touched, "lights_set": lights_set,
                "lights_total": lights_total}
    if released:
        result["released"] = released
    return result
