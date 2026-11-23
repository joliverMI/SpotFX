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
14. **An approved mechanism and a legible render are two separate things
    to verify.** "He approved it" and "it reads clearly on the rendered
    tile" are not the same claim — shape-flares-lead's Fish correction
    arrived INSIDE a blanket approval message naming one tile by name, and
    his 2026-11-17 room verdict showed it is worse than that: three of six
    word-shape mechanisms (Fireworks, Orbits, Fish) were approved on the
    explainer, built to their stated clarity bars, reviewed green, and
    still read "not clear enough" live. Re-read an "I approve" message for
    a per-tile correction before treating it as unconditional sign-off, and
    never let a green bar at build time stand in for his eye in the room.
15. **An honestly unreachable clarity bar still gets reported, with its
    likely room lever pre-planned.** When a build-time measurement shows a
    bar is structurally unreachable on an effect — a property of how it
    renders, not a defect — report the honest number and let his eye
    decide rather than reworking the mechanism further; shape-flares-lead's
    "W3 — the list for the Admiral's eye" named three such cases and his
    ruling on two was explicit option-A ("accept/ship as built, I'll judge
    by eye"). The refinement his W4 verdict added: his eye verdict arrived
    within HOURS of the deploy, as a tuning list, so a row reporting an
    unreachable bar should also pre-plan the cheap room lever it will most
    likely need (a dark canvas, a speed-vs-trail trade) — the follow-up is
    then a one-row ask, not a design round.
16. **A clarity bar must be a CONTRAST bar, never a "lit" bar — and the
    light threshold is DERIVED, not a fixed "half of full".** Counting a
    cell lit at 8-20/255 (shape-flares-lead's W1.2/W1.3 bars) passes a
    trail at half brightness and a canvas full of other sparks just as
    easily as a clearly-formed shape; grade by luminance instead (dark /
    <64 / <128 / ≥128 of 255). But a flat "≥ half of full" requirement is
    itself the wrong bar on a one-pitch band for a blob effect: W4.4 proved
    it structurally unreachable (24 of 24 rows under it) because Orbits'
    splat kernel caps the band's own outer cells at ~65/255 at his
    `blob_size`, whatever the speed or the trail. **Do the band-width-
    against-the-effect's-own-kernel sum FIRST** and set the light threshold
    at what that kernel can actually deposit on the band — 64/255 was the
    honest threshold for Orbits and Fish (blob kernels), 128/255 for
    Fireworks' sparks, which really do reach half of full. Then require the
    band to stand out against the REST of the panel (a band/rest contrast
    ratio) and against the same-seed UNTOLD frame, at EVERY frame of the
    hold. And the CANVAS is part of the design, not just the figure's own
    pixels — what else the effect lights when the figure lands (beat
    bursts, a wake, a trail of other blobs) decides legibility as much as
    the figure does, so a sparse-light effect may need a quiet window
    planned around the figure from the
    start, not added after his verdict names it.
17. **A verdict's numbers can overshoot — build every number as a
    retunable constant, and expect a second pass.** His W4 room verdict's
    own quantified asks on Fireworks — "increase the amount of blobs by
    50%", "have it hold 50% longer" — came back ONE DAY LATER, in his W5
    verdict, as "I think we overtuned the fireworks last time": the
    direction was right, the magnitude was not. A number he states in a
    verdict is a first guess at the fix, not a target to hit exactly;
    land it as a named constant he can retune by voice or by a later row
    (never hand-derived into the math), and plan for a second pass to walk
    it back rather than treating a shipped, measured-green build as the
    close of the question.
18. **The device's orientation belongs in the explainer tiles.** Every
    shape-flares-lead explainer, through W4, rendered a shape in the
    library's own unrotated frame — correct for the math, upside-down on
    the one fixture that draws it. It took him living with it in the room
    to say so: "the shapes should be 'flipped' because they are visually
    upside-down on this device." A tile whose whole point is "this is what
    you will see" has to render the shape the way the device will actually
    show it, not the library's internal convention — the same discipline
    §14 already asks of an approved mechanism, one step earlier, at the
    picture itself.
19. **Measure at the device's own frame rate.** A rig's dt is part of the
    claim: a proportional steer that is stable at 60 fps (gain·dt 0.65)
    overshoots at 30 (1.30), and row W6.1 — the one row that measured Fish
    at the crystal's own 30 fps rather than the rig's inherited 60 — found
    a fish 14–20 px off the lit panel that five earlier rows at 60 had
    never seen. See `docs/agents/fx-effects.md`'s "MEASURE A SHAPED EFFECT
    AT 30 fps" rule (~line 1234) for the arithmetic; this entry only banks
    the discipline.
20. **"Lit", "filled" and "distinct" are three different bars, not one.**
    His three verdicts on Fish/Orbits asked for each in turn — W1: lit; W4:
    "not clear enough"; W6: "filled with fish or trail … not distinct
    enough" — and each one survived the last bar without meeting the next.
    Set the bar at DISTINCT from the first row: a half-brightness threshold
    AND a band/off-band ratio, both at ONE frame, not an average. Give every
    motion bar a derived geometric floor instead of a round number — a
    4.33-pitch fish cannot draw its nose within 1 pitch of a line; a heart's
    cusp forces 1.3–1.6 heading reversals a second by its own geometry — and
    pick a dimming lever by attributing the off-band light per layer before
    touching anything.

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

### 2026-11-15/22 — shape-flares-lead (new, a shared shape library + a new
response class + six effects, Black Hole V2 / STAR / Orbits V2 / Fish /
Sauron / Fireworks V2)

This plan was unusual among the sessions logged here: it was the first one
built in PARALLEL waves by five crews rather than by one agent end-to-end,
and the squadron leader's own review ledger
(`/home/javi/fleet-spotfx/data/shape-flares-lead/report.md`) carries a
second layer of "what we learned" that belongs to THAT process (rebase
sequencing, measurement discipline, honest-bar reporting) rather than to
design-session technique; only the design-session half is recorded here.

- Rounds: 2 (one ten-question grilling round; one approval message that
  carried a real plan revision). Questions asked: 10; answered explicitly:
  1 (Q8); "take your rec" for the rest: 9 (his reply, verbatim, was the
  single line "8C, rest defaults" — the most compressed answer logged in
  this file to date, confirming "How he answers"'s existing note that a
  short bundled reply is a GOOD round, not an under-specified one).
- Changed the plan: Q8, Sauron's pupil-or-iris → he picked C, both at once
  ("have it's pupil or something chagne into that shape"; the recommended
  option was iris-only, with pupil-only and both offered beside it). He
  did not ask for a new option — he picked the combining one already on
  the page over the narrower rec (reinforces "How he answers"'s "he adds
  to the recommendation toward MORE of his own idea" above, with a
  stronger example: "the rec plus the other listed option, taken whole",
  not "the rec plus a hint").
- A revision arrived INSIDE an approval, not as a separate round. His
  message approving the whole plan (P1 A / P2 A / P3 A) also named one
  effect by name as not working yet: "I approve the defaults, but the fish
  didn't seem to be sufficiently making the outline. We may need to boost
  the trail brightness and lower decay briefly to get it to show better.
  They also may need to more tightly flow." This reopened only Fish's own
  tile (trail brightened ~1.5x and its half-life raised under the shape,
  the water trace kept brighter through the hold, the steering tightened)
  while every other scene's design stood as approved (reinforces "How he
  answers"'s "he comments on tiles more than he answers numbered lists"
  above: a message that reads as a blanket APPROVAL can still carry a
  per-tile correction in the same breath).
