"""Build data/star-improve-plan/explainer.html from the two render outputs
(render_star_improve_strips.py, render_star_improve_crystal.py).

Usage: .venv/bin/python scripts/build_star_improve_explainer.py PLAN_DIR
(PLAN_DIR holds render/ and receives explainer.html; sprites are referenced
relatively, so the page and render/ travel together.)
"""
from __future__ import annotations

import json
import os
import sys

plan = sys.argv[1]
R = os.path.join(plan, "render")
cells = json.load(open(os.path.join(R, "cells.json")))
tvl = json.load(open(os.path.join(R, "tv_layout.json")))  # 560 LED centres, HyperHDR layout, 0..1 of the screen
sm = json.load(open(os.path.join(R, "strips_measure.json")))
cm = json.load(open(os.path.join(R, "crystal_measure.json")))
T = cm["tiles"]
C = sm["cands"]


def pct(x):
    return f"{x * 100:.0f}%"


def strip_row(cid, mark=""):
    m = C[cid]
    return (f"<tr><td>{mark}{m['label']}</td><td>{pct(m['lit_frac_mean'])}"
            f" <span class=muted>({pct(m['lit_frac_min'])}–{pct(m['lit_frac_max'])})</span></td>"
            f"<td>{m['lum_mean']:.3f}</td><td>{m['peak_mean']:.2f}</td></tr>")


def tile(anim, cap, kind="hex", group=None, cls=""):
    g = group or anim
    return (f'<figure class="tile {kind} {cls}" data-anim="{anim}" data-group="{g}">'
            f'<canvas></canvas><figcaption>{cap}</figcaption></figure>')


def ctl(g):
    return (f'<div class="ctl"><button class="play" data-g="{g}">⏸</button>'
            f'<input type="range" min="0" max="1000" value="0" class="scrub" data-g="{g}">'
            f'<span class="time" data-g="{g}">0.0 s</span></div>')


def chart(g, series, ylabel, ymax=None):
    """series: list of (label, colourVar, key) read from SERIES[g] at runtime."""
    spec = json.dumps({"series": series, "ylabel": ylabel, "ymax": ymax})
    return f'<canvas class="chart" data-g="{g}" data-spec=\'{spec}\'></canvas>'


def q(n, title, body, rec):
    return (f'<div class="dec"><p>❓ <b>Q{n}</b> — <b>{title}</b>: {body}</p>'
            f'<p>➡️ {rec}</p></div>')


import base64


def data_uri(fn):
    with open(os.path.join(R, fn), "rb") as fh:
        return "data:image/png;base64," + base64.b64encode(fh.read()).decode()


# sprites are embedded: a file:// page cannot getImageData from a sibling PNG
SPR = {}
for name in T:
    SPR[name] = {"src": data_uri(f"star_{name}.png"), "kind": "hex"}
for cid in C:
    SPR["s_" + cid] = {"src": data_uri(f"strip_{cid}.png"), "kind": "strip"}

SERIES = {
    "entry": {k: T[k]["rev_s"] for k in ("entry_today_zero", "entry_today_spin", "entry_prop")},
    "cap": {k: T[k]["rev_s"] for k in ("cap_today", "cap_prop")},
    "starw": {k: T[k]["star"] for k in ("star_today", "star_his", "star_flat_sym", "star_flat_up")},
    "edges": {k: T[k]["edges"] for k in ("edges_today", "edges_prop")},
    "impulse": cm["impulse"],
}

ceil_today = cm["ceil_today_rev_s"]
cap = cm["cap_rev_s"]

