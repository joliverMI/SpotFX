/** ═══════════════════════════════════════════════════════════════════════
 *  SPECTRA in-app Help content — the single source of truth for user docs.
 *
 *  NOTE FOR FUTURE AGENTS (Claude/Opus & friends):
 *  Whenever you add or change a user-facing feature — a page, a tab, a
 *  gesture, a mode, a setting — UPDATE THIS FILE in the same change. This
 *  is part of "done". Rules of the road:
 *    • Keep entries short, imperative, and concrete.
 *    • Gestures go in `table` rows with `kbd: true`.
 *    • `keywords` holds hidden search synonyms; search is typo-tolerant.
 *    • `id`s are deep-link targets used by <HelpLink topic="..."/> —
 *      don't rename an id without updating its callers (grep `topic="`).
 *    • Structure: top-level section per page/area → entries.
 *  ═══════════════════════════════════════════════════════════════════════ */

export type HelpRow = [keys: string, description: string];

export type HelpEntry = {
  id: string;
  title: string;
  body?: string[];
  table?: HelpRow[];
  kbd?: boolean;
  keywords?: string;
};

export type HelpSection = {
  id: string;
  title: string;
  intro?: string;
  keywords?: string;
  entries?: HelpEntry[];
  subsections?: HelpSection[];
};

