# STAR — edge count fixed (2026-08-15)

Durable record for [OQ-6 / §54 in `SPECTRA_SPEC.md`](SPECTRA_SPEC.md#open-questions) — the
Admiral's final word, superseding an earlier "freeze at 6" cut of this fix: **"i will make it
very simple just delete whatever portion of any Flair was changing edges. but initial can be 3
to 6."** `scripts/freeze_star_edges.py --apply` is the migration that does it; this file is the
lookup if he ever wants any of this given back, so restoring it is a command, not an
archaeology exercise.

Scene: **STAR** (`d3aab04c-7e23-4693-bd26-16bad45792a6`), `storage/spectra/scenes.json`.

## Live-proof finding (2026-08-16, 01:33–01:45Z): migration NOT applied to his live room

PR #79 (commit `0608aa8`) merged the code mechanism (`sticky` field,
`scene_response._reroll` honoring it) and was believed fully deployed. It was not: the PR's
own commit message says the migration itself (`scripts/freeze_star_edges.py --apply` against
the live store) had not yet been run, "he was asleep throughout." That step was still missing
at proof time. Verified live via `GET /spectra/api/scenes/{id}`:

- Matrix device's `edges` binding still reads `"sticky": false`, `"dice": "a"` (shared with
  `star`, not independent), and the old unequal 3-value step function
  (`6.0 / 3.0 / 5.0`, fallback `6.0`) — not the new equal 25%-per-value 3/4/5/6 bands this
  file describes above.
- `"Flare patch 0.7–1"` and `"Drop patch 0.7–1"` still carry an explicit `edges: 6.0` override
  in their `params`.

Reproduced live against his room (`POST /spectra/api/scenes/{id}/fire` with `dry_run: false` to
baseline STAR at `edges=6`, then `POST /spectra/api/engine/event {"class": "flare",
"intensity": 0.9}`): the response's own `kinds` list showed **"Dice Re-roll" rolling `edges`
6→5**, immediately followed by **"Flare patch 0.7–1" moving `edges` to `6.0`** — both firing
mid-run, exactly the behaviour this fix exists to stop. Ten `dry_run` fires at intensity 0.5
sampled `edges ∈ {3, 5, 6}` only (no `4`), consistent with the old step function, not the new
uniform one.

**Conclusion: the edge-count rule does not currently hold at his fixtures.** The code is
correct and merged; the data migration is the missing step. Fix: run
`scripts/freeze_star_edges.py --apply` against the live `storage/spectra/scenes.json`, then
re-verify with the same live-fire + flare-event sequence above. Not run during this pass —
applying a live scene-data migration was judged outside a pure proof task's authority and was
escalated instead; see the task status log.

## What changed

**Once a scene run starts, nothing moves its edge count again.** The initial value is a fresh,
uniform roll over every integer 3, 4, 5, 6 — independent of `star`'s own roll — and it holds for
the life of that run.

1. **The Matrix device's `edges` param** — was a `signal="random"` binding re-rolled mid-run by
   the "Dice Re-roll" flare kind. It's still a `signal="random"` binding (a fresh scene FIRE
   still rolls a value — `scene_compiler.resolve_scene` is unaffected by this change), but now
   marked `sticky: true` (`spectra/models/binding.py`), a new field `spectra/services/
   scene_response.py::_reroll` checks and skips — so the "Dice Re-roll" kind can no longer touch
   it mid-run. Its four steps are now equal bands (thresholds `0.0/0.25/0.5/0.75` → `3/4/5/6`,
   each exactly 25%) instead of the old three unequal ones, and it no longer shares a dice
   letter with `star` (`dice: null` — an independent draw).
