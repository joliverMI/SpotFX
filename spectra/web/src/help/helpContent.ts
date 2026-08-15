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
        title: 'Toolbar: Save, Duplicate, Test Fire, Fire, Delete',
        keywords: 'test fire dry run real fire intensity slider no confirm consent',
        body: [
          'The intensity slider picks the axis value a fire resolves against, so ⚡ scenes can be previewed anywhere on the axis. Test Fire compiles at that intensity WITHOUT touching devices and shows the resolved bindings, dice rolls, and per-virtual writes. Fire (live) sends the same writes to LedFX — it exists for the owner; use Test Fire for checking work.',
          'Firing asks for NO confirmation — the press is the consent; it fires the single scene you chose and are looking at. This is a deliberate asymmetry: the global colour-set opt-out (Colour Sets tab) DOES confirm, because that one silently changes every scene in the house.',
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
          'Bands SELECT AND SCALE: each band lists which kinds fire in its intensity window plus a ×scale multiplying their strength (×1 = exactly as declared, ×0 = inert; a dice re-roll has no magnitude, so scale is inert on it; on a colour jump it steers the selector). Kind declarations — including a param\'s target mode and a momentary kind\'s hold — are agent-adjustable — tell the agent to add, rename, or retune one; attaching to bands and scaling is done right on the band rows.',
          'Everything authored before kinds existed — band patches, gains, re-roll and colour-jump flags — loads unchanged as auto-named kinds ("Dice Re-roll", "Colour Jump", "Flare patch …", "Flare gain …"), every param landing in ABSOLUTE mode at the fixed 250 ms hold — today\'s behaviour, unchanged.',
        ],
      },
      {
        id: 'tab-flares',
        title: 'Flares tab — the band strip',
        keywords: 'flare bands kind scale response intensity strip attach chip',
        body: [
          'Bands over the intensity axis decide the response when a flare fires. Drag a band\'s edges to move its window, drag the dot to set the whole band\'s ×scale, double-click to remove, click an empty gap to add. On each band row, click a kind chip to attach or detach that kind, and set its individual ×scale inline — see "Named flare kinds" for what the three types do.',
          'Since S2 these bands EXECUTE: any ordinary trigger fire from spot-effects is a flare at that fire\'s intensity, and the band containing it fires its kinds — drift-jumps, momentary spikes that return, permanent moves that carry. A colour jump ramps its new colours in over a length that shrinks as intensity grows: gentle flares ease in (~2.5 s), full-scale flares land hard (~0.15 s).',
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
          'SPECTRA\'s equivalent of the legacy Override Blend flag (see "Override Blend" under the ported timeline help for the original). A read-only study of the live library (269 legacy blend triggers) found real usage is overwhelmingly Charge/Lull phase builds (265 of 269) with a thin slice on scene selection — so the equivalent has two facets instead of one dynamic rescale.',
          'Charge/Lull ramp override: a scene may set its own charge and/or lull build ramp (phase_blend.charge_ramp_ms / lull_ramp_ms) instead of the fixed 4000 ms / 2500 ms default — drop never overrides, it always stays the 400 ms snap. Legacy dynamically stretched the ramp to land exactly at the NEXT trigger; SPECTRA\'s S2 engine reacts to bridge events with no forward schedule of what fires next (that needs per-song trigger authoring, a separate large gap), so this authors the buildable half: a configurable ramp per scene rather than a dynamically computed one.',
          'Scene-entry blend: a scene\'s entry_ramp_ms (0 by default = instant) blends its compiled writes in over that many ms when it fires live, hue-arc for colour — the same tween shape flare colour jumps use, and the mechanism the colour journey\'s "no snap" custody transfer has always promised. It only blends params on a virtual whose already-active effect matches the entry; a genuine effect-type switch still recreates instantly (a boundary of the underlying render engine, not new here).',
          'Both are agent-tellable — no sliders, same interface-split rule as the rest of this tab.',
        ],
      },
      {
        id: 'tab-sequencing',
        title: 'Sequencing tab',
        keywords: 'sequencer curve likelihood dwell affinity genre profile inline detach promote share',
        body: [
          'As shipped in the sequencer increment: the scene\'s likelihood curve (named profile / inline / flat / not sequenced) is graphical; dwell weight, genre multipliers, and affinity render read-only — adjust them by telling the agent. The status strip shows the engine\'s state. The S2 bridge now feeds it song transitions, section-energy intensity, genre buckets, and deferrals — but the sequencer stays dark until its own enabled switch is flipped (ask the agent).',
          'A curve is either a named PROFILE (pulled from the dropdown — a shared shape; editing it retunes every scene using it, shown by "shared by N scenes" and the "changes every scene using it" caption) or an INLINE one-off (this scene only, no name, nothing added to the profile library). Pick "Inline one-off…" to save a curve directly to this scene without creating a profile.',
          'Editing a scene attached to a shared profile? Click "Detach — edit just this scene" first to copy the curve into this scene\'s own inline curve before dragging — otherwise the edit retunes every scene sharing that profile. Editing an inline curve you now want other scenes to reuse? Click "⇪ Promote to shared profile…" to name it and turn it into a profile (this scene re-attaches to the new profile by reference). Both directions are cheap — promoting an inline curve or detaching a profile never touches other scenes\' curves.',
          'This curve is also the equivalent of the legacy Energy Gate / Energy Tilt on random options — see "Energy gates/tilt → curves" for the equivalence.',
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
        title: 'Room controls — brightness, ambient, transition pace, scene changes, Force Scene',
        keywords: 'brightness multiplier dim undim ambient color transition pace global room bar dimmer midsong mid-song trigger fallback scene change mode transitions analysed full settings model force scene hold pin catch-up catchup ease release ramp snap read-back readback confirm confirmed unconfirmed partial straggler retry rate limit zigbee bulb name',
        body: [
          'The compact strip above the release button, on every page — SPECTRA-native equivalents of legacy room-wide actions (spectra-kept-equivalents), plus the scene-change settings model and Force Scene.',
          'Brightness: a 0–100% room dimmer (legacy Brightness Multiplier action). It scales brightness/background_brightness UNIFORMLY at the write seams — every drift glide, every surge jump, and every scene fire\'s output — never the authored scene values or the engine\'s own carried baseline, so turning it back to 100% always restores exactly what was authored.',
          'Ambient: on/off + a colour swatch — click it to open LedFX\'s own colour picker (see "The colour picker"), solid only (a Hue entertainment stream only ever takes one colour). Legacy ledfx_ambient / ledfx_ambient_color actions. A real takeover: every live Hue device in the room freezes its entertainment stream (so the bridge falls back to normal REST control) and holds at the chosen colour, full brightness, over a short fade. Ambient then READS EVERY LIGHT BACK from the bridge and only counts it as held once its reported state actually matches — a bridge accepting a write (2xx) doesn\'t mean the physical bulb took it (zigbee can silently drop a command under a burst of writes even though the bridge said OK). A straggler is retried a bounded number of times, spaced apart, before being given up on. Non-Hue devices (WLED etc.) keep running their normal reactive show, same as the legacy behaviour this ports. Turning it off is a two-step ease, not a snap: a brief dim fade, then a second ramp (about 8 seconds) that eases the held bulb toward whatever the room\'s live effect is actually showing right now, before finally releasing back to the stream — matching how the legacy app always eased back into the show instead of cutting to it. If SPECTRA isn\'t currently driving the lights, or there\'s no live Hue device in the room, a small grey "ambient: dark" / "ambient: no-hue-devices" badge shows next to the swatch — the switch still saves, but nothing changed live. A red "ambient: failed" badge means SPECTRA tried and every Hue device rejected it (bridge unreachable, etc.) — the switch saved, but the room may not actually match it; check the bridge. A red "ambient: N/total held — <names>" badge means most of the room took the colour but one or more bulbs, NAMED by their own bridge name, did not confirm it even after retries — check those bulbs (power, zigbee range) directly. Dinner Party (the other legacy room-MODES behaviour) is still a separate, later build.',
          'Transition: the room\'s default entry-blend ramp in ms (legacy ledfx_global_transition action) — the fallback a scene fire uses when that scene doesn\'t author its own entry ramp (Scenes → Phase Choreography → Override Blend, entry_ramp_ms). 0 (the default) keeps every undeclared scene an instant switch, unchanged from today.',
          'Scene changes: three understandable, additive ticks for what drives scene changes room-wide. "Transitions only" — a scene change on every song transition, nothing else. "+ Analysed" — transitions plus the analysed mid-song triggers "⟳ Generate" seeds (see the SPECTRA Triggers help). "+ My triggers" (default) — everything: transitions, analysed mid-song triggers, your own hand-placed triggers, AND response-engine flares (charge/lull/drop/flare reactions — a scene\'s own tuned material). Nothing is deleted by moving between ticks — a lower tick just skips firing the higher tiers\' material room-wide.',
        ],
      },
      {
        id: 'live-energy',
        title: 'Live Energy — the number driving scene picks and flares',
        keywords: 'energy intensity section bar top always visible live meter bridge librosa quiet loud',
        body: [
          'The ⚡ Energy meter, on every page, next to the room controls — the shared top-bar strip\'s first widget (a future live device preview joins it here later). It shows the SAME number the engine\'s automatic decisions read, not a lookalike recomputed for display: raw librosa section energy at the current playback position (0.00 = the quietest section this song, 1.00 = the loudest), fed by the read-only bridge (see "The read-only bridge"). That one value is wired directly into the drift conductor\'s pace, the sequencer\'s default scene pick, and automatic transition fires — everything the room does on its own without a hand-placed trigger or authored intensity.',
          'Shows "—" when there\'s no live number to show: the bridge is down, nothing is playing, or this song has no section analysis yet. In every one of those cases the engine itself falls back to a 0.5 neutral internally — the meter doesn\'t fake that number, it tells you why there isn\'t one.',
          'A hand-placed trigger or a mid-song "⟳ Generate" pick can carry its OWN authored/baked intensity instead of this live value at the moment it fires — this meter always shows the live bridge signal, which is what drives everything that ISN\'T an explicitly authored intensity.',
        ],
      },
      {
        id: 'force-scene',
        title: 'Force Scene — hold one scene',
        keywords: 'force scene hold pin lock stuck stay same scene forever pick redirect reassert',
        body: [
          'Ported from the legacy Now Playing "Force Scene" control, same behaviour: turn it on and pick a scene, and every scene the room would otherwise pick automatically — a sequencer roll, a trigger firing, or the automatic change on a song transition — fires that scene instead. It\'s a redirect, not a pause: the room keeps changing on the usual cadence, it just always lands on the scene you pinned, at the intensity/colours that pick would normally have used.',
          'It does NOT touch a manual Fire from the Scenes page editor — that\'s an explicit single fire, not the system picking a scene, so it always fires exactly the scene you pressed Fire on.',
          'Turn Force Scene off to let the sequencer/triggers pick freely again — nothing about the scene you were holding is changed or deleted, it just stops being reasserted.',
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
          'The room controls bar\'s "Scene changes" setting decides which triggers actually fire room-wide (see its help entry): "Transitions only" and "+ Analysed" both skip GENERATED triggers unless you\'ve picked "+ Analysed" or higher, and only "+ My triggers" fires hand-placed ones. Generation and storage happen regardless of the setting — seeded triggers stay visible and editable on the timeline either way.',
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
    ],
  },
  {
    id: 'settings-console',
    title: 'Settings console — talk to it instead of hunting a form',
    keywords: 'settings console agent chat voice dictation mic microphone brightness ambient transition scene change undo change log talk to the software',
    intro:
      'Type (or speak) what you want changed — "turn brightness down to 40%", "turn ambient on and make it warm white" — and a small model changes it for you. The "Current settings" and "Recent changes" cards below the chat are read-only: they show what the settings are and what changed, but nothing on this page except the chat itself can change a value.',
    entries: [
      {
        id: 'settings-console-scope',
        title: 'What it can change',
        keywords: 'brightness ambient colour transition scene change mode scope allowlist force scene',
        body: [
          'Five settings, on purpose, not everything the app has: room brightness, the default scene-entry transition time, ambient mode (on/off + colour), and the scene-change tier (transitions only / + analysed / + your triggers). Each one has a declared legal range or set of choices, enforced by the server — an out-of-range or nonsense request is rejected and the agent explains the legal range instead of guessing.',
          "Force Scene isn't in scope here — it names a scene by id, which fits the room-controls bar's picker better than a spoken request.",
        ],
      },
      {
        id: 'settings-console-voice',
        title: 'Voice: the mic button',
        keywords: 'microphone record dictate speech transcribe',
        body: [
          'Tap 🎤 to record, tap again (■) to stop — the clip is sent to SPECTRA\'s own backend for transcription and the result lands in the text box for you to check before sending, not sent automatically. If transcription isn\'t wired up yet you\'ll see a plain message saying so; typed text always works regardless.',
        ],
      },
      {
        id: 'settings-console-changes',
        title: 'What changed, and Undo',
        keywords: 'change log history undo revert mis-transcription mistake wrong',
        body: [
          'Every change the agent makes — and every undo — appears in "Recent changes" with its old and new value, so a misheard word is easy to spot. "Undo last" reverts the most recent change (voice or typed) back to its previous value; undoing is itself a logged change, not a deletion, so the history stays honest.',
        ],
      },
    ],
  },
];
