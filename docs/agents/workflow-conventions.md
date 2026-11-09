# Workflow conventions: timing, adding effects, help content

Moved from AGENTS.md during the 2026-11-09 trim (PR fm/spotfx-trim-agents-md).
Content below is verbatim from the prior AGENTS.md; see AGENTS.md's routing table
for when to read this file.

---

## Timing and offset-direction conventions — READ BEFORE TOUCHING ANY TIMING CODE

`docs/SPECTRA_TIMING_CONVENTIONS.md` is the canonical, file:line-cited record
of every timing/offset/lead/delay quantity in this codebase — its unit, its
sign convention in plain words, which engine owns it, and whether it's live
in SPECTRA or dark/inherited from the predecessor. **Two families of timing
quantity use OPPOSITE sign conventions for "earlier"** (a `lead_ms` family,
positive=earlier; an `offset_ms` family, negative=earlier) and both are live
simultaneously in `spectra/services/trigger_engine.py`'s `tick()` — mixing
them up is silent and has cost real time more than once. Five real failures
this week (arguing an audio delay in the wrong direction; treating a
wandering `shape_offset_ms` reading as a measurement; reading the
**predecessor's** composite timing offset while SPECTRA's own, narrower one
actually governed the room; diagnosing a trigger-store divergence by
inference instead of reading both stores; asserting a flare offset was
consulted by the firing path without checking) all trace to knowledge that
was already written down in this repo and not read. Check that document
before writing, measuring, or reasoning about anything time-related — it is
also where new timing quantities get recorded, not here.

## Adding a new LedFX effect

Follow `docs/ADDING_EFFECTS.md` — the full checklist (LedFX effect →
smoke test → **tuning gate: Javi tunes defaults before any scene is
seeded** → registry/phase wiring → scene seeder → scene groups → Help
page). Don't improvise the order; the tuning gate is deliberate. **A new
registered effect (a `NAME = "..."` class in `fx/effects/*.py`) also needs
a skill or an explicit acknowledged gap — see the effect/scene-skill rule
at the end of the Help page section below;
`scripts/check_effect_scene_skills_current.py` refuses to let a new effect
land silently unclassified.**

`storage/device_categories.json`'s per-category `effects` array (curated,
hand-maintained, ordering matters) is NOT the whole story any more — found
2026-09-22 when a category-target scene entry's effect dropdown couldn't
offer `fireworks1d`/`eye`/`fish`, none of which any category had ever
curated. `fx.device_model.category_effect_options()` (consumed by
`GET /api/registry`, `spectra/api/registry.py`) widens a category's served
list past the curated names to every registered effect whose device
dimension (`effect_dimension()`, via `fx.effects.twod.Twod` class
inheritance) matches the category's own (`category_dimension()`, Matrix
subtree = 2D, everything else = 1D) — so a new effect is reachable from
the editor the moment it's registered in `config/effect_params.json`,
without waiting on someone to also remember the curation step. Curating a
new effect into `storage/device_categories.json` is still worth doing (it
controls ordering and intent), but is no longer what makes it *selectable*.

## In-app Help page (KEEP IT CURRENT)

The React app has a searchable help page at `/help`, rendered from
`web/src/help/helpContent.ts`. **Whenever you add or change a user-facing
feature — a page, keyboard shortcut, mouse/long-press gesture, filter
syntax, mode, or setting — update `helpContent.ts` in the same change.**
Treat it as part of the definition of done. The file header documents the
content schema and conventions (kbd tables, keywords, deep-link ids).

Deep links: `<HelpLink topic="<section-or-entry-id>" />` renders the small
circled-"?" used across the UI. Don't rename an id in `helpContent.ts`
without updating its `topic=` callers (grep `topic="`).

