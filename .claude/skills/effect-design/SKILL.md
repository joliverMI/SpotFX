---
name: effect-design
description: >
  The design PROCESS for a new or improved light effect, scene, flare kind,
  transition or drop-sequence effect — the interview-first workflow the
  Admiral asked for on 2026-11-12 ("I want to build a new effect/scene" /
  "I want to improve an existing effect/scene", then targeted questions,
  visual comparisons, a plan he confirms, then the build). Load it the
  moment he says either of those sentences or anything shaped like them
  ("make the fish ...", "a new strip effect for ...", "the drop should ...",
  "the switch into STAR looks ..."). It is run by the agent talking
  DIRECTLY to him (DJ / firstmate); scouts gather facts and build the
  visuals; a build crewmate ships the confirmed plan. For the MECHANICS of
  any one effect or scene, this skill points at that effect's own skill
  (`.claude/skills/<name>-effect`, `<name>-scene`, EFFECT_SCENE_MAP.json)
  and `docs/agents/` — it never duplicates them.
---

# Effect design — from "I want to..." to a confirmed plan

This skill is a process, not a knowledge base. Its siblings carry the
substance and grow with every session:

- `question-bank.md` — the questions, organised by KIND and by design-tree
  BRANCH, each with its usual recommended answer and the sessions it came
  from. Draw rounds from it; never read it to him.
- `learnings.md` — what each past session taught: questions that mattered,
  questions that wasted his time, his recurring preferences, the defaults
  he always picks. Append after EVERY session (step 7).
- `visuals.md` — how the past explainers were built (real screen look,
  offline render rig, crystal sprites, side-by-side), with the in-repo
  scripts to copy from.
- `plan-template.md` — the shape of the plan document he confirms.

## Who does what

The interview is between him and the agent he is talking to. Only that
agent asks him anything. Scouts (fresh-context sub-agents) find facts and
render visuals; they never address him. The build crewmate receives the
confirmed plan, never the raw interview. A crewmate who finds an open
design question mid-build routes it back up through its status file; it
does not improvise an answer.

## The flow

### 1. Intake (one message, no questions yet)

Classify his ask on two axes and say the classification back in one line:

- **New vs improve.** "Improve" includes fix, retune, rework, "it looks
  wrong when...".
- **Kind.** Matrix effect (renders to `crystal-mapper`), Strip effect
  (1-D), Singles effect (Hue bulbs / single-colour virtuals), scene (the
  SPECTRA SceneV2 bundle of effects + flare bands + kinds + colour
  preference + dwell), flare kind, transition (an effect switch, a
  transition program, its timing), drop-sequence effect (what the lull and
  the drop do, pre-drop looks, the drop switch), house-lighting look.

For **improve**, load the effect's/scene's own skill FIRST (look it up in
`.claude/skills/EFFECT_SCENE_MAP.json`; a Matrix effect also needs
`crystal-hex-grid`). For **new**, load the skill of the nearest existing
sibling (a new Matrix particle effect: `orbits-effect` + `fish-effect`; a
new strip look: `fx-effects.md`'s strip phase layer section; a new
Singles look: `pulse-effect`). Read the routing-table doc in `AGENTS.md`
for the kind. Then say which docs you loaded, in one line.

### 2. Facts before questions

Dispatch a scout (not him) to establish, read-only, against this checkout
and the live read-only API where the owning doc permits:

