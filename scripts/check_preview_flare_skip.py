"""THE PREVIEW SHOWS FLARES AND TRANSITIONS — measured against the lights.

His report (2026-10-07, watching the device preview in a browser over
Tailscale): "flares and transitions don't work well in the preview, it seems
to jump past them."

THE CAUSE (fx/VENDOR.md deviation #56). The preview stream is sent from
SPECTRA's one event loop (spectra/services/preview_stream.py). Every effect
write through the in-process facade used to save the WHOLE fx config to disk
on that loop — and his live fx-live config.json is about a megabyte, so one
save cost ~25 ms plus an fsync. A flare is a burst of writes (a spike, a gain
and a colour write per virtual) and a scene change is a type switch per
virtual plus the colour moment that rides on it, so the loop stood still for
most of a second. The render threads kept painting the lights; the stream
could send nothing until the burst was over, and then sent the newest frame —
the flare was already gone, the crossfade mostly done. Effect writes now
persist coalesced (fx/facade.py), and that is the only change.

WHAT THIS RUNS, offline and on dummies only: a real fx render host in his
room's real topology (rig_common.build_room_config: the crystal through its
1,952 segments, the copy-mapped TV/sconce strip, the bulbs; his virtuals'
own 0.5 s "Add" crossfade), its stored config padded to the SIZE of his
(STORED_CONFIG_BYTES — the size only, nothing of his is read), the real
preview relay and stream hub, one viewer that acknowledges each tick after
an emulated Tailscale-relay round trip, and the real write paths: the
engine's FacadeExecutor for the flare, fx_seam.apply_writes for the scene
change. THE LIGHTS are the crystal device's own flushes, timed on its render
thread. THE PREVIEW is every crystal frame the viewer was sent, timed at
arrival (send + half the round trip), each shown until the next.

TWO MODES, AND THE FIRST IS THE RED CONTROL:
  inline     facade.PERSIST_QUIET_S = 0 — a save on every write, the code
             before the fix. It must FAIL the bar below, or this instrument
             cannot see the defect it exists for.
  coalesced  the shipped default. It must PASS.

THE BAR, per scenario: the preview first shows the event within ONSET_MAX_S
of the lights (the link's half round trip and one 33 ms tick fit well
inside), and shows it for at least COVERAGE_MIN of the time the lights do.

    .venv/bin/python scripts/check_preview_flare_skip.py

Prints one line per measurement and `ok:` per assertion; exits non-zero on
the first failure.
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import tempfile
import time
import traceback

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts", "preview_perf"))
# The same thread-switch interval the real process runs with.
sys.setswitchinterval(0.001)
_TMP = tempfile.mkdtemp(prefix="preview-flare-skip-")
os.environ["SPECTRA_STORAGE_DIR"] = os.path.join(_TMP, "storage")

from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

import rig_common  # noqa: E402
from fx import facade, headless, light_ownership as lo  # noqa: E402
from fx.consts import CONFIGURATION_VERSION  # noqa: E402
from fx.host import FxHost  # noqa: E402
from spectra import config as scfg  # noqa: E402
from spectra.services import device_preview as dp  # noqa: E402
from spectra.services import fx_seam  # noqa: E402
from spectra.services import preview_stream as ps  # noqa: E402
from spectra.services.fx_executor import FacadeExecutor  # noqa: E402
from spectra.services.live_host import live  # noqa: E402
from spectra.services.scene_response import PULSE_HOLD_S  # noqa: E402

# His live storage/spectra/fx-live/config.json, 2026-10-07: 1,037,471 bytes
# (29 virtuals, 21 devices, his LedFX scenes and presets). Only the SIZE is
# carried over; the bulk here is synthetic.
STORED_CONFIG_BYTES = 1_037_471
# The ts-relay link profile (scripts/preview_perf/linkemu.py): a Tailscale
# relay ping measured 71-88 ms.
LINK_RTT_S = 0.08
# His virtuals' own effect-switch crossfade (fx-live config, every active
# virtual: transition_time 0.5, transition_mode "Add").
CROSSFADE_S = 0.5
ONSET_MAX_S = 0.15
COVERAGE_MIN = 0.5
SETTLE_S = 2.0
LIGHT = "crystal"           # the crystal's real device (976 cells)
VIEWED = "crystal-mapper"   # the virtual the preview streams for it
DIM, BRIGHT = 0.3, 1.0


def ok(message: str) -> None:
    print(f"ok: {message}")


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    sys.stdout.flush()
    os._exit(1)


def _stored_size(cfg: dict) -> int:
    return len(json.dumps(cfg, ensure_ascii=False, sort_keys=True, indent=4))


# His fifth active virtual (fx-live config, read 2026-10-07): a 280-pixel
# dummy carrying no fixture and no favourite — not previewed, but written by
# every scene fire and every flare band like the other four.
EXTRA_VIRTUAL = ("radial-dummy", 280)


def build_config() -> dict:
    cfg = rig_common.build_room_config(CONFIGURATION_VERSION, REPO)
    vid, pixels = EXTRA_VIRTUAL
    cfg["devices"].append({"id": vid, "type": "dummy",
                           "config": {"name": vid, "pixel_count": pixels}})
    cfg["virtuals"].append({
        "id": vid, "is_device": vid, "auto_generated": False, "active": True,
        "config": {"name": vid, "mapping": "span", "rows": 1},
        "segments": [[vid, 0, pixels - 1, False, 0]],
        "effect": rig_common.effect_for(vid)})
    for virtual in cfg["virtuals"]:
        virtual["config"]["transition_time"] = CROSSFADE_S
        virtual["config"]["transition_mode"] = "Add"
    scenes, i = {}, 0
    cfg["scenes"] = scenes
    while _stored_size(cfg) < STORED_CONFIG_BYTES:
        scenes[f"scene-{i}"] = {"name": f"scene {i}", "virtuals": {
            f"virtual-{j}": {"type": "gradient", "config": {
                "gradient": rig_common.RAINBOW, "speed": 1.0, "brightness": 0.5}}
            for j in range(8)}}
        i += 1
    return cfg


class Viewer:
    """One protocol-2 viewer at the far end of the link: records what it
    was sent and acknowledges each tick one round trip later."""

    def __init__(self) -> None:
        self.table: list[str] = []
        self.frames: list[tuple[float, float]] = []   # (arrival, crystal mean)
        self.stream: ps.ViewerStream | None = None

    async def send_text(self, text: str) -> None:
        msg = json.loads(text)
        if msg.get("type") == "device_preview_layout":
            self.table = [d["vis_id"] for d in msg["devices"]]

    async def send_bytes(self, data: bytes) -> None:
        sent = time.monotonic()
        message = ps.decode_message(data)
        for record in message["records"]:
            if self.table[record["device"]] == VIEWED:
                cells = np.frombuffer(record["payload"], dtype=np.uint8)
                self.frames.append((sent + LINK_RTT_S / 2, float(cells.mean())))
        asyncio.get_running_loop().call_later(
            LINK_RTT_S, self.stream.ack, message["seq"])

    async def close(self) -> None:
        pass


def lit_window(lights, start, threshold):
    """[first, last] flush at or over the threshold from `start`."""
    hits = [t for t, m in lights if t >= start and m >= threshold]
    return (hits[0], hits[-1]) if hits else None


def shown_overlap(frames, lo_t, hi_t, inside):
    """Seconds within [lo_t, hi_t] the preview was showing a frame for which
    inside(mean) holds (a frame is shown from its arrival to the next)."""
    total = 0.0
    for (t, m), (t_next, _) in zip(frames, frames[1:] + [(float("inf"), 0)]):
        if not inside(m):
            continue
        a, b = max(t, lo_t), min(t_next, hi_t)
        if b > a:
            total += b - a
    return total


async def scenario_flare(ex, viewer, lights, loop_lag) -> dict:
    """A momentary flare on every virtual: the spike, a gain-shaped write
    and a colour-shaped glide per virtual (the shape of a real multi-virtual
    flare band), then — PULSE_HOLD_S after the crystal's spike — the
    release, landed as a jump so the flare has a sharp end on both sides.
    The second and third writes are aimed at parameters that do not change
    this picture, so the spike alone is what is measured."""
    vids = list(VIRTUALS)
    t0 = time.monotonic()
    for vid in vids:
        await ex.jump(vid, VIRTUALS[vid], {"brightness": BRIGHT})
    for vid in vids:
        await ex.jump(vid, VIRTUALS[vid], {"background_brightness": 1.0})
    for vid in vids:
        await ex.glide(vid, VIRTUALS[vid], {"background_brightness": 0.5}, 220)
    burst = time.monotonic() - t0
    await asyncio.sleep(max(0.0, t0 + PULSE_HOLD_S - time.monotonic()))
    for vid in vids:
        await ex.jump(vid, VIRTUALS[vid], {"brightness": DIM})
    writes_done = time.monotonic()
    await asyncio.sleep(0.6)

    base = statistics.median(m for t, m in lights if t0 - 1.0 <= t < t0)
    peak = max(m for t, m in lights if t >= t0)
    threshold = base + 0.5 * (peak - base)
    window = lit_window(lights, t0 - 0.02, threshold)
    if window is None:
        fail("flare: the lights never showed the spike — the rig is broken")
    l_on, l_off = window
    frames = [f for f in viewer.frames if f[0] >= t0 - 1.0]
    lit = [t for t, m in frames if t >= t0 - 0.02 and m >= threshold]
    onset = (lit[0] - l_on) if lit else float("inf")
    covered = shown_overlap(frames, l_on, l_off, lambda m: m >= threshold)
    return {"burst_ms": burst * 1000, "lights_ms": (l_off - l_on) * 1000,
            "onset_ms": onset * 1000, "coverage": covered / max(l_off - l_on, 1e-3),
            "loop_lag_ms": _held(loop_lag, t0, writes_done)}


async def scenario_transition(ex, viewer, lights, loop_lag) -> dict:
    """A scene change: every virtual switched to a new effect through
    fx_seam.apply_writes (the scene fire's own write path, the crystal
    first), riding his virtuals' own 0.5 s crossfade, followed by the colour
    moment's per-virtual glide that lands with a generated scene cue
    (trigger_engine._fire_analysed_color) — aimed, again, at a parameter that
    does not change this picture."""
    vids = list(VIRTUALS)
    writes = [{"virtual_id": vid, "effect_type": "singleColor",
               "config": {"color": "#ffffff", "brightness": BRIGHT}} for vid in vids]
    t0 = time.monotonic()
    await fx_seam.apply_writes(writes, transition_ms=300)
    for vid in vids:
        await ex.glide(vid, "singleColor", {"background_brightness": 0.5}, 300)
    writes_done = time.monotonic()
    burst = writes_done - t0
    await asyncio.sleep(CROSSFADE_S + 0.5)

    base = statistics.median(m for t, m in lights if t0 - 1.0 <= t < t0)
    final = statistics.median(m for t, m in lights if t >= t0 + CROSSFADE_S + 0.2)
    span = final - base
    if span < 50:
        fail(f"transition: the lights barely moved ({base:.0f} -> {final:.0f}) — the rig is broken")
    lo_m, hi_m = base + 0.15 * span, final - 0.15 * span
    mid = [t for t, m in lights if t >= t0 and lo_m < m < hi_m]
    if len(mid) < 5:
        fail(f"transition: the lights crossfaded in {len(mid)} frames — the rig is broken")
    l_on, l_off = mid[0], mid[-1]
    frames = [f for f in viewer.frames if f[0] >= t0 - 1.0]
    seen = [t for t, m in frames if t >= t0 and lo_m < m < hi_m]
    onset = (seen[0] - l_on) if seen else float("inf")
    covered = shown_overlap(frames, l_on, l_off, lambda m: lo_m < m < hi_m)
    return {"burst_ms": burst * 1000, "lights_ms": (l_off - l_on) * 1000,
            "onset_ms": onset * 1000, "coverage": covered / max(l_off - l_on, 1e-3),
            "preview_frames": len(seen), "lights_frames": len(mid),
            "loop_lag_ms": _held(loop_lag, t0, writes_done)}


VIRTUALS: dict[str, str] = {}   # every active virtual -> its effect type


def _held(loop_lag, t0, writes_done) -> float:
    """The longest the event loop stood still while the scenario's writes ran
    (a probe sample is recorded when the probe wakes, after the stall)."""
    return max((v for t, v in loop_lag if t0 <= t <= writes_done + 0.1), default=0.0)


async def reset(ex) -> None:
    """Back to the starting picture (rainbow at DIM), and long enough for a
    coalesced save from the reset itself to have landed."""
    for vid in VIRTUALS:
        effect = rig_common.effect_for(vid)
        config = {**effect["config"], "brightness": DIM}
        await fx_seam.apply_writes([{"virtual_id": vid, "effect_type": effect["type"],
                                     "config": config}])
        VIRTUALS[vid] = effect["type"]
    await asyncio.sleep(SETTLE_S)


async def main() -> None:
    lo.OWNERSHIP_FILE = Path(_TMP) / "ownership.json"
    scfg.DEVICE_PREVIEW_FILE = Path(_TMP) / "device_preview.json"
    scfg.FIRE_HISTORY_FILE = Path(_TMP) / "fire_history.json"
    scfg.SHOW_LOG_FILE = Path(_TMP) / "show_log.json"
    favourites = [s[0] for s in rig_common.SHAPES]
    scfg.DEVICE_PREVIEW_FILE.write_text(json.dumps(
        {"favorite_virtual_ids": favourites, "paused": False}))
    cfg_dir = os.path.join(_TMP, "fx-live")
    os.makedirs(cfg_dir)
    config = build_config()
    with open(os.path.join(cfg_dir, "config.json"), "w") as f:
        json.dump(config, f)
    print(f"stored config: {_stored_size(config):,} bytes "
          f"(his: {STORED_CONFIG_BYTES:,}); link round trip {LINK_RTT_S * 1000:.0f} ms")

    headless.silence_audio()
    host = FxHost(cfg_dir)
    await host.start()
    host.audio = headless.SyntheticAudioSource()
    live.host = host
    facade.set_host(host)
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
    for virtual in config["virtuals"]:
        if virtual["active"]:
            VIRTUALS[virtual["id"]] = virtual["effect"]["type"]

    lights: list[tuple[float, float]] = []
    device = host.devices.get(LIGHT)
    flush = device.flush

    def record(data):
        cells = np.clip(np.asarray(data), 0, 255).astype(np.uint8)
        lights.append((time.monotonic(), float(cells.mean())))
        return flush(data)
    device.flush = record

    loop_lag: list[tuple[float, float]] = []

    async def lag_probe() -> None:
        while True:
            start = time.monotonic()
            await asyncio.sleep(0.005)
            loop_lag.append((time.monotonic(), (time.monotonic() - start - 0.005) * 1000))
    probe = asyncio.create_task(lag_probe())

    dp.relay._has_viewers = lambda: True
    await dp.start()
    viewer = Viewer()
    viewer.stream = dp.stream_hub.connect(viewer, level="full", scope="favorites")
    ex = FacadeExecutor()

    t = time.monotonic()
    facade.PERSIST_QUIET_S = 0
    await ex.jump(VIEWED, VIRTUALS[VIEWED], {"brightness": DIM})
    print(f"one effect write with an inline save: {(time.monotonic() - t) * 1000:.1f} ms")

    results: dict[str, dict] = {}
    for mode, quiet in (("inline", 0.0), ("coalesced", 1.0)):
        facade.PERSIST_QUIET_S = quiet
        for name, scenario in (("flare", scenario_flare),
                               ("transition", scenario_transition)):
            await reset(ex)
            r = await scenario(ex, viewer, lights, loop_lag)
            results[f"{mode} {name}"] = r
            extra = (f", preview {r['preview_frames']} / lights {r['lights_frames']} "
                     f"crossfade frames" if "preview_frames" in r else "")
            print(f"{mode:9s} {name:10s}: write burst {r['burst_ms']:4.0f} ms, loop held "
                  f"up to {r['loop_lag_ms']:4.0f} ms; lights showed it {r['lights_ms']:4.0f} ms; "
                  f"preview first showed it {r['onset_ms']:5.0f} ms later and for "
                  f"{r['coverage'] * 100:3.0f}% of that{extra}")
    probe.cancel()

    # The pending coalesced save lands, and lands what the live config holds.
    if not facade.save_pending(host):
        await fx_seam.apply_writes([{"virtual_id": VIEWED, "effect_type": "singleColor",
                                     "config": {"color": "#123456"}}])
    if not facade.save_pending(host):
        fail("an effect write did not leave a coalesced save pending")
    await asyncio.sleep(facade.PERSIST_QUIET_S + 0.3)
    if facade.save_pending(host):
        fail("the coalesced save never landed")
    with open(os.path.join(cfg_dir, "config.json")) as f:
        stored = json.load(f)
    stored_crystal = next(v for v in stored["virtuals"] if v["id"] == VIEWED)
    if stored_crystal["effect"]["config"].get("color") != "#123456":
        fail(f"the coalesced save stored {stored_crystal['effect']} — not the last write")
    ok("an effect write's save is coalesced, lands after the quiet period, "
       "and stores the last write")

    def passes(r):
        return r["onset_ms"] <= ONSET_MAX_S * 1000 and r["coverage"] >= COVERAGE_MIN

    for name in ("flare", "transition"):
        red, green = results[f"inline {name}"], results[f"coalesced {name}"]
        if passes(red):
            fail(f"inline {name}: the RED control passed — this instrument cannot see "
                 f"the skip ({red})")
        ok(f"inline {name} (the code before the fix) reproduces the skip: first shown "
           f"{red['onset_ms']:.0f} ms late, for {red['coverage'] * 100:.0f}% of it")
        if not passes(green):
            fail(f"coalesced {name}: the preview still skips it ({green})")
        ok(f"coalesced {name}: the preview shows it within {green['onset_ms']:.0f} ms "
           f"(bar {ONSET_MAX_S * 1000:.0f}) for {green['coverage'] * 100:.0f}% of it "
           f"(bar {COVERAGE_MIN * 100:.0f}%)")

    await dp.stream_hub.disconnect(viewer)
    await dp.stop()
    await host.shutdown()
    print("ALL PREVIEW FLARE/TRANSITION CHECKS PASSED")


if __name__ == "__main__":
    status = 0
    try:
        asyncio.run(main())
    except SystemExit as exc:
        status = int(exc.code or 0)
    except BaseException:
        traceback.print_exc()
        status = 1
    sys.stdout.flush()
    sys.stderr.flush()
    # fx render threads are non-daemon and never joined by a frame-stepped
    # harness; a plain return would leave the interpreter alive (AGENTS.md).
    os._exit(status)
