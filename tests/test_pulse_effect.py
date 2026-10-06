"""The Pulse effect (fx/effects/pulse.py) — single-led-power plan, phase 1.

Two halves:

- SYNTHETIC: the effect's contract, one property at a time, on the real
  class (rise from sharpness, fade in beats from intensity, rest and depth
  from intensity, the smallest pulse, the bulb curve, no background, the
  flash budget WITH a control that goes red without it, the hooks' safe
  defaults, charge/lull/drop), plus the registry + real virtual pipeline
  and the real melbank audio path.
- HIS SONGS: Dopamine, Contra, Let It Be (at half intensity: the calm case)
  and Soy Peor, driven from tests/fixtures/pulse — the effect's own audio
  input recorded through the real pipeline from his captured WAVs
  (scripts/check_pulse_effect.py writes them and proves a fixture-driven
  run lands on the pipeline's light frame by frame). Measured on the
  OUTPUT, not on the effect's own bookkeeping.

Engine wiring (energy, tempo and charge/lull/drop pushed live) is phase 2;
here the harness stands in for it with each song's stored analysis and his
own authored marks.
"""
from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pulse_song_harness as h  # noqa: E402
from fx import headless  # noqa: E402
# Imported BEFORE any test runs headless.silence_audio(): HubMelbankSource
# subclasses whatever fx.effects.audio.AudioAnalysisSource is when
# fx.audio_ingest is first imported, and silence_audio() swaps that name.
from fx.audio_ingest import HubMelbankSource  # noqa: E402
from fx.effects import pulse as pulse_mod  # noqa: E402

FPS = h.FPS
DT = h.DT
RED = "#ff0000"


# ── a small synthetic driver ────────────────────────────────────────────────

class Rig:
    """One standalone Pulse effect on one pixel, its OWN frame clock (exactly
    DT a frame, no global timer patch, so two rigs never share one), and a
    frame loop: audio frame first, then render — the order the live
    pipeline delivers them."""

    def __init__(self, **config):
        cfg = {"gradient": RED, "beat_ms": 500.0}
        cfg.update(config)
        self.e = h.new_effect(cfg)

        def log_sec():                      # Effect.log_sec, one fixed frame
            self.e.now += DT
            self.e.passed = DT

        self.e.log_sec = log_sec
        self.levels: list[float] = []
        self.out: list[np.ndarray] = []
        self.envs: list[float] = []

    def close(self):
        pass

    def frame(self, x: float | None = None):
        if x is not None:
            self.e.ingest_signal(x, DT)
        self.e._render()
        px = self.e.get_pixels()
        self.levels.append(self.e.level)
        self.out.append(px[0].copy())
        self.envs.append(self.e._env)
        return px[0]

    def feed(self, xs):
        for x in xs:
            self.frame(x)

    def write(self, **cfg):
        self.e.update_config(cfg)

    def tween(self, **cfg):
        with self.e.lock:
            self.e._apply_config(cfg, validate=False, fire_event=False)


@pytest.fixture
def rig():
    made = []

    def make(**config):
        r = Rig(**config)
        made.append(r)
        return r

    yield make
    for r in made:
        r.close()


def settle(r: Rig, seconds: float = 3.0, x: float = 0.1):
    r.feed([x] * int(seconds * FPS))


def sharp_hit(r: Rig, base: float = 0.1, peak: float = 1.0):
    """One full-strength, maximally sharp hit: a one-frame step."""
    r.frame(peak)


# ── one light, one colour ──────────────────────────────────────────────────

def test_output_is_the_colour_at_the_level_through_the_bulb_curve(rig):
    for gamma in (1.0, 2.2, 3.0):
        r = rig(gamma=gamma, energy=0.0)
        settle(r)
        rest = r.e.level
        assert rest == pytest.approx(0.40, abs=1e-6)  # calm resting level
        px = r.out[-1]
        assert px == pytest.approx(np.array([255.0, 0, 0]) * rest**gamma, abs=1e-6)


def test_no_background_ever_paints_under_the_pulse(rig):
    """42 of his colour sets carry a Singles background colour; Pulse is one
    colour, so whatever background is written never reaches the light."""
    r = rig(energy=0.0, background_color="#00ff00", background_brightness=1.0,
            background_mode="overwrite")
    settle(r)
    assert r.e.bg_color_use is False
    assert r.out[-1][1] == 0.0 and r.out[-1][2] == 0.0
    r.write(background_color="#0000ff", background_brightness=0.8,
            background_mode="additive")
    settle(r, 1.0)
    assert r.e.bg_color_use is False
    assert r.out[-1][1] == 0.0 and r.out[-1][2] == 0.0
    # the control: the base class WOULD have painted it
    from fx.effects import Effect
    Effect._refresh_bg_render_state(r.e)
    assert r.e.bg_color_use is True


