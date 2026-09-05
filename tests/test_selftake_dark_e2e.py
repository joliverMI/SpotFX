"""THE SELF-TAKING NIGHT, END TO END, MEASURED AT THE EMITTED LIGHT.

WHAT WAS ALREADY PROVEN, AND WHAT WAS NOT. Two halves of this seam pass
today and neither is this file: `tests/test_quiet_take_dark.py` measures a
QUIET CONFIG LOAD and shows it flushes zeros where the ordinary one flushes
white; `tests/test_night_self_take.py` and
`tests/test_night_take_crash_recovery.py` measure the FLOW — the arming
lever, the released-only gate, the give-back ordering, the silence, the
crash — with every handover and release faked so no stack is ever built.
Between them sits the thing the 1am decision actually rests on: THE WHOLE
FLOW, ARMED, WITH A REAL RENDER PIPELINE UNDER IT.

So this file runs the real one. `night_run.start` applies its real gates,
`night_take.take_room` writes its real snapshot and calls the real
`handover.run_handover`, which brings up a real `SpectraSide(quiet=True)`
over a real `fx.headless` host whose devices are vendored dummies and whose
STORED EFFECTS ARE WHITE AT FULL BRIGHTNESS. Every frame that reaches a
device's transport is recorded and labelled with the phase it arrived in.
Then the night's queue runs, the room is given back through the real
`release.release_room`, and the record is read.

WHAT "DARK" IS ALLOWED TO MEAN HERE, stated before any number is quoted. A
capture run LIGHTS THINGS ON PURPOSE — a footprint is `lit - dark`, so a
lamp in the middle of a run is the measurement, not a defect. The claim this
file makes is therefore narrower and sharper than "no light ever": THE SHOW
NEVER COMES BACK. Every frame outside the run's own deliberate lamp window
carries zero, the engine's executor is the RecordingExecutor throughout, and
a write driven straight through the drift conductor's own executor — the
exact call a leg makes — reaches no fixture at all. The lamp window is
measured too, and it is REQUIRED to be non-black: a room that is dark
because nothing can write to it would be useless for the night it was taken
for, and it would also make every other assertion here pass for the wrong
reason.

RED-FIRST, THREE TIMES, IN THE SAME RIG. The ORDINARY (unquiet) path is run
through the identical driver and must go non-black: at the take, because the
stored effects restore, and at the engine drive, because `engine.go_live`
points the conductor at the facade. A restart while the room is OWNED must
light it; a restart while it is RELEASED must not. A proof that cannot fail
on the defect it was written for is decoration, so each dark result here has
a lit twin beside it produced by the same code path.

FRESH INTERPRETER PER OBSERVATION (subprocess), per
`tests/test_cold_load_effect_restore.py`'s precedent and
`test_quiet_take_dark.py`'s: config load order, what the first frame
carries, and whether a module-level singleton was ever pointed at a facade
are not things a warm pytest process can speak to honestly.

NOTHING HERE TOUCHES HIS ROOM, and the isolation is listed rather than
assumed:

  * `SPECTRA_STORAGE_DIR` is a throwaway directory, which moves the night
    stores, the take snapshot AND `config.FX_LIVE_CONFIG_DIR` with it;
  * `fx.light_ownership.OWNERSHIP_FILE` and
    `fx.device_model.CATEGORIES_FILE` are repointed by hand — both are fixed
    repo-relative paths that `SPECTRA_STORAGE_DIR` does NOT move;
  * every device is a vendored `dummy`, so no frame reaches a network;
  * the audio hub is not opened (`SpectraSide(open_audio=False)`), and
    `fx.headless.silence_audio()` runs first, so no host audio device is
    enumerated;
  * the two places `release.release_room` reaches OUTSIDE this process — the
    external LedFX virtuals list and `SpotEffectsSide.verify_quiesced`'s
    systemctl probe — are stubbed. Everything else about the release is the
    production function, including the Hue fade (a no-op with no Hue device)
    and the live-stack teardown.

WHAT IS SUBSTITUTED, AND WHAT THIS THEREFORE DOES NOT PROVE. Four things,
named rather than left to be discovered:

  * THE QUEUE ITEM IS REPRESENTATIVE, NOT A REAL MAP. No camera exists
    offline, and `capture_runs`' own gate refuses a calibration-grade run
    without a native capture session by design. What stands in for it is
    still production code driving production lights:
    `room_mapping.MappingProgram` — the same program a real map builds —
    over `flare_preview_hold.open_program_hold`, the same ONE hold, so the
    snapshot, the dark step, the emitter lamp and the revert are the real
    ones with the real constants. The CAMERA half is absent, and with it
    the exposure lock, the lever self-test and the contamination witness:
    those decide whether a measurement is trustworthy, never what the
    fixtures are told to do.
  * THE ENGINE'S OWN LOOPS ARE NOT TICKING. `engine.start()` opens a bridge
    WebSocket to his live spot-effects process and nothing offline may do
    that. What those loops WRITE is driven here by hand, through the very
    objects they write through (`engine.conductor.executor`,
    `engine.responses.executor`), which is the thing that decides whether a
    show reaches a fixture.
  * THE FIXTURES ARE VENDORED DUMMIES, so this measures what SPECTRA SENDS,
    not what a WLED or a Hue bulb then does with it. That is the right
    boundary for this question — the take's whole promise is about what
    leaves the render pipeline — but it is not a room proof and is not
    claimed as one.
  * `night_run.price_items` is replaced by one that fits. The 05:30 planned
    end is `tests/test_night_run.py`'s subject; re-deriving it here would
    be a second copy of a gate.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


# ── the room: two dummies whose stored effects are BRIGHT ──────────────────

def _device(did, pixels):
    return {"id": did, "type": "dummy",
            "config": {"name": did, "pixel_count": pixels}}


def _virtual(vid, device_id, pixels, effect):
    return {
        "id": vid, "is_device": device_id, "auto_generated": False,
        "config": {"name": vid, "mapping": "span", "rows": 1,
                   "transition_mode": "Add", "transition_time": 0.0},
        "segments": [[device_id, 0, pixels - 1, False, 0]], "active": True,
        "effect": effect, "effects": {effect["type"]: effect},
        "last_effect": effect["type"],
    }


BRIGHT = {"type": "singleColor",
          "config": {"color": "#ffffff", "brightness": 1.0,
                     "background_brightness": 1.0}}

VIRTUAL_IDS = ["tv-backlight", "sconce"]


def write_bright_fx_live(config_dir: Path) -> None:
    """The fx-live config the night's take will load. Its stored effects
    PAINT — that is what an ordinary take-back restores, and it is the light
    the quiet take must not make."""
    config_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "configuration_version": "2.3.6",
        "devices": [_device("tv-backlight", 60), _device("sconce", 30)],
        "virtuals": [_virtual("tv-backlight", "tv-backlight", 60, BRIGHT),
                     _virtual("sconce", "sconce", 30, BRIGHT)],
        "audio": {}, "scenes": {}, "user_presets": {},
    }
    (config_dir / "config.json").write_text(json.dumps(config))


# ── the driver ─────────────────────────────────────────────────────────────

_DRIVER = (Path(__file__).resolve().parent
           / "selftake_dark_e2e_driver.py").read_text()


def _observe(work: Path, mode: str) -> dict:
    """One observation in a fresh interpreter.

    `os._exit` in the driver, per AGENTS.md: fx's TemporalEffect spawns
    non-daemon threads a frame-stepped harness never joins, so a plain
    return reads as a hang rather than a failure."""
    write_bright_fx_live(work / "storage" / "fx-live")
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER, str(work), mode],
        cwd=REPO, capture_output=True, text=True, timeout=600)
    tail = (proc.stdout or "")[-4000:] + "\n--- stderr ---\n" + \
        (proc.stderr or "")[-4000:]
    assert proc.returncode == 0, tail
    line = next((ln for ln in proc.stdout.splitlines()
                 if ln.startswith("RESULT ")), None)
    assert line is not None, tail
    out = json.loads(line[len("RESULT "):])
    assert not out.get("driver_error"), out.get("driver_error")
    return out


def _nonblack(out: dict, *phases: str) -> int:
    return sum(int(out["by_phase"].get(p, {}).get("non_black", 0))
               for p in phases)


def _frames(out: dict, *phases: str) -> int:
    return sum(int(out["by_phase"].get(p, {}).get("frames", 0))
               for p in phases)


# The phases whose boundaries are UNAMBIGUOUS — nothing is legitimately lit
# on either side of them, so a non-black frame in one of these is a real
# light in his room. `queue_revert` is deliberately NOT here: the lamp is
# legitimately still lit while the revert write travels the pipeline, and
# that window is bounded by measurement instead (`lit_after_drain`) rather
# than by a label. See the driver's REVERT_DRAIN_S.
SHOW_PHASES = ("take", "queue_dark", "queue_engine_drive", "queue_done",
               "give_back", "after")
LAMP_PHASE = "queue_lamp"


@pytest.fixture(scope="module")
def quiet(tmp_path_factory):
    """THE THING BEING PROVEN: the armed, self-taking night, quiet."""
    return _observe(tmp_path_factory.mktemp("quiet"), "selftake")


@pytest.fixture(scope="module")
def ordinary(tmp_path_factory):
    """THE CONTROL: the same night down the ORDINARY (unquiet) side, which
    is what makes every dark number above evidence rather than decoration."""
    return _observe(tmp_path_factory.mktemp("ordinary"), "ordinary")


# ── 0. THE INSTRUMENT CAN SEE LIGHT — the control, first ───────────────────

def test_the_ordinary_night_lights_his_room_which_is_the_defect(ordinary):
    """RED-FIRST. Same driver, same config, same night — with the SPECTRA
    side built unquiet. The take restores the stored white effects and
    `engine.go_live` points the conductor at the facade, so both of the two
    independent light sources the quiet take closes are open here. If this
    ever comes back dark, every assertion in this file is passing for the
    wrong reason and this test is what says so."""
    assert ordinary["frames"] > 0, ("nothing reached a transport at all — "
                                    f"the rig is blind: {ordinary}")
    assert _nonblack(ordinary, "take") > 0, (
        "the ORDINARY take came up dark — the stored bright effects did not "
        f"restore, so this rig cannot see the take defect: {ordinary}")
    assert _nonblack(ordinary, "queue_engine_drive") > 0, (
        "a write driven through the drift conductor's OWN executor reached "
        "no fixture on the ordinary path either — this rig cannot see the "
        f"engine defect: {ordinary}")
    assert ordinary["lit_after_drain"] > 0, (
        "the run's hold reverted to BLACK on the ordinary path — it restores "
        "the snapshot it took, and on that path the snapshot is the stored "
        f"white show, so this rig cannot see the revert defect: {ordinary}")
    assert ordinary["executor_modes"]["during_queue"] == ["facade", "facade"], (
        f"the ordinary path did not go live: {ordinary['executor_modes']}")
    assert ordinary["blacked_out"] == [], (
        f"the ordinary take blacked virtuals out: {ordinary}")


# ── 1. THE TAKE COMES UP BLACK ─────────────────────────────────────────────

def test_the_armed_take_drives_the_fixtures_and_emits_nothing(quiet):
    """Step one of the composition. The room is RELEASED, the lever is
    armed, the start event arrives — and not one frame between the take and
    the run's first step carries any light.

    "Held black" and "never written to" are different states, so the frame
    COUNT is asserted too: a quiet take that drove nothing would satisfy
    "no light" and break the freshness the activation gate verifies
    against."""
    assert quiet["took_the_room"] is True, quiet
    assert quiet["owner_after_take"] == "spectra", quiet
    assert sorted(quiet["blacked_out"]) == sorted(VIRTUAL_IDS), (
        f"the take did not report blacking out both virtuals: {quiet}")
    assert _frames(quiet, "take") > 0, (
        f"the quiet take drove no frames at all: {quiet}")
    assert _nonblack(quiet, "take") == 0, (
        f"THE TAKE PUT LIGHT IN HIS ROOM: {quiet['first_lit']}")


# ── 2. IT STAYS DARK WHILE THE DECLARED QUEUE RUNS ─────────────────────────

def test_the_queue_runs_on_a_dark_room_and_the_show_never_returns(quiet):
    """Step two, and the half neither existing proof covers: the take is
    dark AND the calibration running on top of it stays dark.

    The engine drive is the load-bearing measurement. The drift conductor's
    own executor is handed the exact write a leg makes, at full white, to
    every virtual — and no frame moves, because a quiet activation never
    calls `engine.go_live`, so that executor is still the
    RecordingExecutor."""
    assert quiet["executor_modes"]["during_queue"] == \
        ["recording", "recording"], (
        "the engine went LIVE under a quiet take — the show can reach his "
        f"fixtures: {quiet['executor_modes']}")
    assert _frames(quiet, "queue_dark", "queue_engine_drive") > 0, quiet
    assert _nonblack(quiet, "queue_dark") == 0, quiet
    assert _nonblack(quiet, "queue_engine_drive") == 0, (
        "A SHOW WRITE REACHED A FIXTURE during the night's queue: "
        f"{quiet['first_lit']}")
    assert _nonblack(quiet, "queue_done") == 0, (
        f"the room did not go back to black after the lamp: {quiet}")


def test_the_run_s_hold_gives_back_exactly_what_it_found(quiet):
    """THE REVERT IS THE PART A SUBSTITUTED QUEUE WOULD HAVE MISSED, so the
    real one runs here: `room_mapping.MappingProgram` over
    `flare_preview_hold.open_program_hold`, which SNAPSHOTS the live bytes
    through `fx_seam.get_virtuals()` before its first write and restores
    them on close.

    That makes the quiet take's blackness load-bearing twice over: the
    snapshot the run takes is black, so what it hands back at the end of
    every emitter is black too. On the ordinary path the same close restores
    the stored white show — which is exactly what
    `test_the_ordinary_night_lights_his_room_which_is_the_defect` measures,
    41 of 44 frames non-black where this one has none."""
    assert "hold dark step: held=True" in quiet["notes"], (
        f"the real hold never engaged, so nothing here tested it: {quiet}")
    assert any("hold close" in n and "'reverted': True" in n
               for n in quiet["notes"]), (
        f"the real hold never reverted: {quiet['notes']}")
    assert quiet["lit_after_drain"] == 0, (
        "the hold's revert put the show back into his room mid-night: "
        f"{quiet['first_lit']}")


def test_the_run_can_still_write_the_room_which_is_the_second_control(quiet):
    """THE LAMP IS THE OTHER CONTROL. A capture run lights one emitter on
    purpose; a room that could not be written to would be dark for the worst
    possible reason and would make every other number here meaningless. So
    the run's own lamp — a real `fx_seam` write with `room_mapping`'s own
    effect type — MUST show up at the transport, and only on the virtual it
    named."""
    assert _nonblack(quiet, LAMP_PHASE) > 0, (
        "the run's own capture lamp never reached a fixture — the room was "
        f"dark because it was unwritable, not because it was held: {quiet}")
    lit = set(quiet["lamp_lit_devices"])
    assert lit == {quiet["lamp_virtual"]}, (
        f"the lamp lit more than the emitter it named: {lit}")


def test_the_only_light_all_night_is_the_run_s_own_lamp(quiet):
    """THE WHOLE-NIGHT CLAIM, in three numbers.

    ONE: outside the run's own lamp window there is not a single non-black
    frame in any phase whose boundary is unambiguous — the take, the dark
    step, the show being driven, the settle after the revert, the give-back,
    and everything after it.

    TWO: only the emitter the run NAMED was ever lit. A night that lit the
    whole room one fixture at a time would satisfy claim one.

    THREE: the room is black again within `REVERT_DRAIN_S` of the revert
    landing, and nothing is lit after that at all. This is measured rather
    than labelled because a render pipeline has latency — see the driver's
    REVERT_DRAIN_S for the race that taught it."""
    stray = _nonblack(quiet, *SHOW_PHASES)
    assert stray == 0, (
        f"{stray} non-black frame(s) outside the run's own lamp — "
        f"first at {quiet['first_lit']}")
    assert quiet["lit_devices"] == [quiet["lamp_virtual"]], (
        "something other than the emitter the run named was lit tonight: "
        f"{quiet['lit_devices']}")
    assert quiet["revert_landed"] is True, quiet
    assert quiet["lit_after_drain"] == 0, (
        f"{quiet['lit_after_drain']} frame(s) still lit more than "
        f"{quiet['revert_drain_ms']:.0f} ms after the run's revert landed: "
        f"{quiet['first_lit']}")
    assert (quiet["lit_after_revert_ms"] is None
            or quiet["lit_after_revert_ms"] <= quiet["revert_drain_ms"]), quiet


# ── 3. THE GIVE-BACK HANDS THE ROOM BACK ───────────────────────────────────

def test_the_night_gives_the_room_back_to_released_and_drives_nothing_after(
        quiet):
    """Step three. The state he left it in is `released`, and that is the
    state it is in afterwards — with the snapshot dropped, so no cold start
    believes a room is still held.

    ZERO FRAMES AFTER THE GIVE-BACK is the direct measurement of "handed
    back, not left held": the live stack is torn down, so nothing is being
    driven at all. A room still held would keep flushing."""
    assert quiet["night_state"] == "complete", quiet
    assert quiet["gave_back"] is True, quiet
    assert quiet["gave_back_to"] == "released", quiet
    assert quiet["owner_final"] == "released", quiet
    assert quiet["holding_after"] is False, (
        f"the take snapshot survived the give-back: {quiet}")
    assert quiet["live_active_after"] is False, quiet
    assert _nonblack(quiet, "give_back", "after") == 0, (
        f"the give-back left light in his room: {quiet['first_lit']}")
    assert _frames(quiet, "after") == 0, (
        "frames were still reaching a transport after the give-back — the "
        f"room is still being driven: {quiet}")


def test_the_announcement_carries_both_ends(quiet):
    """Order 22, on the record rather than as a sound: taken AND given back,
    both, on the night's own `take` block."""
    events = [a.get("event") for a in quiet["announce"]]
    assert events == ["taken", "given_back"], quiet["announce"]


