# Learnings — what each design session taught

Append under a dated heading after every session (SKILL.md step 7), then
promote the durable lines into `question-bank.md` and `visuals.md` in the
same change. Sessions are named by their short plan-directory name; the
directories themselves live outside this public repo. His words are
quoted only where they are the ruling.

## Standing preferences (promoted; the recommended answers in the bank)

1. **No added white, anywhere.** "I don't want to raise the white in the
   charge, or on the drop. ... increasing brightness means adding more
   color, increasing the brightness of the colors, and having more
   baseline effects, like more orbiting blobs, more fireworks." The most
   cited rule across every session since 2026-10-11; it cost one whole
   plan revision (strip-plan-rev3) and closed a question in another.
2. **Nothing "just appears."** A one-frame jump in lit cells is a defect
   ("The star just appears, make it smoother"). Growth is radial from the
   form's core, staggered, hundreds of ms.
3. **Continuity of motion.** Hand-offs keep velocity and heading; targets
   are met where they will be; "implode to the moving orbits point".
4. **Keep his existing behaviour unless he names it.** He rejected a
   single new lull for all 2D effects ("I prefer my current lulls on all
   the 2d effects") and keeps authored counts, colours and scenes as his.
   Copy, don't modify, for a new sibling effect.
5. **Lulls go dark, drops are big and clean.** Black on the shared dark
   point (3 s cap) with crystal and strips together; the drop out-shines
   the charge, starts on its mark, is a hard cut when the scene changes,
   and changes colour cleanly and immediately.
6. **Low total light output** in lulls and pre-drops is a hard value;
   the strips stay dark (a twinkle, not a background fade).
7. **Flares beat the dark.** A flare landing in a lull punches through.
8. **He judges from pictures, by eye, in the room.** Every override in
   the record came from a tile, a video or a screenshot, never from prose
   or a number. Taste numbers are params with defaults from his tuning
   pass, listed as risks, never asked.
9. **Build → he tunes live → then seed/migrate.** Never seeded ahead of
   the gate; charge/lull/drop choreography for a new effect is deferred
   until he has lived with it.
10. **Music scene first, House scene untouched**, as a per-scene setting.
11. **Compact UI, nothing said twice** (drop a label a swatch already
    says); icon-only, touch-friendly toggles; the live countdown box
    should participate.
12. **He reviews from a claude.ai Artifact, not a local Lavish URL.**
    Lavish serves on `127.0.0.1`; his tablet gets "connection refused."
    Every explainer, every round, and the plan he confirms is published
    as an Artifact (renders as supporting PNG/GIF files, not base64) by
    the agent talking to him; Lavish stays optional, never the only copy.
13. **A numeric shape param gets a full-range grid, not a 3-option row.**
    A narrow row of hand-picked options can't surprise him the way the
    full range can — his "0.5 is flat" assumption on STAR's `edges` only
    broke once he saw the whole -0.7..+0.7 range rendered.

## How he answers

- Short, bundled, verbatim: "all recs, except on 4 ... and 6 ...",
  "A", "yes", "I approve option A for the wake", "Use lull b, drop d 3",
  "Do rec on transitions", "take your rec on the color". A round that
  lets him answer that way is a good round.
- He comments on tiles more than he answers numbered lists: three of the
  six formal questions on transitions-drop-plan were never answered
  across three revisions, while his tile comments produced every
  decision. Put the question UNDER the tile it is about.
- He asks to see comparisons rather than be argued into one ("show me
  side by side of the palette sort, especially several mappings of the
  hype1 color set"; "show me comparison of the three choices for how
  flames are made"). If a choice was made by argument, expect that ask;
  render it first.
- He adds to the recommendation toward MORE of his own idea: lull B and
  drop D3 (built from his hint), A plus the expensive half of E
  (word-effect), punch-through, the twinkle. Offer the option built from
  his hint beside the conservative one.
- A relayed answer is not his answer: an agent that only has the relay
  does not close the hold.

## Questions that wasted his time (demoted or deleted)

- Engineering calls dressed as decisions: join `LULL_DARK_EFFECTS`, morph
  0.6 s, beat on width vs height, the effect's name, the sky floor on by
  default, keep analysed flares out of protected lulls, the pre-drop
  marker colour, the plays-alone bar, repeated-clap rule. He gives a
  silent yes or "take your rec". Fold them into the plan's defaults.
- Facts he could not know or did not need to: what counts as "low
  level" (the capture's own level, a fact of the pipeline), whether
  House Fish should rest (defaults adopted without comment), stale-rule
  thresholds and build order (left to the agent / his eye), candidate
  colour before fire time and do-nothing words (unanswered).
- Any question whose premise the facts step later contradicted:
  Orbits→Fish "bursting" (it never did), the whole 2D Indraw lull.

## Questions that changed a plan (promoted; ask early)

- Which rendered lull / drop / transition (STAR: B and D3 over the recs).
- Cut vs blend at the drop (drop-scene-variety: "just switch at the drop").
- Flare in the dark: punch through (strip-phase).
- Breath-hold with a pre-drop: keep it, move it before the pre-drop.
- Remove semantics on his vs imported drops (delete his, disable imported).
- Reverse transition = forward mirrored (star-plan-rev).
- Strip lull should not ride into the crystal's mapping (STAR, 2026-10-14).
- Wake colour (fish-swim Q3: the one of three he answered explicitly).
- Build Squiggles' pre-drop? No; Star must grow from the centre.

## What the visuals got right and wrong

- Right: real pipeline on the real 976 cells with his sets, same seed on
  every tile, one scrubber per today/proposed pair, numbers beside the
  tiles; real screenshots as the base for UI options; curves for the
  Singles where a light render says nothing.
- Wrong, and what it cost: a demo artefact (fish swimming off-screen
  under a random kick) cost two revision cycles — pin the camera and the
  demo's own randomness before rendering; a full-rectangle dummy matrix
  instead of the hex mask left "unverified on his crystal"; sketches
  that imitated the incoming effect instead of handing off to it; rig
  source discarded with the worktree (recovered from bytecode twice) —
  commit the harness (`tests/star_harness.py` is the precedent); a
  three-column layout unverified above ~1000 px.
- Misreading his words cost a revision each time: "crossfade through the
  lull" (he meant a cut at the drop), "approve all/some" (he meant a
  per-part toggle bar), "flip vertically" (offered as a reading with the
  one-line alternative — the right way to handle it).

## Session log

### 2026-11-12 — skill seeded (no live session)
Seeded from fourteen past plan directories: star-plan, star-plan-rev,
strip-phase-plan, strip-plan-rev, strip-plan-rev3, single-led-power-plan,
transitions-drop-plan, transitions-plan-rev, transitions-plan-rev3,
transition-alignment-plan, shoal-burst-plan, bh-infall-plan,
fish-swim-plan, fish-lull-plan, sauron-eye-plan, sauron-eye-plan-v2,
drop-scene-variety-plan (+v2), predrop-plan, word-effect-highlight-options.
His ask for this skill, verbatim: "we should have a skill or something
for building new scenes/effects, and for modifying/upgrading them,
including transitions and drop sequence effects ... where I say: I want to
build a new effect/scene, or I want to improve an existing effect/scene.
Then you ask me a series of highly targeted questions (learned and
improved from the skill) to build a detailed plan with the visual
comparisons you have been doing." He has an effect to improve as the
first test of the workflow: that session's entry goes here next.

### 2026-11-12 — star-improve-plan (improve, scene + Matrix/Strip effect + flare kind + device mapping, STAR)
- Rounds: 3 (+ one render ask); questions asked: 13; answered explicitly: 5
  (Q5, Q10, Q11, Q13, plus the Q8 fact); "all other defaults": 8.
- Changed the plan: Q10 quiet floor → "it can slow to a stop during quiet
  music" (NO floor — the rec was a 0.12 rev/s floor; demote "never still"
  as a recommendation, his default is: music-driven may stop). Q11/Q13
  star range → "try .3 to .7 (assuming .5 is flat, which i think it is)",
  then after the grid "let's do -.2 to +.4 ... I want it to go through 0"
  (promote: CHECK EVERY NUMERIC ASSUMPTION IN HIS ANSWER AGAINST THE CODE
  — his "0.5 is flat" was wrong; the facts scout must state what the
  neutral/flat/zero value of a param IS before he picks a range).