def test_the_colour_is_the_gradients_first_colour(rig):
    r = rig(gradient="linear-gradient(90deg, #00ff00 0%, #0000ff 100%)", energy=0.0)
    settle(r, 0.5)
    px = r.out[-1]
    assert px[0] == 0.0 and px[2] < 1.0 and px[1] > 0.0


# ── rise ────────────────────────────────────────────────────────────────────

def test_a_sharp_hard_hit_rises_in_one_frame(rig):
    r = rig(energy=1.0)
    settle(r)
    before = r.levels[-1]
    sharp_hit(r)
    t, strength, sharp, rise_ms, _want, _target = r.e.hits[-1]
    assert strength == pytest.approx(1.0) and sharp == pytest.approx(1.0)
    assert rise_ms == pytest.approx(16.0)
    assert r.levels[-1] == pytest.approx(1.0)  # at the peak on the hit's own frame
    assert before < 0.3


def test_a_soft_hit_rises_over_about_160_ms(rig):
    r = rig(energy=1.0)
    settle(r)
    n0 = len(r.e.hits)
    # a gentle swell: a little more every frame
    for k in range(30):
        r.frame(0.1 + 0.004 * (k + 1))
        if len(r.e.hits) > n0:
            break
    assert len(r.e.hits) == n0 + 1
    rise_ms = r.e.hits[-1][3]
    assert 120.0 <= rise_ms <= 160.0
    i = len(r.levels) - 1
    r.feed([0.1 + 0.004 * 30] * 20)
    lv = r.levels[i - 1:]
    peak_at = int(np.argmax(lv))
    measured = peak_at * 1000 * DT
    assert measured == pytest.approx(rise_ms, abs=1000 * DT + 1e-6)


def test_rise_time_follows_sharpness_and_size(rig):
    """The mapping itself, end to end: rise = lerp(soft, sharp,
    sharpness x sqrt(strength))."""
    r = rig()
    for strength, sharp in ((1.0, 1.0), (1.0, 0.0), (0.25, 1.0), (0.64, 0.5)):
        r.e._start_hit(strength, sharp)
        want = 160.0 + (16.0 - 160.0) * sharp * math.sqrt(strength)
        assert r.e.hits[-1][3] == pytest.approx(want)


def test_a_growing_hit_raises_its_peak_but_keeps_its_deadline(rig):
    r = rig(energy=1.0)
    settle(r)
    n0 = len(r.e.hits)
    x = 0.1
    while len(r.e.hits) == n0:
        x += 0.004
        r.frame(x)
    rise_ms = r.e.hits[-1][3]
    target0 = r.e._target
    i = len(r.levels) - 1
    for _ in range(4):  # the sound keeps swelling hard for a few frames
        x += 0.05
        r.frame(x)
    assert r.e._target > target0
    r.feed([x] * 30)
    lv = r.levels[i - 1:]
    peak_at = int(np.argmax(lv))
    assert peak_at * 1000 * DT <= rise_ms + 1000 * DT + 1e-6


# ── fade ────────────────────────────────────────────────────────────────────

def _fade_to_tenth_s(r: Rig) -> float:
    """Envelope at 1.0 now; frames until it reaches a tenth."""
    peak = r.e._env
    n = 0
    while r.e._env > 0.1 * peak:
        r.frame(0.1)
        n += 1
        assert n < 20 * FPS
    return n * DT


@pytest.mark.parametrize("energy,beat_ms,beats", [
    (0.0, 500.0, 1.6), (1.0, 500.0, 0.5), (0.5, 500.0, 1.05),
    (1.0, 250.0, 0.5), (0.0, 1000.0, 1.6),
])
def test_fade_is_counted_in_beats_and_follows_intensity(rig, energy, beat_ms, beats):
    r = rig(energy=energy, beat_ms=beat_ms)
    settle(r)
    sharp_hit(r)
    assert r.e._env == pytest.approx(1.0)
    s = _fade_to_tenth_s(r)
    assert s == pytest.approx(beats * beat_ms / 1000.0, abs=1.5 * DT)


# ── resting level, depth, smallest pulse, easing ───────────────────────────