export const HELP_SECTIONS: HelpSection[] = [
  {
    id: 'overview',
    title: 'SPECTRA — what this app is',
    keywords: 'getting started intro basics purple spot-effects legacy',
    intro:
      'SPECTRA is the merged lighting program: scenes that state what every device shows, plus declared mechanisms — drift (slow evolution), responses (flares/charges/lulls/drops), and a room-level colour journey. It runs beside the legacy spot-effects app (green UI) and takes the lights over only at the owner-called switchover.',
    entries: [
      {
        id: 'concept-increments',
        title: 'What works today (increment S3)',
        keywords: 'roadmap s1 s2 s3 engine bridge ownership dark handover',
        body: [
          'S1 shipped the app and the full tabbed scene editor: bindings, dice, responses, drift declarations, colour journey, test-fire with dry-run compile. S2 added the evolution engine: drift and responses EXECUTE, fed read-only from spot-effects — dark, recording every move. S3 (this build) adds light ownership and the safe handover: the machinery for SPECTRA to take the room is built, proven offline, and GATED OFF — spot-effects owns the lights until the owner\'s word arms and runs the switch. Until then the real Fire button here writes through the same external LedFX service. The one exception is the panic release (below): it works right now, unarmed — going TO no writer is always safe to allow.',
        ],
      },
      {
        id: 'concept-scene',
        title: 'A scene = initial conditions + declared mechanisms',
        keywords: 'model drift respond creep follow surge',
        body: [
          'Initial conditions: every value fixed, ⚡ intensity-mapped, or 🎲 rolled per fire. Mechanisms: drift (creep = bounded wander, follow = tracking the music\'s energy arc), responses (jumps on flares/charges/lulls/drops — a jump, not a blend, and drift resumes from the new point), and the colour journey.',
        ],
      },
    ],
  },
  {
    id: 'scenes-page',
    title: 'Scenes page & editor tabs',
    keywords: 'editor tabs scene list search save',
    intro:
      'Left pane: scene list with search; right pane: the tabbed editor. Drafts live locally until Save — an unsaved dot marks edited scenes and leaving the page asks first. On a phone in portrait the page is single-pane: the editor owns the width and the scene picker collapses into the ☰ bar (see "Phone layout").',
    entries: [
      {
        id: 'editor-toolbar',
        title: 'Toolbar: Save, Duplicate, mode availability, Fire, Delete',
        keywords: 'test fire dry run real fire intensity slider no confirm consent',
        body: [
          'The intensity slider picks the axis value a fire resolves against, so ⚡ scenes can be previewed anywhere on the axis. Fire sends the compiled writes to LedFX live — it exists for the owner.',
          'Firing asks for NO confirmation — the press is the consent; it fires the single scene you chose and are looking at. This is a deliberate asymmetry: the global colour-set opt-out (Colour Sets tab) DOES confirm, because that one silently changes every scene in the house.',
          'The old "Test Fire (dry)" button was retired in favour of the mode-availability toggle in the same slot — see "Mode availability", below. Its dry-run compile is still reachable: POST /api/scenes/{id}/fire with dry_run=true, the surface agents already use directly.',
        ],
      },
      {
        id: 'mode-availability',
        title: 'Mode availability — Hybrid / Light / Dark toggle',
        keywords: 'display availability light dark hybrid skip automatic gate scene color set group toggle',
        body: [
          'A small toggle on the scene toolbar and on a Colour Set/Group\'s toolbar (next to Preview) — tap to cycle Hybrid → Light → Dark → Hybrid. It stays the SAME WIDTH at every state so it never shifts the row under your thumb.',
          'Hybrid (the default): always available. Light: available while the room\'s Display mode is Light or Hybrid, skipped while it\'s Dark. Dark: available while Dark or Hybrid, skipped while Light.',
          'This gates anything that fires WITHOUT a human pressing a button in the moment — the sequencer\'s own picks, a colour Group\'s member cycling, a generated trigger\'s scene pick, and a hand-authored trigger\'s fire_scene action too (the same central gate every automatic scene-fire funnels through). Only two things bypass it: Force Scene (an explicit standing pin — the pinned scene keeps its declared life, same as it already does for Pause/Dinner Party/Ambient) and a literal button press right now (Fire, Test Fire\'s dry-run API, a Colour Set/Group\'s Preview).',
          'Not the same control as a scene\'s colour-set PREFERENCE (Colour Sets tab) — this one gates whether the scene plays at all; that one only narrows which colour sets it draws from once it does. See "Colour-set preference", below. Also not the same as the separate Disable toggle right next to it — Disable is the stronger statement ("don\'t use this scene, period," any room mode), where this one only narrows which room mode a scene plays in. See "Disable", below.',
        ],
      },
      {
        id: 'scene-disable',
        title: 'Disable — temporarily take a scene out of rotation',
        keywords: 'disable enable toggle off pause temporarily stop scene never fires skip skipped',
        body: [
          'A second toggle on the scene toolbar, next to Mode availability — tap to flip Disabled ⇄ Enabled. Nothing is deleted or lost; it\'s reversible any time, and there\'s no timer — it stays off until you turn it back on.',
          'A disabled scene never fires automatically: it\'s dropped from the sequencer\'s own rolls, a generated trigger\'s scene draw, and a hand-authored trigger\'s fire_scene action, the same central gate Mode availability already funnels through — REGARDLESS of the room\'s current display mode. Disabled is the stronger statement: "don\'t use this scene, period," where Mode availability only narrows which room mode it plays in. A scene that\'s both disabled and mode-gated reports "disabled" as the reason, not "mode availability."',
          'Two things still work on a disabled scene, deliberately: a manual Fire/test-fire from this editor (you pressed the button, you mean it — same bypass Mode availability already has), and Force Scene. Pinning a disabled scene is contradictory input, so it\'s honoured, not silently refused or silently allowed — the room bar\'s Force Scene badge says "⚠ overriding disabled scene" when this happens.',
          'The scene list, and the phone header once a scene is open, both show a red "⛔ disabled" badge — a disabled scene that stops showing up should never look indistinguishable from a broken one.',
        ],
      },
      {
        id: 'phone-layout',
        title: 'Phone layout',
        keywords: 'mobile portrait drawer picker narrow single pane responsive',
        body: [
          'On a phone-portrait screen the Scenes page is a first-class single-pane arrangement, not a squeezed desktop: with no scene open the list fills the width; once a scene is open the EDITOR owns the width and the picker collapses into the ☰ bar above it — tap it (or "scenes ▾") to open the full-screen scene drawer with search and + Scene. The editor tabs stay on one row and scroll sideways. The Timeline and Status pages stack their cards full-width.',
        ],
      },
      {
        id: 'tab-summary',
        title: 'Summary tab',
        body: ['A read-only overview of the whole scene: entries, bound values, dice letters, responses, drift, journey, choreography, sequencing. Click a card to jump to its tab.'],
      },
      {
        id: 'tab-initial-set',
        title: 'Initial Set tab — device entries as sub-tabs',
        keywords: 'device entry params sliders category virtual all devices',
        body: [
          'One sub-tab per device entry, titled by its target; + Add entry creates one (All Devices / a category / a single virtual — narrower entries override wider ones at compile). Every parameter from the registry is visible, grouped by aspect, with a real slider; dimmed rows are unset (the device keeps its own value) — click the name to enable at the effect\'s real default.',
        ],
        table: [
          ['⚡', 'Map fire intensity to this value (linear map or threshold steps). The old fixed value becomes the binding\'s fallback.'],
          ['🎲', 'Roll this value fresh per fire — uniform in a range, or a weighted pick via threshold steps.'],
          ['dice A–F', 'On 🎲 bindings: values sharing a letter share ONE roll per fire, so authored combinations land together (e.g. Mid Star\'s star+edges pairs).'],
          ['+/−', 'Random sign: numeric results flip negative 50% of the time.'],
        ],
      },
      {
        id: 'colour-gradient-picker',
        title: 'The colour picker',
        keywords: 'color picker gradient swatch solid hex stops angle ledfx',
        body: [
          'Every colour and gradient field in SPECTRA — Fixed colours here, Background, Ambient\'s colour in the room bar — opens the same picker: LedFX\'s own colour-picker component, not a lookalike. Click a swatch to open it; click outside or press Esc to close.',
          'Two tabs where both apply (a colour field that only ever takes one solid colour, like Ambient, shows Solid only): Solid picks one colour off a board or by hex. Gradient builds a multi-stop CSS gradient — drag to add a stop on the bar, drag a stop to move it, pick each stop\'s colour, set the angle. Saved colours and gradients from the shared library show as quick-pick swatches at the top.',
          'The value it produces is the exact CSS this app already stores everywhere (e.g. `linear-gradient(90deg, rgb(255,0,0) 0%, rgb(0,0,255) 100%)`) — every colour and gradient you already had keeps working, nothing to redo.',
        ],
      },
      {
        id: 'stepped-effect',
        title: 'Stepped effect — a different effect at high intensity',
        keywords: 'effect steps threshold intensity conditional selection melt power star hype fold variant',
        body: [
          'An entry can resolve to a DIFFERENT effect at different fire intensities: the ⚡ Stepped effect strip adds threshold steps, each naming its own effect with its own param set (STAR\'s strips: melt below ⚡ 0.7, power at/above — the Hype Star fold). The base effect fires below the first threshold and whenever no intensity signal exists. Selection is a hard step at fire time — never a blend, never a mid-hold switch; the next fire re-selects.',
          'The params grid edits whichever variant chip is highlighted. Colours, brightness and drift stay entry-level and ride whichever effect the fire selects. Test Fire at a chosen intensity is the honest window: its writes show exactly the effect that intensity picks (an "effect" row appears in the resolution table). Same-effect variation over intensity is a plain ⚡ steps binding on the param — steps here must each name a different effect.',
        ],
      },
      {
        id: 'tab-drift',
        title: 'Drift tab — declarations the engine runs',
        keywords: 'creep follow wander slow evolution profile inline live legs bounds',
        body: [
          'Drift cards state what evolves on its own while the scene holds: creep (bounded wander between lo–hi, bouncing/wrapping/holding) and follow (the value tracks the music\'s energy arc through a drawn intensity→value curve). Declarations use NAMED profiles — one edit retunes every scene using it — with inline one-offs as the escape hatch. Cards are adjusted by telling the agent, except a creep\'s bounds — see "Creep bounds", below — which are graphical, alongside a follow curve\'s shape.',
          'Since S2 the engine EXECUTES these declarations: when this scene is the engine\'s active scene, each card shows a live ● chip per virtual with the creep\'s current wander position. See the Evolution engine section for how legs run (dark until S3).',
          'The colour journey card also lives here — see the colour journey section.',
        ],
      },
      {
        id: 'drift-bounds',
        title: 'Creep bounds — lo, hi, and boundary behaviour',
        keywords: 'lo hi bounce wrap hold floor ceiling legal range too small shrink degenerate visible',
        body: [
          'Every creep card carries an editable lo/hi/boundary row: type the low and high ends of the wander directly, and pick what happens at an edge — bounce (reflect back), wrap (fold through to the other end), or hold (park there and stop, rather than oscillate). Edits save to whichever the card names — an inline one-off saves to the scene, a named profile saves to the profile (every other scene using it follows).',
          'The row shows the param\'s own "legal range" alongside — the effect\'s own declared min/max for that param (the same numbers its other editors use). Whatever lo/hi you set, the engine always clamps the actual wander into that legal range before it ever reaches a light: a creep or follow declaration can shrink a value, but it can never wander it past what the effect itself calls usable — invisible, zero, black, or silent is not a reachable state. This is why Orbits\' particle size can no longer drift down to nothing: its own effect declares a floor, and every drift on it now respects that floor automatically, on top of whatever bounds you choose here.',
        ],
      },
      {
        id: 'flare-kinds',
        title: 'Named flare kinds — the three types',
        keywords: 'kind drift jump momentary permanent slam scale strength declare card offset relative random hold duration target',
        body: [
          'A scene DECLARES named flare kinds — readable cards at the top of the response tabs, shared by every class. Three types: DRIFT-JUMP (🎨/🎲) jumps the drift itself — the colour-set jump through the shipped selector, or a dice re-roll for shape; both carry, the journey walks on from the new point. MOMENTARY (↩) spikes params/gain and RETURNS exactly to the carried baseline. PERMANENT (⚓) lands and BECOMES the new baseline drift carries from.',
          'A momentary/permanent kind\'s params are five ways to say where a value goes. Two are the mode on the param itself: ABSOLUTE (the default) is a plain declared number, landed verbatim. OFFSET is a signed delta from wherever the param currently sits — a creep\'s live wander position, not its static starting value — "star down by 1" is offset −1, up is a positive offset. RANDOM draws once in an authored [lo, hi] range each time the kind fires and lands that same draw everywhere the kind targets. The other two ways sit outside the mode: INTENSITY-DRIVEN is the band\'s own ×scale, which steers how far any of the three modes above lands (×1 = the resolved target verbatim, ×0 = inert) — it composes with absolute, offset, and random alike. A bare ABSOLUTE value with ×1 scale is exactly today\'s declared-target behaviour.',
          'MOMENTARY kinds also carry an optional HOLD — how long the spike shows before it releases, in ms. Unset, it holds the fixed 250 ms default; set it to hold longer or snap back sooner. Kinds with different holds in the same fire release independently — the release always glides back to the baseline AS CARRIED AT RELEASE TIME, a creep\'s continued wander included, exactly like an unheld spike.',
          'Bands SELECT AND SCALE: each band lists which kinds fire in its intensity window plus a ×scale multiplying their strength (×1 = exactly as declared, ×0 = inert; a dice re-roll has no magnitude, so scale is inert on it; on a colour jump it steers the selector). Kind declarations — type, params, gain, hold — are agent-adjustable — tell the agent to add or retune one. Rename, delete, and copy have a direct UI — see "Flare kind edit box" — since those are identity operations, not program-behavior tuning; attaching a kind to a band is done by dragging it into a lane — see "Flares tab — lanes".',
          'Everything authored before kinds existed — band patches, gains, re-roll and colour-jump flags — loads unchanged as auto-named kinds ("Dice Re-roll", "Colour Jump", "Flare patch …", "Flare gain …"), every param landing in ABSOLUTE mode at the fixed 250 ms hold — today\'s behaviour, unchanged.',
        ],
      },
      {
        id: 'flare-kind-edit-box',
        title: 'Flare kind edit box — rename, delete, copy, paste',
        keywords: 'edit rename delete copy paste clipboard port double click tap identity',
        body: [
          'Tap (or double-click) any flare kind card — in the palette above the bands, or inside an occupied lane — to open its edit box: Rename, Delete, or Copy. An unmoved tap/click opens it; a drag attaches or moves the kind instead (see "Flares tab — lanes") — the same gesture works whether you\'re using a mouse or a touchscreen, since a real double-tap is unreliable on phones.',
          'RENAME updates the kind\'s name everywhere it\'s referenced within this scene — every band that attached it, and this scene\'s Update kind if it names this kind — so a save never leaves a dangling reference.',
          'DELETE removes the kind from the scene entirely; the confirm states how many bands it\'s currently attached in, since those attachments detach along with it.',
          'COPY puts the kind\'s own declaration — type, params, gain, hold — on a small clipboard (works across scenes and page reloads). A "📋 Paste" button then appears on every scene\'s Flares/Charges-Lulls-Drops tab. PASTE IS A PORT, NOT A LINK: it creates a brand new, independent kind on whichever scene you paste into (a name collision gets a "(2)" suffix, same as the engine\'s own auto-naming) — never attached to any band yet, and never tied back to the original. Editing or deleting either copy afterward never touches the other. A flare kind\'s identity is scoped to the one scene that declares it; there is no shared cross-scene kind to reference, so a paste is the only way to reuse one elsewhere. A pasted kind may name a param this scene\'s devices don\'t have — harmless: the engine only ever lands a param on a virtual whose live effect actually carries it.',
        ],
      },
      {
        id: 'flare-preview-timeline',
        title: 'Scrubbing preview — ▶ Preview on a flare kind card',
        keywords: 'preview timeline scrub playhead trigger mark animation start end drag loop pause extend evolution starts early gap offset lead',
        body: [
          'Tap ▶ Preview on any flare kind card to open its scrubbing timeline: a ruler that plays across and loops, showing exactly what this one kind would do if it fired right now, in isolation from any band. Play/Pause, then drag the playhead anywhere on the ruler to freeze-frame the effect mid-animation. Extend widens the ruler without changing anything already on it. The intensity slider at the top recomputes the timeline at a different fire strength.',
          'TWO KINDS OF MARKER, and they are not the same thing. The orange line labelled "trigger" is where you place the moment this kind is considered fired — drag it anywhere on the ruler. The two lighter lines labelled "start" and "end" (with the shaded band between them) are computed, not editable: they show exactly when the kind\'s own writes begin moving a light and when the whole thing has settled back — read straight off the real timing this kind will actually run (how long a glide takes to land, how long a momentary spike holds before it releases, how long the release itself takes). The text under the ruler states the gap between them in milliseconds — this is the number that answers "does the light actually start changing when I think it does:" if the trigger line and the start line aren\'t on top of each other, that gap is real and now visible, not something you have to guess at from watching the room.',
          'DRAGGING THE TRIGGER LINE EDITS THE SCENE, it does not just move something around inside the preview. It writes this kind\'s own trigger_offset_ms — how far you\'ve decided the trigger should sit from where the animation actually starts — the same as typing into any other field on this scene: the change lives in the draft immediately and the page\'s own Save button is what makes it permanent, same as everywhere else in this editor. Closing the preview without Saving the scene discards it exactly like any other unsaved edit.',
          'This is preview-only computation — nothing here touches a real light or the trigger engine\'s own live schedule; it\'s the same dark, hardware-free execution model the response engine always runs, just driven once by hand instead of by the music. Opening it automatically pauses the trigger engine for as long as the preview stays open (closing it, or navigating away, un-pauses).',
          'Flares only, today — his own sequencing: charges, lulls, drops, and scene-to-scene transitions get this same treatment next, once he\'s used this version and said what needs to change.',
        ],
      },
      {
        id: 'tab-flares',
        title: 'Flares tab — the band strip',
        keywords: 'flare bands kind scale response intensity strip attach chip',
        body: [
          'Bands over the intensity axis decide the response when a flare fires. Drag a band\'s edges to move its window, drag the dot to set the whole band\'s ×scale, double-click to remove, click an empty gap to add. Which kinds fire in a band, and how many, is the lane rack below each band — see "Flares tab — lanes".',
          'Since S2 these bands EXECUTE: any ordinary trigger fire from spot-effects is a flare at that fire\'s intensity, and the band containing it fires its kinds — drift-jumps, momentary spikes that return, permanent moves that carry. A colour jump ramps its new colours in over a length that shrinks as intensity grows: gentle flares ease in (~2.5 s), full-scale flares land hard (~0.15 s).',
        ],
      },
      {
        id: 'tab-flares-lanes',
        title: 'Flares tab — lanes',
        keywords: 'lane drag attach combine overwrite additive precedence order same param gain dice colour',
        body: [
          'Each band shows a row of vertical LANES — 2 to start, a "+" grows up to 4. Drag a kind card (from the palette above, or from another lane) onto a lane to attach it there; drop on an occupied lane and the existing occupant shifts over rather than being replaced — nothing dragged in is ever silently lost. Drag a kind OUT of the palette and it stays attached everywhere else it already was (a kind can sit in more than one band, or more than one class, at once) — drag an already-attached lane\'s kind to a different lane and it MOVES (detaches from where it was, attaches where you dropped it). The ✕ on a lane detaches without moving it anywhere. A tap/click that doesn\'t move opens the same edit box "Flare kind edit box" describes.',
          'A lane is a POSITION, not a new stored idea — it\'s exactly the existing band.kinds list (kind name → ×scale) that already select-and-scale kinds; lane order is that list\'s order. This matters because it decides what happens when two lanes\' kinds touch the SAME parameter — the engine\'s existing rule, unchanged, not a new one invented for lanes: a dice re-roll and a colour jump are each a SINGLE pick per fire (attaching a second one to the same band is harmless but only the first executes); momentary/permanent PARAM moves overwrite — permanent kinds land first, momentary lands after (so a spike shows over the just-set baseline), and among same-type kinds the LATER lane wins a shared param; a permanent GAIN kind chained after another permanent gain in the same band multiplies onto it rather than replacing it. So a later lane is a deliberate "wins" for a param conflict, not an accident of drag order.',
          'Lane count is a per-band display preference, not scene data — it isn\'t saved, and a band with more attached kinds than the visible lane count (e.g. from legacy data, or an agent edit) always shows them all rather than hiding any.',
          'Lanes render as tall vertical columns, not short wide chips — each one scrolls into view side by side rather than wrapping onto a second row, so a band with several lanes reads the same way at any screen width, phone included.',
        ],
      },
      {
        id: 'tab-phase',
        title: 'Phase Choreography tab',
        keywords: 'transition crossfade anchor descriptive',
        body: [
          'Descriptive card: transition length, mode, and the anchor fraction where the payoff lands. Adjusted by telling the agent — durations and modes are numbers, not shapes, so they get no sliders here.',
          'Below it: the Override Blend equivalent — see "Override Blend (SPECTRA)".',
        ],
      },
      {
        id: 'override-blend-spectra',
        title: 'Override Blend (SPECTRA)',
        keywords: 'blend ramp stretch scale slow fast transition phase charge lull entry jump crossfade',
        body: [
          'SPECTRA\'s equivalent of the legacy Override Blend flag (see "Override Blend" under the ported timeline help for the original). A read-only study of the live library (269 legacy blend triggers) found real usage is overwhelmingly Charge/Lull phase builds (265 of 269) with a thin slice on scene selection — so the equivalent has two facets.',
          'Charge/Lull ramp: automatic, not a per-scene setting. Every charge/lull fire stretches its build/suspend ramp to ~90% of the real gap to the next trigger, then hangs at its peak for the remaining ~10% before the next moment — exactly like legacy\'s own dynamic stretch. A gap that can\'t be known (no trigger schedule for the moment — e.g. a bridge-classified legacy flare) falls back to the tuned default (4000 ms charge, 2500 ms lull); drop never stretches, it always stays the 400 ms snap. A per-scene override number existed briefly and was retired 2026-08-20 — his own two real lull gaps on one song (6040 ms and 900 ms) proved a single constant can\'t fit both, so there\'s nothing to hand-tune here.',
          'Scene-entry blend: a scene\'s entry_ramp_ms (0 by default = instant) blends its compiled writes in over that many ms when it fires live, hue-arc for colour — the same tween shape flare colour jumps use, and the mechanism the colour journey\'s "no snap" custody transfer has always promised. It only blends params on a virtual whose already-active effect matches the entry; a genuine effect-type switch still recreates instantly (a boundary of the underlying render engine, not new here). Agent-tellable — no slider, same interface-split rule as the rest of this tab.',
        ],
      },
      {
        id: 'tab-sequencing',
        title: 'Sequencing tab',
        keywords: 'sequencer curve likelihood affinity genre profile inline one-off detach revert save named overwrite grid thumbnail picker preview button window scroll minimum dwell',
        body: [
          'As shipped in the sequencer increment: the scene\'s likelihood curve (named profile / inline / flat / not sequenced) is graphical; genre multipliers and affinity render read-only — adjust them by telling the agent. The status strip shows the engine\'s state. The S2 bridge now feeds it song transitions, section-energy intensity, genre buckets, and deferrals — but the sequencer stays dark until its own enabled switch is flipped (ask the agent). This tab also carries the scene\'s Minimum dwell curve, below the likelihood curve — see "Minimum dwell" for what that one does; it\'s a different mechanism from everything else on this tab.',
          'Reworked 2026-08-19 (his ask: no expanded/collapsed selector sitting in the window, and an edit should take effect immediately, not default to saving the curve): the tile grid is never shown by default. In its place is a single button — a live preview of the curve currently in effect (drawn with the same thumbnail the picker tiles use, so it can never visually disagree with the real shape) — and pressing it is what pulls the picker up, as a popover card over the page. Pick a tile there (a named profile, "Flat 1.0", "— not sequenced —", or "Inline one-off…") and the picker closes; picking a profile or "Inline one-off…" also opens the curve window to edit its shape.',
          'The curve window lets you drag points. THE SAFETY RULE, and how "immediate" works: an edit (drag, add, or remove a point) writes straight to THIS item\'s own one-off copy the moment you make it — no separate Apply step, no pending state — but it can never write into a shared, named profile. Editing a shared profile\'s curve detaches this item onto its own inline copy on the very first touch; the profile itself, and every OTHER scene/set/group still pointing at it, is untouched. "↺ Revert to original" undoes an edit session, restoring exactly what was attached before you started (including the original points of an already-inline curve you edited, not just "back to inline"). "Detach — make this a one-off copy" (shown before you\'ve touched anything, while a shared profile is attached) forks a private copy now, without changing its shape, so future edits to the shared profile can\'t reach this item either. "Save as named curve…" is the only action that can write a shared, named profile: type a name and Save. If that name already matches an existing curve, a warning dialogue names it, how many other items use it, and requires an explicit "Overwrite" click before anything is written — Cancel/Back leaves the stored curve untouched.',
          'A curve is either a named PROFILE (picked from the picker — a shared shape; editing it forks a one-off rather than retuning every item sharing it, and the picker\'s own tiles badge a profile with how many items use it) or an INLINE one-off (this item only, no name, nothing added to the profile library).',
          'This curve is also the equivalent of the legacy Energy Gate / Energy Tilt on random options — see "Energy gates/tilt → curves" for the equivalence.',
        ],
      },
      {
        id: 'minimum-dwell',
        title: 'Minimum dwell (seconds) — a floor, not the same curve as likelihood',
        keywords: 'dwell minimum hold floor update effect scene change intensity curve default',
        body: [
          'A per-scene MINIMUM HOLD TIME, a curve over intensity — but Y is SECONDS here, not a likelihood weight, so don\'t read it the same way as the likelihood curve above it. Default (no override): 16 seconds at intensity 0, 4 seconds at intensity 1, linear between — his exact numbers. The intensity used is LATCHED the moment the scene actually fires; it never moves mid-hold even if the live intensity changes.',
          'This gates every AUTOMATIC scene change — a sequencer roll, a trigger\'s Fire Scene action, or the automatic song-transition fire — whichever scene is currently showing must clear its own minimum before any of those may switch away from it. A manual Fire press in the editor is exempt (it never goes through this gate) and always fires immediately. Force Scene still wins over an active minimum, but the room bar names the override rather than applying it silently.',
          'If a scene change is requested before the minimum clears, the room does an UPDATE EFFECT instead of switching — the scene\'s own designated Update kind (a permanent flare kind named on the scene, "a major change within the scene, bigger than a flare, overriding the drift, landing on a ramp-in"). A scene with no Update kind authored yet simply holds — recorded, never a silent no-op, so "why didn\'t the room change" is never a mystery.',
          'The clock never resets on an update effect — it keeps running from the moment the current scene actually fired, so a busy song can\'t re-arm the minimum indefinitely.',
        ],
      },
      {
        id: 'energy-gates-equivalence',
        title: 'Energy gates/tilt → curves (equivalence, not a new feature)',
        keywords: 'energy gate tilt floor ceiling scale random option veto superseded',
        body: [
          'Legacy RandomOptions carried an energy gate (floor/ceiling: zero weight outside the window) and an energy tilt (scale: a linear lean toward the low or high end inside it). SPECTRA\'s selector curves express exactly this, byte-for-byte: a curve of zero outside [floor, ceiling] and a straight line from 1−scale to 1+scale inside it reproduces the legacy gate under the kernel\'s own evaluator — proven in scripts/check_sequencer.py (gate_points/tilt checks against the exact legacy formula, trigger_engine.py:2338) — and the kernel treats a zero-scoring curve as a HARD VETO at runtime (selection_kernel.py), not merely a seeding-time translation.',
          'No SPECTRA-native "energy gate" control was built: the curve editor already covers the identical shape, and the real library never exercised the legacy control worth porting (1 event ever authored it, 0 real fires). scripts/seed_sequencer_from_legacy.py prints the floor/ceiling/scale → curve translation for any legacy RandomOption it finds, for reference.',
        ],
      },
      {
        id: 'tab-color-sets',
        title: 'Colour Sets tab — type-to-filter',
        keywords: 'palette filter accept opt out search wheel rainbow',
        body: [
          'Type in the filter box to narrow the set list live. Accept-all takes every set that hasn\'t opted out globally; unchecking narrows to an explicit list (per-set only — groups expand to their members). The wheel dot shows each set\'s hue position; 🌈 marks rainbow sets (no single position — they never move the room\'s wheel). "Opt out" is GLOBAL (every scene) and asks for confirmation; it is stored on the spot-effects side, the shared colour library.',
          'To create, edit, or delete a Colour Set or a Group, use the Colours page (nav bar) — see "Colour Sets & Groups page".',
        ],
      },
      {
        id: 'scene-colorset-preference',
        title: 'Colour-set preference — Any / Prefers Dark / Prefers Light',
        keywords: 'prefer dark light colour set mode black hole fireworks dancers roll selection',
        body: [
          'A SECOND toggle on the Colour Sets tab, separate from Mode availability above — do not confuse the two. Mode availability decides whether THIS SCENE plays at all in the room\'s current Display mode. This one decides WHICH of the scene\'s already-accepted colour sets the automatic roll draws from once the scene does play.',
          '"Any" (default): no preference — unchanged behaviour. "Prefers Dark"/"Prefers Light": the automatic colour-set roll narrows to sets marked the same way on the Colours page (their own Mode availability toggle) PLUS every unmarked set — you never have to re-mark a set just because a scene now prefers one mode; only a set explicitly marked the opposite mode is skipped.',
          'The room\'s own explicit Display mode always wins: a scene preferring Dark still runs Light-marked sets if the room itself is explicitly set to Light (and the symmetric case for a Light-preferring scene under an explicit Dark room) — the preference is only consulted while the room is Hybrid. A manual Fire, Test Fire, or a Colour Set/Group Preview bypasses this entirely, same as Mode availability.',
          'This only narrows a pool that already has marked members in it — it marks no colour sets itself. Until some sets are marked Light or Dark on the Colours page, a scene\'s preference changes nothing it draws from (every set still reads as unmarked/"Any"). Mark sets there first if you want a preference to actually do anything.',
        ],
      },
      {
        id: 'tab-responses',
        title: 'Charges / Lulls / Drops tab',
        keywords: 'charge lull drop event classes bands phase build suspend release',
        body: [
          'Charges, lulls, and drops now drive the REAL phase choreography that lived in LedFX for the original program — the build/suspend/release grammar written into the particle effects, the dancers, and the eye. Every charge/lull/drop event arms the phase machinery on each device whose effect carries it and ramps the build (charge ~4s, lull ~2.5s, drop 0.4s — the snap), band or no band. See "Response families" below for what each effect family does.',
          'The band strip here is the scene\'s COLOURING on top of that arc, same idiom as Flares: the band containing the fire\'s intensity fires its attached kinds at their ×scales (see "Named flare kinds"). A track change releases a lingering charge/lull automatically.',
        ],
      },
      {
        id: 'response-families',
        title: 'Response families — what charge/lull/drop look like',
        keywords: 'blackhole orbits radial fireworks squiggles dancer eye grammar visual',
        body: [
          'Black Hole: charge — the horizon swallows the panel behind a glowing capture ring; lull — held full-screen black; drop — pinch to a point, a 24-blob centre explosion, ease back.',
          'Orbits: charge — the population swells then sheds to a single blob; lull — its orbit collapses to a tiny centre swirl; drop — full population returns with a burst plus 2× ballistic ejecta, spin boosted and decaying.',
          'Radial: charge — the spin accelerates, peaking at the ramp end; lull — the pattern implodes to a held centre point; drop — it blooms back out.',
          'Fireworks: charge — launch rate climbs 6× while bursts shrink and slow; lull — launching stops, three dim rockets cross the dark panel; drop — every rocket explodes where it is, giant, in its own colour.',
          'Squiggles: charge — walls turn solid and the figure fills with trapped scribble; lull — an old-TV switch-off to a held white dot; drop — a nine-chain fan erupts from centre.',
          'Dancers: charge — the dance intensifies as the build climbs; lull — the crew sinks into a held squat; drop — every dancer fires a stunt (breaker freeze-spin, grand jeté splits, or a huge leap), staggered.',
          'Eye: charge — the iris grows, the pupil constricts, flames stream inward; lull — the lids close with a suspense pause; drop — the eye explodes open with a flame burst.',
          'Effects without phase machinery simply ride the band extras. Full engineering detail: docs/SPECTRA_RESPONSES.md.',
        ],
      },
    ],
  },
  {
    id: 'bindings',
    title: 'Value bindings (⚡ / 🎲)',
    keywords: 'binding map steps fallback dice random intensity',
    intro:
      'Any numeric, toggle, or option value in the Initial Set can be computed at fire time instead of fixed.',
    entries: [
      {
        id: 'binding-map',
        title: 'Map mode',
        body: ['Linear range map: intensity in [in-min, in-max] → value in [out-min, out-max]. Inverted output ranges are legal (e.g. slower at higher energy). With 🎲, map mode is a uniform random pick between the two values.'],
      },
      {
        id: 'binding-steps',
        title: 'Steps mode',
        body: ['Ordered thresholds; the last step at or below the signal wins. The only mode for toggles and option values (a dance style is a select with steps). Below the first step, the fallback applies.'],
      },
      {
        id: 'binding-fallback',
        title: 'Fallback — the migrated scenes\' old look',
        keywords: 'static migration mid group',
        body: ['When no signal is available (e.g. no music context yet), the fallback value applies. The migrated Mid Group scenes carry their old static values as fallbacks — with no signal they look exactly as before.'],
      },
      {
        id: 'binding-dice',
        title: 'Correlated dice',
        keywords: 'correlation letters shared roll pairs mid star',
        body: ['🎲 bindings sharing a dice letter (A–F) read ONE roll per fire. Mid Star\'s three shape variants are star+edges steps on the same letter, so the authored pairs (0.3/6, −0.3/3, plain/5) always land together at their 2:2:1 weights.'],
      },
    ],
  },
  {
    id: 'color-journey',
    title: 'Colour journey (destinations + override)',
    keywords: 'wheel walk rotate palette drift destination hue override room pace travel arrival',
    intro:
      'The room owns ONE continuous colour journey, and it is DESTINATION-DRIVEN: the room picks a destination colour set (via the selector: curve × genre × wheel-travel) and drifts toward its wheel position; on arrival it picks the next destination and sets off again. Never aimless — always a target, and each destination fixes its own travel pace. Scenes ride the room journey by default.',
    entries: [
      {
        id: 'journey-destination',
        title: 'Destinations and per-destination pace',
        keywords: 'target speed travel reference arrive reselect',
        body: [
          'The destination determines BOTH where the journey is heading and how fast: the room has a reference pace (°/min, agent-adjusted), and a destination 90° away travels at exactly that pace — nearer destinations stroll (down to ×0.5), farther ones hurry (up to ×2). Travel follows the shortest arc; the active palette\'s hues rotate with the wheel. On arrival the wheel lands exactly on the destination position and the next destination is picked (the arrived set excluded). The status strip shows the current destination and progress toward it.',
          'The destination is a bearing, not an applied palette — sets are still applied by scene fires and flare jumps. When a jump teleports the wheel, the bearing clears and the journey re-orients from the new point. If no eligible chromatic set exists, the walk holds (never forced churn).',
          'A room is NEVER set-less: with no active set the journey immediately selects a first set and applies it (engine start included), scene fires always wear the room\'s active set instead of effect defaults, and the owner or fleet can apply a specific set directly — tell the agent, which uses POST /spectra/api/room-color/apply.',
        ],
      },
      {
        id: 'journey-inherit',
        title: 'Inherit (default) and pace',
        body: ['An inheriting scene rides the room\'s destination journey, its pace factor scaling the travel speed — 0 holds the walk while that scene shows (no destinations picked). Adjusted by telling the agent.'],
      },
      {
        id: 'journey-override',
        title: 'Override — a scene takes the pen',
        keywords: 'custody transition into out of snap palette bounds',
        body: [
          'A scene may override the room journey outright: the same destination model, but destinations are picked WITHIN THE SCENE\'S OWN PALETTE BOUNDS (its accepted sets), at the scene\'s own reference pace. The override takes CUSTODY of the wheel, never a fork: entering, the scene\'s journey starts from wherever the room\'s walk had reached and picks its own destination (no snap — the palette change itself rides the normal scene crossfade). Leaving, the room\'s own journey resumes from wherever the override left the wheel with a fresh room destination — it never snaps back. One continuous story; only who steers changes.',
        ],
      },
      {
        id: 'journey-rainbow',
        title: 'Rainbow sets pause the walk',
        body: ['Rainbow and achromatic palettes have no wheel position, so the walk pauses while one is live (the bearing is kept) and resumes when a chromatic set returns. A rainbow set is never a destination — it is everywhere and nowhere on the wheel.'],
      },
    ],
  },
  {
    id: 'colorsets-groups',
    title: 'Colour Sets & Groups page',
    keywords: 'palette library author create edit delete swatch entries members rotate synced pool tier tiered nested bulk edit',
    intro:
      'Create, edit, and delete Colour Sets (named FG/BG palettes) and Groups (tiered containers of Sets, with an override layer that bulk-edits everything nested under them). Writes go through spot-effects\' own shared colour-set storage — the same library the sequencer, drift conductor, and every scene already read — so an edit here is visible everywhere immediately. Drafts live locally until Save, same convention as the Scenes page.',
    entries: [
      {
        id: 'colorsets-groups-page',
        title: 'Sets vs Groups, and the tiered list',
        keywords: 'apply now proof rotation cursor test fire preview tier tiered nested ungrouped bulk edit',
        body: [
          'A Set is a reusable palette: entries scoped to a device/category/role, each with FG colour, BG colour + mode, and brightness — applied wherever the room\'s active Colour Set lands.',
          'A Group is a tiered container: the left list nests every Set under the Group(s) that list it (▾/▸ collapses a group\'s tier). A Set can sit under more than one Group — it then appears under each one, labelled "also in: …" so the other membership is never hidden. A Set that belongs to no Group lists under "Ungrouped" at the bottom. Typing in Search temporarily flattens the list back to a plain filtered result, same as before tiering.',
          'A Group is also still an ordered/weighted pool: firing the Group directly (not any of its member Sets) picks ONE member — see "Rotation" in the Group\'s own editor, and "Palette Sync"/"Group overrides" below.',
          'The toolbar\'s ▶ Preview button and mode-availability toggle work on the DRAFT as edited — see "Preview: tap vs hold" and "Mode availability", below. Neither needs a Save first; Save is only for keeping the edit.',
          'A Set\'s own Mode availability marking (Hybrid/Light/Dark) does double duty: besides gating whether the set itself is offered automatically, a scene\'s colour-set PREFERENCE (Scenes page, Colour Sets tab) matches against this exact marking. Marking a Set here as Dark or Light is how a preferring scene finds it — see "Colour-set preference".',
        ],
      },
      {
        id: 'colorsets-rainbow',
        title: 'Rainbow select — 🌈 Rainbow vs ⬤ Single',
        keywords: 'rainbow select single hype black hole limit intensity enumerated marked',
        body: [
          'Each Set and Group card carries a Rainbow/Single toggle, next to Mode availability. ENUMERATED, not inferred from name or colours — only the three Hype sets, the Hype group, and Black Hole Rainbow are marked Rainbow by default; a colourful-sounding name elsewhere means nothing on its own.',
          'The room controls bar\'s drift-gradient panel (see "Drift gradient", above) carries the Rainbow select limit (default 0.9). Above that intensity, automatic colour-set selection is restricted to Rainbow-marked sets only; at or below it, to Single sets only — never both, never neither.',
        ],
      },
      {
        id: 'colorsets-preview',
        title: 'Preview: tap vs hold',
        keywords: 'apply to room preview tap hold press revert pause live drag temporary',
        body: [
          'Preview replaced the old permanent "Apply to room" — every apply here is temporary and reverts. TAP: pauses SPECTRA\'s own automatic scene/response/set changes for 5 seconds, applies this card\'s colours to the room, then reverts to EXACTLY what was live the instant you tapped. HOLD (½ second): pauses for up to 60 seconds and STAYS applied — release it early with a second tap, wait out the timer, or just navigate away (leaving the page releases it too).',
          'While previewing, drag any colour on the card (FG, BG, an override entry) and the room updates live — the preview keeps running, the pause timer keeps counting from when you started, nothing restarts or drops.',
          'The revert always restores the room\'s TRUE pre-preview state, read live the instant Preview started — never a guess. His show keeps running underneath a tap or a released hold exactly as if nothing happened.',
          'Previewing a plain Set shows exactly what firing it for real will render — including any enclosing Group\'s override, same as "Group overrides" below.',
        ],
      },
      {
        id: 'colorsets-group-mechanics',
        title: 'How a Group picks — cycle, bounce, weighted',
        keywords: 'wrap advance sequential random order',
        body: [
          'Cycle (the default): members fire in list order. Wrap loops back to the top; Bounce reverses direction at each end instead of jumping back to the start. A cycling Group never re-fires the member currently showing — reordering members changes the sequence, not just labels.',
          'Weighted: each member rolls with a chance proportional to its weight. "Exclude current from next roll" (weighted mode only — cycle already never repeats by construction) zeroes the showing member\'s weight for that roll so back-to-back picks favour variety; if that would zero every weight (a group of one), the roll falls back to the raw weights rather than jamming.',
        ],
      },
      {
        id: 'colorsets-palette-sync',
        title: 'Palette Sync',
        keywords: 'anchor hue nearest current room wheel reanchor',
        body: [
          'A synced Group starts its pick from wherever the room\'s colour actually is, instead of its own private cycle position: the room\'s current Colour Set when it happens to be a member of this Group, else the member whose hue is nearest the room\'s current wheel position. From that anchor it advances one step by the Group\'s normal cycle/weighted rule. Switching between two synced Groups therefore keeps the room on one colour family instead of jumping cold — the point of the name.',
          'With Palette Sync off, a Group keeps its own private cursor regardless of what the room is currently showing.',
        ],
      },
      {
        id: 'colorsets-group-overrides',
        title: 'Group overrides — the bulk-edit lever',
        keywords: 'layer replace field win merge scope bulk edit apply direct fire multi group precedence chain',
        body: [
          'A Group\'s own Overrides section is the bulk-edit lever for every colour set nested under it: edit it once here, instead of opening each Set individually, and any field it sets (colour, BG, brightness…) replaces that value for every member — for the virtuals its scope resolves to. Fields left blank keep each member\'s own value. An override entry can also reach virtuals a member\'s own entries never touch, so a Group-level clamp (e.g. "always keep Matrix dim") behaves the same no matter which member gets picked.',
          'This is a LIVE layer, never a destructive write: overrides are computed fresh at fire/preview time and never rewrite a member Set\'s own stored entries — editing or deleting a Group never touches its members\' own data.',
          '2026-08-19: the override now applies whenever a member Set fires, not only when the enclosing Group is the resolved fire target — a scene or trigger that names the Set directly wears its Group\'s override too, same as firing the Group itself. (Before this date it applied only on a Group fire; if something here reads stale, that\'s the behaviour it changed from.)',
          'A Set sitting under more than one Group (the list view shows this with "also in: …") gets EVERY enclosing Group\'s override chained on top of its own entries, in ascending alphabetical order by Group name — never just one Group "winning" and the rest ignored. A field two Groups both set resolves to the alphabetically-LAST Group\'s value; fields only one Group touches land regardless of the other. A Group with no override entries authored contributes nothing to the chain.',
        ],
      },
      {
        id: 'colorsets-likelihood-curves',
        title: 'Likelihood — Colour Sets and Groups',
        keywords: 'curve likelihood weight sequencer roll wheel travel multiply group chain compound flat identity',
        body: [
          'Every Set and Group card carries a Likelihood section — the SAME curve editor the Scenes page\'s Sequencing tab uses (see "Sequencing tab" for the full preview-button / picker / curve-window / Detach / Revert / Save-as-named-curve mechanics; it is literally the same component, so the safety rule there — an edit takes effect immediately as this item\'s own one-off and can never write into a shared profile — applies here identically). This only affects the automatic wheel-travel colour roll; a manual Fire, Test Fire, or Preview always bypasses it.',
          'A Set\'s curve shapes how likely the automatic roll is to pick it at the room\'s current intensity — unchanged from before Groups got their own curve.',
          'A Group\'s curve MULTIPLIES onto every member Set\'s own score — it never overwrites it. No curve (or an explicit Flat 1.0) is a true ×1.0 identity, so an unmarked Group changes nothing. A Set sitting under more than one Group (the list view already shows this with "also in: …") gets EVERY enclosing Group\'s curve multiplied in together — they chain, none of them "wins" alone.',
          'Multiplying several curves together can compound toward a small number — a Set can go from rarely-picked to practically never without its own curve ever changing. Only an exact zero (a Set\'s own curve, or every remaining factor) is a hard veto that blocks a pick outright; a small-but-nonzero score is never silently skipped — it is just very unlikely relative to its peers. The Sequencer status strip\'s "last colour pick" breakdown (Scenes page) always lists curve/genre/wheel/group/score per candidate, so a Set that stopped showing up is explainable by looking there, not a mystery.',
        ],
      },
    ],
  },
  {
    id: 'engine',
    title: 'Evolution engine (S2)',
    keywords: 'drift conductor response surge leg bridge dark recording carry',
    intro:
      'The S2 engine is a scene\'s declared life, running: a drift conductor (one leg every ~20s glides creeping and following values, and walks the room\'s colour journey) plus a response engine (flares/charges/lulls/drops execute their bands). It is fed READ-ONLY from spot-effects and runs DARK — every move is computed, recorded, and shown here, but no write reaches the lights until the S3 handover.',
    entries: [
      {
        id: 'engine-dark',
        title: 'Dark — recording, not driving',
        keywords: 'recording executor s3 handover safe',
        body: [
          'The "dark — recording" badge means the engine\'s executor records every glide and jump instead of sending them. The identical engine runs against the real render pipeline in the offline test bed; the S3 handover swaps the executor when the ownership record grants SPECTRA the lights — nothing else changes.',
        ],
      },
      {
        id: 'engine-strip',
        title: 'The Engine strip (Scenes page)',
        keywords: 'status strip journey position legs live',
        body: [
          'Live display only: journey custody (room, or a scene OVERRIDE) with pace and wheel position, the engine-active scene with its drift legs (expand for per-virtual positions), holds (pause / Dinner Party / Ambient — Force Scene does NOT hold drift), the last surge, and bridge health with the current section-energy intensity.',
        ],
      },
      {
        id: 'engine-surges',
        title: 'Surges — how a response executes',
        keywords: 'flare band kind scale momentary permanent drift jump reroll colour carry baseline ramp',
        body: [
          'The bridge classifies every spot-effects trigger fire: charge/lull/drop stay themselves, scene changes are observations, everything else is a FLARE. The band containing the fire\'s intensity fires its attached kinds at their ×scales, in a fixed order: dice re-rolls (correlated dice stay correlated), permanent then momentary param moves (a key lands on every device whose effect has that param), gain envelopes, then the colour jump — the shipped selector picks, the keep-current rung never forces churn, and the new colours RAMP IN over a length that shrinks with intensity (gentle ~2.5 s, full-scale ~0.15 s) while the room journey resumes from the new wheel point.',
          'CARRY: re-rolls, permanent moves, held gains, and colour jumps move the baseline drift resumes from. MOMENTARY kinds return exactly — the release honors the carried-now baseline, including a creep\'s current wander position. A surge on a followed value is an impulse the follow re-asserts from smoothly over its slew.',
        ],
      },
      {
        id: 'engine-bridge',
        title: 'The read-only bridge',
        keywords: 'spot-effects feed websocket intensity section energy genre deferral degradation',
        body: [
          'SPECTRA subscribes to spot-effects\' existing broadcasts (track state, trigger fires with intensity) and reads the analysis storage — one-directional; spot-effects is untouched. Intensity between fires is librosa section energy at the playback position. If the bridge is down, nothing breaks: no moments tick, no surges fire, intensity holds at the 0.5 neutral — a stated degradation, not a failure.',
        ],
      },
    ],
  },
  {
    id: 'status-page',
    title: 'Status page',
    keywords: 'health ownership bridge liveness engine',
    intro:
      'App status (scene count, light ownership from the durable record, bridge state, sequencer state, room journey) plus the evolution-engine card: journey custody, active scene and legs, bridge health, recorded writes.',
  },
  {
    id: 'ownership',
    title: 'Light ownership & handover (S3)',
    keywords:
      'handover switchover owner spot-effects spectra liveness two writers quiesce armed',
    intro:
      'Exactly one process owns the lights — spot-effects (the external LedFX service) or SPECTRA — never both. The durable record (storage/spectra/ownership.json) is enforced in every write path: while spot-effects owns (the shipped default), SPECTRA touches no device and no audio input; during a handover NEITHER world writes. There is no UI switch by design: the room changes hands only on the owner\'s word, via the armed API (tell the agent; procedure in docs/SPECTRA_HANDOVER.md).',
    entries: [
      {
        id: 'ownership-record',
        title: 'Reading the state',
        keywords: 'inspect status api record json',
        body: [
          'GET /spectra/api/ownership shows the owner, any in-flight handover step, and the history trail; the Status page and spot-effects\' Debug page (ledfx-health) surface the same record. States: spot-effects owns · spectra owns · handing-over · released (the panic handle — see below).',
        ],
      },
      {
        id: 'ownership-liveness',
        title: 'The liveness endpoint',
        keywords: 'health checker frame flush freshness 503 contract',
        body: [
          'GET /spectra/api/liveness is the binding fleet contract: per-virtual frame-flush freshness straight from the render loop, HTTP 200 healthy / 503 not. While SPECTRA is dark it answers healthy only if provably dark (a live stack without ownership is the split-brain tripwire). Never remove or repoint it without the owner\'s word.',
        ],
      },
      {
        id: 'ownership-handover',
        title: 'How the switch works (owner-run only)',
        keywords: 'quiesce activate commit rollback failure single owner armed latch readiness precondition refuse seeder',
        body: [
          'Before anything moves, the READINESS GATE: the switch checks the go-day preparations itself and REFUSES — room untouched, current owner still writing — when SPECTRA\'s fx-live device config is missing, empty, or has no usable virtuals (the refusal names the seeder command), or in reverse when the LedFX service unit is missing. Skipped preparation can no longer dark the room.',
          'Then two steps, strictly ordered: quiesce the current writer and VERIFY it stopped (Hue DTLS session released, DDP sending stopped), only then activate the other (SPECTRA\'s in-process device layer + the shared audio hub — or, in reverse, restart LedFX). Any failure lands back at the old owner automatically — never two writers, never a split. The API refuses entirely until the process is armed (SPECTRA_HANDOVER_ARMED=1).',
        ],
      },
      {
        id: 'panic-release',
        title: 'Panic release — let go of every light',
        keywords: 'release home assistant ha panic emergency let go stop wled hue ddp virtuals band',
        body: [
          'The red "Release to Home Assistant" button, always reachable (top of every page, next to the nav) — press it and SpotFX AND SPECTRA both let go, no confirmation, the press is the consent. Unlike the handover above this is NOT gated by SPECTRA_HANDOVER_ARMED: releasing is always safe to allow, because there is no new writer coming up. The ownership record moves to "released" first, before anything else happens; then BOTH worlds\' devices are cleaned up EVERY press, regardless of which one the record said owned — a rogue writer the record didn\'t know about (e.g. the external LedFX service started behind its back) still gets addressed. Each device is told to let go explicitly rather than just falling silent: WLED devices get the JSON API\'s {"live": false} so they drop out of realtime now instead of waiting for their timeout to lapse; Hue\'s entertainment/streaming session is stopped so the bridge frees the group; the external LedFX service\'s active virtuals are deactivated over its own API, reached directly (not through SpotFX\'s app) so this always works even after the record moves. A released room shows the banner below until someone takes it back.',
          'Release VERIFIES, it doesn\'t just command: after cleanup it reads real state back — is the SPECTRA stack actually down, are the external LedFX virtuals actually inactive (or the service not even running). If everything checks out, the button and banner behave as above. If a device could not be confirmed dark, a loud toast says so ("these lights may still be lit") and lists what failed — the room record still shows released (that part always succeeds), but treat an unverified release as needing a manual check of the flagged device.',
          'The way back — "Take back (SPECTRA)" on the banner — is the SAME guarded handover described above: readiness-gated, and still requires SPECTRA_HANDOVER_ARMED. Releasing is instant and unconditional; coming back is deliberate, same as any other handover.',
        ],
      },
      {
        id: 'room-controls-bar',
        title: 'Room controls — Mode, Ambient, Scenes, brightness',
        keywords: 'dark mode light display mode lock dark_lock brightness multiplier dim undim ambient color colour dark colour second colour transition pace global room bar dimmer midsong mid-song trigger fallback scene change mode transitions analysed triggers only my triggers only full settings model force scene hold pin catch-up catchup ease release ramp snap read-back readback confirm confirmed unconfirmed partial straggler retry rate limit zigbee bulb name music wins precedence yielding holding partial transitioning resting state playing paused off always auto on during music auto-return three settings mode stale age verified verify honesty confirmed ago hue areas entertainment area group groups dining room which lights press hold long press tap cycle grouped button expand panel light bulb icon toggle spam delay debounce per-song preference fallback',
        body: [
          'The compact strip above the release button, on every page — three press-and-hold grouped buttons (2026-08-17, his ask: related controls collapsed into one button each) plus a standalone room-wide Brightness dimmer.',
          'Mode groups the Hybrid/Dark/Light display-mode control with its Light-mode colour picker and brightness slider. It carries no text — the fill colour alone tells you the mode: white = Light, black = Dark, grey = Hybrid (a fixed accent border on every state keeps it readable as a button, whichever fill is showing). A short tap CYCLES the three modes (Hybrid → Dark → Light → …). Holding the button (~½s) opens the colour/brightness panel instead of cycling. The button\'s fill updates the instant you tap — cycling never feels delayed — but the actual change is only sent to the room after a full second with no further taps, so cycling past a mode on your way to another one never spams the room with modes you were only passing through; if you keep tapping, only the mode you land on is ever applied. See "Display mode — Hybrid, Dark, or Light" below for the mode mechanics themselves.',
          'Ambient is the light-bulb icon (💡). A short tap toggles it straight on/off, applied immediately (no delay) — turning it back on restores whichever of the three settings (below) you had picked, rather than one fixed choice. Holding the button opens the full panel: the three-setting select (Off / On during music / Auto-return), both authored colours (normal and the separate Dark-mode colour), the Hue entertainment-area picker (which areas Ambient may hold — embedded directly in the panel, not a separate popup), and the live status badge. See "Ambient Hue areas" and the ambient details below for the mechanics.',
          'Scenes bundles the scene-change tier, Force Scene, and the global transition pace together. A tap always just opens the panel — by his own design, Scenes never cycles anything on a tap (unlike Mode), since there\'s no single "next" scene-change setting that would make sense to step through blindly.',
          'Every panel opens downward from its button, clamped to stay on-screen horizontally — it never runs off the side of a phone, however close to the edge the button sits. Tap outside a panel, or press Escape, to close it.',
          'Dark mode: see "Dark mode — force every background black" below.',
          'Brightness: a 0–100% room dimmer (legacy Brightness Multiplier action). It scales brightness/background_brightness UNIFORMLY at the write seams — every drift glide, every surge jump, and every scene fire\'s output — never the authored scene values or the engine\'s own carried baseline, so turning it back to 100% always restores exactly what was authored.',
          'Ambient: a three-setting dropdown ("Off" / "On during music" / "Auto-return") plus TWO colour swatches — the first for normal/hybrid use, a second marked "(dark)" that\'s held instead whenever Dark mode is also on (see "Ambient\'s dark-mode colour" below). Click either swatch to open LedFX\'s own colour picker (see "The colour picker"), solid only (a Hue entertainment stream only ever takes one colour). Legacy ledfx_ambient / ledfx_ambient_color actions, extended 2026-08-15 (spectra/services/ambient_music_gate.py) to his own three settings: "Off" — Ambient never holds, the whole room performs, Hue included. "On during music" — Hue is held lit at the ambient colour UNCONDITIONALLY, music playing or not; every other device (WLED etc.) keeps running the show regardless, since Ambient only ever touches Hue devices. "Auto-return" — Ambient is the room\'s RESTING state: MUSIC WINS while it\'s actually playing, Ambient stands aside automatically and resumes on its own the instant the room goes quiet, with no manual re-toggle needed. Because the setting and the live hold can differ under "Auto-return", a second badge next to the swatch shows what\'s ACTUALLY happening, always, not just right after a save: a purple "ambient: holding" badge means every claimed light is CONFIRMED lit at the chosen colour right now (always true under "On during music" once genuinely held, and only when confirmed-quiet under "Auto-return"); a red "ambient: partial" badge means Ambient believes it should be holding but the most recent check found at least one light not actually lit (or nothing left to hold at all) — hover it to see which bulbs, by name; an amber "ambient: yielding" badge means it\'s standing aside for music, or an unresolved playback read (only reachable under "Auto-return" — the safe default either way is to NOT hold); a grey "ambient: transitioning" badge means a hold or release is physically in flight. Every one of those badges also carries a "· Ns/m/h ago" suffix — how long ago the room was last actually confirmed, whether by a fresh write\'s own read-back or an independent recheck that runs on its own every 30 seconds regardless of whether anything else changed (2026-08-15 fix: a claimed hold used to just replay its last write\'s outcome forever with no re-check at all — his room once read "holding, 17/17" all night while every bulb was actually off). That independent recheck only ever READS the bridge, never writes — a bulb turned off out-of-band (by him, the Hue app, a physical switch) is reported honestly, never fought or re-lit. When Ambient does hold: every live Hue device in the room freezes its entertainment stream (so the bridge falls back to normal REST control) and holds at the chosen colour, over a short fade, at a brightness DERIVED from that same colour (2026-08-16 fix — picking a darker shade used to have no visible effect at all, since the bridge\'s own colour math discards how light or dark a colour is; brightness now tracks it, so a paler pick reads brighter and a darker pick reads dimmer, at either swatch). Ambient then READS EVERY LIGHT BACK from the bridge and only counts it as held once its reported state actually matches — a bridge accepting a write (2xx) doesn\'t mean the physical bulb took it (zigbee can silently drop a command under a burst of writes even though the bridge said OK). A straggler is retried a bounded number of times, spaced apart, before being given up on. Non-Hue devices (WLED etc.) keep running their normal reactive show, same as the legacy behaviour this ports, under every setting. Releasing — whether by switching away from a hold or "Auto-return" doing it automatically when music starts — is always a two-step ease, not a snap: a brief dim fade, then a second ramp (about 8 seconds) that eases the held bulb toward whatever the room\'s live effect is actually showing right now, before finally releasing back to the stream — matching how the legacy app always eased back into the show instead of cutting to it. A separate, one-shot save-outcome badge can still appear right after you touch the setting: grey "ambient: dark" / "ambient: no-hue-devices" (SPECTRA isn\'t currently driving the lights, or there\'s no live Hue device — saved, nothing changed live), red "ambient: failed" (every Hue device rejected it — saved, but the room may not match; check the bridge), or red "ambient: N/total held — <names>" (most of the room took the colour but one or more bulbs, NAMED by their own bridge name, did not confirm it even after retries — check those bulbs directly). Dinner Party (the other legacy room-MODES behaviour) is still a separate, later build.',
          'Ambient Hue areas — inside the Ambient panel, below the two colour swatches — narrows Ambient to just some of your Hue entertainment areas instead of every live one; see "Ambient Hue areas" below.',
          'Transition: a flat MANUAL override for the room\'s default entry-blend ramp in ms (legacy ledfx_global_transition action) — wins over everything below when set above 0. Leave it at 0 (the default) to let "Transition @ low/high intensity" scale it by intensity instead — see "Intensity-scaled scene transitions" below.',
          'Transition @ low intensity / @ high intensity: the two bounds a scene\'s entry-blend ramp scales between by intensity, linearly, when that scene doesn\'t author its own entry ramp (Scenes → Phase Choreography → Override Blend, entry_ramp_ms) and Transition above is 0. See "Intensity-scaled scene transitions" below for the full mechanic, including why quiet flares land the LONGER transition and hard ones the SHORTER — and why the transition starts slightly before the trigger, not on it.',
          'Scene changes: four ticks for what drives scene changes room-wide — three of them stack, one doesn\'t. "Transitions only" — a scene change on every song transition, nothing else. "Transitions + analysed" — transitions plus the analysed mid-song triggers "⟳ Generate" seeds (see the SPECTRA Triggers help). "My triggers only" — a PER-SONG preference, not an absolute: on a song where you\'ve placed any trigger of your own, ONLY your hand-placed triggers fire — transitions, analysed mid-song triggers, and flares are all silenced for that one song. On a song where you haven\'t placed one, it behaves exactly like "Transitions + analysed" instead — it never leaves a song silent. "Everything" (default) — every source, on every song: transitions, analysed mid-song triggers, your own hand-placed triggers, AND response-engine flares (charge/lull/drop/flare reactions — a scene\'s own tuned material). Nothing is deleted by moving between ticks — a lower tick just skips firing the higher tiers\' material room-wide.',
        ],
      },
      {
        id: 'drift-gradient',
        title: 'Drift gradient — the two-dimensional colour space',
        keywords: 'gradient 2d two dimensional drift square vertices vertex top bottom edge x axis time y axis intensity loop bounce rainbow select single limit save overwrite new picker',
        body: [
          'The square swatch next to Scenes in the room controls bar. A saved 2D gradient is what the room\'s colour drifts THROUGH when one is active — a square, not the usual single horizontal colour bar, with colours authored only along the top edge (high intensity) and bottom edge (low intensity); everything in between blends linearly. This is NOT a rotation control — there\'s no angle to set, only the two edges.',
          'Tap the swatch to open the picker: saved gradients as tiles (tap one to make it active), "Off" (the wheel-based colour journey drives the room as before — the unmodified default), and "New…" to start one from scratch. With a gradient open, each edge is the SAME gradient-stop picker used everywhere else in the app — drag/add/remove colour stops along it — plus a Loop/Bounce choice for how the drift travels along time, and "Save (overwrite)" / "Save as new…" / "Delete" below.',
          'While a gradient is active, the room\'s picker moves steadily along the TOP-TO-BOTTOM square as time passes (looping or bouncing per the gradient\'s own setting) and along top-to-bottom as the song\'s intensity changes — drifting toward the new position rather than snapping, re-aiming only when a trigger fires or the song transitions (not continuously chasing every fluctuation). Flares still jump the colour exactly as they always have — this is in addition to that, not instead of it.',
          'Rainbow select limit — the numeric field at the bottom of the same panel. Above this intensity, automatic colour-set selection is restricted to sets marked "Rainbow" (Colours page); at or below it, only "Single" (non-rainbow) sets are chosen. Default 0.9.',
        ],
      },
      {
        id: 'intensity-scaled-transitions',
        title: 'Intensity-scaled scene transitions — and why they start early',
        keywords: 'transition time crossfade intensity scale linear gentle hard low high min max lead early midpoint mid-point mid point land on the trigger beat momentary flare first switch finish hold flip back inspector settings scene transition lookahead horizon predict prediction',
        body: [
          'Two settings in the Scenes panel (room controls bar, above) — "Transition @ low intensity" and "Transition @ high intensity" — scale how long a scene\'s entry crossfade takes, LINEARLY by the fire\'s own intensity: quiet, low-intensity fires get the LONGER transition (300ms by default), loud, full-scale fires get the SHORTER one (200ms by default). Either bound is a plain number you can change any time — no code change needed either way. They only apply when the room\'s flat "Transition" override above is left at 0 and the firing scene has no entry ramp of its own.',
          'The transition also starts slightly BEFORE the trigger moment it belongs to, not on it — so its MID-POINT lands exactly on the beat instead of its start. A few effect pairs (radial swapping with a particle-style effect like Black Hole, Orbits, or Fireworks) have their own tuned landing point instead of the plain midpoint, matching the moment those effects\' own visual payoff (the bloom, the burst) actually happens.',
          'The same idea applies to a momentary flare (one that switches, holds, then flips back) — but anchored differently: the flare\'s FIRST SWITCH finishes exactly on the trigger, then it holds, then it flips back to normal afterward. Not every flare switch takes visible time to land — an instant jump (most parameter types, and every momentary brightness pulse) already lands the instant it fires, so only a flare landing on a smoothly-interpolated parameter actually starts early.',
          'Most of your triggers don\'t name a scene in advance — you leave that choice to the room, which only decides at the moment the trigger fires. Landing a mid-point early needs to know which scene is coming, so a trigger like that used to just start ON the beat with no early lead at all. It now looks ahead — up to five seconds before the trigger — and commits to the same pick the room would make anyway, early enough to compute and apply the lead. If anything about the room changes in that window (the picked scene gets disabled, the display mode changes, Force Scene points elsewhere), the early commitment is thrown away and the trigger just fires the normal way instead — late, but always the right scene. It never shows you a scene you didn\'t ask for.',
          'You will never see this as a delay — it means a transition or flare that used to start exactly ON the beat now starts a little before it, so its most noticeable moment (the mid-point, or the switch itself) is what you actually hear/see land on the beat.',
        ],
      },
      {
        id: 'live-energy',
        title: 'Live Energy — the number driving scene picks and flares',
        keywords: 'energy intensity section bar top always visible live meter bridge librosa quiet loud',
        body: [
          'The ⚡ Energy meter, on every page, next to the room controls — the shared top-bar strip\'s first widget, alongside the device preview (below). It shows the SAME number the engine\'s automatic decisions read, not a lookalike recomputed for display: raw librosa section energy at the current playback position (0.00 = the quietest section this song, 1.00 = the loudest), fed by the read-only bridge (see "The read-only bridge"). That one value is wired directly into the drift conductor\'s pace, the sequencer\'s default scene pick, and automatic transition fires — everything the room does on its own without a hand-placed trigger or authored intensity.',
          'Shows "—" when there\'s no live number to show: the bridge is down, nothing is playing, or this song has no section analysis yet. In every one of those cases the engine itself falls back to a 0.5 neutral internally — the meter doesn\'t fake that number, it tells you why there isn\'t one.',
          'A hand-placed trigger or a mid-song "⟳ Generate" pick can carry its OWN authored/baked intensity instead of this live value at the moment it fires — this meter always shows the live bridge signal, which is what drives everything that ISN\'T an explicitly authored intensity.',
        ],
      },
      {
        id: 'intensity-mark',
        title: 'Mark — the current song\'s intensity scale',
        keywords: 'intensity mark scale factor genre bass ceiling cap gate hype auto automatic manual override percent percentage slider drag',
        body: [
          'Next to ⚡ Energy on the top-bar strip. Every song has an intensity SCALING FACTOR — a multiplier on the live energy number above, based on its genre and how bass-forward it measures against the analysed library. 100% means no adjustment; a hyped-up genre like EDM lands well above 100%, a mellow one well below.',
          'Automatic scaling always tops out at a 75% delivered intensity, on ANY song, however hyped its genre — a deliberate gate, not a bug: the room only reaches full-scale hype effects on a track you\'ve personally marked as one, never automatically.',
          'Tap "Mark" to set this song\'s factor by hand (0–200%) — the one way past that 75% ceiling. Editing gives you a real slider you can drag AND a number field next to it for the exact value — drag to get close, then type the precise percent (this factor drives how loud the room gets, so exact matters). A marked song keeps its number every time it plays again, not just this once. "Edit" changes it, "Clear" removes the mark and returns the song to automatic scaling.',
        ],
      },
      {
        id: 'device-preview',
        title: 'The device strip — watch your favourite devices while you edit',
        keywords: 'device preview swatch pixel strip live favourite favorite favourites star pause resume conserve resources ledfx facade visualisation visualization websocket connected paused reconnecting unavailable expand collapse pixel matrix grid rows columns phone mobile idle tab hidden auto-pause auto pause auto-resume auto resume background tab source ownership status icon button',
        body: [
          'The top-bar device strip, next to ⚡ Energy — one small colour swatch per favourite device, live, on every page while you tweak scenes, settings, or colour sets. It reads real pixels off whichever world is actually driving your lights right now: her own in-process render pipeline when SPECTRA owns the lights (your normal setup), or LedFX\'s own visualisation feed on the rare occasion spot-effects owns them instead. SPECTRA never invents its own render — it always reads the real thing, wherever it currently lives.',
          '★ Favourites opens a picker (checkboxes against the same device registry every scene tab uses) to choose which devices show. Leave it empty and it auto-populates with a sensible default (the same "genuinely driven" virtuals the S3 activation gate trusts) so the strip works the first time you open the app, no setup needed. "Reset to default" clears your explicit picks and goes back to that auto-populated list.',
          '▸ Expand swaps the compact one-swatch-per-device row for a full per-pixel view, one device per line, stacked vertically — remembered on this browser/device, not synced. A true matrix (more than one row, e.g. a mapped grid fixture) draws as an actual grid at its own aspect ratio; an ordinary single-row strip draws as one line spanning the full width. Expanding always grows the page downward, never sideways — nothing runs off the edge of a phone screen, however many pixels a device has.',
          'One round button next to the swatches IS the status — no separate label, click it to toggle. Its colour and icon together tell you which of four states you\'re in: ⏸ purple means live (click to pause); ▶ gray means YOU paused it (click to resume — it stays paused until you do, the connection genuinely closed, not just a blank display); ⏾ blue means the tab itself just isn\'t visible right now and the connection dropped on its own to save resources (switching back reconnects automatically, no click needed — clicking the button in this state pauses it manually instead, and it\'ll then stay paused even after you switch back); ↻ amber means reconnecting, or that nobody currently owns the lights right now (a handover in flight) — it never restarts or wakes anything, it just waits. Your own manual pause always wins over the tab-hidden state, so pausing and then switching tabs still shows ▶ gray, not ⏾ blue.',
          'If it ever costs you something you\'d rather not pay while you\'re not looking at it, clicking to your own pause is the answer for a deliberate stop — the tab-hidden behaviour already handles the common case of just switching away for a while.',
        ],
      },
      {
        id: 'dark-light-mode',
        title: 'Display mode — Hybrid, Dark, or Light',
        keywords: 'dark light mode display mode hybrid default toggle lock dark_lock background black hard clamp shield singles category exempt restore repaint snapshot music playing deferred three state',
        body: [
          'The legacy global Default/Dark/Light display-mode cycle, all three states, on the room bar\'s Mode button — tap to cycle Hybrid → Dark → Light → …, hold to open a panel with a direct select plus the Light colour/brightness controls (see "Room controls — Mode, Ambient, Scenes, brightness" above). Hybrid ("default" on the wire — his own word for legacy\'s Default) forces nothing: each device shows whatever its scene authors. Dark hard-clamps every non-shielded device\'s background to black at LedFX itself (the same dark_lock flag the legacy toggle drove) — no write path, drift glide, or scene fire can relight a background while it\'s set. Light forces the colour/brightness picker in the panel onto every non-shielded device\'s background, live, right now, whether or not music is playing — see "Light mode — forced background" below.',
          'Switching to Hybrid repaints whatever each device was showing right before you last switched to Dark, from a snapshot taken the instant you switched — UNLESS music is playing right now, in which case that stale snapshot is deliberately left unpainted (a grey "repaint deferred to live show" badge says so) and the room\'s own automatic show repaints it on its next natural fire instead. Forcing an old still frame back over a room that should be tracking live music is the same mistake as freezing the room under Ambient mid-song — dark_lock still clears either way, it just doesn\'t also impose a stale look while something live is about to replace it anyway. Switching to Light instead overwrites the background outright, so there\'s nothing stale to skip.',
          'Devices in the "Singles" category (legacy\'s own default) always keep their own authored background regardless of mode, in BOTH Dark and Light — SPECTRA never locks/unlocks or force-writes them. Additional exempt categories/virtuals are settable via the room-controls API (dark_light_shield_categories / dark_light_shield_virtuals), not yet a bar-level control.',
          'Composes with Ambient\'s three settings, not a simple on/off: whenever a Hue device is actually frozen right now (Ambient "On during music" unconditionally, or "Auto-return" while confirmed quiet), that device is driven by direct bridge REST, bypassing LedFX entirely — Dark/Light\'s LedFX-side writes have no visible effect on it. Dark mode DOES still change which Ambient colour that frozen device holds, though — see "Ambient\'s dark-mode colour" below; display mode never bypasses Ambient, and Ambient never blocks it, Dark mode changes what Ambient holds. The moment a device isn\'t frozen (Ambient "Off", or "Auto-return" while music plays), it\'s rendered by LedFX like any other device and responds to Dark/Light normally.',
          'A red badge in the Mode panel names any device that didn\'t confirm the requested state (dark_lock, or the Light background) after a live read-back from LedFX — checked, never assumed. An unconfirmed device also puts a small red dot on the collapsed Mode button, so you don\'t have to open the panel to notice.',
        ],
      },
      {
        id: 'display-light-mode',
        title: 'Light mode — forced background',
        keywords: 'light mode forced background colour color brightness picker unconditional playing test before after watchable',
        body: [
          'Light is the state built specifically so you can SEE the display-mode feature work: since every scene authors a dark colour set, Hybrid and Dark look the same to the eye — nothing to compare against. Switch Display to Light and every non-shielded device\'s background changes to the colour/brightness picker next to the select, immediately, regardless of what song is playing, what scene is active, or whether that scene authors a background at all.',
          'The write is unconditional — not gated on whether music is playing. A fresh "set the background to this now" write is authoritative the instant it lands, the same reason Dark\'s own clamp isn\'t gated either. That means you can watch it work while your music plays, no pausing, no waiting for a scene change.',
          'Only the background is touched — background_color and background_brightness on each device\'s currently-running effect. The running effect itself and every other/foreground parameter are left exactly as the scene set them.',
          'The colour and brightness you pick here are saved with the room (defaults #201830 at 30%, legacy\'s own default) — editing either while Light is already selected re-applies live immediately, same as picking Light in the first place.',
          'A red badge names any device whose background didn\'t confirm at the requested colour/brightness after a live read-back from LedFX.',
        ],
      },
      {
        id: 'ambient-dark-colour',
        title: 'Ambient\'s dark-mode colour — a second colour just for Dark mode',
        keywords: 'ambient dark colour color second colour dark mode combination interaction ease glide swap transition snap picker',
        body: [
          'Ambient holds TWO authored colours, not one: the normal swatch on the room bar (used whenever Dark mode is off, and while it\'s on but hybrid/normal is what you want) and a second "(dark)" swatch, held instead whenever Dark mode is also switched on. Both use the exact same colour picker — there\'s no new control, just a second colour to author with it.',
          'They start out identical — the dark swatch mirrors the normal one until you explicitly pick a different colour for it. Nothing about your room changes just from this feature shipping; you get a second colour to diverge only once you choose to.',
          'Each swatch\'s brightness comes from that same colour — picking a paler or darker shade changes how bright the held lights read, not just their hue, for BOTH swatches. A vivid, fully-saturated colour still reads at full brightness (it\'s the intensity you asked for, not a dim one) — only lightening or darkening a colour moves its brightness.',
          'Dark mode never bypasses Ambient, and Ambient never blocks Dark mode — Dark mode changes WHICH colour Ambient holds. If Ambient isn\'t holding at all right now (setting "Off", or "Auto-return" while music plays), turning Dark mode on/off has nothing to swap.',
          'Toggling Dark mode while Ambient is actively holding your Hue lights EASES from one colour to the other — the exact same graceful bridge-side glide Ambient already uses whenever you change its colour by hand, not a hard cut. If you haven\'t authored a distinct dark colour yet, toggling Dark mode holds the identical colour, so nothing visibly moves and no redundant write happens.',
        ],
      },
      {
        id: 'ambient-hue-groups',
        title: 'Ambient Hue areas — choose which Hue lights Ambient holds',
        keywords: 'ambient hue areas group groups entertainment area select choose dining room living room bridge scope subset pick which lights',
        body: [
          'Embedded directly in the Ambient panel (hold the 💡 button on the room bar), below the two colour swatches. By default Ambient reaches EVERY live Hue entertainment area in the room — this picker lets you narrow that to just the ones you want, e.g. your dining room versus your other Hue lights, if you have more than one Hue bridge/area.',
          'Opens a checkbox list, one row per live Hue area, by its own bridge-configured name. Nothing checked (the default, shown as every box already ticked) means every area — leave it alone and nothing about your room changes. Uncheck an area and Ambient will never freeze or write to it: it keeps running its normal reactive show exactly like your non-Hue devices always do under Ambient.',
          'Unchecking an area that Ambient is CURRENTLY holding releases it immediately, the same graceful two-step ease Ambient always uses to release (a brief dim fade, then easing toward whatever the room\'s live effect is actually showing, before finally handing back to the stream) — not a hard cut. An area you never had checked, and that was never held, is left completely untouched by this — no fade, no flicker, nothing.',
          '"Reset to default (all)" clears your choice back to every live area — including any area added later (a third bridge, say): the default always tracks whatever Hue is live in the room, it\'s never a frozen list.',
          'Ported from the legacy front-page Ambient button\'s own long-press group picker — same idea (choose which Hue group is in play), same unit of choice (one entertainment area per checkbox).',
        ],
      },
      {
        id: 'force-scene',
        title: 'Force Scene — hold one scene',
        keywords: 'force scene hold pin lock stuck stay same scene forever pick redirect reassert immediate now activate',
        body: [
          'Turning it on (or picking a different scene while it\'s already on) fires that scene IMMEDIATELY — you don\'t have to wait for a song transition or a trigger to land. On top of that, it also holds: every scene the room would otherwise pick automatically from then on — a sequencer roll, a trigger firing, or the automatic change on a song transition — fires the pinned scene instead, at the intensity/colours that pick would normally have used.',
          'If nothing happens, look for the badge under the picker — it always says why: "fired" names the scene that just activated; "not fired" means nothing was pinned yet, or the pinned scene no longer exists.',
          'It does NOT touch a manual Fire from the Scenes page editor — that\'s an explicit single fire, not the system picking a scene, so it always fires exactly the scene you pressed Fire on.',
          'Turn Force Scene off to let the sequencer/triggers pick freely again — nothing about the scene you were holding is changed or deleted, it just stops being reasserted.',
          'Pinning a scene you\'ve marked Disabled (see "Disable" on the Scenes page) still fires it — you pressed the button, you mean it — but the badge adds a second line, "⚠ overriding disabled scene," so the contradiction is visible instead of silent.',
        ],
      },
    ],
  },
  {
    id: 'builder',
    title: 'Timeline (song profiles)',
    keywords: 'timeline canvas triggers place edit profile builder song',
    intro:
      'The song timeline from the SpotFX Profile Builder, carried into SPECTRA whole: build a song\'s lighting profile on a zoomable timeline. Arm an event on a palette key, then place triggers with the mouse; circles show intensity, triangles show timing. Reads and edits go straight to the SpotFX app\'s own APIs (same process) — profiles, waveform, librosa analysis, palettes, setlists, and the live playhead over its WebSocket.',
    subsections: [
      {
        id: 'builder-palettes',
        title: 'Palettes & arming',
        entries: [
          {
            id: 'builder-palette-keys',
            title: 'Keyboard palettes',
            keywords: 'arm hotkey bank assign keys',
            body: [
              'A palette maps keyboard keys to events. Activate a palette, press a key to arm its event (Escape or clicking the key tile disarms; re-pressing the key keeps it armed), then right-click the timeline to place it. With the trigger dialog open, pressing a palette key assigns that event directly.',
            ],
            table: [
              ['1–0, Q–P, A–L, Z–M', 'Arm that key\'s event from the active palette (36 keys); re-pressing keeps it armed.'],
              ['Esc', 'Disarm the blend brush, then the armed key (after clearing any selection).'],
            ],
            kbd: true,
          },
          {
            id: 'builder-palette-card',
            title: 'Palette card gestures',
            keywords: 'edit long press double click activate',
            table: [
              ['Click palette', 'Activate / deactivate the palette.'],
              ['Long-press / double-click palette', 'Open the palette editor.'],
              ['Click a key tile', 'Arm/disarm that key (or select it in edit mode).'],
            ],
            kbd: false,
          },
        ],
      },
      {
        id: 'builder-placing',
        title: 'Placing & editing triggers',
        entries: [
          {
            id: 'builder-mouse',
            title: 'Canvas mouse actions',
            keywords: 'right click place drag move delete create circle triangle',
            table: [
              ['Right-click empty canvas', 'Place the armed event — time snaps to the nearest bass onset, intensity starts at the section\'s energy.'],
              ['Hold right button', 'Keep holding after placing to slide the intensity live until you release.'],
              ['Right-click a trigger', 'Reassign that trigger to the armed event — or, with the blend brush armed ([ / ]), paint/clear its Override Blend.'],
              ['Drag a circle ↕', 'Change intensity — snaps to the previous trigger\'s value and to 0.5. With a multi-selection, all selected circles shift together.'],
              ['Drag a triangle ↔', 'Move the trigger in time (20 ms grid, snaps to librosa markers by row).'],
              ['Drag off the canvas', 'Delete the trigger (pull it more than ~24 px out).'],
              ['Double-click', 'Edit the trigger under the cursor, or create a new one on empty canvas.'],
              ['Click circle / empty canvas', 'Select a trigger / clear the selection.'],
            ],
            kbd: false,
          },
          {
            id: 'builder-selection-keys',
            title: 'Selection & intensity keys',
            keywords: 'arrow nudge undo redo select all ripple enter numeric',
            table: [
              ['Ctrl+A', 'Select all triggers.'],
              ['Ctrl+Z / Ctrl+Shift+Z', 'Undo / redo.'],
              ['Left / Right', 'Select the previous / next trigger (Shift extends the selection).'],
              ['Up / Down', 'Nudge selected intensity ±0.01 (Shift = ±0.1).'],
              ['. then digits', 'Type an exact intensity: ".9" → 0.90, ".09" → 0.09.'],
              ['Enter', 'Copy the previous trigger\'s intensity, then advance — fast ripple editing.'],
              ['Esc', 'Clear the selection.'],
            ],
            kbd: true,
          },
          {
            id: 'builder-trigger-dialog',
            title: 'Trigger edit dialog',
            keywords: 'double click edit timestamp event labels intensity open new tab reference palette assign blend color group override drop scene group',
            body: [
              'Double-click a trigger (or empty canvas) to open it: timestamp (m:ss.t), event (recently used float to the top), filter labels, intensity, the Colors picker (scene-group color override — see below), and the Override Blend toggle.',
              'When the picked event is the fixed Drop, a Drop 🎯 picker appears: choose a Scene Group the drop falls back to for this trigger instead of the global drop group.',
              'The ↗ next to the event picker opens the chosen event\'s editor in the SpotFX app in a new tab, so the trigger you\'re editing stays put.',
            ],
          },
          {
            id: 'filter-labels',
            title: 'Label filter syntax',
            keywords: 'exclude not minus comma separator negative',
            body: [
              'Used wherever you filter by labels — e.g. the trigger dialog\'s color-set filter.',
            ],
            table: [
              ['chorus, big', 'Comma-separated labels: ALL listed labels must match.'],
              ['-quiet', 'Minus prefix excludes: matches anything NOT labeled "quiet".'],
              ['(blank)', 'No filtering — everything is eligible.'],
            ],
            kbd: false,
          },
          {
            id: 'override-blend',
            title: 'Override Blend',
            keywords: 'blend ramp stretch scale slow fast transition next trigger no action paint brush bracket',
            body: [
              'A trigger with Override Blend on rescales its event\'s ramps and delays — proportionally — so the last ramp completes exactly at the next enabled trigger (or at song end when none follows). Beat-timed steps stay on their beats — only their ramps scale. On both timelines the blended span is tinted in the event\'s color from the blend trigger to the trigger that ends it.',
              'On Charge and Lull triggers this stretches the phase build to exactly the gap to the NEXT trigger — the charge peaks the instant the lull fires, the lull finishes coiling the instant the drop hits. Drop never blends: it stays a snap.',
            ],
            table: [
              ['[', 'Arm the blend brush — right-click triggers to turn Override Blend ON. Re-press or Esc disarms.'],
              [']', 'Arm the eraser — right-click triggers to turn Override Blend OFF.'],
            ],
            kbd: true,
          },
          {
            id: 'trigger-color-override',
            title: 'Scene-group color override',
            keywords: 'color group override trigger scene group palette designate colors picker',
            body: [
              'The Colors picker in the trigger dialog overrides which Color Group the SpotFX scene machinery pulls its colors from — for that one trigger. Blank (the default) changes nothing; a deleted pick falls back to the normal choice instead of failing. The override lives on the trigger, so the same Scene Group can be blue at one trigger and gold at the next.',
            ],
          },
          {
            id: 'charge-lull-drop',
            title: 'Charge / Lull / Drop triggers',
            keywords: 'charge lull drop phase buildup build payoff snap fixed built-in',
            body: [
              'The three fixed events drive the build→hold→payoff arc on every phase-capable effect: fire Charge on a buildup, Lull at the peak hush, Drop at the impact. In SPECTRA these same fires reach the response engine as the charge/lull/drop classes and drive the identical vendored choreography — see "Response families" under the editor help for what each effect family does. Give Charge/Lull triggers Override Blend so the build stretches to the next trigger; Drop stays a snap and re-fires cleanly every time.',
              'Where each of these actually LANDS relative to the trigger\'s own timestamp isn\'t the same for all four — a Drop begins ON the mark, a plain Flare\'s payoff finishes there instead (so it starts early), and Charge/Lull ride the Override Blend stretch above. See "Lead-time alignment — three anchors, not one" for the full rule.',
            ],
          },
          {
            id: 'display-modes',
            title: 'Dark / Light mode (per trigger)',
            keywords: 'dark mode light mode display background moon sun',
            body: [
              'The Mode 🌗 select on a trigger feeds the SpotFX room-wide dark/light cascade: Dark forces backgrounds black on affected devices (hard-locked in the render pipeline), Light fills default light backgrounds, Default defers down the cascade. The full cascade and shielding live in the SpotFX app\'s Settings help.',
            ],
          },
        ],
      },
      {
        id: 'builder-navigation',
        title: 'Navigation & view',
        entries: [
          {
            id: 'builder-pan-zoom',
            title: 'Pan, zoom & follow',
            keywords: 'middle drag scroll window playhead resume auto',
            body: [
              'In Live mode, follow resumes automatically (zoomed to the sticky window size) when the page opens, when Live mode turns on, and when the song changes; within one song your pan/zoom choice sticks. In song-search mode there is no playhead, so the view stays where you leave it.',
            ],
            table: [
              ['Middle-drag', 'Pan the zoom window (drag right → window moves right). Panning switches follow off.'],
              ['` (backtick)', 'Toggle follow mode (auto-scroll with playback) vs. manual zoom.'],
              ['Ctrl+F', 'Also toggles follow mode.'],
              ['Full-song bar', 'Drag the zoom region\'s center to pan (switches follow off); drag its edges to resize — in follow mode edge drags adjust window size and look-ahead.'],
            ],
            kbd: false,
          },
          {
            id: 'builder-timeline-bar',
            title: 'Full-song timeline bar',
            keywords: 'overview marker minimap',
            table: [
              ['Drag a marker', 'Move that trigger in time; drag well above/below the bar to delete it.'],
              ['Click a marker', 'Edit the trigger.'],
              ['Double-click empty bar', 'Create a trigger there.'],
              ['Right-click', 'Place the armed event (on a marker: reassign it). With the blend brush armed, paint/clear Override Blend instead.'],
            ],
            kbd: false,
          },
          {
            id: 'builder-shape-controls',
            title: 'Waveform & layer controls',
            keywords: 'bands bass mid high total scale lightning intensity background source',
            table: [
              ['Click a band button', 'Toggle that frequency band\'s fill (Total / Bass / Mid / High).'],
              ['Right-click a band button', 'Toggle its rolling-average line.'],
              ['Long-press + drag ↕ a band button', 'Adjust that band\'s vertical scale (snaps back to 1.0).'],
              ['⚡ click', 'Toggle the intensity background layer.'],
              ['⚡ scroll wheel', 'Cycle intensity-background sources.'],
              ['⚡ hold', 'Open the source chooser.'],
            ],
            kbd: false,
          },
          {
            id: 'builder-misc',
            title: 'Other timeline controls',
            keywords: 'shift all offset resize canvas height live capture import setlist mode manual verify calibrating badge',
            table: [
              ['Shift all', 'Preview sliding every trigger by an offset, then apply. Double-click the slider to reset to 0.'],
              ['Offset badge ✎ / ✕', 'Write the shape offset by hand (saved as user-verified) or clear it back to unverified so auto-calibration relearns.'],
              ['🎯 auto-calibrating…', 'Shown in the Audio Shape header while xcorr auto-calibration is targeting this song\'s (still unverified) offset.'],
              ['⣀ handle below canvas', 'Drag to resize the canvas height.'],
              ['Modes', 'Song search picks any profile; Live mode follows Spotify playback; Auto Wait pauses placement until playback reaches the window.'],
            ],
            kbd: false,
          },
        ],
      },
      {
        id: 'ownership-resume',
        title: 'Restarts while SPECTRA owns',
        keywords: 'restart resume auto reactivate dark crash deploy',
        intro:
          'SPECTRA runs as her own process (spectra.service). If that process restarts while the record says she owns the room, the light stack reactivates itself at startup through the same guarded path the handover uses — no manual handover cycle. If the resume fails, the room stays dark-but-owned and the liveness endpoint answers 503 until the cause is fixed.',
      },
    ],
  },

  /* ── Timing & Debug (ported from spot-effects, same pages) ─────── */
  {
    id: 'timing-debug',
    title: 'Timing & Debug',
    keywords: 'sync diagnostics xcorr offset latency spot-effects ported',
    intro:
      'Read-only diagnostics ported from spot-effects\' own /timing and /debug pages, unchanged — both call spot-effects\' existing endpoints directly (same-origin), the same live xcorr/anchor machinery spot-effects has always run. Timing is a read-only xcorr/anchor dump for any song; Debug shows the live sync state for whatever is playing now. SPECTRA\'s own trigger clock consumes spot-effects\' shape_offset term (see "SPECTRA Triggers" below) — these pages are how you see the offset it\'s using.',
    entries: [
      {
        id: 'timing-lock-history',
        title: 'Lock history',
        keywords: 'last 10 songs grade time to lock offset delta search recent plays',
        body: [
          'The panel at the top of the Timing page lists the last 10 distinct songs\' lock outcomes: how long into the song the hard lock landed ("time to lock"), the final offset, how far it had to move from the previous baseline (Δ needed), the lock quality Q, and a letter grade. Click any row to load that song\'s full timing dump below; type in the search box to switch to a full-history search (every stored play matching title, artist, or uri).',
          'Grades: the base comes from the play\'s best Q (A ≥ 0.9, B ≥ 0.8, C ≥ 0.7, D ≥ 0.6, F below). A play that finished its windows without a hard lock drops one notch, and so does a hard lock that landed more than 30 s into the song (the song ran that long on the cold-start baseline).',
        ],
      },
      {
        id: 'timing-pipeline',
        title: 'Trigger fire-time pipeline',
        keywords: 'shape offset buffer rtt effective audio latency',
        body: [
          'This box shows spot-effects\' own fire-time pipeline: Spotify song position + shape_offset (from xcorr) + LedFX trigger buffer + LedFX RTT; audio latency shifts where the playhead is drawn, not when triggers fire. SPECTRA\'s own trigger clock only ever applies the shape_offset term (its LedFX buffer/RTT don\'t apply — SPECTRA doesn\'t write through spot-effects\' LedFX HTTP gate) — see the effective_position_ms note under "SPECTRA Triggers".',
        ],
      },
      {
        id: 'debug-analyzed-override',
        title: 'Analyzed override',
        keywords: 'force analyzed triggerless test training profile stored manual triggers',
        body: [
          'The "Analyzed override" toggle (track header) makes the current song ignore its stored triggers and run spot-effects\' analyzed-triggerless pipeline instead — useful for testing a tuned training profile against songs that already have hand-built profiles. This affects spot-effects\' own legacy trigger world, not SPECTRA\'s triggers.',
        ],
      },
      {
        id: 'debug-lock',
        title: 'Lock badge & live nudge',
        keywords: 'locked suspect recovering pearson confidence buffer nudge',
        body: [
          'The lock badge shows the matcher\'s state (LOCKED / SUSPECT / RECOVERING / IDLE / NO LOCK) with the rolling Pearson r — its live confidence in the current alignment.',
        ],
        table: [
          ['[ / ]', 'Nudge spot-effects\' LedFX trigger buffer −50 / +50 ms live.'],
        ],
        kbd: true,
      },
      {
        id: 'debug-shape-canvas',
        title: 'Reading the shape canvas',
        keywords: 'saved live capture mismatch magenta centerline legend',
        body: [
          'The saved shape draws upward from the centerline; live capture (25 ms bins) draws downward, so a good lock looks like a mirror image. Brackets mark the xcorr windows; magenta spikes are confirmed mismatches. Middle-drag pans; the timeline handles zoom. Follow resumes automatically when the page opens or the song changes.',
          'Perception trim is a per-track manual offset layered on top of the xcorr result — negative fires lighting earlier, positive later.',
        ],
      },
      {
        id: 'debug-diff-canvas',
        title: 'Reading the diff / rolling-R canvas',
        keywords: 'z-score matcher view correlator gain volume blue orange',
        body: [
          'This is the matcher\'s view: both signals squared, binned to 25 ms, and z-scored, so gain/volume differences cancel. Blue above center = live louder than expected; orange below = saved louder. The colored line is the rolling r (lock confidence): green ≥ 0.5, amber ≥ 0.2, red below — gaps mean the span was too quiet to testify. Sustained excursions or time-skewed mirror pairs indicate misalignment.',
        ],
      },
    ],
  },

  {
    id: 'spectra-triggers',
    title: 'SPECTRA Triggers (the mid-song clock)',
    keywords: 'trigger authoring keystone mid-song scene change fire response colour set place drag edit delete generate seed provenance',
    intro:
      'Scene changes are driven by triggers — ordinary, editable moments placed on the same timeline as the legacy Builder\'s, living in the "SPECTRA Triggers" card just below it. Every song always gets a scene change on its own transition (in and out) automatically — no authoring needed; adding, moving, or deleting triggers is how you hand-tune it further, one moment at a time. A song with no stored triggers yet gets seeded automatically the first time it plays, from its own analysis; ⟳ Generate re-runs the same seeding on demand — see "Generating from analysis" below. Which of these actually fire room-wide is the room controls bar\'s "Scene changes" setting (see its help entry) — a song that has never been hand-tuned still gets its automatic transitions regardless of that setting. This is a separate authoring surface from the legacy trigger dialog above it — the two worlds coexist, and a SPECTRA trigger only ever fires SPECTRA-native things.',
    entries: [
      {
        id: 'spectra-trigger-actions',
        title: 'The four action kinds',
        keywords: 'fire scene fire response fire update select color set intensity class',
        table: [
          ['Fire scene', 'Fires a scene by name at a chosen intensity (⚡), optionally wearing a specific colour set instead of the room\'s active one — through the same choke point the sequencer\'s own picks use.'],
          ['Fire response', 'Fires a response class (flare / charge / lull / drop) at a chosen intensity — the same phase drive and band selection a bridge-classified charge/lull/drop/flare already drives.'],
          ['Fire update', 'Fires the ACTIVE scene\'s own UPDATE content directly, at a chosen intensity — no target to pick, and it bypasses band selection entirely (unlike Fire response). A major change WITHIN the current scene: bigger than a flare, overrides the drift, lands somewhere new on a ramp-in. If the active scene has no UPDATE authored, this is a silent no-op.'],
          ['Select colour set', 'Moves the room to a named colour set directly — the same manual-apply surface as the Scenes page\'s colour controls.'],
        ],
        kbd: false,
      },
      {
        id: 'spectra-trigger-colours',
        title: 'Marker colours',
        keywords: 'color colour code charge lull drop flare regular violet amber teal red blue pink gold',
        body: [
          'Each marker on the trigger bar is coloured by what it fires: violet for Fire scene, teal for Select colour set, red for Fire update. A Fire response marker is coloured by its own class instead of one flat amber — a plain flare stays amber (the "regular" trigger colour), while Charge (gold), Lull (sky blue), and Drop (magenta) each get their own colour so they read apart from a flare and from each other at a glance while a sequence is running. The edit dialog\'s Class picker shows the same colour next to its dropdown.',
        ],
      },
      {
        id: 'spectra-trigger-sync',
        title: 'When a trigger actually fires (xcorr sync)',
        keywords: 'xcorr sync shape offset lag audio latency effective position timing',
        body: [
          'The clock this page ticks against isn\'t the raw Spotify-reported song position — it\'s that position corrected by spot-effects\' own live xcorr audio-alignment offset (shape_offset_ms), the same correction spot-effects\' own trigger engine has always applied before comparing against a trigger\'s timestamp. Without it a migrated trigger fires late or early by however far that song\'s own offset runs (seconds, not milliseconds, for some songs) — see the Timing page\'s "Trigger fire-time pipeline" to see the live number for whatever\'s playing.',
        ],
      },
      {
        id: 'spectra-trigger-lead-time-alignment',
        title: 'Lead-time alignment — three anchors, not one',
        keywords: 'lead time alignment anchor early start middle end momentary flare scene transition drop explosion timing begins finishes midpoint',
        body: [
          'A trigger\'s own stored timestamp is the moment on the clock — but what actually LANDS there depends on which kind of change is firing, because three different kinds of change anchor to the mark in three different places. His settled rule, 2026-08-20:',
          '• A MOMENTARY FLARE anchors its first switch\'s END to the mark — the switch fires early enough that it finishes exactly on the trigger, then holds, then flips back afterward. Starts before the mark, on purpose.',
          '• A SCENE TRANSITION (Fire scene) anchors its MIDDLE to the mark — a registered phased effect\'s own payoff point, or the plain half-way point of an ordinary crossfade, lands on the trigger. Also starts before the mark, on purpose.',
          '• A DROP/EXPLOSION anchors its START to the mark — the explosion begins ON the trigger, never before it. This is the newest of the three, added after Black Hole was tried and then withdrawn as a "the timing feels right" reference for drops specifically (his words: "an explosion begins on the trigger mark rather than before it").',
          'None of the three is more "correct" than the others — a flare\'s payoff and a scene\'s midpoint are SUPPOSED to start early; only a drop is supposed to start exactly on time. If a drop still looks early after the fire itself lands on the mark, the cause isn\'t this alignment — it\'s something inside the effect\'s own choreography (what it visibly does as its phase ramps from 0 to 1), a separate, ongoing question from where the trigger fires.',
        ],
      },
      {
        id: 'spectra-trigger-authoring',
        title: 'Placing & editing',
        keywords: 'double click drag move delete create',
        table: [
          ['Double-click empty strip', 'Create a trigger at that moment.'],
          ['+ Add Trigger', 'Create a trigger at the current playhead.'],
          ['Click a marker', 'Edit that trigger — timestamp, action, and its fields.'],
          ['Drag a marker ↔', 'Move the trigger in time (20 ms grid).'],
          ['Drag a marker out of the strip', 'Delete it.'],
          ['Hover a marker', 'Shows the action summary (scene/response/colour set + intensity).'],
        ],
        kbd: false,
      },
      {
        id: 'spectra-trigger-recents',
        title: 'Quick-pick recent actions',
        keywords: 'recent quick pick common palette',
        body: [
          'The trigger dialog remembers the last few actions you saved and offers them as one-click buttons — a minimal stand-in for the legacy Builder\'s full keyboard-palette system (a later stage). Picking a recent action carries the intensity you already had dialed in.',
        ],
      },
      {
        id: 'spectra-trigger-enabled',
        title: 'Enabled toggle',
        keywords: 'disarm mute disable',
        body: [
          'Unchecking Enabled disarms a trigger without deleting it — its placement and action stay saved, but the clock skips it. Delete removes it outright.',
        ],
      },
      {
        id: 'spectra-trigger-generate',
        title: 'Generating from analysis',
        keywords: 'generate seed regenerate provenance authored generated kernel scene picks analysis section boundary',
        body: [
          'A song is also seeded automatically the first time it plays and has no stored triggers yet — you don\'t have to open this page and press ⟳ Generate yourself for the room to work; the same generation runs in the background the moment the song starts, and it degrades honestly (no fake triggers) when there\'s no analysis for it yet. ⟳ Generate here is for re-running it on demand — after a re-analysis, or just to check what a song seeded.',
          '⟳ Generate reads this song\'s librosa analysis and seeds a "Fire scene" trigger at every structural section boundary (drops/section changes) it finds, with intensity taken from that section\'s own energy (renormalized per song, quietest → loudest). It\'s deterministic and idempotent — running it again updates or removes seeded triggers to match the current analysis without ever touching one you\'ve placed or edited by hand.',
          'A seeded trigger shows a dashed outline on the strip and its hover summary starts with "Seeded —". It\'s otherwise an ordinary trigger: move it, edit it, or delete it exactly like one you placed yourself. The moment you save any change to a seeded trigger — even just nudging it — it becomes yours: a later ⟳ Generate (automatic or manual) will never move, edit, or remove it again, and instead seeds a fresh trigger for that same analysis moment alongside your edit.',
          'A generated trigger\'s Scene field starts blank ("— sequencer picks at fire time —") rather than a fixed scene: SPECTRA leaves the WHICH-scene choice to the sequencer\'s own selection kernel (curve × genre × affinity) at the moment it fires, using the trigger\'s own intensity. Pick a scene explicitly in the dialog to pin it instead, same as any hand-placed trigger.',
          'The room controls bar\'s "Scene changes" setting decides which triggers actually fire room-wide (see its help entry): "Transitions only" skips GENERATED triggers entirely; "Transitions + analysed" and "Everything" both fire them; "My triggers only" fires them ONLY on a song where you haven\'t placed a hand-authored trigger of your own (a song you have authored on runs your triggers exclusively instead). Generation and storage happen regardless of the setting — seeded triggers stay visible and editable on the timeline either way.',
        ],
      },
    ],
  },
  {
    id: 'feedback-page',
    title: 'Feedback session (mark-then-nudge)',
    keywords: 'feedback mark nudge queue send batch note timestamp show session review',
    intro:
      'A phone-first page for giving timestamped feedback DURING a played show. You react to something, tap Mark, correct the moment with the nudge buttons, then type what happened — all before it ever leaves your phone. Nothing sends until you press Send.',
    entries: [
      {
        id: 'feedback-mark-then-nudge',
        title: 'Mark, then nudge',
        keywords: 'mark button position timestamp correct tenth flash live',
        body: [
          'The "Now:" line tracks the actual song position live, down to a tenth of a second — it interpolates between polls rather than showing the raw (up to 3s stale) value the app last pulled from Spotify, and freezes rather than drifting whenever the song is paused.',
          '● Mark captures the moment: wall time, the current song, and the song position, read from the live music bridge. Marking is instant — it never waits on the network, and never blocks a second Mark while an earlier note is half-typed. The button flashes "Marked!" so a tap registers without needing to look at the screen.',
          'You react a beat after the moment actually happened, so use the -5s/-1s/+1s/+5s buttons on the mark to correct the captured position BEFORE typing a note — nudging only moves the song position, never the wall-clock order the mark was made in. A nudge briefly highlights the position so you can see the correction land.',
        ],
      },
      {
        id: 'feedback-queue',
        title: 'The queue',
        keywords: 'batch local reload survive correct delete reorder colour bar song',
        body: [
          'Every mark lands in a queue that lives in this browser (localStorage) — it survives a page reload, so a mid-show refresh loses nothing. Edit a note, nudge a position, delete an entry, or reorder with ▲/▼ at any point before sending.',
          'Each entry has a colour bar down its left edge, keyed to its song — on a long multi-song queue it lets you scan by song at a glance instead of reading truncated track IDs.',
          'Send All leaves the whole queue in ONE request — never a per-mark round-trip during the show. If Send fails (bad signal, etc.), the queue stays exactly as it was; just tap Send again.',
        ],
      },
    ],
  },
  {
    id: 'review-page',
    title: 'Review (notes against the reconstructed show)',
    keywords: 'review reconstruct show log playback timeline pin jump session desk',
    intro:
      'The desk-review counterpart to the Feedback page: pick a sent feedback session and a song, and see your notes pinned against everything that actually fired during that stretch of the show — scenes, responses, colour sets, and trigger fires, in song-position order. Best used at a desk after the show, but stays usable from a phone.',
    entries: [
      {
        id: 'review-session-song',
        title: 'Picking a session and song',
        keywords: 'session picker chip song batch send',
        body: [
          'A "session" is one Send press on the Feedback page — everything queued and sent together. Pick a session from the chip row, then pick a song from the ones you took notes on in that session; the review is always scoped to one song within one session.',
        ],
      },
      {
        id: 'review-lane-and-list',
        title: 'The lane bar and the list',
        keywords: 'lane bar marker tick pin vertical list fill progress time swatch',
        table: [
          ['Thin tick', 'A show-log event — colour-coded by kind (scene / response / colour set / trigger); the same colour swatch shows on its row in the list below.'],
          ['Tall pin', 'One of your notes, pinned at the song position it was nudged to.'],
          ['Filled portion of the bar', 'How far into the song the reconstruction reaches, with start/end time labels beneath.'],
          ['Click a marker or row', 'Selects it and opens the detail panel below.'],
          ['Hover a marker', 'Shows a quick summary without selecting it.'],
        ],
        kbd: false,
        body: [
          'The lane bar mirrors the SPECTRA trigger strip elsewhere in the app, but read-only — nothing here can be dragged or edited. The list below it shows the same merged timeline vertically, which is easier to scan on a narrow screen.',
        ],
      },
      {
        id: 'review-note-detail',
        title: 'Note detail + jumping between notes',
        keywords: 'context surrounding prev next jump',
        body: [
          'Selecting a note shows its text alongside everything else that happened within ±15s of it — the surrounding show, not just the note in isolation. Prev/Next note steps straight to your other notes in this song without hunting on the lane bar.',
        ],
      },
      {
        id: 'sonic-token-usage',
        title: 'Sonic token usage',
        keywords: 'sonic tokens usage cost quota subscription api credits day week query last budget',
        body: [
          'Three real numbers, at the top of this page: the last Sonic query, this fixed day, and this fixed week. Every figure is captured directly off the model runtime\'s own response for that call — never estimated from word/character counts. A call the runtime genuinely didn\'t report usage for contributes nothing (no fabricated zero); "No Sonic calls recorded yet" means exactly that, not "zero tokens used."',
          'Day and week are FIXED periods anchored to Monday 10:00 p.m. Eastern (America/New_York, DST-aware) — not a rolling last-24h/last-7d window. That boundary is almost certainly aligned to his subscription\'s own quota reset, so "what this period has used" doubles as a rough read on how much is left before the next reset — the number that matters after a quota exhausted without warning. A rolling window would only ever show how much has been spent, and resets on the clock rather than the quota, which can hide a heavy session that just happened.',
          'The "subscription"/"API credits" badge on the last query shows which backend answered it — Sonic can run on either (spectra/services/settings_agent.py or settings_agent_cli.py), and both are tracked in the same totals.',
        ],
      },
    ],
  },
  {
    id: 'settings-console',
    title: 'Sonic — talk to it instead of hunting a form',
    keywords: 'settings console sonic agent chat voice dictation mic microphone brightness ambient transition scene change undo change log talk to the software',
    intro:
      'Type (or speak) what you want changed — "turn brightness down to 40%", "turn ambient on and make it warm white" — and Sonic, a small model, changes it for you. The "Current settings" and "Recent changes" cards below the chat are read-only: they show what the settings are and what changed, but nothing on this page except the chat itself can change a value.',
    entries: [
      {
        id: 'settings-console-scope',
        title: 'What it can change here',
        keywords: 'brightness ambient colour transition scene change mode scope allowlist force scene',
        body: [
          'Five room-wide settings, on purpose, not everything the app has: room brightness, the default scene-entry transition time, ambient mode (off / on during music / auto-return, + colour), and the scene-change tier (transitions only / transitions + analysed / my triggers only / everything). Each one has a declared legal range or set of choices, enforced by the server — an out-of-range or nonsense request is rejected and Sonic explains the legal range instead of guessing.',
          "Force Scene isn't in scope here — it names a scene by id, which fits the room-controls bar's picker better than a spoken request.",
          'Anything inside a scene itself — a flare, an effect parameter, a scene\'s own shape or edge count — is out of scope too; that lives in the scene/timeline editor. Tested against a real example: asking it not to let a scene\'s flares change an edge count got a plain "I have no tool to touch that," not a made-up yes.',
        ],
      },
      {
        id: 'sonic-scenes',
        title: 'Sonic on the Scenes page: flares, scene settings, new scenes, and overwrite',
        keywords: 'sonic scenes page flare kind flares chat popup pop-up create scene entry ramp phase blend choreography colour journey pace overwrite edit',
        body: [
          'The Scenes page has its own floating 💬 button (bottom-right) that opens the same Sonic chat, scoped to a second domain: flares and scenes. It can create a new, empty scene by name (always a brand-new scene — it can never overwrite one of your existing scenes just by creating, even given the exact same name); change a scene\'s own scalar settings (entry blend time, charge/lull phase ramps, phase-choreography timing, colour-journey pace, whether it accepts every colour set); create, update, or remove a scene\'s NAMED flare kinds (the drift-jump / momentary / permanent building blocks a scene\'s charge/lull/flare/drop bands select and scale); and — the newer, more powerful one — wholesale OVERWRITE an existing scene\'s name/labels/settings/flare kinds in one shot.',
          'Say which scene you mean by name — Sonic looks it up rather than needing an id. Every change is re-validated server-side exactly like the settings-only chat: an illegal value, an unknown flare-kind field, or removing a flare kind still referenced by a band is rejected with the legal range or the reason, never silently guessed at.',
          "Device/effect editing (the Initial Set tab) isn't in scope for Sonic — that stays a deliberately visual, drag-and-tune editor, even for overwrite.",
        ],
      },
      {
        id: 'sonic-scene-backups',
        title: 'Backups, undo, and preview for scene edits',
        keywords: 'backup verify undo restore genesis preview check-in overwrite safety net',
        body: [
          'Before Sonic changes ANYTHING on a scene you already have, it backs up that scene\'s current state first — and confirms the backup actually landed before touching your scene, not just that the write call didn\'t error. If that confirmation fails, the edit is refused and nothing about your scene changes.',
          'Every scene keeps its last 10 edits as restore points, plus one PERMANENT snapshot of exactly how it looked the very first time Sonic ever touched it — that one is never deleted, no matter how many edits pile up after it, so there\'s always a guaranteed way back to where you started.',
          'After a change, Sonic shows you a preview — a plain readout of what actually changed, generated by comparing the saved scene to its backup, not by Sonic describing itself from memory. It\'s shown in its own dashed box in the chat so you can tell it apart from Sonic\'s own reply at a glance.',
          'The "↺ Undo last" button at the top of the Sonic popover undoes the single most recent scene edit Sonic made, whichever scene it touched — press it again to step back one more. It works instantly, with no chat needed. To go back further than one step, or to restore a scene to exactly how it was before Sonic ever touched it, ask Sonic to restore a specific backup (or "restore the original") from the chat.',
        ],
      },
      {
        id: 'settings-console-voice',
        title: 'Voice: the mic button',
        keywords: 'microphone record dictate speech transcribe',
        body: [
          'Tap 🎤 to record, tap again (■) to stop — the clip is sent to SPECTRA\'s own backend for transcription and the result lands in the text box for you to check before sending, not sent automatically. If transcription isn\'t wired up yet you\'ll see a plain message saying so; typed text always works regardless. Both the Settings page chat and the Scenes page popover work the same way.',
        ],
      },
      {
        id: 'settings-console-changes',
        title: 'What changed, and Undo',
        keywords: 'change log history undo revert mis-transcription mistake wrong',
        body: [
          'Every settings change Sonic makes — and every undo — appears in "Recent changes" with its old and new value, so a misheard word is easy to spot. "Undo last" reverts the most recent settings change (voice or typed) back to its previous value; undoing is itself a logged change, not a deletion, so the history stays honest. Scene/flare changes from the Scenes page popover have their own separate history and their own "↺ Undo last" button (see "Backups, undo, and preview for scene edits" above) — the two undo buttons are independent, one per domain.',
        ],
      },
    ],
  },
];