html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>STAR improve plan</title>
<style>
:root{{--bg:#0a0612;--surface:#140d1f;--surface2:#1f1430;--border:#372552;--accent:#a855f7;--accent2:#e879f9;--text:#ece7f7;--muted:#9585b5;--ok:#4ade80;--warn:#d9a441;--danger:#f87171;--radius:10px;--cur:#c2781c;--prop:#a855f7;--prop2:#22d3ee;--prop3:#4ade80;--font:'Inter',system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
*{{box-sizing:border-box;min-width:0}}html,body{{margin:0;background:var(--bg);color:var(--text);font-family:var(--font);line-height:1.5;overflow-x:hidden}}
main{{max-width:1060px;margin:0 auto;padding:16px}}h1{{font-size:1.5rem;margin:.3em 0 .1em;color:var(--accent2);line-height:1.2}}
h2{{font-size:1.2rem;margin:1.8em 0 .5em;color:var(--accent);border-bottom:1px solid var(--border);padding-bottom:.3em}}h3{{font-size:1.02rem;margin:1.1em 0 .4em}}
p{{margin:.5em 0}}.muted{{color:var(--muted)}}.small{{font-size:.85rem}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px;margin:10px 0}}
.pill{{display:inline-block;padding:1px 9px;border-radius:999px;font-size:.76rem;font-weight:600;border:1px solid var(--border);white-space:nowrap;vertical-align:middle;margin-right:4px}}
.p-cur{{background:var(--cur);color:#fff;border:0}}.p-prop{{background:var(--prop);color:#fff;border:0}}
blockquote{{margin:.6em 0;padding:.6em 1em;border-left:3px solid var(--accent);background:var(--surface2);border-radius:0 var(--radius) var(--radius) 0;font-size:.95rem}}
code{{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.82em;background:var(--surface2);padding:1px 5px;border-radius:4px;word-break:break-word}}
table{{border-collapse:collapse;width:100%;font-size:.88rem}}th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--border);vertical-align:top}}th{{color:var(--muted);font-weight:600}}
.tscroll{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
button{{background:var(--surface2);color:var(--text);border:1px solid var(--border);border-radius:999px;padding:5px 12px;font:inherit;font-size:.85rem;cursor:pointer}}
.pair{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px;align-items:start;margin:8px 0}}
.pair.multi{{grid-template-columns:repeat(auto-fit,minmax(min(100%,230px),1fr))}}
.pair.tvpair{{grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr))}}
.pair.strips{{grid-template-columns:1fr}}
.pair .ctl{{grid-column:1/-1;display:flex;align-items:center;gap:10px}}.ctl input{{flex:1;min-width:0}}.ctl .time{{font-variant-numeric:tabular-nums;font-size:.8rem;color:var(--muted);width:3.6em;text-align:right}}
.tile{{margin:0;background:#07060b;border:1px solid var(--border);border-radius:8px;overflow:hidden}}.tile canvas{{display:block;width:100%;height:auto;aspect-ratio:72/37}}
.tile.strip canvas{{aspect-ratio:14/1}}.tile.tv canvas{{aspect-ratio:16/10}}.tile figcaption{{font-size:.78rem;padding:4px 8px;color:var(--muted)}}
.tile.today{{border-color:var(--cur)}}.tile.today figcaption::before{{content:"TODAY · ";color:var(--cur);font-weight:700}}
.tile.prop figcaption::before{{content:"PROPOSAL · ";color:var(--accent2);font-weight:700}}
.chart{{grid-column:1/-1;width:100%;height:124px;display:block;background:var(--surface2);border-radius:8px}}
.dec{{border:1px dashed var(--accent);padding:10px;border-radius:8px;margin:8px 0}}
.stat{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,140px),1fr));gap:8px}}.stat div{{background:var(--surface2);border-radius:8px;padding:8px}}.stat b{{display:block;font-size:1.3rem;color:var(--accent2)}}
.num{{font-variant-numeric:tabular-nums}}
@media (max-width:560px){{.pair{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>STAR — the improve plan, pictures first</h1>
<p class="small muted">Every tile is the real render pipeline offline (fx.headless, the real 976 crystal cells, a real Melt strip under the real Radial; strips at the TV's own 560 px), one scripted song and one seed on every tile. Colour set: {sm['palette']}. Numbers beside a tile are measured on the frames you are looking at. Nothing here touched the room.</p>
<blockquote>His ask (2026-11-12): “I want to improve the star scene. Currently, when it shows up, it is not dynamic at all, and once there is an update, it starts to spin. I want it to be able to spin from the beginning. It should also cap the max speed it can spin to 70% of what it is now, but it shouldn't slow down at lower speeds. Also, the amount of star should dynamically change with the music. Keep it somewhat subtle, but it should constantly be flowing and bouncing between the top and bottom values for that setting. Flares should change the number of edges, but do it visually smoothly like we have. The melt (which is used as the effect for radial) should have more "dark blobs" so that the whole effect isn't as overpoweringly bright compared to other effects in dark mode … Try to match the perceived brightness of other effects a little closer, but it is okay if it is still the brightest. The TV currently has blobs all moving from the right to the left along the top and bottom because of how it is segmented. Make it work more radially, like the other round strips (sconces).”</blockquote>
<p class="small">Rounds 1 and 2 are settled; his round-2 words: “q10, it can slow to a stop during quiet music. q11: try .3 to .7 (assuming .5 is flat, which i think it is). all other defaults on the start questions”. Each section below now shows the DECIDED option beside today. One thing to check by eye in §5: <b>flat is star = 0, not 0.5</b> — the frozen shapes there show what 0.3, 0.5 and 0.7 actually look like, and two ranges symmetric about flat are rendered beside his 0.30↔0.70.</p>

<h2>1 · The strips: Melt is the brightest strip by a wide margin</h2>
<p class="small">All five strips below ran the same 14 s of the same audio on 560 px in dark mode (background black). <b>Lit</b> = share of the strip above 8% brightness; <b>luminance</b> = mean perceived brightness of the whole strip (0..1); <b>peak</b> = the brightest pixel's level.</p>
<div class="card"><div class="pair strips" data-pairgroup="strips">
{tile('s_melt_today', C['melt_today']['label'] + f" — lit {pct(C['melt_today']['lit_frac_mean'])}, luminance {C['melt_today']['lum_mean']:.3f}", 'strip', 'strips', 'today')}
{tile('s_blackhole1d', C['blackhole1d']['label'] + f" — lit {pct(C['blackhole1d']['lit_frac_mean'])}, luminance {C['blackhole1d']['lum_mean']:.3f}", 'strip', 'strips')}
{tile('s_orbits1d', C['orbits1d']['label'] + f" — lit {pct(C['orbits1d']['lit_frac_mean'])}, luminance {C['orbits1d']['lum_mean']:.3f}", 'strip', 'strips')}
{tile('s_fireworks1d', C['fireworks1d']['label'] + f" — lit {pct(C['fireworks1d']['lit_frac_mean'])}, luminance {C['fireworks1d']['lum_mean']:.3f}", 'strip', 'strips')}
{tile('s_orbits1d_dim', C['orbits1d_dim']['label'] + f" — lit {pct(C['orbits1d_dim']['lit_frac_mean'])}, luminance {C['orbits1d_dim']['lum_mean']:.3f}", 'strip', 'strips')}
{ctl('strips')}</div></div>

<h3>Melt with more dark: two ways to make the gaps</h3>
<p class="small">Melt's brightness along the strip is a sine-of-sine wave squared, so it is never black between blobs — that is the 61%. Two candidate knobs, both a single new Melt param that defaults to “off” (every other Melt, House Star and House Fish included, stays byte-identical): <b>value power</b> keeps every blob's peak and darkens the slopes; <b>dark floor</b> cuts everything below a level to black, so the blobs become separate islands with real gaps between them (the look the particle strips have).</p>
<div class="card"><div class="pair strips" data-pairgroup="melts">
{tile('s_melt_today', 'Melt today — lit ' + pct(C['melt_today']['lit_frac_mean']) + ', luminance ' + f"{C['melt_today']['lum_mean']:.3f}", 'strip', 'melts', 'today')}
{tile('s_melt_gamma2', 'A1 · value² — lit ' + pct(C['melt_gamma2']['lit_frac_mean']) + ', luminance ' + f"{C['melt_gamma2']['lum_mean']:.3f}", 'strip', 'melts', 'prop')}
{tile('s_melt_gamma3', 'A2 · value³ — lit ' + pct(C['melt_gamma3']['lit_frac_mean']) + ', luminance ' + f"{C['melt_gamma3']['lum_mean']:.3f}", 'strip', 'melts', 'prop')}
{tile('s_melt_cut35', 'B1 · dark floor 0.35 — lit ' + pct(C['melt_cut35']['lit_frac_mean']) + ', luminance ' + f"{C['melt_cut35']['lum_mean']:.3f}", 'strip', 'melts', 'prop')}
{tile('s_melt_cut50', 'B2 · dark floor 0.50 — lit ' + pct(C['melt_cut50']['lit_frac_mean']) + ', luminance ' + f"{C['melt_cut50']['lum_mean']:.3f}", 'strip', 'melts', 'prop')}
{tile('s_melt_cut65', 'B3 · dark floor 0.65 — lit ' + pct(C['melt_cut65']['lit_frac_mean']) + ', luminance ' + f"{C['melt_cut65']['lum_mean']:.3f}", 'strip', 'melts', 'prop')}
{ctl('melts')}</div>
<div class="tscroll"><table><tr><th>Strip</th><th>Lit share (min–max)</th><th>Mean luminance</th><th>Peak</th></tr>
{strip_row('melt_today', '<span class="pill p-cur">today</span>')}
{strip_row('blackhole1d')}{strip_row('orbits1d')}{strip_row('fireworks1d')}{strip_row('orbits1d_dim')}
{strip_row('melt_gamma2', '<span class="pill p-prop">A1</span>')}{strip_row('melt_gamma3', '<span class="pill p-prop">A2</span>')}
{strip_row('melt_cut35', '<span class="pill p-prop">B1</span>')}{strip_row('melt_cut50', '<span class="pill p-prop">B2</span>')}{strip_row('melt_cut65', '<span class="pill p-prop">B3</span>')}
</table></div>
<p class="small muted">The crystal reads this same strip (Star's rings are the strip's colours), so a darker Melt also makes the STAR crystal itself less full: the rings get dark gaps that turn with the star. The crystal tiles further down were rendered on today's Melt; the build re-measures them on the chosen floor.</p>
<div class="dec"><p>✅ <b>Q7 decided</b> — <b>B2, dark floor 0.50</b> (“all other defaults”): lit 33%, luminance 0.082, still the brightest strip. Built as a Melt param <code>dark_floor</code> (0 = today), set to 0.5 on STAR's Strips entry only; Sonic reaches it per entry; the exact number is his to tune live.</p></div>
</div>

<h2>2 · The TV: the real strip path, and the ring</h2>
<p class="small"><b>Facts (read, not assumed).</b> The TV, both kitchen sconces and the TV backlight are ONE copy-mapped virtual (<code>tv-mapper</code>): the strip effect renders once at 560 px (the TV's length) and each sconce segment (28 px and 60 px rings) gets that whole picture squeezed into its ring — so a sconce always shows the entire pattern wrapped once round, every blob is an arc, and motion is rotation. The TV strip is now driven by the stand-in on the Pi (WLED 16.0.1 emulation, one segment 0–560, not reversed, not mirrored) and its geometry is HyperHDR's own LED layout, read from the Pi: <b>one loop, clockwise seen from the front — LED 0 at the bottom-right corner, 0–199 run left along the bottom, 200–259 up the left edge, 260–479 right along the top, 480–559 down the right edge</b>. LedFX rolls the frame by the device's <code>center_offset</code> 90, so effect pixel 0 lands on LED 90, 45% along the bottom from the right. Every TV dot below sits at its real layout position.</p>
<p class="small"><b>River confirmed the last piece</b>: straight through, no HyperHDR in the path — while Spectra streams, DDP pixel <i>i</i> is written as physical LED <i>i</i>, no remap, reverse, offset or gamma; LED 0 is the first LED at the strip's data input. So the first tile IS today: one clockwise loop, rolled 90 by LedFX. The second tile is the image-sampled reading, kept only to show why it was considered — it is ruled out.</p>
<div class="card"><div class="pair tvpair" data-pairgroup="tv">
<figure class="tile tv today" data-tv="led" data-src="s_melt_today" data-group="tv"><canvas></canvas><figcaption>Today (confirmed): pixel i → LED i on the real loop, rolled 90 — blobs circulate clockwise, bottom right→left, top left→right</figcaption></figure>
<figure class="tile tv" data-tv="image" data-src="s_melt_today" data-group="tv"><canvas></canvas><figcaption>RULED OUT (River): the image-sampled reading, where both long edges would march the same way</figcaption></figure>
<figure class="tile tv prop" data-tv="angle" data-src="s_melt_today" data-group="tv"><canvas></canvas><figcaption>Ring mapping: each LED shows the strip pixel at ITS ANGLE round the TV's centre (equal angle, not equal length) — a blob is an arc of constant angle and turns about the centre like a sconce, whichever of the two the stand-in does</figcaption></figure>
<figure class="tile tv prop" data-tv="angle" data-src="s_melt_cut50" data-group="tv"><canvas></canvas><figcaption>Ring mapping on the darker Melt (B2)</figcaption></figure>
<figure class="tile tv" data-tv="sconce" data-src="s_melt_today" data-group="tv"><canvas></canvas><figcaption>For reference: the same frame on a 28-px sconce ring (copy mapping squeezes the whole strip in)</figcaption></figure>
{ctl('tv')}</div>
<p class="small">The ring mapping is a per-LED lookup table for the TV (effect pixel → LED, by the angle of that LED's real layout position about the screen centre), applied to every strip effect on the TV (Black Hole, Orbits, Fireworks, Melt alike) — your Q6 answer. The layout above is the table's input; nothing else is needed from you.</p>
<div class="dec"><p>✅ <b>Q9 decided</b> — <b>ring by angle about the TV's centre</b>, a per-LED lookup on the TV device, applied to every strip effect. Q8 is the HyperHDR loop read above, and River confirmed the straight DDP pixel→LED pass-through.</p></div>
</div>

<h2>3 · Spin from the first moment</h2>
<p class="small"><b>Fact, and it is a defect.</b> At a STAR fire the Speed binding (trigger intensity → 0.4..1.0, <i>random sign</i>) is resolved by flipping the sign half the time and THEN clamping to the registry's 0..1 range — so on about half of all fires (1,040 of 2,000 simulated) Speed lands at exactly <b>0</b>, the quiet floor is 0, and nothing turns until a flare or an update writes Speed back (the update is a 2× flare, and its band's “Flare patch” kind writes Speed 0.55). On the other half Speed is fine but the motion is reactive only — rev/s = 4.8 × bass impulse × Speed² — so a quiet intro still reads as parked.</p>
<div class="card"><div class="pair multi" data-pairgroup="entry">
{tile('entry_today_zero', T['entry_today_zero']['label'], 'hex', 'entry', 'today')}
{tile('entry_today_spin', T['entry_today_spin']['label'], 'hex', 'entry', 'today')}
{tile('entry_prop', T['entry_prop']['label'], 'hex', 'entry', 'prop')}
{chart('entry', [["Today (Speed 0 → update at 4 s)", "--cur", "entry_today_zero"], ["Today (Speed set, reactive)", "--warn", "entry_today_spin"], ["Decided: 1 s ease, no floor", "--prop", "entry_prop"]], "rev/s", 2.6)}
{ctl('entry')}</div>
<p class="small">The build: (1) the sign flip on Speed is dropped at fire time (the magnitude binding never lands 0; the direction is Flip's job — his own “use the flip control for star”); (2) from the first frame Star eases its own rotation up to the song's current speed over ~1 s instead of starting at whatever the audio callback happens to give; No quiet floor (<code>base_rotation</code> stays 0, his knob if he ever wants one).</p>
<div class="dec"><p>✅ <b>Q10 decided</b> — his words: “it can slow to a stop during quiet music”. No floor; it still spins from the first moment whenever the music has energy (the ease-in and the sign-flip fix stand).</p></div>
</div>

<h2>4 · The 70% speed cap (decided — shown so you can check it)</h2>
<p class="small">Today's ceiling: {ceil_today:.1f} rev/s (Speed 1.0 at full impulse). The cap is a hard clamp on the per-frame advance at <b>{cap:.2f} rev/s</b>; anything slower passes through unchanged (the two curves lie on top of each other until the loud section's hits). In this clip a loud fire's Speed 0.94 peaks at {T['cap_today']['rev_s_max']:.2f} rev/s today and {T['cap_prop']['rev_s_max']:.2f} capped; the mean over the song barely moves ({T['cap_today']['rev_s_mean']:.2f} → {T['cap_prop']['rev_s_mean']:.2f}).</p>
<div class="card"><div class="pair" data-pairgroup="cap">
{tile('cap_today', T['cap_today']['label'], 'hex', 'cap', 'today')}
{tile('cap_prop', T['cap_prop']['label'], 'hex', 'cap', 'prop')}
{chart('cap', [["Today", "--cur", "cap_today"], ["Capped at 3.36", "--prop", "cap_prop"]], "rev/s", 4.6)}
{ctl('cap')}</div>
<p class="small muted">The cap applies to the sum of every rotation source (audio spin, the charge spin-up, the floor), so a charge cannot push past it either.</p>
</div>

<h2>5 · The amount of star flows — and what “flat” actually is</h2>
<p class="small"><b>Fact.</b> “Amount of star” is Radial's <code>star</code>. In <code>fx/effects/radial.py</code> (<code>_shaped_radius</code>) the polygon's radius is multiplied by <code>1 + star × cos(edges × angle)</code>: at <b>star = 0 the ripple is exactly 1 and the shape is the plain polygon — that is flat</b>. 0.5 is not flat: it is a strong star whose points reach (1+0.5)/(1−0.5) = <b>3.0×</b> further than its valleys. 0.3 → 1.9×, 0.7 → 5.7× (the valleys sit almost at the core). A negative value is the same star with its points at the polygon's corners instead of its edge-midpoints — the sign swaps WHERE the points are, not whether there are points. Today STAR rolls ±0.3 or ±0.5 once at the fire and never re-rolls; the 0.7–1 patch kinds set it to 0 (flat) permanently.</p>
<div class="card"><h3>The frozen shapes (same frame, same music, only <code>star</code> differs)</h3><div class="pair multi" data-pairgroup="shapes">
{tile('shape_m05', 'star = −0.5 · points 3.0× valleys, at the corners', 'hex', 'shapes')}
{tile('shape_m02', 'star = −0.2 · 1.5×, at the corners', 'hex', 'shapes')}
{tile('shape_00', 'star = 0 · FLAT — the plain polygon', 'hex', 'shapes', 'today')}
{tile('shape_03', 'star = 0.3 · 1.9× (his stored low)', 'hex', 'shapes')}
{tile('shape_05', 'star = 0.5 · 3.0× (his stored high — not flat)', 'hex', 'shapes')}
{tile('shape_07', 'star = 0.7 · 5.7× (the top of his 0.3–0.7)', 'hex', 'shapes')}
{ctl('shapes')}</div>
<p class="small muted">Mean per-cell change between frames while turning (how busy the shape is): star 0 → {T['shape_00']['cell_delta_mean']}, 0.3 → {T['shape_03']['cell_delta_mean']}, 0.5 → {T['shape_05']['cell_delta_mean']}, 0.7 → {T['shape_07']['cell_delta_mean']}, −0.5 → {T['shape_m05']['cell_delta_mean']}.</p></div>
<div class="card"><h3>The wave, three ranges</h3><div class="pair multi" data-pairgroup="starw">
{tile('star_today', T['star_today']['label'], 'hex', 'starw', 'today')}
{tile('star_his', 'A · as typed: 0.30 ↔ 0.70 (always a star, 1.9× ↔ 5.7×)', 'hex', 'starw', 'prop')}
{tile('star_flat_sym', 'B · his intent with flat = 0: −0.20 ↔ +0.20 (points tuck in through flat and come out at the other angle)', 'hex', 'starw', 'prop')}
{tile('star_flat_up', 'C · flat ↔ star: 0.00 ↔ 0.40 (plain polygon breathes into a 2.3× star)', 'hex', 'starw', 'prop')}
{chart('starw', [["Today", "--cur", "star_today"], ["A 0.30↔0.70", "--prop", "star_his"], ["B −0.20↔0.20", "--prop2", "star_flat_sym"], ["C 0↔0.40", "--prop3", "star_flat_up"]], "star", 0.75)}
{ctl('starw')}</div>
<p class="small">All three are the same mechanism: a continuous cosine between the two bounds whose period follows the song's energy (7 s quiet → 3 s loud), never a jump, never parked; the bounds and periods are entry params (Sonic-reachable). Lit cells over the clip: today {T['star_today']['lit_min']}–{T['star_today']['lit_max']}, A {T['star_his']['lit_min']}–{T['star_his']['lit_max']}, B {T['star_flat_sym']['lit_min']}–{T['star_flat_sym']['lit_max']}, C {T['star_flat_up']['lit_min']}–{T['star_flat_up']['lit_max']}.</p>
{q(13, "Which star range (only because flat turned out to be 0, not 0.5)", "A 0.30↔0.70 exactly as typed · B −0.20↔+0.20, his “±0.2 about flat” translated to the real flat · C 0.00↔0.40, flat polygon breathing into a star.",
   "<b>C, 0.00 ↔ 0.40</b> — it is “between flat and a star”, which is what “the amount of star” names; it never crosses zero, so the points never swap angle mid-wave; and 0.40 stays inside the looks he already lives with (0.3–0.5). If he wants it exactly as typed, A ships unchanged.")}
</div>

<h2>6 · Flares change the edges, smoothly (decided — shown)</h2>
<p class="small"><b>Fact.</b> Edges are rolled once at the fire (3, 4, 5 or 6, sticky) and hold; no flare touches them today. The 0.6 s shape morph already exists in Radial — it just never gets a new value to morph to.</p>
<div class="card"><div class="pair" data-pairgroup="edges">
{tile('edges_today', T['edges_today']['label'], 'hex', 'edges', 'today')}
{tile('edges_prop', T['edges_prop']['label'], 'hex', 'edges', 'prop')}
{chart('edges', [["Today", "--cur", "edges_today"], ["Proposal", "--prop", "edges_prop"]], "edges", 7)}
{ctl('edges')}</div>
<p class="small">His Q5 answer: a flare morphs to a NEW count (never the same twice in a row) and it stays until the next scene update or flare. Built as a new flare kind on STAR, “Edge Morph” (permanent; picks from 3–6 excluding the current), attached to the bands he chooses; the morph is the existing <code>shape_morph_s</code> (0.6 s). Largest frame-to-frame change per cell across the three morphs: {T['edges_prop']['cell_delta_max']:.1f}, against {T['edges_today']['cell_delta_max']:.1f} on the unchanged star (the turning itself).</p>
<div class="dec"><p>✅ <b>Q12 decided</b> — Edge Morph on the two upper flare bands (0.35–0.7 and 0.7–1) only; small flares leave the shape alone.</p></div>
</div>

<h2>7 · What gets built</h2>
<div class="card"><table>
<tr><th>Change</th><th>Where</th><th>Undo</th></tr>
<tr><td>Speed never lands 0 at a fire (no sign flip on a magnitude-only param); 1 s ease-up from the first frame; no quiet floor</td><td>binding resolver + radial.py (<code>spin_ease_in_s</code>, 0 = today)</td><td>param 0; the resolver fix is engine code</td></tr>
<tr><td>Hard cap 3.36 rev/s on total rotation</td><td>radial.py (<code>ROTATION_CAP_REV_S</code>)</td><td>constant</td></tr>
<tr><td>Star wave between two bounds (Q13: 0↔0.40 rec, or 0.30↔0.70 as typed), period by energy</td><td>radial.py (<code>star_wave</code>, <code>star_wave_period_s</code> params); STAR's 0.7–1 patch kinds drop their <code>star: 0</code> write (his data, backed up)</td><td>params off; kinds restored from backup</td></tr>
<tr><td>“Edge Morph” flare kind on STAR</td><td>scene data (new kind + band attachment, backed up)</td><td>detach the kind</td></tr>
<tr><td>Melt <code>dark_floor</code> (0 = today), 0.5 on STAR's Strips entry</td><td>melt.py + STAR Strips entry (his data, backed up)</td><td>set 0</td></tr>
<tr><td>TV ring lookup (effect pixel → LED by angle)</td><td>tv-backlight device mapping, every strip effect</td><td>remove the table</td></tr>
</table><p class="small muted">Help content and the star-scene / radial-effect / melt-effect skills update in the same change. Merge is not deploy; the live units are restarted separately.</p></div>

</main><script>
const COLS=72,ROWS=37;const CELLS={json.dumps(cells, separators=(',', ':'))};
const SPR={json.dumps(SPR)};const TVL={json.dumps(tvl, separators=(',', ':'))};const SERIES={json.dumps(SERIES, separators=(',', ':'))};
const anims=[],groups={{}};const cache={{}};
function cssv(n){{return getComputedStyle(document.documentElement).getPropertyValue(n).trim()}}
function loadSprite(name,cb){{if(cache[name]){{cache[name].ready?cb(cache[name]):cache[name].cbs.push(cb);return}}const s=cache[name]={{ready:false,cbs:[cb]}};const im=new Image();im.onload=()=>{{const oc=document.createElement('canvas');oc.width=im.width;oc.height=im.height;const o=oc.getContext('2d');o.drawImage(im,0,0);s.w=im.width;s.n=im.height;s.data=o.getImageData(0,0,im.width,im.height).data;s.ready=true;s.cbs.forEach(f=>f(s))}};im.src=SPR[name].src}}
class Anim{{constructor(fig){{this.fig=fig;this.g=fig.dataset.group;this.cv=fig.querySelector('canvas');this.ctx=this.cv.getContext('2d');this.tv=fig.dataset.tv||null;this.name=fig.dataset.anim||fig.dataset.src;this.kind=this.tv?'tv':SPR[this.name].kind;this.ready=false;this.visible=false;this.lastFrame=-1;this.n=0;
 (groups[this.g]=groups[this.g]||{{anims:[],t:0,playing:true,max:0}}).anims.push(this);loadSprite(this.name,s=>{{this.s=s;this.n=s.n;this.w=s.w;this.ready=true;this.layout();this.draw(0)}})}}
 layout(){{const r=this.cv.getBoundingClientRect();const dpr=Math.min(2,window.devicePixelRatio||1);const W=Math.max(1,Math.round(r.width*dpr));const H=this.kind==='strip'?Math.round(W/14):this.kind==='tv'?Math.round(W*10/16):Math.round(W*ROWS/COLS);if(this.cv.width!==W||this.cv.height!==H){{this.cv.width=W;this.cv.height=H;this.lastFrame=-1}}}}
 px(f,i){{const d=this.s.data,j=(f*this.w+i)*4;return [d[j],d[j+1],d[j+2]]}}
 draw(f){{if(!this.ready)return;f=Math.min(this.n-1,Math.max(0,Math.floor(f)));if(f===this.lastFrame)return;this.lastFrame=f;const c=this.ctx,W=this.cv.width,H=this.cv.height;c.fillStyle='#07060b';c.fillRect(0,0,W,H);
  if(this.kind==='strip'){{const n=this.w,cw=W/n;for(let i=0;i<n;i++){{const p=this.px(f,i);c.fillStyle=`rgb(${{p[0]}},${{p[1]}},${{p[2]}})`;c.fillRect(i*cw,0,cw+0.6,H)}}}}
  else if(this.kind==='tv'){{this.drawTV(f,c,W,H)}}
  else{{const cw=W/COLS,ch=H/ROWS,rad=Math.max(1,cw*0.95);for(let i=0;i<CELLS.length;i++){{const p=this.px(f,i);const x=(CELLS[i][0]+0.5)*cw,y=(CELLS[i][1]+0.5)*ch;if(p[0]+p[1]+p[2]<10){{c.fillStyle='#1a1a24';c.beginPath();c.arc(x,y,rad*0.35,0,6.283);c.fill()}}else{{c.fillStyle=`rgb(${{p[0]}},${{p[1]}},${{p[2]}})`;c.beginPath();c.arc(x,y,rad,0,6.283);c.fill()}}}}}}}}
 drawTV(f,c,W,H){{const N=this.w;const mode=this.tv;
  if(mode==='sconce'){{const n=28,cx=W/2,cy=H/2,R=Math.min(W,H)*0.36,rad=Math.max(2,R*0.11);c.strokeStyle='#2a2340';c.lineWidth=rad*2.4;c.beginPath();c.arc(cx,cy,R,0,6.283);c.stroke();for(let k=0;k<n;k++){{const i=Math.min(N-1,Math.round(k*N/n));const p=this.px(f,i);const a=-Math.PI/2+6.283*k/n;c.fillStyle=`rgb(${{p[0]}},${{p[1]}},${{p[2]}})`;c.beginPath();c.arc(cx+R*Math.cos(a),cy+R*Math.sin(a),rad,0,6.283);c.fill()}}c.fillStyle='#9585b5';c.font=`${{Math.round(H*0.08)}}px system-ui`;c.textAlign='center';c.fillText('sconce · 28 px ring',cx,cy+4);return}}
  // the TV: the REAL 560-LED layout (HyperHDR's, read from the Pi), drawn in a 16:9 screen rectangle
  const tw=W*0.84,th=tw*9/16,x0=(W-tw)/2,y0=(H-th)/2,cx=W/2,cy=H/2;
  const rad=Math.max(2,(2*(tw+th))/N*1.7);
  c.strokeStyle='#1c1830';c.lineWidth=rad*2.8;c.strokeRect(x0,y0,tw,th);c.fillStyle='#0d0b16';c.fillRect(x0+rad*1.6,y0+rad*1.6,tw-rad*3.2,th-rad*3.2);
  for(let k=0;k<N;k++){{const [u,v]=TVL[k];const x=x0+u*tw,y=y0+v*th;let i;
   if(mode==='led'){{i=((k-90)%N+N)%N}}
   else if(mode==='image'){{const horiz=(v<0.1||v>0.9);i=Math.min(N-1,Math.round((horiz?u:v)*(N-1)))}}
   else{{const a=Math.atan2(v-0.5,(u-0.5)*16/9);i=Math.floor((((a+Math.PI/2)/(2*Math.PI))%1+1)%1*N)%N}}
   const p=this.px(f,i);c.fillStyle=`rgb(${{p[0]}},${{p[1]}},${{p[2]}})`;c.beginPath();c.arc(x,y,rad,0,6.283);c.fill()}}
  c.fillStyle='#6e6390';c.font=`${{Math.round(H*0.07)}}px system-ui`;c.textAlign='center';c.fillText(mode==='led'?'TV · real loop, pixel i → LED i':mode==='image'?'TV · real loop, image-sampled (hypothesis)':'TV · ring by angle',cx,cy+4);
  c.font=`${{Math.round(H*0.045)}}px system-ui`;c.fillText('LED 0 ↘ bottom-right · clockwise',cx,cy+Math.round(H*0.1))}}
}}
document.querySelectorAll('figure.tile').forEach(f=>anims.push(new Anim(f)));
const io=new IntersectionObserver(es=>es.forEach(e=>{{const a=anims.find(x=>x.fig===e.target);if(a)a.visible=e.isIntersecting}}),{{rootMargin:'120px'}});anims.forEach(a=>io.observe(a.fig));
// charts
const charts=[];document.querySelectorAll('canvas.chart').forEach(cv=>{{const spec=JSON.parse(cv.dataset.spec);const g=cv.dataset.g;charts.push({{cv,spec,g}});(groups[g]=groups[g]||{{anims:[],t:0,playing:true,max:0}})}});
function drawChart(ch,frame){{const cv=ch.cv,dpr=Math.min(2,devicePixelRatio||1);const r=cv.getBoundingClientRect();cv.width=Math.round(r.width*dpr);cv.height=Math.round(r.height*dpr);const c=cv.getContext('2d'),W=cv.width,H=cv.height;c.fillStyle=cssv('--surface2');c.fillRect(0,0,W,H);const S=SERIES[ch.g];const keys=ch.spec.series;const n=Math.max(...keys.map(k=>S[k[2]].length));let ymax=ch.spec.ymax||Math.max(...keys.map(k=>Math.max(...S[k[2]].map(Math.abs))))*1.1;const pad=28*dpr,pb=16*dpr;const X=i=>pad+(W-pad-6*dpr)*i/(n-1),Y=v=>H-pb-(H-pb-6*dpr)*Math.abs(v)/ymax;
 // impulse shading
 c.fillStyle='rgba(255,255,255,0.05)';const imp=SERIES.impulse;for(let i=0;i<imp.length-1;i++){{c.fillRect(X(i),H-pb-(H-pb-6*dpr)*imp[i],X(i+1)-X(i)+1,(H-pb-6*dpr)*imp[i])}}
 c.strokeStyle='#372552';c.lineWidth=dpr;c.beginPath();c.moveTo(pad,H-pb);c.lineTo(W,H-pb);c.stroke();c.fillStyle='#9585b5';c.font=`${{10*dpr}}px system-ui`;c.textAlign='left';c.fillText(ch.spec.ylabel+' (max '+ymax.toFixed(2)+'); grey = bass impulse',pad+4*dpr,10*dpr);
 for(let s=3;s<=9;s+=3){{const x=X(Math.round(s*20));c.fillText(s+' s',x,H-3*dpr)}}
 let lx=pad+4*dpr;keys.forEach(([lab,col,key],ki)=>{{const v=S[key];c.strokeStyle=cssv(col)||col;c.lineWidth=1.6*dpr;c.beginPath();v.forEach((y,i)=>{{i?c.lineTo(X(i),Y(y)):c.moveTo(X(i),Y(y))}});c.stroke();c.fillStyle=c.strokeStyle;c.fillText('— '+lab,lx,22*dpr);lx+=c.measureText('— '+lab).width+14*dpr}});
 const fx=X(Math.min(n-1,frame));c.strokeStyle='#fff';c.lineWidth=dpr;c.beginPath();c.moveTo(fx,4*dpr);c.lineTo(fx,H-pb);c.stroke()}}
let last=performance.now();
function loop(now){{const dt=Math.min(0.1,(now-last)/1000);last=now;for(const [gid,g] of Object.entries(groups)){{g.max=Math.max(0,...g.anims.map(a=>a.ready?a.n:0));if(!g.max)continue;const vis=g.anims.some(a=>a.visible);if(g.playing&&vis){{g.t+=dt*20;if(g.t>=g.max+16)g.t=0}}
 const f=Math.min(g.max-1,Math.floor(g.t));if(vis){{g.anims.forEach(a=>a.draw(Math.min(f,a.n-1)));charts.filter(ch=>ch.g===gid).forEach(ch=>{{if(ch.last!==f){{ch.last=f;drawChart(ch,f)}}}})}}
 if(g.ui){{if(!g.ui.scrub.matches(':active'))g.ui.scrub.value=Math.round(1000*f/Math.max(1,g.max-1));g.ui.time.textContent=(f/20).toFixed(1)+' s'}}}}
 requestAnimationFrame(loop)}}
document.querySelectorAll('.pair').forEach(p=>{{const gid=p.dataset.pairgroup;const g=groups[gid];if(!g)return;g.ui={{scrub:p.querySelector('.scrub'),time:p.querySelector('.time'),play:p.querySelector('.play')}};
 g.ui.play.onclick=()=>{{g.playing=!g.playing;g.ui.play.textContent=g.playing?'⏸':'▶'}};g.ui.scrub.oninput=()=>{{g.playing=false;g.ui.play.textContent='▶';g.t=g.ui.scrub.value/1000*(g.max-1);g.anims.forEach(a=>a.draw(Math.min(Math.floor(g.t),a.n-1)))}}}});
requestAnimationFrame(loop);
window.addEventListener('resize',()=>anims.forEach(a=>{{a.layout();a.draw(a.lastFrame<0?0:a.lastFrame)}}));
</script></body></html>
"""
out = os.path.join(plan, "explainer.html")
with open(out, "w") as fh:
    fh.write(html)
print(out, len(html), "bytes")