@pytest.mark.parametrize("energy,rest,peak", [(0.0, 0.40, 0.50), (1.0, 0.22, 1.0)])
def test_rest_and_depth_scale_with_intensity(rig, energy, rest, peak):
    r = rig(energy=energy)
    settle(r)
    assert r.levels[-1] == pytest.approx(rest, abs=1e-6)
    sharp_hit(r)
    assert r.levels[-1] == pytest.approx(peak, abs=1e-6)


def _weak_hit(r: Rig) -> float:
    """A hit well under the recent peak; returns its envelope peak."""
    settle(r, 3.0)
    r.feed([0.1, 1.0, 0.1])       # teach it a recent peak of ~0.8
    settle(r, 2.0)
    n0 = len(r.e.hits)
    r.frame(0.25)
    assert len(r.e.hits) == n0 + 1
    r.feed([0.25] * 12)
    return r.e.hits[-1][5]


def test_the_smallest_pulse_keeps_a_weak_calm_hit_visible(rig):
    with_min = rig(energy=0.0)
    env = _weak_hit(with_min)
    without = rig(energy=0.0, min_pulse=0.0)
    assert _weak_hit(without) == pytest.approx(env)
    lift_with = max(with_min.levels[-12:]) - 0.40
    lift_without = max(without.levels[-12:]) - 0.40
    assert lift_without == pytest.approx(0.10 * env)   # calm depth x envelope
    assert lift_without < 0.05
    assert lift_with == pytest.approx(max(0.10 * env, 0.05 * min(1.0, 3.0 * env)))
    assert lift_with > lift_without


def test_intensity_eases_over_two_seconds_not_a_snap(rig):
    r = rig(energy=0.0)
    settle(r, 1.0)
    r.write(energy=1.0)
    r.feed([0.1] * int(2.0 * FPS))
    assert r.e._energy_live == pytest.approx(1.0 - math.exp(-1.0), abs=0.01)
    steps = np.abs(np.diff(r.levels[-int(2.0 * FPS):]))
    assert steps.max() < 0.01


# ── the hooks: safe defaults, nothing wired ────────────────────────────────

def test_the_hooks_have_safe_defaults(rig):
    from fx.effects.pulse import PulseAudioEffect
    d = PulseAudioEffect.schema()({})
    assert d["energy"] == 0.5 and d["beat_ms"] == 0.0
    assert d["phase"] == "none" and d["phase_progress"] == 0.0
    r = rig(beat_ms=0.0)
    assert r.e.beat_s() == pytest.approx(0.5)   # no tempo known: 120 bpm
    r.e._live_bpm = 128.0
    assert r.e.beat_s() == pytest.approx(60.0 / 128.0)
    r.e._live_bpm = 300.0                         # an implausible read
    assert r.e.beat_s() == pytest.approx(0.5)
    r.write(beat_ms=420.0)                        # a pushed tempo wins
    assert r.e.beat_s() == pytest.approx(0.42)


def test_pulse_is_not_yet_a_phase_effect_the_engine_drives():
    from fx.device_model import PHASE_EFFECTS
    assert "pulse" not in PHASE_EFFECTS


def test_a_stale_persisted_phase_never_fires_on_a_fresh_effect(rig):
    r = rig(phase="drop", phase_progress=0.5, energy=0.0)
    assert r.e._config["phase"] == "none"
    settle(r, 0.5)
    r.write(gradient="#00ff00")                   # any later write
    settle(r, 0.5)
    assert max(r.levels) == pytest.approx(0.40, abs=1e-6)
    assert r.e._burst == 0.0


def test_config_writes_never_reset_a_pulse_in_flight(rig):
    r = rig(energy=1.0)
    settle(r)
    sharp_hit(r)
    r.frame(0.1)
    env = r.e._env
    hits = len(r.e.hits)
    r.write(gradient="#0000ff")
    r.tween(phase_progress=0.0, brightness=0.9)  # a tween frame, as _advance_tweens lands it
    assert r.e._env == env and len(r.e.hits) == hits
    r.frame(0.1)
    assert 0.0 < r.e._env < env


def test_the_first_audio_frame_is_not_a_hit(rig):
    """Switched on mid-song, it must not read the music it walked into as
    one big hit."""
    r = rig(energy=1.0)
    r.feed([0.8] * 5)
    assert len(r.e.hits) == 0


# ── the flash budget ────────────────────────────────────────────────────────

def _hit_train(r: Rig, per_s: float, seconds: float):
    period = int(round(FPS / per_s))
    for k in range(int(seconds * FPS)):
        r.frame(1.0 if k % period == 0 else 0.1)


