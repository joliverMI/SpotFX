# The Fireworks melds — offline evidence

Rendered by `scripts/render_fireworks_melds.py` on his crystal-mapper's real
cells (the device profile's mask, through `fx.headless` — the real vendored
render pipeline, audio silenced, beats pulsed by hand). Every switch is the
trigger clock's own one-call hard cut (`Virtual.set_effect(cut=True)`,
`fx/VENDOR.md` #63). Nothing touched the live room or live storage.

| GIF | What it shows | Measured (lit cells on his real panel) |
|---|---|---|
| `fireworks_meld_keepers.gif` | Fish (his music Fish entry) above Orbits: a charge, a 4 s lull told `lull_keep = 3, lull_next = "fireworks"`, then the cut to Fireworks ON the drop with its drop arm | 3 keepers flagged each time; each becomes a giant firework at its own position on the cut frame (peak 557 lit for Fish, 690 for Orbits) |
| `fireworks_meld_swallowed.gif` | Fireworks' own charge, lull and drop; the cut to the Black Hole 1.0 s after the drop | 759 lit before the cut, 700 on the cut frame; 239 pieces adopted into the infall |
| `fireworks_meld_implode.gif` | Fireworks' own drop; the cut on "the next big bass hit" (stood in by 1.5 s after the drop — the room's is the next analysed flare at least `drop_switch_hit_threshold` strong) into Fish / Orbits / Squiggles. The fish's own swim burst fires with the cut, as the incoming scene's flare does in the room | 189 lit before; Fish 168, Orbits 188, Squiggles 42 on the cut frame (Squiggles was 0 for five frames before its adopted chains stopped fading in on a cut) |

The "loud" arrival in the room is the incoming scene's own authored flare
band, fired by the hit flare landing on the new scene (or by the deadline);
the offline render can only stand that in with the fish's swim burst.

Reproduce: `.venv/bin/python scripts/render_fireworks_melds.py --out DIR`.