- Waved through: Q7 (Melt floor), Q9 (ring by angle), Q12 (which bands),
  Q1–Q4, Q6 — all "defaults" (demote: engineering-shaped; fold into the
  plan's defaults next time, ask only the taste ones).
- Facts that were decisive and he could not know: the fire-time
  sign-flip-then-clamp defect (the "not dynamic at all" was a bug, not
  taste); Melt's lit share (61% vs 14–28%); flat = 0. A visual/number
  settled each.
- New preference: a FULL-RANGE GRID beats a three-option pick for a
  continuous param — he asked for it himself ("Show me what the full range
  from -.7 to +.7 star looks like in increments of .1 ... with 3, 4, 5, and
  6 sides in a grid") and decided from it in one message. Offer the grid
  first for any "what range" question (→ bank, look/motion; visuals.md).
  Promoted to a standing preference (§13 above) and into `visuals.md`.
- New constraint: he reviews on a TABLET. He opened the STAR explainer
  from a local Lavish URL and got "connection refused" — Lavish serves on
  `127.0.0.1`, unreachable from his tablet. The fix that worked: DJ
  published a claude.ai Artifact with the render PNGs (a `star x edges`
  grid) as supporting files, and sent stills/GIFs straight into chat.
  Make every explainer tablet-reachable from the start (→ visuals.md).
  Promoted to a standing preference (§12 above) and into the skill files
  in this same change: every explainer, every round, and the confirmed
  plan now default to an Artifact publish, with Lavish optional at most.
- Visuals: the sprite tiles + measured numbers drove Q7 and Q9 without a
  word of argument; the frozen "what is flat" row caught his wrong
  assumption; the TV tile needed the REAL geometry (HyperHDR's LED layout
  read off the Pi) — an assumed loop would have mis-shown today. Missed:
  the first explainer embedded nothing and showed blank tiles under
  file:// (sprites must be data URIs); the first entry tiles carried a
  floor he then declined.
- Confirmation: "STAR plan is approved, go ahead and deploy as soon as
  it's ready" (from the plan artifact).
- Room verdict: pending (after deploy).

### 2026-11-12 — star-spin-smooth (improve, Matrix effect motion law, STAR / Radial)
- Rounds: 2 (one analysis page, one answer); questions asked: 4; answered
  explicitly: 4 (Q1/Q2 "yes to both", Q3 "do 18 degrees per frame for
  now", Q4 answered with his OWN law instead of a pick).
- Changed the plan: Q4 release length (0.3 s rec vs 0.2 / 0.45) → "the
  burst fade should be snappier at higher energies and lazier at low
  energies" — an ENERGY-DEPENDENT time, not one of the three offered
  (promote: when a timing param is offered as fixed options, also offer
  "follows the music energy" with the two ends, the way the star wave's
  period and Pulse's calm/intense pairs already do; he reaches for it
  himself). Q3 clamp → 18 deg with "for now" (demote: he does not want to
  own a constant's exact value yet; ship it as one named constant, say so).
- Waved through / unanswered: none; Q1 (how he judges a burst) and Q2
  (only bursts change, steady speed kept) confirmed as stated.
- New preference: he answers well from SYNCED SIDE-BY-SIDE animations of
  today vs each candidate on the real crystal, with the per-frame numbers
  (peak deg/frame, rise/decay ms, cap hits) beside them and a ¼× slow-
  motion pair of one big hit — one message back, no re-render asked.
  "Do actual analysis on how it moves" means a motion trace, not a look.
- Facts that were decisive and he could not know: the crystal renders at
  30 fps (not the 60 Hz the audio runs at), so the "cap" question was an
  aliasing question (180/edges deg per frame); the jerk was the lows
  filter's burst shape, not the cap (no cap hits at his usual spin).
  State the render rate and the per-frame jump limit in any motion plan.
- Visuals: four synced cases (two songs at his two live spin levels), a
  mean-preserving law so "steady speed unchanged" was a number (within 3%)
  not a claim; what missed: a 22 deg variant was rendered for the loud case
  only — he picked 18 without it, but a full-range row of clamp levels
  would have fit his §13 preference better.
- Confirmation: "yes to both questions"; "do 18 degrees per frame for now".
- Room verdict: pending (after deploy).

### Template for the next entry
```
### YYYY-MM-DD — <plan name> (<new|improve>, <kind>, <effect/scene>)
- Rounds: N; questions asked: N; answered explicitly: N; "take your rec": N.
- Changed the plan: Qn <title> → <his answer>.   (promote)
- Waved through / unanswered: Qn, Qn.            (demote)
- New preference: "<his words>".                  (→ bank §, visuals.md)
- Visuals: what drove the pick; what missed and why.
- Room verdict (after he judged it): <his words>; what the plan got wrong.
```