2. **`"Flare patch 0.7–1"`** (the top flare band's permanent kind) — no longer patches `edges`
   at all; still patches `spin`/`star` exactly as before.
3. **`"Drop patch 0.7–1"`** (the drop band's permanent kind) — same: `edges` removed,
   `spin`/`star` unchanged.

No other engine behaviour changed: the "Dice Re-roll" and "Colour Jump" kinds still work exactly
as before for `star` and for every other scene — `sticky` is a per-binding opt-out, default
`False`, so nothing anywhere else moved. `edges` appears in no other scene (checked).

## Provenance — recorded, but NOT what drove the 3-to-6 value

His **legacy** STAR authored `edges` as a bare static `6` — no signal binding, no steps, and
**neither** `"Flare patch 0.7–1"` nor `"Drop patch 0.7–1"` exists anywhere in the legacy
per-band `param_patch` data. The 6/3/5 dice binding and both patches were introduced during the
SPECTRA rebuild by an agent, not by him — he never asked for any of it, and noticed only because
his six-pointed star stopped being six-pointed. See `AGENTS.md` ("A scene's stored data is not
proof he authored it") for the general rule this instance is evidence for.

**This did not decide the frozen value.** An earlier pass argued "6" because both patches and
the old binding's fallback all pointed at six — reasonable evidence, but for the wrong question:
once he said "3 to 6" directly, that instruction stands regardless of what any prior authoring
(agent-introduced or otherwise) pointed at. Don't re-litigate this if revisiting the file.

## Exactly what was retired (what `--restore` gives back)

`--restore` undoes exactly what this fix changes: back to what's actually deployed in his room
immediately before this migration runs (the 6/3/5 dice binding + both patches' `edges`
override) — **not** his deeper legacy static `6`, which is a separate, bigger change this script
does not make.

### 1. The Matrix device's `edges` binding, as deployed today

```json
{
  "bind": "signal",
  "signal": "random",
  "window_beats": 0,
  "window_dir": "past",
  "mode": "steps",
  "in_min": 0.0,
  "in_max": 1.0,
  "out_min": 0.0,
  "out_max": 1.0,
  "steps": [
    {"threshold": 0.0, "value": 6.0},
    {"threshold": 0.4, "value": 3.0},
    {"threshold": 0.8, "value": 5.0}
  ],
  "fallback": 6.0,
  "random_sign": false,
  "dice": "a"
}
```

(6/3/5 at 40/40/20%, dice-correlated with `star` — proven at 6000 draws in `scripts/
check_spectra.py`'s synthetic dice-correlation fixture, which is untouched by this change.)

### 2 & 3. The two hand-authored flare-kind patches, as deployed today

- `"Flare patch 0.7–1"` (`type: "permanent"`, top flare band, `[0.7, 1.0]`):
  `"edges": {"mode": "absolute", "value": 6.0, "offset": null, "lo": null, "hi": null}`
- `"Drop patch 0.7–1"` (`type: "permanent"`, the drop band, `[0.7, 1.0]`):
  the identical target.

All three retired values are also kept as constants in `scripts/freeze_star_edges.py`
(`RETIRED_EDGES_BINDING`, `RETIRED_EDGES_TARGET`, `RETIRED_PATCH_KIND_NAMES`) — kept there too,
not just here, so `--restore` is a real one-step command and the two copies can be diffed
against each other.

## What did NOT change

- `spin`/`star` on the Matrix device, and both patches' `spin`/`star` overrides — exactly as
  authored (agent-introduced provenance and all), still random/dice-correlated where they were.
- The "Dice Re-roll" and "Colour Jump" kinds, and the generic dice-reroll/patch-broadcast
  mechanisms in `spectra/services/scene_response.py` — still work exactly as before for every
  other scene, and for `star` within STAR itself.
- Every other scene in `storage/spectra/scenes.json`.
- `scripts/check_spectra.py`'s synthetic `"Spec"` fixture (lines ~91–144, ~707–763) exercising
  the *generic* dice-correlation/re-roll capability with `star`/`edges`-named example params —
  independent of the real STAR scene, still tests the capability itself.

## Restore

```
.venv/bin/python scripts/freeze_star_edges.py --restore --apply
```

Dry-run by default (drop `--apply` to preview first, same as fixing). Proven to round-trip
exactly against his real live scene data — `scripts/check_spectra.py`'s "STAR edges restore is
the exact inverse of the freeze" check, plus a manual proof against a snapshot of his live
`storage/spectra/scenes.json` during this change's review (the only diff after a full
freeze→restore round-trip is `sticky: false` appearing on every OTHER binding in the file too —
a new schema field's explicit default, not a semantic change).

## Status at merge

**Built and unit-tested (`scripts/check_spectra.py`: idempotency, exact restore-inversion, a
4000-draw uniformity proof over 3/4/5/6, and a full response-engine proof firing flare at
0.1/0.5/0.97 and drop at 0.97 against the fixed scene — confirming `edges` never appears in any
executor write while `star` still does), not yet applied to his live room.** He was asleep — no
restart, no scene edit, no light driven — while this was authored. Deploying it is:

```
.venv/bin/python scripts/freeze_star_edges.py --apply
```

run against the live `storage/spectra/scenes.json` (default `--scenes-file`), by whoever owns
that deploy step next.