- Waved through / unanswered: Q1 (the name, "Word Shapes"), Q2 (a fifth
  Words section), Q3 (a Shapes row on Sung labels), Q4 (the five timing
  numbers), Q5 (the word-colour play rules), Q6 (on for every song once a
  scene's Words band carries the kind), Q7 (STAR included, spin eases to a
  stop), Q9 (one big centred Fireworks burst), Q10 (3-or-fewer threshold).
- New preference: §14 and §15 above (approved-mechanism-vs-legible-render,
  honest-bar-reporting) were both drafted from this session and CONFIRMED,
  harder than first drafted, by the room verdict below.
- Visuals: the per-scene animated crystal tiles (the real 976-cell mask,
  his three shapes, a scrubber with the sung word marked) is what let him
  give the Fish correction with no argument — he named the exact effect
  and the exact two levers (trail brightness, decay) from watching the
  tile, not from reading the mechanism's prose. What the FIRST pass of the
  Fish tile got wrong, worth stating for the next session that renders a
  sparse-light effect (few particles, a trail, a wake): the simulation's
  law was correct but its rendered line was too faint/short to read as
  "the shape" at a glance — a continuous param like a trail's own
  brightness or half-life needs its own look-right-at-a-glance pass on the
  actual render, the same way §13's full-range-grid preference exists for
  a shape PARAMETER's range, not just for whether a motion law is right.
  One more miss, found only after the room verdict: the explainer's
  crystal tiles rendered the shape's own pixels on a dark tile, while the
  room showed them on top of the effect's ordinary light at his tuned
  densities — the next explainer for a figure on a live effect should
  render the figure INTO a busy frame of that effect (a loud-Energy frame
  at his stored params), not onto black.