# ── 4. A RESTART WHILE THE ROOM IS RELEASED IS INVISIBLE TO IT ─────────────

def test_a_restart_on_a_released_room_drives_nothing(tmp_path):
    """THE OPERATIONAL ASSESSMENT THE EVENING RESTART NEEDS. Arming the
    lever is a systemd `Environment=` edit and a restart, so the question is
    whether that restart is visible in his room while it is released.

    Measured, not argued: the four light-relevant startup steps of the real
    `spectra/app.py` lifespan are run against the released record and not
    one frame reaches a transport. (`engine.start()` and
    `device_preview.start()` are left out on purpose — they open a bridge
    WebSocket to his live spot-effects process, which no offline proof may
    do; what they would drive is the engine executor, and that is asserted
    to still be the RecordingExecutor.)"""
    out = _observe(tmp_path, "restart_released")

    assert out["owner_final"] == "released", out
    assert out["resumed"] is False, (
        f"a restart re-activated a RELEASED room: {out}")
    assert out["live_active_after"] is False, out
    assert out["executor_modes"]["after_restart"] == \
        ["recording", "recording"], out["executor_modes"]
    assert out["frames"] == 0, (
        "a restart on a released room drove frames at a fixture — the "
        f"evening restart is NOT invisible to his room: {out['first_lit']}")


def test_a_restart_on_an_owned_room_does_light_it_which_is_the_control(
        tmp_path):
    """RED-FIRST for the claim above. The same startup steps against a
    record that says SPECTRA owns bring the stack up and restore the stored
    white effects — so "zero frames" in the released case is a property of
    the released record, not of a driver that never got as far as starting
    anything."""
    out = _observe(tmp_path, "restart_owned")

    assert out["resumed"] is True, out
    assert out["frames"] > 0, out
    assert _nonblack(out, "restart") > 0, (
        "a restart on an OWNED room came up dark, so the released result "
        f"proves nothing: {out}")
