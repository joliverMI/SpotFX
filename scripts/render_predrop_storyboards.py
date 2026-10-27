#!/usr/bin/env python3
"""THE PRE-DROP STORYBOARDS (predrop plan steps 6-8, report 3.4-3.5):
Fireworks, Pulse, Orbits, Black Hole, the Fish, Star and Sauron rendered
offline through the shipped effects, today and with each kind of pre-drop,
driven by the lull arm the real engine writes (tests/pre_drop_look_harness.py
— the same rig the tests use).

It is the tuning loop and a proof at once. It writes to
docs/evidence/predrop-storyboards/:

  fireworks_<clip>.png / .gif  his crystal's 976 real cells (gap cells grey)
                               through the lull and the drop, one frame per
                               0.2 s on the sheet (and orbits_<clip>,
                               blackhole_<clip>, fish_<clip>, star_<clip>,
                               sauron_<clip>, the same clips, plus
                               star_spike_0.8s_newset: the set changing at
                               the pre-drop);
  pulse_levels.png             Pulse's level on one light over the lull and
                               the drop, today (dashed) and with a pre-drop,
                               for Winny's spike gap, his 2 s maximum and
                               Dopamine's vocal intro;
  README.md                    the light over the lull (report 3.5's measure)
                               and Pulse's measured curve, as printed here.

and FAILS (exit 1) unless: each effect without a pre-drop is today's frame
for frame against its own module before the looks (pinned out of git);
Fireworks is black in every frame of the breath and its light over the lull
is below today's; Pulse is black through the breath and its dark span, the
span a quarter of the gap clamped to 100-500 ms; Orbits is dim, never black,
through the breath and its light is below today's at the plan's 0.8 s gap
(within +20% at a longer one — a named deviation); Black Hole is black
through the breath and its light is below today's at every gap; the Fish is
never dark and its light is within the plan's own named +4%; Star and Sauron
are black through the breath and their light is below today's at every gap;
Star's drop wears the set as it is at the drop.

Run from the repo root: .venv/bin/python scripts/render_predrop_storyboards.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import pre_drop_look_harness as H  # noqa: E402
from fx.effects import phase_grammar  # noqa: E402
from fx.effects import pulse as pulse_mod  # noqa: E402

OUT = REPO / "docs" / "evidence" / "predrop-storyboards"
MASK = H.crystal_real_mask()
SCALE = 4
EPS = 1e-6

# (name, lull s, gap s or None, kind)
FW_CLIPS = [("today_3s", 3.2, None, ""), ("spike_0.8s", 3.2, 0.8, "spike"),
            ("spike_2s", 3.2, 2.0, "spike"), ("today_6s", 6.0, None, ""),
            ("intro_3.3s", 6.0, 3.3, "intro")]
PULSE_CASES = [("Spike, Winny 627 ms", 3.2, 0.627, "spike"),
               ("Spike, his max 2000 ms", 3.2, 2.0, "spike"),
               ("Vocal intro, Dopamine 3295 ms", 6.0, 3.295, "intro")]


def arms_for(effect, lull, gap, kind):
    if gap is None:
        return H.engine_arms(effect, lull)
    return H.engine_arms(effect, lull, at_s=lull - gap, gap_s=gap, kind=kind)


def crystal_image(frame: np.ndarray) -> Image.Image:
    f = np.clip(np.asarray(frame, dtype=np.float32), 0, 255).reshape(
        H.ROWS, H.COLS, 3)
    if MASK is not None:
        gap = ~MASK.reshape(H.ROWS, H.COLS)
        f = f.copy()
        f[gap] = 18.0
    img = Image.fromarray(f.astype(np.uint8), "RGB")
    return img.resize((H.COLS * SCALE, H.ROWS * SCALE), Image.NEAREST)


def fw_sheet(name, run, lull, gap, prefix="fireworks") -> None:
    lull_rows = [(t, f) for (ph, t), f in zip(run.phase, run.frames)
                 if ph == "lull"]
    drop_rows = [(t, f) for (ph, t), f in zip(run.phase, run.frames)
                 if ph == "drop"]
    picks = [(t, f, "lull") for t, f in lull_rows
             if abs((t / 0.2) - round(t / 0.2)) < 0.5 * H.DT / 0.2]
    picks += [(t, f, "drop") for t, f in drop_rows if t in
              {drop_rows[k][0] for k in (0, 6, 18, 36) if k < len(drop_rows)}]
    w, h = H.COLS * SCALE, H.ROWS * SCALE + 14
    cols = 8
    sheet = Image.new("RGB", (cols * (w + 4), ((len(picks) + cols - 1) // cols)
                              * (h + 4)), (8, 4, 14))
    d = ImageDraw.Draw(sheet)
    for k, (t, f, ph) in enumerate(picks):
        x, y = (k % cols) * (w + 4), (k // cols) * (h + 4)
        sheet.paste(crystal_image(f), (x, y + 14))
        mark = ""
        if gap is not None and ph == "lull":
            at = lull - gap
            mark = (" breath" if at - 0.4 - EPS <= t < at - EPS
                    else " pre-drop" if t >= at - EPS else "")
        d.text((x + 2, y + 1), f"{ph} {t:.1f}s{mark}", fill=(200, 190, 230))
    sheet.save(OUT / f"{prefix}_{name}.png")
    frames = [crystal_image(f) for (ph, _), f in zip(run.phase, run.frames)
              if ph in ("lull", "drop")][::4]
    frames[0].save(OUT / f"{prefix}_{name}.gif", save_all=True,
                   append_images=frames[1:], duration=66, loop=0)


def light_split(run, lull, gap):
    rows = [(t, H.light(f, MASK)) for t, f, _ in H.lull_frames(run)]
    at = lull - (gap if gap is not None else 0.8)
    before = [v for t, v in rows if t < at - EPS]
    after = [v for t, v in rows if t >= at - EPS]
    return (float(np.mean(before)), float(np.mean(after)),
            sum(v for _, v in rows) * H.DT)


def pulse_chart(results) -> None:
    W, Hh, pad = 900, 200, 40
    img = Image.new("RGB", (W, (Hh + pad) * len(results) + 10), (8, 4, 14))
    d = ImageDraw.Draw(img)
    for k, (label, lull, gap, today, told) in enumerate(results):
        y0 = k * (Hh + pad) + 24
        t0, t1 = -lull - 0.3, 1.2
        X = lambda t: 50 + (t - t0) / (t1 - t0) * (W - 70)      # noqa: E731
        Y = lambda v: y0 + (1 - v) * Hh                       # noqa: E731
        dark = pulse_mod.pre_drop_dark_s(gap)
        d.rectangle([X(-dark), y0, X(0), y0 + Hh], fill=(26, 22, 34))
        d.rectangle([X(-gap - 0.4), y0, X(-gap), y0 + Hh], fill=(30, 34, 44))
        d.line([X(0), y0, X(0), y0 + Hh], fill=(236, 72, 153))
        d.line([X(-gap), y0, X(-gap), y0 + Hh], fill=(251, 146, 60))
        d.text((54, y0 - 18), f"{label}: breath, pre-drop (orange), "
               f"dark {dark * 1000:.0f} ms, drop (pink)", fill=(200, 190, 230))
        for series, colour, dash in ((today, (149, 133, 181), True),
                                     (told, (255, 255, 255), False)):
            pts = [(X(t), Y(v)) for t, v in series if t0 <= t <= t1]
            for j in range(1, len(pts)):
                if dash and (j // 4) % 2:
                    continue
                d.line([pts[j - 1], pts[j]], fill=colour, width=2)
    img.save(OUT / "pulse_levels.png")


def pulse_series(run, lull):
    out = []
    for (ph, t), inf in zip(run.phase, run.info):
        if ph == "lull":
            out.append((t - lull, inf["level"]))
        elif ph == "drop":
            out.append((t, inf["level"]))
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="predrop_storyboards_"))
    problems: list[str] = []
    lines = ["# Pre-drop storyboards (predrop plan steps 6-8)", "",
             "Rendered by `scripts/render_predrop_storyboards.py` through the "
             "shipped effects, driven by the lull arm the real engine writes. "
             "Light: each real cell's brightest channel / 255, summed over the "
             "crystal's 976 real cells (cells at full), averaged over the lull "
             "before the pre-drop and from the pre-drop to the drop (for a "
             "\"today\" clip, the same stretches of its lull); the whole lull "
             "is cells at full x seconds.", "",
             "## Fireworks", "",
             "| Clip | Lull before the pre-drop | Pre-drop to drop | Whole lull "
             "| vs today |", "|---|---:|---:|---:|---:|"]

    # Fireworks: today unchanged, then each clip
    pinned = H.load_pinned("fireworks", "fireworks_prelook", "pre_drop")
    arms = arms_for("fireworks", 3.2, None, "")
    now = H.run_async(H.fireworks_run(tmp, "fireworks", arms))
    then = H.run_async(H.fireworks_run(
        tmp, pinned, {k: H.todays_arm(a, "fireworks") for k, a in arms.items()}))
    same = (len(now.frames) == len(then.frames) and all(
        np.array_equal(a, b) for a, b in zip(now.frames, then.frames)))
    if not same:
        problems.append("Fireworks without a pre-drop is not today's")
    today = {}
    for name, lull, gap, kind in FW_CLIPS:
        run = H.run_async(H.fireworks_run(
            tmp, "fireworks", arms_for("fireworks", lull, gap, kind), lull_s=lull))
        fw_sheet(name, run, lull, gap)
        a, b, whole = light_split(run, lull, gap)
        if gap is None:
            today[lull] = whole
            vs = ""
        else:
            vs = f"{100 * (whole / today[lull] - 1):+.0f}%"
            if whole >= today[lull]:
                problems.append(f"Fireworks {name}: lull light not below today's")
            at = lull - gap
            p = H.engine_arms("fireworks", lull, at_s=at, gap_s=gap,
                              kind=kind)["lull"].params
            breath_at = p[phase_grammar.BREATH_AT_KEY]
            black = all(float(f.max()) == 0.0 for t, f, _ in H.lull_frames(run)
                        if breath_at + H.DT - EPS <= t < at - EPS)
            if not black:
                problems.append(f"Fireworks {name}: not black through the breath")
        lines.append(f"| {name} (lull {lull} s) | {a:.1f} | {b:.1f} | "
                     f"{whole:.0f} | {vs} |")
    lines += ["", f"Without a pre-drop, frame for frame against the module "
              f"before the looks ({H.PRE_REF[:8]}): "
              f"{'unchanged' if same else 'CHANGED'}.", "", "## Pulse", "",
              "| Case | Peak in the gap | Dark before the drop | Black through "
              "the breath | Whole lull light (x today) |",
              "|---|---:|---:|---|---:|"]

    # Pulse: today unchanged, then each case
    pinned_p = H.load_pinned("pulse", "pulse_prelook", "pre_drop")
    arms = arms_for("pulse", 3.2, None, "")
    now = H.pulse_run(arms)
    then = H.pulse_run({k: H.todays_arm(a, "pulse") for k, a in arms.items()},
                       module=pinned_p)
    same_p = [i["level"] for i in now.info] == [i["level"] for i in then.info]
    if not same_p:
        problems.append("Pulse without a pre-drop is not today's")
    chart = []
    for label, lull, gap, kind in PULSE_CASES:
        at = lull - gap
        plain = H.pulse_run(arms_for("pulse", lull, None, ""), lull_s=lull)
        told_arms = arms_for("pulse", lull, gap, kind)
        told = H.pulse_run(told_arms, lull_s=lull)
        breath_at = told_arms["lull"].params[phase_grammar.BREATH_AT_KEY]
        rows = [(t, i["level"], i["lin"]) for t, _, i in H.lull_frames(told)]
        breath_black = all(lv == 0.0 for t, lv, _ in rows
                           if breath_at + H.DT - EPS <= t < at - EPS)
        lit = [t for t, lv, _ in rows if t >= at - EPS and lv > 0.0]
        dark = lull - (lit[-1] + H.DT) if lit else gap
        want = pulse_mod.pre_drop_dark_s(gap)
        peak = max(lv for t, lv, _ in rows if t >= at - EPS)
        if not breath_black:
            problems.append(f"Pulse {label}: not black through the breath")
        if abs(dark - want) > H.DT + EPS:
            problems.append(f"Pulse {label}: dark {dark:.3f} s, want {want:.3f}")
        lin_today = sum(i["lin"] for _, _, i in H.lull_frames(plain))
        lin_told = sum(lin for _, _, lin in rows)
        lines.append(f"| {label} | {peak:.2f} | {dark * 1000:.0f} ms | "
                     f"{'yes' if breath_black else 'NO'} | "
                     f"{lin_told / max(lin_today, 1e-9):.2f} |")
        chart.append((label, lull, gap, pulse_series(plain, lull),
                      pulse_series(told, lull)))
    pulse_chart(chart)
    lines += ["", f"Without a pre-drop, level for level against the module "
              f"before the looks: {'unchanged' if same_p else 'CHANGED'}. "
              "Pulse's light is delivered light (level ^ gamma) summed over "
              "the lull; the spike's burst is the look he asked for, so it can "
              "add light where the lull is short.", ""]

    # Orbits and Black Hole (step 7): today unchanged, then each clip
    for effect, title in (("orbits", "Orbits"), ("blackhole", "Black Hole")):
        lines += [f"## {title}", "",
                  "| Clip | Lull before the pre-drop | Pre-drop to drop | "
                  "Whole lull | vs today |", "|---|---:|---:|---:|---:|"]
        cfg = H.STEP7_CFG[effect]
        pinned = H.load_pinned(effect, f"{effect}_prelook7",
                               H.STEP7_LACKS[effect], ref=H.STEP7_REF)
        arms = arms_for(effect, 3.2, None, "")
        now = H.run_async(H.crystal_run(tmp, effect, arms, cfg))
        then = H.run_async(H.crystal_run(
            tmp, pinned, {k: H.todays_arm(a, effect) for k, a in arms.items()},
            cfg))
        same7 = (len(now.frames) == len(then.frames) and all(
            np.array_equal(a, b) for a, b in zip(now.frames, then.frames)))
        if not same7:
            problems.append(f"{title} without a pre-drop is not today's")
        today = {}
        for name, lull, gap, kind in FW_CLIPS:
            run = H.run_async(H.crystal_run(
                tmp, effect, arms_for(effect, lull, gap, kind), cfg,
                lull_s=lull))
            fw_sheet(name, run, lull, gap, prefix=effect)
            a, b, whole = light_split(run, lull, gap)
            if gap is None:
                today[lull] = whole
                vs = ""
            else:
                ratio = whole / today[lull]
                vs = f"{100 * (ratio - 1):+.0f}%"
                strict = effect == "blackhole" or gap <= 0.8 + EPS
                if strict and ratio >= 1.0:
                    problems.append(f"{title} {name}: lull light not below "
                                    "today's")
                if not strict and ratio > 1.20:
                    problems.append(f"{title} {name}: lull light past its "
                                    "named +20% bound")
                breath = [H.light(f, MASK) for (ph, t), f, i in zip(
                    run.phase, run.frames, run.info)
                    if ph == "lull" and i["segment"] == "breath"]
                if effect == "blackhole" and max(breath) > 0.0:
                    problems.append(f"{title} {name}: not black through the "
                                    "breath")
                if effect == "orbits" and min(breath) <= 0.0:
                    problems.append(f"{title} {name}: the dim blob went black")
            lines.append(f"| {name} (lull {lull} s) | {a:.1f} | {b:.1f} | "
                         f"{whole:.0f} | {vs} |")
        lines += ["", f"Without a pre-drop, frame for frame against the "
                  f"module before step 7 ({H.STEP7_REF[:8]}): "
                  f"{'unchanged' if same7 else 'CHANGED'}.", ""]
    lines += ["Orbits is back at full and growing for the whole gap, so a "
              "longer gap adds light: the plan's own prototype measured only "
              "the 0.8 s gap, where it is below today's; a 2 s spike and a "
              "3.3 s vocal intro run above it (named, bounded at +20%).", ""]

    # the Fish, Star and Sauron (step 8): today unchanged, then each clip
    star_scene = H.star_scene()

    def run8(effect, effect_type, lull, gap, kind, today_arm=False, **kw):
        arms = arms_for("radial" if effect == "star" else effect, lull, gap,
                        kind) if effect != "star" else H.engine_arms(
            "radial", lull, at_s=None if gap is None else lull - gap,
            gap_s=gap, kind=kind, scene=star_scene)
        if today_arm:
            arms = {k: H.todays_arm(a, "radial" if effect == "star"
                                    else effect) for k, a in arms.items()}
        if effect == "star":
            strip = H.engine_arms(
                "melt", lull, at_s=None if gap is None else lull - gap,
                gap_s=gap, kind=kind, scene=star_scene)
            return H.run_async(H.star_run(tmp, effect_type, arms, strip,
                                          lull_s=lull, **kw))
        info = H._fish_info if effect == "fish" else H._sauron_info
        return H.run_async(H.crystal_run(tmp, effect_type, arms,
                                         H.STEP8_CFG[effect], lull_s=lull,
                                         info=info, **kw))

    for effect, module, title in (("fish", "fish", "Fish"),
                                  ("star", "radial", "Star"),
                                  ("sauron", "sauron", "Sauron")):
        lines += [f"## {title}", "",
                  "| Clip | Lull before the pre-drop | Pre-drop to drop | "
                  "Whole lull | vs today |", "|---|---:|---:|---:|---:|"]
        pinned = H.load_pinned(module, f"{module}_prelook8",
                               H.STEP8_LACKS[module], ref=H.STEP8_REF)
        now = run8(effect, module, 3.2, None, "")
        then = run8(effect, pinned, 3.2, None, "", today_arm=True)
        same8 = (len(now.frames) == len(then.frames) and all(
            np.array_equal(a, b) for a, b in zip(now.frames, then.frames)))
        if not same8:
            problems.append(f"{title} without a pre-drop is not today's")
        today = {}
        for name, lull, gap, kind in FW_CLIPS:
            run = run8(effect, module, lull, gap, kind)
            fw_sheet(name, run, lull, gap, prefix=effect)
            a, b, whole = light_split(run, lull, gap)
            if gap is None:
                today[lull] = whole
                vs = ""
            else:
                ratio = whole / today[lull]
                vs = f"{100 * (ratio - 1):+.0f}%"
                lull_lit = [H.light(f, MASK) for _t, f, _i in H.lull_frames(run)]
                breath = [H.light(f, MASK) for (ph, t), f, i in zip(
                    run.phase, run.frames, run.info)
                    if ph == "lull" and i["segment"] == "breath"]
                if effect == "fish":
                    if ratio > 1.04:
                        problems.append(f"{title} {name}: lull light past the "
                                        "plan's named +4%")
                    if min(lull_lit) <= 0.0:
                        problems.append(f"{title} {name}: the lull went dark")
                else:
                    if ratio >= 1.0:
                        problems.append(f"{title} {name}: lull light not below "
                                        "today's")
                    if max(breath) > 0.0:
                        problems.append(f"{title} {name}: not black through "
                                        "the breath")
            lines.append(f"| {name} (lull {lull} s) | {a:.1f} | {b:.1f} | "
                         f"{whole:.0f} | {vs} |")
        lines += ["", f"Without a pre-drop, frame for frame against the "
                  f"module before step 8 ({H.STEP8_REF[:8]}): "
                  f"{'unchanged' if same8 else 'CHANGED'}.", ""]
        if effect == "star":
            # the set changes at the pre-drop (the colour fade, landed at
            # once): the drop's pieces come back out in the new set
            change = {("lull", int(round(2.4 / H.DT))): {
                "gradient": "linear-gradient(90deg, #ff2000 0%, "
                            "#ffa000 100%)"}}
            run = run8(effect, module, 3.2, 0.8, "spike",
                       strip_pokes=change)
            fw_sheet("spike_0.8s_newset", run, 3.2, 0.8, prefix=effect)
            if not any(i["snap_resampled"] for (ph, _t), i in zip(
                    run.phase, run.info) if ph == "drop"):
                problems.append("Star's drop did not take the set as it is "
                                "at the drop")
            lines += ["star_spike_0.8s_newset: the set changes to a warm one "
                      "at the pre-drop; the drop's pieces come back out in it "
                      "(today they keep the colours they fell in with).", ""]
    lines += ["The Fish takes no breath, so its lull is never dark; the "
              "plan's prototype measured it +4% (named), the build is at or "
              "below today's. Sauron ships at the plan's dimmer setting "
              "(the glare at 20% rising to 36%, the prototype's 35% to 60%).",
              ""]
    (OUT / "README.md").write_text("\n".join(lines))
    print("\n".join(lines))
    if problems:
        print("FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("OK: unchanged without a pre-drop; black where it must be; the "
          "Fireworks, Black Hole, Star and Sauron lulls below today's, Orbits' "
          "at the plan's gap, the Fish's within the plan's +4%.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