def test_dense_full_depth_hits_stay_inside_three_flashes_a_second(rig):
    r = rig(energy=1.0)
    settle(r)
    _hit_train(r, 8.0, 6.0)
    out = np.max(np.asarray(r.out), axis=1) / 255.0
    assert h.max_rise_per_second(out) <= 3.0 + 1e-6
    limited = [x for x in r.e.hits if x[5] < x[4] - 1e-6]
    assert limited, "the budget must have shrunk some hits"
    # every hit still gets something once there is budget again
    assert max(out[-int(FPS):]) > 0.5


def test_the_control_goes_red_without_the_budget(rig):
    r = rig(energy=1.0, max_flash_rate=20.0)
    settle(r)
    _hit_train(r, 8.0, 6.0)
    out = np.max(np.asarray(r.out), axis=1) / 255.0
    assert h.max_rise_per_second(out) > 4.0


def test_calm_pulses_are_never_shrunk(rig):
    r = rig(energy=0.0)
    settle(r)
    _hit_train(r, 8.0, 6.0)
    assert not [x for x in r.e.hits if x[5] < x[4] - 1e-6]


def test_the_budget_is_a_setting(rig):
    r = rig(energy=1.0, max_flash_rate=1.5)
    settle(r)
    _hit_train(r, 8.0, 6.0)
    out = np.max(np.asarray(r.out), axis=1) / 255.0
    assert h.max_rise_per_second(out) <= 1.5 + 1e-6


# ── charge, lull, drop (the keys the engine will push in phase 2) ─────────

def _ramp(r: Rig, phase: str, seconds: float, x: float = 0.1, hits_every: int = 0):
    r.write(phase=phase, phase_progress=0.0)
    n = int(seconds * FPS)
    for k in range(n):
        r.tween(phase_progress=min(1.0, (k + 1) / n))
        r.frame(1.0 if hits_every and k % hits_every == 0 else x)


def test_a_charge_builds_to_its_top_and_still_pulses(rig):
    r = rig(energy=1.0)
    settle(r)
    _ramp(r, "charge", 4.0, hits_every=30)
    assert r.e._rest == pytest.approx(0.80)
    for k in range(90):                 # the ramp's hang: progress held at 1
        r.frame(1.0 if k % 30 == 0 else 0.1)
    last = np.asarray(r.levels[-90:])
    assert last.min() >= 0.80 - 1e-6
    assert last.max() - last.min() >= 0.12 - 1e-6   # pulses never vanish
    # it climbed steadily: the resting level never stepped down
    rests = []
    r2 = rig(energy=1.0)
    settle(r2)
    r2.write(phase="charge", phase_progress=0.0)
    for k in range(240):
        r2.tween(phase_progress=(k + 1) / 240)
        r2.frame(0.1)
        rests.append(r2.e._rest)
    assert np.all(np.diff(rests) >= -1e-9)