- How it works TODAY: the module/scene data, the params and their live
  values (stored values drift from seed scripts — `fireworks` spawn_rate
  and the Fish scene's strip entry are the recorded examples), which
  scenes bind it, what the lull / charge / drop / flares do on it now.
- The REAL look: a short render of today's behaviour through the offline
  rig (`visuals.md`), or screenshots of the real page for UI-shaped asks.
- The constraints that bound the answers: the device (976 real cells on
  the hex crystal, strip lengths, Hue rate limits), the Pi/ESP frame
  budget, the timing conventions (`docs/SPECTRA_TIMING_CONVENTIONS.md`),
  and any decision already recorded in `docs/SPECTRA_SPEC.md`.

Rule: a question that asks him for a fact the scout could have found is a
wasted question (`learnings.md` lists the ones that were). Ask him for
DECISIONS and for what he SEES.

Do not block the whole interview on the scout: ask the frontier that does
not depend on its findings now; the rest waits one round.

### 3. Grilling rounds

Work the design tree in rounds. The FRONTIER is every decision whose
prerequisites are settled; ask the whole frontier in one round, numbered,
each with ONE recommended answer worded so a plain "yes" accepts it. A
question whose answer depends on another question still open this round
belongs to the next round. The format (the fleet's grilling skill, which
this skill applies to effect work):

```
❓ **Q1** - **<title>**: <body; multiple choice when the choices are real>

➡️ <recommended answer, with the one reason it is recommended>

---

❓ **Q2** - ...
```

Build each round from `question-bank.md`: pick the branches the kind
needs (look/motion, music response, colour, fixtures, transitions in/out,
flares, performance, testing, done-criteria), drop any question the facts
step already settled, and lead with the questions `learnings.md` marks as
the ones that changed past plans. His recorded defaults become the
recommended answers. Three to six questions per round is the usual size;
he answers in short lines ("A", "yes", "approve option A for the wake"),
so keep each body to what the choice needs.

When the choice is visual, do not ask it in words: go to step 4 and ask
the question beside the pictures.

The interview is over when the frontier is empty and nothing is silently
assumed. He may end it earlier ("go ahead on the defaults"): then the plan
records every unanswered question with the default it took, marked open.

### 4. Visual comparisons

A question about how something LOOKS is answered by looking. Build the
options as realistic renders or mockups from the real look and publish
them as one HTML explainer page (today beside each proposal, same seed,
same music, one scrubber per pair), then ask the question under the
tiles. `visuals.md` records how every past explainer was built and which
in-repo render scripts to start from (`scripts/render_*.py`,
`tests/*_harness.py`, `fx/headless.py`). Never describe in words what a
render could show; never show a hand-drawn sketch of an effect when the
real pipeline can render it offline.

He reviews the page himself, edits it when he wants (the UI-layout plan's
`explainer-final.html` is the precedent: his edited copy became the
spec), and answers in chat. Measured numbers belong beside the tiles
(lit cells, mean brightness, frames to settle), because "too abrupt" and
"washes out" are claims a number can check.

**Every round ships as a claude.ai Artifact he can open on his tablet or
phone, not a local Lavish session.** Lavish serves on `127.0.0.1`, which
his tablet cannot reach ("connection refused" — the STAR session,
2026-11-12, `learnings.md`); a local Lavish session is optional, at most,
alongside the Artifact, never the only way he can see a round. Scouts
build the HTML page and the render PNG/GIF files; the agent talking to
him (DJ/firstmate) is the one who publishes — scouts never address him
and cannot publish to him directly. See `visuals.md`'s artifact
constraints for what that means for the scout's output.

### 5. The plan document

When the frontier is empty, write the plan (`plan-template.md`): his
verbatim ask, the decisions in his words, what is built (files,
params, scene data, migrations), what is NOT built, the acceptance checks
(offline measurements the build must reproduce, tests), how HE will judge
it in the room (which song, which scene, what to watch for, how to undo),
and the open defaults. Publish the plan itself as a claude.ai Artifact
too (the template's "Review link" line carries its URL) and get his
explicit confirmation FROM THAT ARTIFACT before any build is dispatched.
A plan he has not confirmed is a draft.

### 6. The build

The confirmed plan goes to a build crewmate on the normal ship path, with
`docs/ADDING_EFFECTS.md`'s human tuning gate intact for a NEW effect
(build, register, let him tune live, THEN seed any scene). The crewmate
updates the effect's/scene's own `SKILL.md` and `helpContent.ts` in the
same change (the structural gate `scripts/check_effect_scene_skills_current.py`
enforces the skill half). Deploy is a separate step from merge; say so.

### 7. The learning loop (not optional)

After he confirms the plan — and again after he judges the result in the
room — append to `learnings.md` under a dated heading:

- which questions changed the plan (promote them to the bank, or raise
  them in the branch's order);
- which questions he waved through, answered "you decide", or had
  already answered by fact (demote or delete them from the bank);
- any preference he stated that will recur (becomes a recommended answer);
- what the visuals got right or wrong (into `visuals.md`).

Durable entries are then PROMOTED into `question-bank.md` in the same
change, so the next session's rounds start sharper. Ship the learnings
edit as its own small PR if the build PR is not yours.

## Safety and scope reminders that apply to this process

- The interview and the renders touch nothing live. The scout reads;
  the offline rig renders onto dummy devices. His room is not a preview
  surface for a plan (`AGENTS.md` safety rules).
- His authored scene data is his: a plan that changes stored scene
  values names each one and how it is backed up and undone.
- Keep private paths, hostnames, tokens and his home-network details
  out of the skill files and the explainer: this repo is public. The
  explainer itself lives outside the repo (the fleet's data directory);
  the repo keeps only the recipe and the in-repo render scripts.