- Room verdict (2026-11-17, in his room, hours after the deploy),
  verbatim: "a few pieces of feedback on the word shapes. First, it's hard
  to test for a couple reasons: the preview of the flare doesn't seem to
  work (I only tested orbits and black hole, but it didn't seem to show).
  Second, star and black hole look pretty good, but could last a little
  longer. Fireworks is too cluttered to visually identiy the shape. Let's
  have it plan to make sure no fireworks fire right before, or
  concurrently, so that it is on a mostly dark canvass. Also, increase the
  amount of blobs by 50% so it is more clearly visible, and have it hold
  50% longer. Finally, I can tell the fish and orbits are trying to do
  something, but it's not clear enough. They need to increase speed so
  they can pass the outline fast enough that their trail stays and it
  clearly forms the shape. Start with orbits and when we get that dialed
  in, we will do fish. I think fish are going to have to override some of
  the motion rules to move sharply enough to form corners, like on the
  star." The two build-time "ship as built, I judge by eye" items from the
  plan's own honest-miss list resolved differently than either reads on
  paper: Fireworks' near-white was NOT what he saw — the clutter of his
  own beat bursts under the shape was (a canvas problem, not a colour
  one); Fish's white tail was not mentioned at all — the faint, slow
  outline was, the same complaint as Orbits (fixed there first, per his
  own sequencing — "start with orbits ... then we will do fish"). What the
  plan got wrong: three of six mechanisms (Fireworks, Orbits, Fish) were
  approved on the explainer, built to their stated clarity bars, measured
  green, and still read "not clear enough" live — the tile problem was the
  room problem, confirming §14 harder than it was first drafted; and the
  "lit at 8-20%" bars used for Fireworks and Orbits (W1.2, W1.3) were
  exactly the vacuous kind §16 now rules out — the Fish review's
  band-against-rest contrast metric caught the same defect and was never
  re-run on the other five rows before the room session.
- Second room verdict (2026-11-18, his second verdict on this feature),
  verbatim: "Word Shape feedback: I don't need the banner for the word
  shape test mode. Show the word/effect details on the audio shape on home
  page. Put the trigger point on the audio shape, not just to top ticker.
  i should be able to tap the audio shape to learn more. make it clean. In
  the countdown box, don't show the triggering phrase or word, just say
  'red' or 'sky blue' or whatever it is getting interpreted as. I told you
  to have low energy colors hold untl next scene change, instead of a
  temporary flare, but i want to see it just as a flare, just not as fast.
  I think you can do this without changing code by changing a setting to
  0. Oribits is really good at showing shape, we need to get Fish to
  behave similarly. Ask me questions if it's hard to implement, but you
  might need to override some min turn radii to match the effect,
  especially on the star. I think we overtuned the fireworks last time.
  The background doesn't need to be clear of other fireworks, just they
  need to be dimmer, so fading out already. I think we can give it 80%
  less pre-fire darkness time. It also holds too long and fades too
  abruptly. And it's too well-defined. Let's turn back the increase in
  blob count, and at the end, the blobs should lightly break apart and
  fade out. Also, the burst is too fast. Slow the burst by 60% so we can
  see the blobs moving out to the outline, and then decelerating to almost
  a stop, but not quite a stop. The blobs should always be slightly
  drifting. Finally, the shapes should be 'flipped' because they are
  visually upside-down on this device. Rotate 180 degrees, and make that
  the 'default' orientation. As I think most of what I want is settings
  changes, not major coding, no test is needed, just deploy when ready."
  His W4.4 brightness A/B/C question is SETTLED by this verdict's own
  words — "Oribits is really good at showing shape" — as A, as built, no
  further change asked. Wave 5 answered it, parallel-built and merged in
  this order: W5.7 (the half-turn default orientation, PR #546,
  `324d411d`), W5.1 (the test-mode banner removed, PR #543, `9fafb6d6`),
  W5.3 (the countdown box reads the colour word, not the phrase, PR #544,
  `da75df3e`), W5.2 (Home's audio shape carries the trigger point and a
  tap-for-details popover, PR #545, `d7245341`), W5.6 (Fireworks retuned —
  dim not dark, 80% less pre-fire quiet, sparks back to 60/100, the hold
  stretch dropped, a 60%-slower burst that drifts rather than stopping, PR
  #547, `c110176a`), W5.5 (Fish takes Orbits' speed-and-trail approach and
  overrides its own turn radii at the corners, PR #548, `feaaf4c4`); W5.4
  (the `energy_cutoff` setting written to 0 at deploy, so every low-energy
  colour word reads as a flare rather than a hold, no code of its own) and
  W5.8 (this docs row) close the wave. No live room test was asked for
  this verdict ("no test is needed, just deploy when ready"); the gate was
  CI green plus the squadron leader's review, then one web build and one
  `spectra` restart. Two learnings promoted to the standing list above
  from this verdict specifically: §17 (his own W4 numbers — "+50% blobs",
  "hold 50% longer" — read back as "overtuned" a day later, so a verdict's
  magnitude is a first guess, not a target) and §18 (the orientation ask
  itself — every tile through W4 showed the math's own frame, never the
  panel's).
- Third room verdict (2026-11-18, msg 105), verbatim: "Only thing left is
  the fish needs a little more tuning. Everything else was good. The shape
  outline needs to reach at least a moment where it is either filled with
  fish or trail. Right now, the fish seem to jitter out of the outline and
  so it isn't distinct enough. Also, if we did a highlight of the shape in
  orbits, do it on fish." Everything else in waves 0–5 was accepted by his
  own word; one row, W6.1, answered it. W6.1 (PR #551, `d1def3e3`): the
  Fish rig had measured at 60 fps while the crystal renders at 30, so every
  W5.5 number was read at twice the live rate; at 30 fps the proportional
  steer overshot and fish walked off the panel outright. Four arithmetic
  causes were found and fixed (a proportional steer past `gain·dt < 1`, a
  turn clamp expressed as an angular rate rather than a per-frame ceiling,
  a pursuit aim arc shorter than a frame's own travel, and an ungated
  wander term) — none of it a guess. "A highlight of the shape in orbits"
  did not exist to port: Orbits has no shape-time brightness lift at all,
  so what Fish actually took was Orbits' trail-outlives-the-revisit-gap
  PERSISTENCE, reversing W5.5's own choice to divide the trail half-life by
  the lap speed-up. The row's own bars (95% of the band filled at the
  fullest hold frame, a 20× band/off-band ratio) were missed on four of six
  rows and reported with their derived geometric floors rather than moved
  to force a pass. Deployed 2026-11-19 09:36 EST (`data/ws-w6-deploy/report.md`).
- Fourth room verdict (2026-11-19, msg 110), verbatim: "I'm happy with
  fish." Fish is accepted; with it every wave of the plan (0–6) is built,
  deployed and accepted by his own word.
- His verdict on Sauron's shaped eye, W1.5 (2026-11-22, msg 112), verbatim:
  "sauron looks good." The W3-list departure for his eye — the shaped iris
  reading 1.5–1.65× taller than wide, the eye's own aspect — is accepted.

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