@pytest.mark.parametrize("seconds", [0.9, 1.2, 5.4])
def test_a_lull_reaches_black_exactly_when_its_ramp_completes(rig, seconds):
    r = rig(energy=1.0)
    settle(r)
    _ramp(r, "charge", 3.0, hits_every=30)
    _ramp(r, "lull", seconds, hits_every=25)   # hits keep landing in a lull
    assert r.levels[-1] == 0.0
    assert np.all(r.out[-1] == 0.0)
    # it faded, it did not drop out at the end
    lull = np.asarray(r.levels[-int(seconds * FPS):])
    assert lull[0] > 0.6 and lull[len(lull) // 2] > 0.05


def test_a_drop_bursts_on_its_mark_whitened_then_settles_and_rearms(rig):
    r = rig(energy=1.0, beat_ms=500.0)
    settle(r)
    _ramp(r, "lull", 1.0)
    assert r.levels[-1] == 0.0
    r.write(phase="drop", phase_progress=0.0)
    r.frame(0.1)
    assert r.levels[-1] == pytest.approx(1.0)
    px = r.out[-1]
    assert px[0] == pytest.approx(255.0) and px[1] == pytest.approx(255.0 * 0.45)
    r.feed([0.1] * int(3.0 * FPS))          # 2 beats to settle, then some
    assert r.e._phase == "none" and r.e._config["phase"] == "none"
    assert r.levels[-1] == pytest.approx(0.22, abs=0.01)
    r.write(phase="drop", phase_progress=0.0)   # an identical later drop edges
    r.frame(0.1)
    assert r.levels[-1] == pytest.approx(1.0)


def test_a_drop_is_never_shrunk_but_spends_the_budget(rig):
    r = rig(energy=1.0)
    settle(r)
    _hit_train(r, 8.0, 2.0)                    # the budget is spent
    r.write(phase="drop", phase_progress=0.0)
    r.frame(0.1)
    assert r.levels[-1] == pytest.approx(1.0)


def test_a_charge_ending_without_a_drop_eases_back(rig):
    r = rig(energy=1.0)
    settle(r)
    _ramp(r, "charge", 3.0)
    r.write(phase="none")
    settle(r, 1.5)
    seg = np.asarray(r.levels[-int(1.5 * FPS) - 1:])
    assert seg[0] == pytest.approx(0.80, abs=0.01)
    assert np.abs(np.diff(seg)).max() < 0.03   # no snap
    assert seg[-1] == pytest.approx(0.22, abs=0.01)


def test_an_orphaned_lull_releases_itself(rig):
    from fx.effects import particle_handoff
    r = rig(energy=1.0)
    settle(r)
    _ramp(r, "lull", 1.0)
    settle(r, particle_handoff.PHASE_GRACE_S + 2.5)
    assert r.e._phase == "none" and r.e._config["phase"] == "none"
    assert r.levels[-1] == pytest.approx(0.22, abs=0.01)


# ── the registry, the real virtual pipeline, the real audio path ───────────

def _run_async(coro):
    return asyncio.run(coro)


def test_registered_as_pulse_and_renders_through_a_virtual(tmp_path):
    async def main():
        host = await headless.start_headless_host(
            str(tmp_path / "fx"), pixel_count=1, rows=1, device_id="single")
        try:
            v = host.virtuals.get("single")
            with headless.fake_clock() as clock:
                e = headless.attach_effect(host, v, "pulse",
                                           {"gradient": RED, "energy": 0.0})
                assert type(e).__name__ == "PulseAudioEffect" and e.NAME == "Pulse"
                assert e.pixel_count == 1
                frames = headless.render_frames(v, 30, clock=clock)
        finally:
            await host.shutdown()
        return frames

    frames = _run_async(main())
    assert frames[-1][0] == pytest.approx(np.array([255.0, 0, 0]) * 0.40**2.2, abs=0.5)


def _bass_bursts(seconds: float, per_s: float = 2.0) -> np.ndarray:
    rate = 44100
    n = int(seconds * rate)
    out = np.zeros(n, dtype=np.float32)
    burst = int(0.12 * rate)
    t = np.arange(burst) / rate
    tone = (0.6 * np.sin(2 * np.pi * 60 * t) + 0.3 * np.sin(2 * np.pi * 120 * t))
    tone *= np.exp(-t / 0.05)
    step = int(rate / per_s)
    for start in range(int(0.5 * rate), n - burst, step):
        out[start:start + burst] += tone.astype(np.float32)
    return out


def test_the_live_audio_path_hears_bass_hits(tmp_path, monkeypatch):
    """The real melbank pipeline (HubMelbankSource, what SPECTRA's live stack
    installs) feeding the real effect: hits land on the bursts, and the
    detector's signal is exactly lows + 2 x the virtual's own melbank mean."""
    from fx.effects import audio as fx_audio

    pcm = _bass_bursts(4.0)
    hop = 44100 // 60

    async def main():
        host = await headless.start_headless_host(
            str(tmp_path / "fx"), pixel_count=1, rows=1, device_id="single")
        monkeypatch.setattr(fx_audio, "AudioAnalysisSource", HubMelbankSource)
        mel = HubMelbankSource(host)
        host.audio = mel
        checks = []
        try:
            v = host.virtuals.get("single")
            with headless.fake_clock() as clock:
                e = headless.attach_effect(host, v, "pulse",
                                           {"gradient": RED, "energy": 1.0, "beat_ms": 500.0})
                for i in range(len(pcm) // hop):
                    before = e._audio_t
                    mel.ingest(pcm[i * hop:(i + 1) * hop])
                    if e._audio_t > before and i % 7 == 0:
                        want = float(np.max(mel.lows_power(filtered=False))) + 2.0 * float(
                            np.mean(e.melbank(filtered=False)))
                        checks.append((e.last_signal, want))
                    headless.render_frames(v, 1, clock=clock)
                hits = [x[0] for x in e.hits]
        finally:
            await host.shutdown()
        return hits, checks

    hits, checks = _run_async(main())
    assert checks and all(a == pytest.approx(b) for a, b in checks)
    bursts = np.arange(0.5, 4.0 - 0.12, 0.5)
    # every burst made a hit within a few frames of its start
    for b in bursts:
        assert any(-DT <= x - b <= 0.1 for x in hits), (b, hits)
    assert len(hits) <= 2 * len(bursts)


# ── his songs ───────────────────────────────────────────────────────────────

_TRACES: dict = {}


def song(slug: str):
    if slug not in _TRACES:
        meta, arrays = h.load_fixture(slug)
        scale = h.SONGS[slug]["scale"]
        cfg = h.full_config(h.base_config(meta, scale))
        tr = h.run(meta, arrays, scale=scale)
        _TRACES[slug] = (meta, arrays, cfg, tr, h.measure(tr, meta, arrays, cfg))
    return _TRACES[slug]


SLUGS = list(h.SONGS)


@pytest.mark.parametrize("slug", SLUGS)
def test_his_songs_make_hits_at_a_musical_rate(slug):
    *_rest, m = song(slug)
    assert 75.0 <= m["hits_per_min"] <= 135.0, m["hits_per_min"]


@pytest.mark.parametrize("slug", SLUGS)
def test_his_songs_rise_between_one_frame_and_the_soft_rise(slug):
    _meta, _arr, _cfg, tr, m = song(slug)
    rises = h.rise_times_ms(tr)
    assert len(rises) >= 5
    assert rises.min() >= 1000 * DT - 1e-6
    assert rises.max() <= 160.0 + 1000 * DT + 1e-6
    p10, _p50, p90 = m["planned_rise_ms"]
    assert p10 < 60.0 and p90 > 120.0       # the whole range is in use


@pytest.mark.parametrize("slug", ["dopamine", "contra", "soypeor"])
def test_his_songs_fade_faster_when_intense(slug):
    _meta, _arr, _cfg, _tr, m = song(slug)
    for band in ("fade_hi", "fade_lo"):
        ratio, n = m[band]
        assert 0.85 <= ratio <= 1.3, (band, m[band])  # measured / nominal
    assert m["fade_hi_s"] < 0.7 * m["fade_lo_s"]


def test_calm_music_moves_subtly_but_visibly():
    """Let It Be at half intensity: Power held it inside 0.640-0.645."""
    _meta, _arr, cfg, tr, m = song("letitbe")
    swing = m["level_p95"] - m["level_p5"]
    assert 0.10 <= swing <= 0.35, swing
    assert m["swing_lo"] >= 2 * cfg["min_pulse"]
    out8 = tr.out * 255.0
    assert np.percentile(out8, 95) - np.percentile(out8, 5) >= 10.0   # 8-bit steps
    assert m["max_rise_per_s"] < 1.5        # a calm song never nears the cap


@pytest.mark.parametrize("slug", ["dopamine", "contra", "soypeor"])
def test_intense_sections_swing_far_more_than_calm_ones(slug):
    *_rest, m = song(slug)
    assert m["swing_hi"] > 2.0 * m["swing_lo"]
    assert m["level_p95"] - m["level_p5"] > 0.35   # Power: 0.07


@pytest.mark.parametrize("slug", SLUGS)
def test_his_songs_never_flash_past_the_budget(slug):
    _meta, _arr, cfg, _tr, m = song(slug)
    assert m["max_rise_per_s"] <= cfg["max_flash_rate"] + 0.05


@pytest.mark.parametrize("slug", ["dopamine", "contra"])
def test_his_builds_climb_go_black_on_time_and_burst(slug):
    _meta, _arr, cfg, _tr, m = song(slug)
    lulls = [p for p in m["phases"] if p["cls"] == "lull" and "before_drop" in p]
    drops = [p for p in m["phases"] if p["cls"] == "drop"]
    charges = [p for p in m["phases"] if p["cls"] == "charge"]
    assert lulls and drops and charges
    for p in lulls:
        assert p["before_drop"] == 0.0, p
    for p in drops:
        assert p["peak_100ms"] == pytest.approx(cfg["drop_burst"]), p
    for p in charges:
        assert p["end_rest"] == pytest.approx(cfg["charge_top"]), p
        assert p["start_rest"] < 0.45, p


@pytest.mark.parametrize("slug", SLUGS)
def test_hits_mostly_land_on_analysed_onsets(slug):
    *_rest, m = song(slug)
    assert m["onset_agreement_pct"] >= 55.0
