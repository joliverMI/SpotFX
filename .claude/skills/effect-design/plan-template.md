# Plan document — the shape he confirms

Write the plan as `report.md` in the session's data directory (outside
this repo), with the explainer beside it. Every section below is present,
even when one line long. Publish the plan itself as a claude.ai Artifact
(the "Review link" line below carries its URL) — he confirms FROM THAT
ARTIFACT, in chat; record his confirming words verbatim at the top of the
file when they arrive.

```
# <Effect/scene> — <one-line what changes>              (plan, YYYY-MM-DD)

## Review link
<the claude.ai Artifact URL he confirms from; a local Lavish URL, if one
exists too, is a secondary convenience only>

## His ask, verbatim
<the sentence(s) he typed; nothing paraphrased>

## Classification
new | improve · kind (Matrix/Strip/Singles effect · scene · flare kind ·
transition · drop-sequence effect · house look) · which effect/scene ·
skills and docs loaded

## How it works today (facts, from the scout)
Module(s), stored params and their LIVE values (note where live drifts
from the seed), scenes that bind it, what charge/lull/drop/flares do now,
device constraints that bound the design. Cite file:line.

## Decisions (his words, round by round)
Q1 <title>: <his answer> — <what it fixes in the design>
...
Open (he did not answer; default taken, marked open): Qn <default>

## Visual comparisons
Where the explainer is; which options were shown; which he picked and
what he said about it; the measured numbers behind the pick.

## What is built
- Code: files, new/changed params with units, sign conventions
  (docs/SPECTRA_TIMING_CONVENTIONS.md), escape hatch back to today's
  behaviour (a param value that reproduces the old motion exactly).
- Scene data: which stored fields change, on which scenes, how they are
  backed up and undone; what stays his.
- Migrations / seeders: written but NOT run before the tuning gate
  (docs/ADDING_EFFECTS.md) for a new effect.
- Skill + help: the effect's/scene's SKILL.md, helpContent.ts, Sonic
  follow-up (sonic-ops skill) if a setting or action is user-facing.

## What is NOT built
Explicitly out of scope, and why (his call or deferred).

## Acceptance checks (offline, reproducible)
The measurements from the explainer the build must reproduce, as tests or
check scripts (scripts/check_<effect>_*.py pattern); frame budget on the
target; the structural gates (skill currency, help content).

## How he judges it in the room
Which scene, which song or Test Bed clip, what to watch for (the two or
three visible claims), how long to watch, what "wrong" looks like, how to
undo (the escape-hatch param, the backup file, the restart hazard
AGENTS.md names). The tuning gate for a new effect: build → he tunes live
→ then seed.

## Ship path
direct-PR or pipeline; deploy is a separate step; which unit restarts.
```
