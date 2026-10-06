"""Camera measurement of how the Singles respond: brightness and delay
(single-led-power plan, phase 1 — the numbers Pulse's `gamma` and the
per-device timing offsets will be tuned from).

DRIVES REAL FIXTURES with --apply. Dry run (the default) only READS: it
checks the room is measurable and prints the exact plan. Never run --apply
without firstmate's go, and only between 08:30 and 22:30.

What it does, through deployed endpoints only (nothing here needs a deploy):

  * drives each fixture through the LIGHT SHOW's per-fixture holds
    (`POST /api/light-show/fire`: device_state steady <grey> / dark) and
    lets each one go with `POST /api/light-show/release/{device}` — in a
    `finally`, so an error or Ctrl-C still hands every fixture back;
  * reads the camera through the capture session's frame tap
    (`GET /api/rooms/map/frame/latest`, grey8 PGM, nothing stored).

Protocol, per run:

  1. ISOLATE: every target held dark; a dark reference is averaged.
  2. FIND: each target alone at full white; the pixels it lights (its own
     region, saturated pixels excluded) are found from the difference. A
     target the camera cannot see is reported as such and skipped.
  3. SWEEP: each visible target alone through SWEEP_LEVELS (sent value,
     0..1, as a grey steady colour), up then down; the camera's mean over
     the region, minus dark, per level.
  4. DELAY: pairs of one WLED and one Hue fixture switched on in ONE fire,
     repeatedly from dark; the frame on which each one's region crosses
     half its full reading, sub-frame interpolated. Their DIFFERENCE is the
     relative delay (the camera's own seconds-long stream lag cancels,
     because both are seen in the same frames); the random wait between
     trials dithers the 5 fps frame clock so the average resolves well
     below one frame.

THE NAMED ASSUMPTION. A webcam encodes light with a tone curve. Readings
are linearised with the sRGB/BT.709-style curve (CAMERA_DECODE) before the
fixture's own curve is fitted, so a fixture gamma here is an ESTIMATE under
that assumption; the raw readings are reported beside it so it can be
redone under another. The RELATIVE answers (Hue vs WLED, one camera, one
assumption) are the robust part.

Run:  .venv/bin/python scripts/measure_singles_response.py --spectra-url URL
          [--fixture porch-rail --fixture hue-lights ...] [--apply] [--out FILE]
      .venv/bin/python scripts/measure_singles_response.py --simulate
          (the whole protocol against a simulated room with known answers)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

DEFAULT_FIXTURES = ["porch-rail", "dining-table", "hue-lights", "dining-hues"]
SWEEP_LEVELS = [0.03, 0.06, 0.1, 0.18, 0.3, 0.5, 0.75, 1.0]
SETTLE_S = 2.6            # the kiosk stream runs 1.4-2.1 s behind the room
CAPTURE_FRAMES = 4        # averaged per reading (5 fps -> ~0.8 s)
DELAY_TRIALS = 24
DELAY_WAIT_S = 4.0        # longest to wait for a switch to show in frame
VISIBLE_MIN = 8.0         # grey levels: below this the camera cannot see it
POLL_S = 0.05


def camera_decode(v):
    """Encoded grey (0..255) -> relative linear light (0..1): the sRGB curve,
    THE NAMED ASSUMPTION above."""
    x = np.clip(np.asarray(v, dtype=float) / 255.0, 0.0, 1.0)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def grey_hex(level: float) -> str:
    v = int(round(255 * min(1.0, max(0.0, level))))
    return "#%02x%02x%02x" % (v, v, v)


def hold_actions(steps: list[tuple[str, Optional[str]]]) -> list[dict]:
    """Light Show device_state steps, ONE named fixture each. A target with
    no "kind" is "everything" to the Light Show — never send one."""
    return [
        {"kind": "device_state",
         "params": {"target": {"kind": "fixture", "id": d},
                    "state": "steady" if c else "dark",
                    **({"color": c} if c else {}), "fade_ms": 0}}
        for d, c in steps
    ]


def check_run(run: dict, steps: list[tuple[str, Optional[str]]]) -> None:
    """Every step applied, each to exactly its own fixture — or stop."""
    got = run.get("steps") or []
    if len(got) != len(steps):
        raise RuntimeError(f"light-show ran {len(got)} steps for {len(steps)}")
    for (d, _c), st in zip(steps, got):
        if st.get("status") != "applied" or st.get("devices") != [d]:
            raise RuntimeError(f"light-show step for {d} did not apply to exactly "
                               f"{d}: {st}")


# ── the room: live (HTTP) or simulated ─────────────────────────────────────

class LiveRoom:
    """The deployed SPECTRA API. Writes only Light Show holds/releases."""

    def __init__(self, base: str):
        import httpx
        self.base = base.rstrip("/")
        self.http = httpx.Client(timeout=10.0)
        self._last_hash = None
        self.frame_period_s = 0.2

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, s: float) -> None:
        time.sleep(s)

    def get(self, path: str):
        r = self.http.get(self.base + path)
        r.raise_for_status()
        return r.json()

    def hold(self, steps: list[tuple[str, Optional[str]]]) -> None:
        """[(device, colour-or-None for dark)] in ONE fire."""
        r = self.http.post(self.base + "/api/light-show/fire",
                           json={"actions": hold_actions(steps),
                                 "name": "Singles measurement"})
        if r.status_code != 200:
            raise RuntimeError(f"light-show fire refused: {r.status_code} {r.text}")
        check_run(r.json(), steps)

    def release(self, device: str) -> None:
        r = self.http.post(self.base + f"/api/light-show/release/{device}",
                           params={"fade_ms": 0})
        r.raise_for_status()

    def latest_frame(self):
        """(sequence-key, grey array) of the newest tapped frame."""
        r = self.http.get(self.base + "/api/rooms/map/frame/latest")
        if r.status_code != 200:
            return None, None
        data = r.content
        # P5\n<w> <h>\n255\n<bytes>
        parts = data.split(b"\n", 3)
        w, h = (int(x) for x in parts[1].split())
        arr = np.frombuffer(parts[3], dtype=np.uint8).reshape(h, w)
        key = hashlib.sha1(parts[3]).hexdigest()
        return key, arr.astype(float)


@dataclass
class SimFixture:
    region: tuple          # (y0, y1, x0, x1)
    gain: float            # camera-linear light at full
    gamma: float           # sent -> light
    delay_s: float         # write -> light
    tau_s: float           # light smoothing (Hue smooths between frames)


@dataclass
class SimRoom:
    """A camera watching fixtures with KNOWN curves and delays, on a virtual
    clock: the analysis must recover what is put in."""
    fixtures: dict
    fps: float = 5.0
    lag_s: float = 1.8
    ambient: float = 0.02
    noise: float = 0.4
    seed: int = 7
    t: float = 0.0
    log: list = field(default_factory=list)

    def __post_init__(self):
        self.rng = np.random.default_rng(self.seed)
        self.frame_period_s = 1.0 / self.fps
        self._cmd = {d: [(-1e9, 0.0)] for d in self.fixtures}  # (t, sent)

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def get(self, path):
        if path == "/api/ownership":
            return {"owner": "spectra", "live_stack_active": True}
        if path == "/api/light-show/targets":
            return {"fixtures": [{"id": d, "name": d, "type": "hue" if "hue" in d else "wled",
                                  "held_by_ambient": False} for d in self.fixtures]}
        if path == "/api/light-show/status":
            return {"output": {"refusal": None, "standdown": None, "holds": [],
                               "base": {"levels": {}, "states": {}}, "withheld": []}}
        if path == "/api/rooms/map/status":
            return {"capture_source": {"host": {"present": True, "client": {
                "pose_name": "sim", "locked": True,
                "camera": {"fps": self.fps, "frame_size": [64, 36]}}}}}
        raise KeyError(path)

    def hold(self, steps):
        for d, c in steps:
            sent = 0.0 if c is None else int(c[1:3], 16) / 255.0
            self._cmd[d].append((self.t, sent))
        self.log.append((self.t, list(steps)))

    def release(self, device):
        self._cmd[device].append((self.t, 0.0))

    def _light(self, d, t):
        f = self.fixtures[d]
        # light follows the command after delay_s, first-order smoothed
        level = 0.0
        prev_t, prev_v = None, 0.0
        for ct, v in self._cmd[d]:
            ct = ct + f.delay_s
            if ct > t:
                break
            if prev_t is not None:
                level = prev_v + (level - prev_v) * math.exp(-(ct - prev_t) / max(1e-6, f.tau_s))
            prev_t, prev_v = ct, v ** f.gamma
        if prev_t is not None:
            level = prev_v + (level - prev_v) * math.exp(-(t - prev_t) / max(1e-6, f.tau_s))
        return f.gain * level

    def latest_frame(self):
        k = math.floor((self.t - self.lag_s) * self.fps)
        t_shot = k / self.fps
        img = np.full((36, 64), self.ambient)
        for d, f in self.fixtures.items():
            y0, y1, x0, x1 = f.region
            img[y0:y1, x0:x1] += self._light(d, t_shot)
        enc = 255.0 * np.where(img <= 0.0031308, 12.92 * img,
                               1.055 * np.clip(img, 0, None) ** (1 / 2.4) - 0.055)
        enc = enc + self.rng.normal(0, self.noise, enc.shape)
        return k, np.clip(np.round(enc), 0, 255)


# ── the protocol ────────────────────────────────────────────────────────────

def preflight(room, fixtures: list[str]) -> list[str]:
    """Why this room cannot be measured right now (empty = measurable)."""
    problems = []
    own = room.get("/api/ownership")
    if own.get("owner") != "spectra" or not own.get("live_stack_active", False):
        problems.append(f"SPECTRA does not hold the room live (owner {own.get('owner')}).")
    st = room.get("/api/light-show/status").get("output", {})
    if st.get("refusal"):
        problems.append(f"Light Show refuses: {st['refusal']}")
    if st.get("standdown"):
        problems.append(f"Light Show stands down: {st['standdown']}")
    targets = {t["id"]: t for t in room.get("/api/light-show/targets").get("fixtures", [])}
    for d in fixtures:
        t = targets.get(d)
        if t is None:
            problems.append(f"{d}: no such fixture.")
        elif t.get("held_by_ambient"):
            problems.append(f"{d}: held by Hue Hold (the house layer drives it over the "
                            f"bridge, so nothing streamed reaches it) — lift the hold first.")
    cam = (room.get("/api/rooms/map/status").get("capture_source") or {}).get("host") or {}
    client = cam.get("client") or {}
    if not cam.get("present"):
        problems.append("No capture camera is connected.")
    elif not client.get("locked"):
        problems.append("The camera's exposure is not locked; readings would not compare.")
    return problems


def _fresh_frames(room, n: int, settle_s: float) -> np.ndarray:
    room.sleep(settle_s)
    seen, frames = set(), []
    deadline = room.now() + n * 1.5 + 3.0
    while len(frames) < n and room.now() < deadline:
        key, img = room.latest_frame()
        if img is not None and key not in seen:
            seen.add(key)
            frames.append(img)
        room.sleep(POLL_S)
    if not frames:
        raise RuntimeError("no camera frames arrived")
    return np.mean(frames, axis=0)


def find_region(dark: np.ndarray, full: np.ndarray) -> Optional[np.ndarray]:
    diff = full - dark
    if np.percentile(diff, 99.9) < VISIBLE_MIN:
        return None
    lin = camera_decode(full) - camera_decode(dark)
    ok = full < 250
    top = np.percentile(lin[ok], 99.5) if ok.any() else 0.0
    mask = ok & (lin >= 0.5 * top) & (diff >= VISIBLE_MIN)
    if mask.sum() < 4:
        return None
    return mask


def reading(img: np.ndarray, dark: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
    """(linear light over the region above dark, raw grey above dark)."""
    lin = float(np.mean(camera_decode(img)[mask] - camera_decode(dark)[mask]))
    raw = float(np.mean(img[mask] - dark[mask]))
    return lin, raw


def fit_gamma(levels, ys) -> Optional[dict]:
    """Power-law fit of normalised light against sent value."""
    levels = np.asarray(levels, float)
    ys = np.asarray(ys, float)
    top = ys[np.argmax(levels)]
    if top <= 0:
        return None
    y = ys / top
    ok = (levels >= 0.05) & (y > 0.01)
    if ok.sum() < 3:
        return None
    lx, ly = np.log(levels[ok]), np.log(y[ok])
    slope, icept = np.polyfit(lx, ly, 1)
    resid = ly - (slope * lx + icept)
    se = float(np.sqrt(np.sum(resid**2) / max(1, ok.sum() - 2)) /
               np.sqrt(np.sum((lx - lx.mean()) ** 2)))
    return {"gamma": round(float(slope), 3), "stderr": round(se, 3),
            "points": int(ok.sum())}


def crossing_time(t: list, y: list, half: float) -> Optional[float]:
    for i in range(1, len(y)):
        if y[i] >= half > y[i - 1]:
            return t[i - 1] + (half - y[i - 1]) / (y[i] - y[i - 1]) * (t[i] - t[i - 1])
    return None


def measure(room, fixtures: list[str], *, trials: int = DELAY_TRIALS,
            rng: Optional[random.Random] = None) -> dict:
    rng = rng or random.Random(11)
    out: dict = {"fixtures": {}, "pairs": [], "assumption": "camera = sRGB curve"}
    room.hold([(d, None) for d in fixtures])
    dark = _fresh_frames(room, CAPTURE_FRAMES, SETTLE_S)
    masks, full_lin = {}, {}
    for d in fixtures:
        room.hold([(d, grey_hex(1.0))])
        full = _fresh_frames(room, CAPTURE_FRAMES, SETTLE_S)
        room.hold([(d, None)])
        mask = find_region(dark, full)
        if mask is None:
            out["fixtures"][d] = {"visible": False}
            room.sleep(SETTLE_S)
            continue
        masks[d] = mask
        full_lin[d] = reading(full, dark, mask)[0]
        out["fixtures"][d] = {"visible": True, "pixels": int(mask.sum())}
        room.sleep(SETTLE_S)
    for d, mask in masks.items():
        ups, raws = [], []
        order = SWEEP_LEVELS + SWEEP_LEVELS[-2::-1]
        for lv in order:
            room.hold([(d, grey_hex(lv))])
            img = _fresh_frames(room, CAPTURE_FRAMES, SETTLE_S)
            lin, raw = reading(img, dark, mask)
            ups.append(lin)
            raws.append(raw)
        room.hold([(d, None)])
        room.sleep(SETTLE_S)
        n = len(SWEEP_LEVELS)
        up = ups[:n]
        down = [None] * n
        for k, lv in enumerate(SWEEP_LEVELS[-2::-1]):
            down[SWEEP_LEVELS.index(lv)] = ups[n + k]
        down[-1] = up[-1]
        both = [np.mean([a, b]) for a, b in zip(up, down)]
        out["fixtures"][d].update(
            levels=SWEEP_LEVELS, light_up=up, light_down=down, raw=raws[:n],
            fit=fit_gamma(SWEEP_LEVELS, both),
            hysteresis=round(float(np.max(np.abs(np.asarray(up) - np.asarray(down))) /
                                   max(1e-9, up[-1])), 3))
    wleds = [d for d in masks if "hue" not in d]
    hues = [d for d in masks if "hue" in d]
    pairs = list(zip(wleds, hues)) if wleds and hues else []
    for a, b in pairs:
        diffs, lags = [], []
        for _ in range(trials):
            room.hold([(a, None), (b, None)])
            room.sleep(SETTLE_S + rng.uniform(0.0, room.frame_period_s * 2))
            t_fire = room.now()
            room.hold([(a, grey_hex(1.0)), (b, grey_hex(1.0))])
            seen, ts, ya, yb = set(), [], [], []
            k0 = None
            while room.now() - t_fire < DELAY_WAIT_S:
                key, img = room.latest_frame()
                if img is not None and key not in seen:
                    seen.add(key)
                    k0 = len(seen) if k0 is None else k0
                    ts.append(len(seen) * room.frame_period_s)
                    ya.append(reading(img, dark, masks[a])[0] / full_lin[a])
                    yb.append(reading(img, dark, masks[b])[0] / full_lin[b])
                    if ya[-1] > 0.9 and yb[-1] > 0.9:
                        break
                room.sleep(POLL_S)
            ta, tb = crossing_time(ts, ya, 0.5), crossing_time(ts, yb, 0.5)
            if ta is not None and tb is not None:
                diffs.append(tb - ta)
        room.hold([(a, None), (b, None)])
        arr = np.asarray(diffs)
        out["pairs"].append({
            "wled": a, "hue": b, "trials": len(diffs),
            "hue_minus_wled_ms": round(1000 * float(arr.mean()), 1) if len(arr) else None,
            "sem_ms": round(1000 * float(arr.std(ddof=1) / math.sqrt(len(arr))), 1)
            if len(arr) > 1 else None,
        })
    return out


def run(room, fixtures: list[str], **kw) -> dict:
    try:
        return measure(room, fixtures, **kw)
    finally:
        for d in fixtures:
            try:
                room.release(d)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! could not release {d}: {exc}", file=sys.stderr)


def estimate_minutes(n_fixtures: int, n_pairs: int, trials: int = DELAY_TRIALS) -> float:
    per = SETTLE_S + CAPTURE_FRAMES * 0.25
    s = per * (1 + n_fixtures) + n_fixtures * SETTLE_S
    s += n_fixtures * (per * (2 * len(SWEEP_LEVELS) - 1) + SETTLE_S)
    s += n_pairs * trials * (SETTLE_S + 0.2 + DELAY_WAIT_S)
    return s / 60.0


def simulated_room() -> SimRoom:
    return SimRoom(fixtures={
        "porch-rail": SimFixture((2, 8, 2, 10), 0.55, 2.4, 0.016, 0.01),
        "dining-table": SimFixture((2, 8, 20, 28), 0.45, 2.2, 0.016, 0.01),
        "hue-lights": SimFixture((20, 30, 2, 12), 0.6, 2.0, 0.090, 0.06),
        "dining-hues": SimFixture((20, 30, 40, 50), 0.5, 1.8, 0.110, 0.08),
    })


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spectra-url", help="e.g. http://127.0.0.1:8010/spectra (no default)")
    ap.add_argument("--fixture", action="append")
    ap.add_argument("--apply", action="store_true", help="DRIVE the fixtures")
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--trials", type=int, default=DELAY_TRIALS)
    ap.add_argument("--out")
    args = ap.parse_args()
    fixtures = args.fixture or DEFAULT_FIXTURES
    if args.simulate:
        room = simulated_room()
    elif args.spectra_url:
        room = LiveRoom(args.spectra_url)
    else:
        ap.error("--spectra-url is required (no default target) unless --simulate")
    problems = preflight(room, fixtures)
    n_pairs = min(sum("hue" not in d for d in fixtures), sum("hue" in d for d in fixtures))
    print(f"fixtures: {', '.join(fixtures)}")
    print(f"about {estimate_minutes(len(fixtures), n_pairs, args.trials):.0f} minutes "
          f"of these fixtures switching dark/steady white")
    if problems:
        print("NOT MEASURABLE NOW:")
        for p in problems:
            print("  - " + p)
        return 1
    if not (args.apply or args.simulate):
        print("dry run: measurable. Re-run with --apply ONLY with firstmate's go.")
        return 0
    result = run(room, fixtures, trials=args.trials)
    text = json.dumps(result, indent=1, default=float)
    print(text)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