**A single-quoted body string containing an apostrophe (`it's`, `panel's`,
`fish's`) must escape it (`\'`) or the SPECTRA web app fails to build**
(`spectra/web/src/help/helpContent.ts` specifically — found 2026-10-07, PR
#368, when three such strings shipped unescaped and silently broke every
subsequent deploy's `npm run build`). `tests/test_spectra_web_type_checks_cleanly`
in `tests/test_spectra_web_typecheck.py` runs `tsc --noEmit` over
`spectra/web` as an ordinary pytest test (skipped only when
`spectra/web/node_modules` isn't installed) specifically to catch this and
any other TypeScript syntax defect before merge — there was no such guard
before.

**A topic isn't done when it's written — it's done when something in the UI
links to it.** Found 2026-08-21 (`fm/help-context-sensitive-question-mark`):
65 of SPECTRA's 117 help topics had real, written content and were never
`topic=`'d from any component — reachable only by guessing a search term.
Audit method (cheap, run it after any content pass): extract every `id:
'...'` from `helpContent.ts`, then for each id grep the app's `.tsx`/`.ts`
files (excluding `helpContent.ts` itself) for that id as a quoted string —
zero hits means orphaned. Also watch for a topic nested under the wrong parent
section/subsection in the content tree (one was found filed as a
subsection of the Timeline builder page while describing SPECTRA process
restarts entirely unrelated to it) — that kind of misfiling makes a topic
functionally unreachable from any sane UI location even before anyone
tries to link it.

SPECTRA's global "?" (`spectra/web/src/App.tsx`'s NavBar) is
context-sensitive: `spectra/web/src/help/routeTopics.ts` maps the current
route to the page's own help topic, so it opens Help already scrolled to
the current page instead of always landing on the bare index. Add a route
there when adding a new top-level SPECTRA route; a route with no entry
falls back to the plain index rather than guessing. It's route-level only,
not tab-level (a page's internal tabs are local component state, not part
of the URL).

Prefer adding a `HelpLink` next to a complex control over embedding
instructional prose in the UI; short tooltips (`title=`) are fine.

**A "?" click JUMPS and FLASHES, every time** (2026-09-04, PR
fm/spectra-help-icon-jump-highlight). `spectra/web/src/help/helpTarget.ts`
is the binding statement. Three things it exists to keep true, each of
which was a measured defect: the scroll waits until the expanded subtree is
actually in the laid-out DOM (a single rAF is not guaranteed to be after
React commits the expansion — a cold `?topic=` load left the page at
scrollY 0 with the target 6603px down); every "?" click carries a fresh
NONCE (`hl=`) because a repeat click produces an identical URL, so
`?topic=` alone can never re-fire the effect; and `.help-target-flash`
(tokens.css, 1.8s self-fading, separate from `.help-highlight`'s
search-match styling) is applied imperatively after a forced reflow so a
re-click RESTARTS the animation instead of re-adding a class that is
already there. **`HelpLink` binds a NATIVE click listener and deliberately
leaves it attached on unmount**: the second click of a double-click lands
on an anchor React has already detached, React's delegated root listener
never sees it, and the browser follows the `href` — a full page reload of
the SPA. Any in-app link that navigates away on click has this shape.

**The same "keep it current" discipline applies one layer down, to a
skill per effect and per scene** (card
a-skill-per-effect-scene-kept-current-by-jgt7, his ask verbatim: "have dj
make sure we have a skill for each effect/scene and a rule to update the
skills as we work on each effect/scene and add more"). `.claude/skills/`
carries one skill per **effect** (`fx/effects/*.py` that's actually bound
into a live scene — a `NAME = "..."` registered effect) and one per
**scene** (his 10 live SPECTRA scenes) — cold-start knowledge for an agent
picking that effect/scene up fresh: what each param actually means and its
real range, which params Sonic can reach (almost never directly — only
through an already-attached `FlareKind`, see `.claude/skills/*-effect/
SKILL.md`'s own "Sonic reach" section), and the invariants that are NOT
visible from reading the code cold (a saturating audio signal meeting a
`>=` never-threshold, a param that means something different on one
effect than every sibling effect, a fix that was tried and withdrawn once
already). `.claude/skills/EFFECT_SCENE_MAP.json` is the hand-maintained
manifest naming which files trigger which skill, under ONE mapping rule: an
effect's own code (`fx/effects/<name>.py`) and its instrument/measurement
scripts and tests trigger ONLY that effect's skill; a scene's own authored
data/configuration (its seed script, a flare-kind migration naming that
scene, a test asserting that scene's stored config) triggers ONLY that
scene's skill — no file is listed under both.

**Whenever you change an effect's or scene's behaviour — touch
`fx/effects/<name>.py`, tune a param default, fix a timing/threshold
defect, add or rewire a flare kind's authored data — update that effect's
and/or scene's own `SKILL.md` in the same change.** Treat it as part of the
definition of done, exactly like `helpContent.ts` above. Not every effect
has a scene-authoring skill yet and not every registered effect has ANY
skill yet — `EFFECT_SCENE_MAP.json`'s `acknowledged_effect_gaps` names the
ones deliberately skipped (not bound into any live scene today) rather
than padding with thin stubs; move an effect out of that list into a real
skill the day it gets bound into a live scene.

Unlike the help-topic orphan audit above, this one doesn't rely on running
a grep by hand after the fact: `.venv/bin/python scripts/
check_effect_scene_skills_current.py` diffs the branch's changes (working
tree + committed, against its merge-base with `origin/master`) against the
manifest and FAILS if a mapped effect/scene file changed without its skill
also changing, or if a brand-new registered effect appears in neither the
manifest nor the acknowledged gaps — a "remember to update the docs"
reminder lapses exactly when things are busy, so this is a check, not a
paragraph anyone can skip. **The enforcement is a pytest test, not a
separately configured gate**: `tests/test_effect_scene_skills_current.py::
test_the_real_branch_diff_leaves_no_effect_or_scene_skill_stale` runs that
same real-diff evaluation, so it fires on every full test run — including
the one `no-mistakes` runs on every change — and FAILS LOUDLY when the diff
cannot be computed at all (no base ref, a git error) rather than passing
having checked nothing. The new-effect half is also held by
`test_every_live_registered_effect_is_either_mapped_or_acknowledged`, which
re-scans `fx/effects/*.py` directly. See that script's own module docstring
for exactly what it checks and its one named, honest limitation: scene
data lives in the gitignored `storage/spectra/scenes.json`, so a scene
skill can go stale from a LIVE-app-only edit with nothing in git to catch
it — the agent still owes the scene skill an update by hand in that case,
the same as the help-topic rule above already relies on human diligence
for anything not machine-checkable.

