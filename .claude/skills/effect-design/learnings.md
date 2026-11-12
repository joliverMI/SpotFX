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
