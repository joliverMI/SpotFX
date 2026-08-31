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
 *      One id can also be referenced from OUTSIDE the .tsx sources: an
 *      effect param in `config/effect_params.json` may carry a
 *      `"help_topic"`, which InitialSetTab renders as a HelpLink on that
 *      param's row (e.g. `radial-base-rotation`). Grep the registry too
 *      before calling such a topic orphaned or renaming its id.
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
        id: 'power-button',
        title: 'The ⏻ power button — one control for every enable/disable',
        keywords: 'power button green dim lit on off enable disable toggle switch selection bar list row flare colour set scene',
        body: [
          'Everything in SPECTRA that can be switched off uses the SAME control: a round ⏻ power button, LIT GREEN when the thing is on and DIM when it is off. One tap flips it, immediately — there is no confirm and no second step.',
          'WHERE IT IS. On the Scenes page: on every row of the scene list, on the phone\'s scene selector bar, and on the open scene\'s own toolbar. On the Colour Sets page: on every row of the tiered Sets & Groups list (Groups and their members alike) and on the open card\'s toolbar. On the Flares and Charges/Lulls/Drops tabs: on every flare kind card, and on every kind inside a lane in the rack below the bands.',
          'STRAIGHT FROM THE LIST. Pressing the power button on a scene or colour-set LIST ROW takes effect at once — it saves by itself, so you never have to open the item first. The one exception: if that item already has other unsaved edits pending, the flip lands in your draft alongside them and the toast says so, rather than committing half-finished work you had not decided to save yet. A flare kind\'s power button is a scene edit like any other field — it lives in the draft until you press Save.',
          'The button never changes size when it flips, at any of the sizes it appears in, so a list row can never jump under your thumb on a phone.',
          'WHAT "OFF" MEANS is the same idea in all three places and is spelled out per item below: never chosen automatically, always still reachable by an explicit press in the moment — and when you do press it, the contradiction is named rather than quietly honoured. See "Disable — temporarily take a scene out of rotation" (below), "Disable — temporarily take a colour set out of rotation" (Colour Sets page), and "Switching a flare off" (Flares tab).',
        ],
      },
      {
        id: 'scene-disable',
        title: 'Disable — temporarily take a scene out of rotation',
        keywords: 'disable enable toggle off pause temporarily stop scene never fires skip skipped power button green dim',
        body: [
          'The ⏻ power button on the scene toolbar, next to Mode availability — and on every row of the scene list, and on the phone\'s scene selector, so you can switch a scene off without opening it. Green = on, dim = off; one tap flips it. Nothing is deleted or lost; it\'s reversible any time, and there\'s no timer — it stays off until you turn it back on. See "The ⏻ power button" for the shared control.',
          'A disabled scene never fires automatically: it\'s dropped from the sequencer\'s own rolls, a generated trigger\'s scene draw, and a hand-authored trigger\'s fire_scene action, the same central gate Mode availability already funnels through — REGARDLESS of the room\'s current display mode. Disabled is the stronger statement: "don\'t use this scene, period," where Mode availability only narrows which room mode it plays in. A scene that\'s both disabled and mode-gated reports "disabled" as the reason, not "mode availability."',
          'Two things still work on a disabled scene, deliberately: a manual Fire/test-fire from this editor (you pressed the button, you mean it — same bypass Mode availability already has), and Force Scene. Pinning a disabled scene is contradictory input, so it\'s honoured, not silently refused or silently allowed — the room bar\'s Force Scene badge says "⚠ overriding disabled scene" when this happens.',
          'A disabled scene is marked wherever it shows: a red ⛔ marker beside its name in the scene list (its power button on the same row is dim), and the spelled-out "⛔ disabled" badge on the phone header once the scene is open — a disabled scene that stops showing up should never look indistinguishable from a broken one.',
          'Colour Sets and Groups have the identical control, with the identical rules — see "Disable — temporarily take a colour set out of rotation" on the Colour Sets page. Individual FLARE KINDS have it too — see "Switching a flare off" on the Flares tab.',
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
        keywords: 'color picker gradient swatch solid hex stops linear ledfx',
        body: [
          'Every colour and gradient field in SPECTRA — Fixed colours here, Background, Ambient\'s colour in the room bar — opens the same picker: LedFX\'s own colour-picker component, not a lookalike. Click a swatch to open it; click outside or press Esc to close.',
          'Two tabs where both apply (a colour field that only ever takes one solid colour, like Ambient, shows Solid only): Solid picks one colour off a board or by hex. Gradient builds a multi-stop linear CSS gradient — drag to add a stop on the bar, drag a stop to move it, pick each stop\'s colour. Saved colours and gradients from the shared library show as quick-pick swatches at the top.',
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
        id: 'fish-effect',
        title: 'Fish — the effect, and every knob it adds',
        keywords: 'fish school ripple wake flap tail turn radius oval swim pond rush orbits copy',
        body: [
          'Fish is Orbits\' twin: the same scene, the same flare kinds and bands, the same initial values, weightings and curves — a copy, not a re-tuning. What differs is the creature. Each one is a thin oval seen from above that POINTS the way it is swimming, its spine flaps as it goes, and it leaves an expanding ripple wake instead of Orbits\' comet smear. It turns through a real circle: nothing can spin a fish faster than its Turn Radius allows, so an about-face is always an arc and never a flip on the spot.',
          'Avoid Each Other (added 2026-08-28) is how hard they steer clear of a neighbour that gets close. It is STEERING ONLY: it just adds one more pull to where a fish wants to point, and that still passes through the same turn-rate limit as everything else — so avoidance can never reverse a fish on the spot, never tighten its circle past its Turn Radius, and never nudge one sideways. The distance they start dodging at is not a knob: it comes from their own body length, so bigger fish take more room automatically. At 0 they swim straight through one another, exactly as they did before this existed. It is deliberately OFF during the charge\'s school (they are meant to move almost identically) and during the lull\'s rush (which is meant to be chaotic) — those are authored moments, not crowds to fix.',
          'Six knobs are Orbits\' own, re-read for a fish. Turn Radius (Orbits\' Orbit Radius) is the tight circle it traces when it turns — the single number that makes the turn read as a turn. Current Swirl (Ring Spin) is a steady bias making every fish curve the same way, like a slow current; Reverse flips it. Swim Speed (Orbit Speed) is how fast they cross the panel, deliberately independent of Turn Radius. Home Ring (Tether Radius) and Home Scatter place each fish\'s own loose home patch — a pull it feels only once it has wandered well away, never a tether. Fish Size (Particle Size) is how big the creature is: the oval is that size stretched along its length, so a fish covers about the area the Orbits blob of the same size would.',
          'Body Length sets how thin and long the oval is (1.0 is literally an Orbits blob). Pond Size is how much of the panel they use before turning back — 1.0 is the panel\'s own inscribed ellipse, which on the crystal keeps them inside the lit hexagon rather than swimming into the dark corners.',
          'A strong beat makes them LUNGE: the speed boost is held near full for about six tenths of a second instead of dying away in a blink, so a beat is a real dash of several body lengths and the ripple it drops is matched to a motion that actually happened. It rides Speed Jump and the music, so there is no knob for it, and it only arms on a genuinely strong beat — quiet swimming is exactly the cruise it always was.',
          'Tail Flap is how far the spine throws its tail; Flap Rate is beats per second at cruise, and it rises with speed. Flap Accel is his ask made adjustable: the tail waves harder while a fish is speeding up and visibly softer while it slows.',
          'Ripple Wake sets the wake\'s strength — always subtle against the fish itself, stronger the faster it swims, and a ripple is dropped on every tail beat, so a faster fish also ripples more often. Ripple Spread is how fast a ring opens out (capped so the wake stays fish-sized, matched to the motion that made it), Ripple Life how long it takes to fade, Ripple Width its thickness. Wake Length is separate — that is the fish\'s own smear, not the rings.',
          'The remaining knobs shape the charge and the lull (see "Response families"): School Size, School Variation and School Turn Gap for the charge; Rush Size, Rush Time and Rush Chaos for the lull.',
          'On the strips the scene still runs Orbits\' own 1D effect — a fish seen from above needs two dimensions, and there is no 1D fish. Every number above is a considered first guess, not a tuned value: the look is not finished until you have watched it and moved them.',
        ],
      },
      {
        id: 'fish-camera-window',
        title: 'Fish — Window Travel (the view moves through the water)',
        keywords: 'fish camera window travel view pan world water ripple scroll stream charge lull school follow wake anchored',
        body: [
          'Window Travel makes the panel a WINDOW onto a larger body of water rather than the whole of it. Turn it up and, during a charge or a lull, the school really travels — through water that extends past the edges of the panel — and the view follows it. Turn it to 0 and you get exactly the effect as it was before this existed, down to the pixel.',
          'What changes is which things move. Before this, a charge held the school still and pushed the water past it at exactly the swim speed: one motion, and the shoal itself pinned. Now the window has its OWN speed — slower than the fish, because it lags behind them on purpose — so the shoal visibly crosses the view AND the wake streams past it, at two different rates. Measured at his own scene state over a four-second charge: the school covers about 51px across the window at 0 and about 61px at the shipped 0.8, while the window itself pans at about 11px/s against a swim speed of 17.5px/s. A lull had no view motion at all before this; it now streams about 15px of water past in three and a half seconds.',
          'Ripples are anchored to the WATER, not to the screen. A ring is dropped where the fish dropped it and stays there, so once the window moves on it scrolls away behind and is gone — it is never carried along with the view, and one that ends up far off-window is dropped rather than wrapping round.',
          'The view only ever moves during a charge or a lull; the rest of the time it eases back to rest and ordinary roaming is centred exactly as it always was. It only ever FOLLOWS the fish it can currently see, its pan speed is capped at well under twice the swim speed, and a leash keeps the school from ever drifting out of the window — so a rush, a beat turn or a lunge can never whip the view, and the school is never lost. scripts/check_fish_camera.py is the measured version of every number here.',
        ],
      },
      {
        id: 'radial-base-rotation',
        title: 'STAR / Radial — Speed vs Base Speed (they scale differently)',
        keywords: 'radial star spin speed base rotation quiet minimum floor revolutions per second rev/s silence parked audio reactive squared gain lows bass motor',
        body: [
          'STAR (the Radial effect) has TWO rotation controls and they are not the same kind of number. SPEED is a GAIN on the live audio: the effect squares it and multiplies it by the room\'s captured bass power, so in a quiet passage it produces exactly zero rotation at ANY setting — that is why a perfectly healthy Speed can look completely parked between bass hits, and why raising Speed from 0.55 to 0.8 barely doubles a crawl (the squaring means the top of the range is where it matters).',
          'BASE SPEED (rev/s) is the opposite kind of number: LINEAR, absolute, and independent of the music. It is stated in revolutions per second — 0.05 is one full turn every 20 seconds, 0.25 is one every four, 1.0 is one a second. Set it and the pattern never turns slower than that, audio or no audio.',
          'The two combine as a FLOOR, not a sum: the pattern turns at whichever is faster right now. In quiet it turns at your Base Speed; the moment the music\'s own drive is faster, the reactive Speed takes over completely unchanged — so setting a base never speeds up or alters what you already tuned at the peaks. Base Speed is left at 0 by default, which is exactly today\'s behaviour.',
          'Direction is not a separate choice: the base follows whichever way the pattern is already turning (Speed\'s own sign, which is what the Flip control writes), so it never fights a reverse flare. And it is advanced by the render clock, not by audio frames, so it keeps turning even if the audio capture goes quiet or stalls entirely.',
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
        title: 'Named flare kinds — the five types',
        keywords: 'kind drift jump momentary permanent slam scale strength declare card offset relative random hold duration target reverse toggle boolean color rotate rotate-and-back hue foreground degrees dwell ramp fade star radial spin flip spin_sign sign instant no pause freeze firework burst rockets payoff explode fireworks line up blob rush black hole 12 blobs evenly spread density cap max blobs lane alternative',
        body: [
          'A scene DECLARES named flare kinds — readable cards at the top of the response tabs, shared by every class. Five types: DRIFT-JUMP (🎨/🎲) jumps the drift itself — the colour-set jump through the shipped selector, or a dice re-roll for shape; both carry, the journey walks on from the new point. MOMENTARY (↩) spikes params/gain and RETURNS exactly to the carried baseline. PERMANENT (⚓) lands and BECOMES the new baseline drift carries from. COLOR ROTATE-AND-BACK (🔄) spins the foreground colour\'s hue and returns it — see below. FIREWORK BURST (🎆) explodes extra payoff rockets the instant the flare fires — see below.',
          'A momentary/permanent kind\'s params are five ways to say where a value goes. Two are the mode on the param itself: ABSOLUTE (the default) is a plain declared number, landed verbatim. OFFSET is a signed delta from wherever the param currently sits — a creep\'s live wander position, not its static starting value — "star down by 1" is offset −1, up is a positive offset. RANDOM draws once in an authored [lo, hi] range each time the kind fires and lands that same draw everywhere the kind targets. The other two ways sit outside the mode: INTENSITY-DRIVEN is the band\'s own ×scale, which steers how far any of the three modes above lands (×1 = the resolved target verbatim, ×0 = inert) — it composes with absolute, offset, and random alike. A bare ABSOLUTE value with ×1 scale is exactly today\'s declared-target behaviour.',
          'A TOGGLE param (a plain on/off switch, e.g. Black Hole/Orbits/Squiggles\' `reverse`) only ever takes an ABSOLUTE target — an authored true/false lands as a real switch, never blended or offset (a toggle has no "current position" to measure an offset from). Black Hole\'s / Orbits\' / Squiggles\' own "Reverse Momentarily (500ms)" kind is the example: MOMENTARY, hold_ms 500, forces `reverse` to its opposite state for half a second and then releases back to whatever the scene\'s own baseline actually was (or, for a device whose scene entry never set `reverse` at all, the effect\'s own default — since 2026-08-21 a spike on a never-set value is never left stranded) — the hold is timed from the moment the switch actually lands on the device, and the release is an instant switch back, never a glide (an on/off has nothing to glide through); same anchor rule as any other momentary kind (its first switch lands ON the trigger mark, not before it — that\'s a DROP\'s rule, not a flare\'s). `reverse` means something different per effect: on Squiggles it flips each chain\'s travel direction (retrace), on Orbits it flips the ring\'s spin direction, and on Black Hole it inverts infall itself — blobs fly OUTWARD instead of IN, the most dramatic of the three. On Black Hole the two halves are deliberately asymmetric (his ask, 2026-08-24): the SPIKE ejects instantly — the event horizon throws its blobs outward the moment the flare lands — but the RELEASE never flips them back. Blobs already flying outward keep going, decelerate, stall, and fall back in, taking about half a second to turn around; the turn ends the instant a blob is falling at the speed the scene\'s own fall curve would give it at that distance, so it rejoins the ordinary show with no jolt. Blobs orbiting the horizon keep their place in the ring the whole time — the flare never empties it. Like every named kind, it\'s declared but not band-attached — attach it into a lane on whichever bands should fire it (every band, to run "at all intensity levels") via "Flares tab — lanes". On Black Hole it now shares a LANE with "Blob rush" (12 blobs at once, evenly spread around the circle, ignoring the effect\'s max-blob cap and disturbing nothing already on screen): pooled in one lane, exactly one of the two fires per flare — his ask, "a shape flare that randomly chooses between the momentary reverse and this one". Every other kind on those bands still fires every time.',
          'STAR (radial) has no `reverse` toggle — its direction lives in `spin`, a single signed SPEED param, so its own "Reverse Direction" / "Reverse Momentarily (500ms)" kinds target `spin_sign` ("Flip") instead: an authored 0/1 flips spin\'s sign while preserving its current magnitude. This is deliberately NOT the same transport as a normal param patch on a smooth param (which would glide) — a sign flip always lands INSTANTLY, no ease-in, on both the turn and the release, because gliding a signed speed through zero means a real moment of zero speed along the way (the freeze he reported and asked to fix by switching to Flip). His own trade, made knowingly: no pause, but a more jarring, instant turn.',
          'MOMENTARY kinds also carry an optional HOLD — how long the spike shows before it releases, in ms. Unset, it holds the fixed 250 ms default; set it to hold longer or snap back sooner. Kinds with different holds in the same fire release independently — the release glides back to the baseline AS CARRIED AT RELEASE TIME, a creep\'s continued wander included, exactly like an unheld spike — EXCEPT a TOGGLE (on/off) kind\'s release and a `spin_sign`/Flip kind\'s release, which are instant jumps, for the same reason their own departures are (see above). Since 2026-08-21 the hold is timed from the moment each device\'s spike actually lands (not from the end of the whole flare\'s write burst — his 500 ms reverse used to hold ~1 s on a busy fire for exactly that reason), and every release belongs to the flare that made it: two flares close together on the same value extend the hold to the LATER one\'s end, never cut it short.',
          'COLOR ROTATE-AND-BACK spins the room\'s live foreground colour around the colour wheel and brings it back — a colour-lane accent, not a new colour pick (that\'s still the drift-jump colour jump above). It carries none of its own numbers to set: every one of its four quantities scales straight off how hard the flare fired. At a gentle flare it rotates 60°, ramping in over 1000 ms, holding 1000 ms, then fading back over 1500 ms (1.5× the ramp); at a full-scale flare it rotates a full 180°, ramping in over 250 ms, holding 400 ms, fading back over 375 ms — every value in between scales linearly with the fire\'s own intensity. The ramp-in is timed to land its full rotation exactly ON the trigger mark — the same anchor rule momentary kinds use (finish the switch on the mark, then hold, then release), not a drop\'s "start on the mark" rule. It targets only the foreground (the same colour a colour jump lands) — the background is untouched — so it composes freely alongside a shape-changing kind in the same band without displacing it; nothing about it stops a concurrently-firing shape flare. Declared but not band-attached, same as every named kind — attach it into a lane via "Flares tab — lanes" when ready to run it. Pooling it INTO THE SAME LANE as the Colour Jump makes each fire pick one of the two (never both fighting over the colour at once) — see that topic\'s "why pool" note.',
          'FIREWORK BURST explodes a volley of extra payoff rockets at the moment the flare fires — the same fat, layered bursts a drop\'s own payoff spawns, landed immediately (never queued for the next beat, unlike the beat-burst param a patch might raise) on every device currently running a fireworks effect. Like Color Rotate-and-Back it has no numbers of its own to set: it adds 3 rockets at a gentle flare, scaling linearly up to 6 at a full-scale one. The burst layers ON TOP of whatever the scene is already launching — the scene\'s own rockets, beat bursts, and charge/lull/drop choreography are never restarted or interrupted, and the density cap never swallows it. On a scene with no fireworks effect running it simply has nothing to land on.',
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
        id: 'flare-disable',
        title: 'Switching a flare off — the ⏻ power button on a flare kind',
        keywords: 'disable enable flare kind off power button green dim lane pool silence mute skip never fires',
        body: [
          'Every flare kind carries a ⏻ power button — on its card in the palette above the bands, and on the kind itself inside each lane of the rack below them. Green = on, dim = off; one tap flips it. It is the same control scenes and colour sets use (see "The ⏻ power button"). Nothing is deleted and nothing detaches: the kind stays declared and stays attached to exactly the bands it was attached to, it simply stops firing. There is no timer — it stays off until you turn it back on. Like every other field on this page, the flip lives in the scene draft until you press Save.',
          'The flag is on the KIND, not on one band\'s attachment: switching a kind off silences it in EVERY band that attaches it at once, in this scene. That is what "disable this flare" means — if you only want it out of one band, detach it there (✕) instead.',
          'A disabled kind is dropped from every automatic path: it never enters its lane\'s pick-one pool (so it can never win a fire-time roll), it never executes when a band fires, and — this is the easy one to miss — it no longer contributes its own trigger offset or its automatic head-start to the fire\'s timing. A flare you have switched off cannot retime a fire it is not part of.',
          'A LANE WHOSE KINDS ARE ALL SWITCHED OFF fires nothing at all — no substitution, no fallback to another lane\'s member. That is deliberate and it is stated rather than silent: the lane shows "⏻ lane off" in the rack, and the fire record says so too, so a lane that has gone quiet never looks the same as a broken one.',
          'ONE thing still works, deliberately: ▶ Preview. You pressed the button, so it runs the kind for real on your fixtures — and because that contradicts the flag, the preview panel says so ("this flare is switched OFF"), the same way Force Scene names an overridden disabled scene and a colour-set Preview names a disabled card.',
        ],
      },
      {
        id: 'flare-preview-timeline',
        title: 'Scrubbing preview — ▶ Preview on a flare kind card',
        keywords: 'preview timeline scrub playhead trigger mark animation start end drag loop pause extend evolution starts early gap offset lead loops repeats every time simulation',
        body: [
          'OPENING THIS PREVIEW CHANGES YOUR REAL LIGHTS. Your trigger engine pauses the instant you open it — if a song is playing, its scene changes, other flares, and charge/lull/drop moments all go silent for as long as the window stays open, whether or not this kind has fired yet. Opening does NOT fire anything by itself any more: the scrub ruler loops on its own real-time clock, and every time the white playhead reaches the accent-coloured "start" line, this card\'s own scene fires onto your fixtures and this one flare kind fires on top of it for real — then it holds there until the NEXT lap reaches "start" again, over and over, for as long as the window stays open. This is a TRUE SIMULATION of a trigger crossing, not a single flash: the first fire waits for the mark exactly like every fire after it. Closing the preview (or navigating away) reverts your room to exactly what it was showing before you opened it, and your live show resumes from wherever it would otherwise be. Two separate releases protect you here, and they are not the same guarantee: if you close the browser tab or lose connection instead of pressing close, the app notices on its own and reverts anyway — typically within about 17 seconds of your last moment on the page. Separately, and no matter what — even if the tab stays open and keeps checking in the whole time — a preview can never hold your room for more than 3 minutes total; past that it releases itself automatically and tells you so right in the panel, whether or not anything else ever notices — closing and reopening the preview, or nudging the intensity slider, starts a fresh look after that. The first number is how fast an abandoned preview lets go; the second is the hard ceiling on how long any single preview can run at all.',
          'Tap ▶ Preview on any flare kind card to open its scrubbing timeline: a ruler that plays across and loops, showing exactly what this one kind does, in isolation from any band, AND re-firing it live on your fixtures every lap. Play/Pause stops the loop AND the live re-firing together — a paused preview never touches your lights again until you press Play. Drag the playhead anywhere on the ruler to freeze-frame the effect mid-animation (scrubbing pauses the loop the same way). Extend widens the ruler without changing anything already on it. The intensity slider at the top recomputes the timeline at the new strength and restarts the loop from the beginning, so the next live fire — at the new strength — still waits for the mark rather than firing immediately.',
          'TWO KINDS OF MARKER, and they are not the same thing. The orange line labelled "trigger" is where you place the moment this kind is considered fired — drag it anywhere on the ruler. The two lighter lines labelled "start" and "end" (with the shaded band between them) are computed, not editable: they show exactly when the kind\'s own writes begin moving a light and when the whole thing has settled back — read straight off the real timing this kind will actually run (how long a glide takes to land, how long a momentary spike holds before it releases, how long the release itself takes) PLUS the same automatic head-start a real trigger fire would give this exact kind, so "start" sits however many milliseconds earlier than the trigger line that this kind genuinely needs to land its animation on the mark — never a hardcoded gap. The text under the ruler states the gap between them in milliseconds — this is the number that answers "does the light actually start changing when I think it does:" if the trigger line and the start line aren\'t on top of each other, that gap is real and now visible, not something you have to guess at from watching the room. THE LIVE FIRE IS TIMED TO THE "start" LINE, not the trigger line — it fires every time the playhead reaches "start," which is exactly when the animation itself needs to begin moving for its own landing point to reach the trigger mark on schedule.',
          'DRAGGING THE TRIGGER LINE EDITS THE SCENE, it does not just move something around inside the preview. It writes this kind\'s own trigger_offset_ms — the same as typing into any other field on this scene: the change lives in the draft immediately and the page\'s own Save button is what makes it permanent, same as everywhere else in this editor. Closing the preview without Saving the scene discards it exactly like any other unsaved edit. THE SIGN: drag the trigger line to the RIGHT of "start" and the offset goes MORE NEGATIVE — negative means "fire earlier," so the animation has more head start before the mark. Drag it to the LEFT and the offset goes positive — "fire later." Landing the trigger line exactly on "start" is 0 (coincident) — the field\'s own default, and where every flare kind starts out.',
          'THE SAVED OFFSET RETIMES YOUR REAL SHOW, not just this preview. Once the scene is Saved, any of your own song triggers that fires this scene\'s flare response actually fires early or late by this offset — the engine reads the offset of whichever kinds the fired band carries, moves the fire by it, and only then applies the same automatic head-start the "start" line shows here, so a crossing in the real show lands exactly where this ruler says it will. If a band carries several kinds with different offsets, the whole band fires together at the EARLIEST offset anyone in it authored (the siblings fire a hair off their own mark) — a kind still at 0 never holds a sibling\'s authored offset back. Bridge-relayed legacy flares are the one exception: they arrive at their own moment with no advance notice, so there is nothing to fire earlier — same reason automatic song-transition fires take no head start.',
          'CHARGES, LULLS, DROPS AND SCENE-TO-SCENE TRANSITIONS now have their own previews too — the second half of the same idea, on the Phase Choreography tab. See "Scrubbing preview — a scene transition" and "Scrubbing preview — the drop sequence". They share this preview\'s hold, so only one preview can be open at a time and all three release your room the same way.',
          'ONE PLACE A DROP-BAND KIND READS DIFFERENTLY. If this kind is attached ONLY to a drop band, the panel says so and there is no head start at all: an explosion BEGINS on the trigger mark rather than finishing there. That is deliberate and settled — a momentary flare anchors the END of its first switch to the mark, a scene transition anchors its MIDDLE, and a drop anchors its START. The preview follows whichever rule the bands you attached this kind to actually put it under, so it can never promise a head start the real show would not take.',
        ],
      },
      {
        id: 'transition-preview-timeline',
        title: 'Scrubbing preview — a scene transition',
        keywords: 'transition preview scrub crossfade anchor midpoint middle phased handoff lead offset drag scene change ruler loop hold release phase tab',
        body: [
          'OPENING THIS PREVIEW CHANGES YOUR REAL LIGHTS, exactly like the flare preview does. Your trigger engine pauses the instant you open it — scene changes, flares and drop moments all go silent for as long as the window stays open. Each lap, the ruler first resets your room to the scene you picked under "Coming from", then performs the real transition into this scene when the playhead reaches the fire moment. Closing (or navigating away) puts your room back exactly as it was. If you close the tab or lose connection instead, it reverts on its own within about 17 seconds of your last moment on the page; and no matter what — even with the tab open and checking in — no preview can hold your room longer than 3 minutes total, after which it releases itself and says so in the panel.',
          'WHAT THE RULER SHOWS. The shaded band is the transition\'s REAL crossfade at the intensity you have selected — the same length your show would use, not a stand-in: your scene\'s own blend time if it has one, otherwise your room\'s global transition setting, otherwise the automatic intensity-scaled default (gentler and longer at low intensity, harder and shorter at full). The line labelled "anchor" is where the transition\'s visual PAYOFF lands. For an ordinary pair of effects that is the plain mid-point of the blend. For a pair that choreographs a phased handoff — particles gathering into a radial and blooming, a radial imploding into an eruption, and their relatives — it is that handoff\'s own moment instead, and the panel tells you which of the two is in force.',
          'A SCENE TRANSITION ANCHORS ITS MIDDLE. That is one of three settled rules and the reason the write goes out EARLY: a momentary flare anchors the END of its first switch to the mark, a scene transition anchors its MIDDLE, and a drop anchors its START. So the show fires this transition ahead of the mark by exactly the anchor\'s share of the crossfade, and the "start"/"end" lines show where the blend actually begins and finishes around it.',
          'DRAGGING THE TRIGGER LINE EDITS THE SCENE. It writes this scene\'s own trigger_offset_ms — a draft edit like any other field, made permanent by the page\'s Save button and discarded if you close without saving. THE SIGN is the same as everywhere else in SPECTRA: drag RIGHT to fire EARLIER (the number goes more negative), LEFT to fire later, and landing on the anchor is 0. Once saved, your real song triggers that fire this scene move by that offset too — the drag retimes your show, not just this preview.',
          'ONE HONEST LIMIT, worth knowing rather than discovering. Most of your song triggers do not name a scene: they let the app choose one as they arrive, and it commits that choice about five seconds ahead of the mark. A scene offset inside that window lands normally. An offset MORE than about five seconds early cannot be seen in time, so that trigger simply fires at its un-shifted mark instead — late relative to what you asked for, never at the wrong moment. Dragging on this ruler cannot reach that far in practice.',
        ],
      },
      {
        id: 'drop-sequence-preview-timeline',
        title: 'Scrubbing preview — the drop sequence',
        keywords: 'drop sequence preview charge lull drop ramp stretch hang gap explosion start anchor phase machinery scrub ruler phase tab blob centre',
        body: [
          'OPENING THIS PREVIEW CHANGES YOUR REAL LIGHTS, exactly like the other two. Your trigger engine pauses, this scene is held on your fixtures, and each lap the app drives a real charge, then a real lull, then a real drop through the same machinery your show uses — the effects\' own choreography, not an imitation of it — before releasing the phase and starting again. Closing puts your room back. An abandoned preview reverts on its own within about 17 seconds; no preview can hold your room longer than 3 minutes in total.',
          'WHAT THE RULER SHOWS, band by band. Each of charge and lull draws TWO bands: the RAMP, and the HANG after it. A charge or lull ramp is not a fixed length — it stretches to about 90% of the real gap to the next moment, and then holds at full for the last 10%. That is the shape you asked for: "the single blob waiting in lull should reach the centre just, and hang for just a moment, before the explosion." The two sliders set those gaps, so you can see the stretch and the hang change as you move them, and judge the hang directly instead of guessing at a number. The DROP never stretches — it is the fixed snap — and it has no hang.',
          'THE DROP BEGINS ON ITS MARK. That is the settled rule for an explosion, and it is why the drop\'s mark and its ramp start are the same place on this ruler: no head start, ever, whatever is attached to the drop band. Charge and lull keep the ordinary flare rule instead — if what they fire needs a moment to switch, they fire that much early so the switch finishes on the mark, and the panel says by how much.',
          'THE MARKS HERE ARE NOT DRAGGABLE, and that is deliberate. A band\'s timing offset is shared by every flare kind attached to it, so a drag would have to pick one kind to write it to — and picking for you would be inventing an answer. Retime a kind from its own ▶ Preview on the Flares or Charges/Lulls/Drops tab and this ruler shows the result: each class\'s mark sits at whatever its band\'s kinds authored, so it always tells the truth about where your show will fire.',
          'IF THIS SCENE HAS NO EFFECT THAT CAN BE DRIVEN by charge/lull/drop, the panel says so in red rather than looping a preview that changes nothing. The ruler still shows the timing the scene would use.',
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
        keywords: 'lane drag attach combine pool pick one alternative random weight or overwrite additive precedence order same param gain dice colour rotate',
        body: [
          'Each band shows a row of vertical LANES — 2 to start, a "+" grows up to 4. When the band fires, EVERY lane fires together — and a lane holding SEVERAL kinds picks exactly ONE of them, at random with even odds, fresh on every fire (the SpotFX morph-lane behaviour: each lane is a pool of alternatives, one pick per lane, all picks land together). A lane holding a single kind just fires that kind every time — so until you deliberately put two kinds into one lane, a band behaves exactly as it always has: everything attached fires.',
          'THE DRAG GESTURES: drop a kind card ON an occupied lane to POOL it there — the lane shows its members stacked with "— or —" between them and a "⚄ picks 1 of N" badge. Drop it on the slim strip just before a lane, or on an empty lane, to give it a lane of its OWN (shifting later lanes over — nothing dragged in is ever silently lost). Drag a kind out of the palette and it stays attached everywhere else it already was (a kind can sit in more than one band, or more than one class, at once); drag an already-attached lane\'s kind elsewhere and it MOVES (detaches from where it was, lands where you dropped it — a pool it leaves behind with one member left just becomes a normal always-fires lane). The ✕ on a member detaches it from the band without moving it anywhere. A tap/click that doesn\'t move opens the same edit box "Flare kind edit box" describes.',
          'WHY POOL: two colour-changing kinds — the drift-jump Colour Jump and Color Rotate-and-back — in one "colour lane" means each trigger fires exactly one of the two, never both fighting over the same colour, while the shape lanes beside them still fire their own picks concurrently. The odds are even today; weighting the pick (e.g. by curves) is a possible later step, deliberately not built yet.',
          'Lane ORDER still matters, exactly as before: it decides what happens when kinds that actually fire touch the SAME parameter — the engine\'s existing rule, unchanged: a dice re-roll and a colour jump are each a SINGLE pick per fire (two firing at once is harmless but only the first executes); momentary/permanent PARAM moves overwrite — permanent kinds land first, momentary lands after (so a spike shows over the just-set baseline), and among same-type kinds the LATER lane wins a shared param; a permanent GAIN kind chained after another permanent gain in the same band multiplies onto it rather than replacing it. So a later lane is a deliberate "wins" for a param conflict, not an accident of drag order — and pooling never reorders anything: it only decides WHICH of a lane\'s members fires.',
          'Lane count is a per-band display preference, not scene data — it isn\'t saved, and a band with more lanes than the visible count (e.g. from legacy data, or an agent edit) always shows them all rather than hiding any. Which kinds share a lane IS scene data, saved with the scene like any other edit.',
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
          'TWO PREVIEWS LIVE HERE. "▶ Preview transition into this scene" and "▶ Preview drop sequence" open scrubbing rulers that show — and actually run, on your fixtures — the two things this tab describes in words. Both take over your room while they are open and put it back when you close. See "Scrubbing preview — a scene transition" and "Scrubbing preview — the drop sequence".',
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
        keywords: 'dwell minimum hold floor update effect flare double intensity scene change intensity curve default',
        body: [
          'A per-scene MINIMUM HOLD TIME, a curve over intensity — but Y is SECONDS here, not a likelihood weight, so don\'t read it the same way as the likelihood curve above it. Default (no override): 16 seconds at intensity 0, 4 seconds at intensity 1, linear between — his exact numbers. A scene with no override shows exactly that on the curve button: "Default (16s → 4s)" with the default\'s own descending shape, and picking the "Default (16s → 4s)" tile in the picker returns to it. Dwell curve changes apply immediately when picked or edited — they don\'t wait on the page\'s Save button. The intensity used is LATCHED the moment the scene actually fires; it never moves mid-hold even if the live intensity changes.',
          'This gates every AUTOMATIC scene change — a sequencer roll, a trigger\'s Fire Scene action, or the automatic song-transition fire — whichever scene is currently showing must clear its own minimum before any of those may switch away from it. A manual Fire press in the editor is exempt (it never goes through this gate) and always fires immediately. Force Scene still wins over an active minimum, but the room bar names the override rather than applying it silently.',
          'If a scene change is requested before the minimum clears, the room does an UPDATE EFFECT instead of switching: it fires the CURRENT scene\'s own ordinary Flare response — whatever\'s already attached to its bands — at DOUBLE the intensity that would otherwise have applied (capped at 1.0, so anything already at intensity 0.5 or above reads the same doubled or not). This is a deliberate placeholder standing in for a future purpose-built Update effect — nothing new needs authoring, and it works on every scene that already has a Flare response. You will see a real flare during a hold where the room previously did nothing; that\'s expected, not a bug. A scene with no Flare response/bands declared at all still just holds, silently — recorded, never a silent no-op internally, so "why didn\'t the room change" is a log lookup, not a mystery.',
          'The "Update kind" picker on the Flares tab is reserved for a future, purpose-built Update effect and is not read by this placeholder — attaching one there does nothing yet.',
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
        keywords: 'blackhole orbits fish radial fireworks squiggles dancer eye grammar visual',
        body: [
          'Black Hole: charge — the event horizon holds its size while its ring THICKENS, blobs start forming faster and faster (up to 12 a second, past the density cap) and fall in faster with them; lull — that fast formation keeps up while the horizon expands, filling the panel exactly half way through the lull and holding there, so the second half is dark; drop — a centre explosion on the mark, then ease back. On the strips the same arc reads as a thickening halo on the ring, then the strip darkening to black half way through the lull.',
          'Orbits: charge — the population swells then sheds to a single blob; lull — its orbit collapses to a tiny centre swirl; drop — full population returns with a burst plus 2× ballistic ejecta, spin boosted and decaying.',
          'Radial: charge — the spin accelerates, peaking at the ramp end; lull — the pattern implodes to a held centre point; drop — it blooms back out.',
          'Fireworks: charge — launch rate climbs 6× while bursts shrink and slow; lull — launching stops, six dim rockets cross the dark panel from evenly spaced points around the rim (about 60° apart, each nudged a little so the ring is not mechanical), travelling about twice as far past centre as before exploding; drop — every rocket explodes where it is, giant, in its own colour, then a shower of ordinary fireworks keeps launching through the afterglow (8 a second at first, easing back to the scene\'s own show over about 2½ s) — and the scene\'s own beat bursts keep coming underneath the whole time, since a payoff, a burst flare, or the tail never counts against the density cap.',
          'Squiggles: charge — walls turn solid and the figure fills with trapped scribble; lull — an old-TV switch-off to a held white dot; drop — a nine-chain fan erupts from centre.',
          'Dancers: charge — the dance intensifies as the build climbs; lull — the crew sinks into a held squat; drop — every dancer fires a stunt (breaker freeze-spin, grand jeté splits, or a huge leap), staggered.',
          'Eye: charge — the iris grows, the pupil constricts, flames stream inward; lull — the lids close with a suspense pause; drop — the eye explodes open with a flame burst.',
          'Fish: charge — up to twelve fish swim in and lock into one heading, and the camera follows them so perfectly that the school holds station while the WATER streams past; from then on the whole school changes direction on every beat, never closer together than 400ms, each fish varying just slightly from the shared heading. Lull — they disperse one by one until a single fish is left, alone and still swimming, holding the centre of view by half way through; then a rush of up to twenty pours in from the direction that fish is heading and zooms past it for about a second, chaotically, leaving behind exactly as many fish as the scene\'s own Fish count. Drop — Orbits\' payoff unchanged: the full population bursts back out of centre plus 2× ballistic ejecta, speed boosted and decaying. The school and the rush are the only two moments a fish scene exceeds its own population limit.',
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
          'Because that partition is exclusive, disabling cards interacts with it: disable every Rainbow set and there is nothing legal above the limit. The room is never left with no colour — it keeps what it is already wearing — and the sequencer status strip says so. See "Disable", below.',
        ],
      },
      {
        id: 'colorsets-disable',
        title: 'Disable — temporarily take a colour set out of rotation',
        keywords: 'disable enable toggle off pause temporarily stop colour color set group never chosen skip skipped exhausted power button green dim',
        body: [
          'The ⏻ power button on the colour-set toolbar, next to Rainbow select — and on every row of the tiered Sets & Groups list, so you can switch a card off without opening it. Green = on, dim = off; one tap flips it, and from a list row it saves by itself. It is the same control, the same wording, and the same rules as a scene\'s Disable (Scenes page, see "Disable — temporarily take a scene out of rotation"). Nothing is deleted or lost; it\'s reversible any time, and there\'s no timer — it stays off until you turn it back on.',
          'A disabled Set is never CHOSEN automatically: it\'s dropped from the sequencer\'s own colour roll, a colour Group\'s rotation, the drift journey\'s destinations, a flare\'s colour jump, and a hand-authored select_color_set trigger — REGARDLESS of the room\'s display mode. Disabled is the stronger statement than Mode availability, which only narrows which room mode a card plays in; a card that is both reports "disabled" as the reason.',
          'It is never yanked mid-paint. If a set you disable is the palette the room is wearing right this second, the room keeps wearing it — the next natural colour change simply picks something else. That is exactly how disabling a scene behaves.',
          'Groups: disabling a MEMBER takes it out of that group\'s rotation/weighted pool. Disabling the GROUP stops the group being chosen as a pool — but it does NOT strip the group\'s Overrides from an enabled member fired by its own id, because overrides are a bulk-edit layer, not a choice, and disabling must not silently change an enabled set\'s colours. A group whose members are ALL disabled is itself unusable, and says so rather than quietly resolving to something else.',
          'Two things still work on a disabled card, deliberately: this page\'s Preview, and an explicit apply to the room. Both are you pressing a button in the moment, so they win — and because that contradicts the flag, they say so ("previewing a disabled colour set"), the same way Force Scene names an overridden disabled scene.',
          'A disabled card is marked wherever it shows: a red ⛔ marker beside its name in the tiered list (its power button on the same row is dim), and the spelled-out "⛔ disabled" badge on the header once the card is open — a card that stops showing up should never look indistinguishable from a broken one.',
          'Safety: if you disable enough cards that NOTHING is eligible at some intensity (easy to do above the Rainbow select limit, where only Rainbow sets can be picked), the room is never left with no colour — it keeps the palette it already has. That is reported, not silent: the sequencer status strip\'s "last colour pick" shows "no colour set was eligible" with how many of your sets are currently disabled.',
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
    keywords: 'health ownership bridge liveness engine lights skipped take-back',
    intro:
      'App status (scene count, light ownership from the durable record, which lights the last take-back/restart brought up and which it had to skip — see "A light the take-back had to skip", bridge state, sequencer state, room journey) plus the evolution-engine card: journey custody, active scene and legs, bridge health, recorded writes, the parameter watchdog\'s count.',
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
        id: 'testing-bar',
        title: 'TESTING IN PROGRESS — the top bar',
        keywords: 'testing bar top banner loud agent live test declared painting driving stripes amber warning unknown who since holding room busy',
        body: [
          'A loud striped bar across the very top of every page, above the nav. It is up ONLY while something is actually testing on your room, and it disappears completely the moment nothing is. If you can see it, somebody or something is using your lights right now.',
          'It tells you three things. WHO: a declared take names the agent and what it is testing; if nobody declared anything but one of SPECTRA\'s own preview paths is holding your room, the bar names that path instead. SINCE WHEN: your own wall clock, plus how long it has been running once that is over a minute. AND WHETHER IT IS ACTUALLY PAINTING: "driving your lights (frames flowing)" means your room really is being rendered; "holding the room but NOT painting — that\'s a fault, not a test" means somebody has taken your lights and they have gone dark, which is a problem, not testing. Those two are different facts, which is why the bar states which one it is — an owner indicator alone once read green right through an outage.',
          'It clears itself. Every declaration carries a mandatory expiry (an hour at the very most, renewed while the work is still going), checked every time the bar is drawn — there is no flag anyone has to remember to switch off, so a bar cannot outlive the testing that raised it. The automatic half needs no declaration at all: a colour-set preview, a flare preview, or anything else holding your room lights this bar on its own.',
          'A grey "CAN\'T CONFIRM whether your room is under test right now" bar means SPECTRA could not answer or a status source could not be read. It shows deliberately rather than staying quiet: when the app cannot tell, assume your lights may be in use. A single dropped poll will not raise it — it takes two in a row.',
        ],
      },
      {
        id: 'ownership-liveness',
        title: 'The liveness endpoint',
        keywords: 'health checker frame flush freshness 503 contract',
        body: [
          'GET /spectra/api/liveness is the binding fleet contract: per-virtual frame-flush freshness straight from the render loop, HTTP 200 healthy / 503 not. While SPECTRA is dark it answers healthy only if provably dark (a live stack without ownership is the split-brain tripwire). Never remove or repoint it without the owner\'s word.',
          'Additive, informational keys ride alongside (never part of `healthy`): `activation_gaps` (a config-declared virtual that never came up — this one DOES make it unhealthy), `write_seam`, `param_watchdog`, and since 2026-08-21 `activation` — the activation report: which lights the last take-back/restart had to skip, why, whether each has come back since, and how long ago it was last rechecked. A skipped light is deliberately NOT an unhealthy 503: the systemd dead-man watches this same health and a dark fixture must never restart-loop the whole service.',
        ],
      },
      {
        id: 'ownership-handover',
        title: 'How the switch works (owner-run only)',
        keywords: 'quiesce activate commit rollback failure single owner armed latch readiness precondition refuse seeder',
        body: [
          'Before anything moves, the READINESS GATE: the switch checks the go-day preparations itself and REFUSES — room untouched, current owner still writing — when SPECTRA\'s fx-live device config is missing, empty, or has no usable virtuals (the refusal names the seeder command), or in reverse when the LedFX service unit is missing. Skipped preparation can no longer dark the room.',
          'Then two steps, strictly ordered: quiesce the current writer and VERIFY it stopped (Hue DTLS session released, DDP sending stopped), only then activate the other (SPECTRA\'s in-process device layer + the shared audio hub — or, in reverse, restart LedFX). Any failure lands back at the old owner automatically — never two writers, never a split. The API refuses entirely until the process is armed (SPECTRA_HANDOVER_ARMED=1).',
          'ONE deliberate exception to "any failure lands back" (owner ruling 2026-08-21: one unreachable device must not be able to keep the whole room dark): the way back FROM RELEASED — the "Take back (SPECTRA)" button on the released banner. There is no old owner to land back on, only darkness, and aborting never rescues the light that could not be reached — it only darkens the ones that did come up (he hit exactly this six times in one night on one WLED whose network name would not resolve, and twice the morning before on two sconces that merely answered too slowly). So a take-back from released that brings the stack up with at least one light driving now COMMITS over whatever it could not confirm, names every skipped light loudly (the toast, the amber strip on every page, the Status page, the liveness endpoint, the record\'s own history note) and keeps rechecking it — see "A light the take-back had to skip" below. A handover FROM A RUNNING SHOW is unchanged: it still rolls back on any gap, because there a working show is genuinely at risk and there is a real owner to land back on. A take-back whose stack never comes up at all, or with not one light driving, still fails back to released as before.',
        ],
      },
      {
        id: 'ownership-resume',
        title: 'Restarts while SPECTRA owns',
        keywords: 'restart resume auto reactivate dark crash deploy',
        body: [
          'SPECTRA runs as her own process (spectra.service). If that process restarts while the record says she owns the room, the light stack reactivates itself at startup through the same guarded path the handover uses — no manual handover cycle. If the resume fails, the room stays dark-but-owned and the liveness endpoint answers 503 until the cause is fixed.',
          'A PARTIAL resume (the stack came up, one light could not be confirmed — the same policy the take-back from released now follows) keeps every other light driving and shows the same amber strip / Status page line / liveness `activation` report the take-back does — see "A light the take-back had to skip". Before 2026-08-21 this case was a CRITICAL log line and nothing visible in the app.',
        ],
      },
      {
        id: 'take-back-skipped-light',
        title: 'A light the take-back had to skip',
        keywords: 'skipped skip dark light fixture unreachable unresolved did not resolve address mdns .local slow too slowly no answer failed to connect live=false not receiving partial take-back take back released restart resume amber strip banner which device why recheck rechecked retried driver came back recovered one light dark rest of room whole room dark abort aborted dining table sconce wled',
        body: [
          'WHAT YOU SEE: after "Take back (SPECTRA)" (or a SPECTRA restart), an amber strip at the top of every page — "⚠ Take-back skipped N lights — the show is running on the rest" — listing each skipped light by its own name with the reason in plain words and when it was last rechecked. The toast right after the press says the same thing once. The Status page\'s "Lights at take-back" line shows the count (e.g. "20/21 lights up") and the same list, including lights that have since come back. GET /spectra/api/ownership carries it as `activation`, GET /spectra/api/liveness as a compact `activation` summary, and the ownership record\'s history note for that commit names the light — the one place that survives a restart.',
          'WHAT IT MEANS: the room came up on every light that answered; the named light is dark because SPECTRA could not bring it up — not because the show was held back. The reasons, each its own sentence: "address \'…\' did not resolve" — the light\'s network name (a wled-xxxx.local mDNS name, say) is not answering on the network at all, so the driver has nowhere to send (power-cycle the light, or check its network); "no answer from <ip>" — the address is valid but the light did not respond inside the activation\'s window (slow, off, or unreachable — this is what two kitchen sconces did one morning, and they came up by themselves moments later); "<ip> answers but reports it is not receiving SPECTRA\'s stream" — the light is up and talking but not taking the stream (a WLED with realtime disabled, or a blocked port). A "virtual never came up" line is a different class: a config-load failure for that virtual, also on the liveness endpoint\'s `activation_gaps`.',
          'WHAT HAPPENS NEXT, WITHOUT YOU: every 30 s SPECTRA re-asks each still-dark light the same question the take-back asked (its own live flag), and for a light whose name never resolved it also retries the light\'s own driver start-up — so once you fix the light (plug it back in, fix its network), it joins the running show on its own and the strip drops it; there is NO need to release the room and take it back again just to collect one fixture. The "rechecked Ns ago" age is the honesty of that claim — a fresh age means the sentence next to it is current. If a light stays on the strip after you believe it is fixed, the strip is telling you it still cannot confirm it: check the light itself (and the SPECTRA service log, which names each recheck).',
          'WHY IT WORKS THIS WAY (owner ruling 2026-08-21): before this, a take-back from released aborted the WHOLE room — tearing down the twenty lights that had come up — the instant any one device could not be confirmed, and fell "back" to released, which is darkness, not safety. Aborting never saved the unreachable light (it was unreachable either way). No light in this room is load-bearing for another — an unreachable device\'s part of a shared virtual is simply skipped each frame and the other lights on that virtual keep painting — so one dark fixture can only dim the room, never corrupt it, which is why "skip it and say so" is safe here. Handing the room over FROM a running show is deliberately unchanged (strict all-or-nothing), and a take-back whose stack never comes up at all still fails back to released.',
        ],
      },
      {
        id: 'param-watchdog',
        title: 'Parameter watchdog — a value left stranded gets put back',
        keywords: 'watchdog orphan orphaned stuck stranded reverse backwards parameter param value baseline restore restored put back momentary flare release lost nothing holding it left alone permanent in flight hold glide liveness count show log review 30 seconds grace status engine card given up',
        body: [
          'A background safety net (runs every 10 s) under the evolution engine\'s flares. A momentary flare spikes an effect value — `reverse` on Black Hole, a brightness duck, a shape param — and releases it back after its hold; if that release is ever lost, the effect is left stuck (running backwards, dimmed, whatever the spike was) with nothing holding it there. The watchdog reads every engine-tracked device\'s LIVE effect values and compares them to the engine\'s own baseline for that scene. A value sitting away from its baseline with nothing legitimately holding it — no pending release, no drift creep/follow owning it, no glide still in flight — for 30 s continuously is put back to the baseline: the exact value the lost release would have returned it to, landed the same way a release lands (a 1.5 s glide, or an instant switch for an on/off value).',
          'It never fights an authored change. A PERMANENT flare moves the baseline itself — that IS the new baseline, so there is nothing to restore (an effect you told to run backwards permanently stays backwards). A momentary flare still inside its hold is left alone for as long as the hold lasts, however long the engine takes to release it; a glide still in flight is left to land. Backgrounds are out of scope on purpose — colour sets, Dark mode and Light mode all write those legitimately — and the room Brightness dimmer is understood, not "corrected". It stands down entirely while a Colour Set/Group Preview or a flare preview holds the room, and while SPECTRA is dark (not owning the lights).',
          'Loud, not silent: every restore is logged in the SPECTRA service log (which device, which value, what it found, what it put back, how long it had been stranded), counted on the Status page\'s engine card, on GET /spectra/api/liveness under `param_watchdog` (informational — never part of `healthy`), and written to the show log as a "watchdog" event you can see on the Review page. A recurring restore means something keeps losing a release — the log line is what finds the cause; the restore only covers for it. A restore that doesn\'t take (something keeps moving the value back, or the effect rejects the write) is retried twice more on the same 30 s grace, then given up on — named in the status — rather than fought forever.',
        ],
      },
      {
        id: 'panic-release',
        title: 'Panic release — let go of every light',
        keywords: 'release home assistant ha panic emergency let go stop wled hue ddp virtuals band',
        body: [
          'The red "Release to Home Assistant" button, always reachable (top of every page, next to the nav) — press it and SpotFX AND SPECTRA both let go, no confirmation, the press is the consent. Unlike the handover above this is NOT gated by SPECTRA_HANDOVER_ARMED: releasing is always safe to allow, because there is no new writer coming up. The ownership record moves to "released" first, before anything else happens; then BOTH worlds\' devices are cleaned up EVERY press, regardless of which one the record said owned — a rogue writer the record didn\'t know about (e.g. the external LedFX service started behind its back) still gets addressed. Each device is told to let go explicitly rather than just falling silent: WLED devices get the JSON API\'s {"live": false} so they drop out of realtime now instead of waiting for their timeout to lapse; Hue\'s entertainment/streaming session is stopped so the bridge frees the group; the external LedFX service\'s active virtuals are deactivated over its own API, reached directly (not through SpotFX\'s app) so this always works even after the record moves. A released room shows the banner below until someone takes it back.',
          'Release VERIFIES, it doesn\'t just command: after cleanup it reads real state back — is the SPECTRA stack actually down, are the external LedFX virtuals actually inactive (or the service not even running). If everything checks out, the button and banner behave as above. If a device could not be confirmed dark, a loud toast says so ("these lights may still be lit") and lists what failed — the room record still shows released (that part always succeeds), but treat an unverified release as needing a manual check of the flagged device.',
          'The way back — "Take back (SPECTRA)" on the banner — is the SAME guarded handover described above: readiness-gated, and still requires SPECTRA_HANDOVER_ARMED. Releasing is instant and unconditional; coming back is deliberate, same as any other handover. ONE difference since 2026-08-21: if a light cannot be reached at take-back time, the take-back no longer fails the whole room back to released — it commits over that light, names it on the amber strip at the top of every page (and in the toast, the Status page and the liveness endpoint), and keeps rechecking it so it joins on its own once fixed. See "A light the take-back had to skip". A take-back whose stack never comes up at all still fails back to released.',
        ],
      },
      {
        id: 'room-controls-bar',
        title: 'Room controls — Mode, Ambient, Scenes, brightness',
        keywords: 'dark mode light display mode lock dark_lock brightness multiplier dim undim ambient color colour dark colour second colour transition pace global room bar dimmer midsong mid-song trigger fallback scene change mode transitions analysed triggers only my triggers only full settings model force scene hold pin catch-up catchup ease release ramp snap read-back readback confirm confirmed unconfirmed partial straggler retry rate limit zigbee bulb name music wins precedence yielding holding partial transitioning resting state playing paused off always auto on during music auto-return three settings mode stale age verified verify honesty confirmed ago hue areas entertainment area group groups dining room which lights press hold long press tap cycle grouped button expand panel light bulb icon toggle spam delay debounce per-song preference fallback partial update PUT api patch merge home assistant curl script ambient_mode alias preserve overwrite reset',
        body: [
          'The compact strip above the release button, on every page — three press-and-hold grouped buttons (2026-08-17, his ask: related controls collapsed into one button each) plus a standalone room-wide Brightness dimmer.',
          'Mode groups the Hybrid/Dark/Light display-mode control with its Light-mode colour picker and brightness slider. It carries no text — the fill colour alone tells you the mode: white = Light, black = Dark, grey = Hybrid (a fixed accent border on every state keeps it readable as a button, whichever fill is showing). A short tap CYCLES the three modes (Hybrid → Dark → Light → …). Holding the button (~½s) opens the colour/brightness panel instead of cycling. The button\'s fill updates the instant you tap — cycling never feels delayed — but the actual change is only sent to the room after a full second with no further taps, so cycling past a mode on your way to another one never spams the room with modes you were only passing through; if you keep tapping, only the mode you land on is ever applied. See "Display mode — Hybrid, Dark, or Light" below for the mode mechanics themselves.',
          'Ambient is the light-bulb icon (💡). A short tap toggles it — on or off, nothing else (2026-08-30: the old three-setting dropdown is gone). Turning Ambient on or off is not instant on real Hue bulbs — it takes roughly 15 to 22 seconds — so while it is moving the button itself says "Turning on…" or "Turning off…". You never have to wait: tapping again during a transition CANCELS it and snaps the room straight to the new state, with no fade at all. See "Ambient" below.',
          'Scenes bundles the scene-change tier, Force Scene, and the global transition pace together. A tap always just opens the panel — by his own design, Scenes never cycles anything on a tap (unlike Mode), since there\'s no single "next" scene-change setting that would make sense to step through blindly.',
          'Every panel opens downward from its button, clamped to stay on-screen horizontally — it never runs off the side of a phone, however close to the edge the button sits. Tap outside a panel, or press Escape, to close it.',
          'Dark mode: see "Dark mode — force every background black" below.',
          'Brightness: a 0–100% room dimmer (legacy Brightness Multiplier action). It scales brightness/background_brightness UNIFORMLY at the write seams — every drift glide, every surge jump, and every scene fire\'s output — never the authored scene values or the engine\'s own carried baseline, so turning it back to 100% always restores exactly what was authored.',
          'Ambient: one on/off toggle, a separate "When music pauses" checkbox, and TWO colour swatches — the first for normal/hybrid use, a second marked "(dark)" that\'s held instead whenever Dark mode is also on (see "Ambient\'s dark-mode colour" below). Click either swatch to open LedFX\'s own colour picker (see "The colour picker"), solid only (a Hue entertainment stream only ever takes one colour). Full detail — what the toggle does, what "Turning on…" means, what interrupting one does, and every badge — is in "Ambient" below.',
          'Ambient Hue areas — inside the Ambient panel, below the two colour swatches — narrows Ambient to just some of your Hue entertainment areas instead of every live one; see "Ambient Hue areas" below.',
          'Transition: a flat MANUAL override for the room\'s default entry-blend ramp in ms (legacy ledfx_global_transition action) — wins over everything below when set above 0. Leave it at 0 (the default) to let "Transition @ low/high intensity" scale it by intensity instead — see "Intensity-scaled scene transitions" below.',
          'Transition @ low intensity / @ high intensity: the two bounds a scene\'s entry-blend ramp scales between by intensity, linearly, when that scene doesn\'t author its own entry ramp (Scenes → Phase Choreography → Override Blend, entry_ramp_ms) and Transition above is 0. See "Intensity-scaled scene transitions" below for the full mechanic, including why quiet flares land the LONGER transition and hard ones the SHORTER — and why the transition starts slightly before the trigger, not on it.',
          'Driving these from outside the app (Home Assistant, a script, curl): PUT /api/room-controls is a PARTIAL update — send only the fields you want to change and every other room control keeps exactly the value it already had. Nothing you don\'t name is reset, so a one-field write can never quietly drop your A/V-sync calibration or a Force Scene pin sitting next to it. The retired ambient_mode key ("off"/"always"/"auto") is still accepted as an alias for the on/off toggle — "auto" maps to the "When music pauses" behaviour — and if a request sends both the old key and the new one, the new key wins and the response says so.',
          'Scene changes: four ticks for what drives scene changes room-wide — three of them stack, one doesn\'t. "Transitions only" — a scene change on every song transition, nothing else. "Transitions + analysed" — transitions plus the analysed mid-song triggers "⟳ Generate" seeds (see the SPECTRA Triggers help). "My triggers only" — a PER-SONG preference, not an absolute: on a song where you\'ve placed any trigger of your own, ONLY your hand-placed triggers fire — transitions, analysed mid-song triggers, and flares are all silenced for that one song. On a song where you haven\'t placed one, it behaves exactly like "Transitions + analysed" instead — it never leaves a song silent. "Everything" (default) — every source, on every song: transitions, analysed mid-song triggers, your own hand-placed triggers, AND response-engine flares (charge/lull/drop/flare reactions — a scene\'s own tuned material). Nothing is deleted by moving between ticks — a lower tick just skips firing the higher tiers\' material room-wide.',
        ],
      },
      {
        id: 'drift-gradient',
        title: 'Drift gradient — the two-dimensional colour space',
        keywords: 'gradient 2d two dimensional drift square vertices vertex top bottom edge x axis time y axis intensity loop bounce rainbow select single limit save overwrite new picker drop drops kick jump extra step target energy',
        body: [
          'The square swatch next to Scenes in the room controls bar. A saved 2D gradient is what the room\'s colour drifts THROUGH when one is active — a square, not the usual single horizontal colour bar, with colours authored only along the top edge (high intensity) and bottom edge (low intensity); everything in between blends linearly. This is NOT a rotation control — there\'s no angle to set, only the two edges.',
          'Tap the swatch to open the picker: saved gradients as tiles (tap one to make it active), "Off" (the wheel-based colour journey drives the room as before — the unmodified default), and "New…" to start one from scratch. With a gradient open, each edge is the SAME gradient-stop picker used everywhere else in the app — drag/add/remove colour stops along it — plus a Loop/Bounce choice for how the drift travels along time, and "Save (overwrite)" / "Save as new…" / "Delete" below.',
          'While a gradient is active, the room\'s picker moves steadily along the TOP-TO-BOTTOM square as time passes (looping or bouncing per the gradient\'s own setting) and along top-to-bottom as the song\'s intensity changes — drifting toward the new position rather than snapping, re-aiming only when a trigger fires or the song transitions (not continuously chasing every fluctuation). Flares still jump the colour exactly as they always have — this is in addition to that, not instead of it.',
          'Drops kick it. On a drop — on every effect, wherever a gradient is active — the room does three things at once instead of waiting for its next slow step: the colour changes right there on the drop, the drift jumps a full extra step along time (looping or bouncing exactly as an ordinary step does), and the drift TARGET is pushed UP the square by how big the drop was — never down, never past the top. Where the colour actually IS still drifts up toward that target at its normal pace over the following steps: the drop moves the destination, not the room in one jump. With no gradient active, a drop does none of this and the wheel-based colour journey is untouched.',
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
        id: 'ambient',
        title: 'Ambient — one on/off toggle, and what happens in between',
        keywords: 'ambient on off toggle turning on turning off transition interrupt snap cancel '
          + 'phase hue hold lag press twice music pause auto return released unavailable',
        body: [
          'Ambient holds the room\'s Hue lights lit at a colour you pick, over the bridge directly, while every other device (WLED and the rest) keeps running the normal show. It is a plain ON/OFF toggle: tap the light-bulb button on the room bar. There is no third setting — the old "Off / On during music / Auto-return" dropdown was replaced on 2026-08-30 by this toggle plus one separate checkbox (below).',
          'IT IS NOT INSTANT, AND THE BUTTON SAYS SO. Turning Ambient on writes every Hue bulb one at a time, deliberately spaced apart (a burst of writes can be silently dropped by the Zigbee mesh — the bridge says OK either way), and reads each one back to confirm it actually took the colour. On a 17-bulb room that is about 15 seconds. Turning Ambient off is longer still, about 22 seconds, because releasing is a two-step ease rather than a cut: a brief dim fade, then a slower ramp toward whatever the room\'s live show is actually rendering right now, and only then does the bulb get handed back to the stream. While either is happening the button reads "Turning on…" or "Turning off…", so you can always tell it started.',
          'INTERRUPTING IS ALLOWED, AND IT SNAPS. The button is never disabled — tapping during a transition is not a mistake to be prevented, it is a real instruction. The transition in flight is cancelled at the next safe point (never part-way through writing one bulb) and the new state is applied straight away with every fade dropped: interrupt a gradual turn-off with ON and the lights go to full ambient brightness as fast as the confirmed writes can land, not after the fade you changed your mind about. The individual write spacing stays — that is the Zigbee mesh, not choreography — so a snap still takes a few seconds on a large room, but it never waits for the sequence it cancelled. Pressing three times quickly is fine too: the last press is what the room ends up doing, and only one transition ever exists.',
          'An UNINTERRUPTED turn-off still does the full two-step ease. Only interrupting skips it.',
          '"When music pauses" (the checkbox in the Ambient panel) is off by default. Turn it on and Ambient becomes the room\'s resting state: while the toggle itself is OFF, Ambient turns itself on whenever the music is confirmed stopped, and releases the instant it starts again — no manual toggling. This is the old "Auto-return" behaviour, kept exactly as it was but now something you switch on deliberately rather than a mode you can land in by accident. The toggle itself always wins: with Ambient ON, it holds regardless of what is playing.',
          'IF SPECTRA ISN\'T DRIVING THE LIGHTS (the room is released, or spot-effects owns it), a press cannot move a bulb — the button says so rather than pretending. Your choice is still saved, and it is applied for real the moment the room comes back to SPECTRA (a take-back, or a SPECTRA restart). Nothing is silently dropped.',
          'The badges below the swatches are unchanged and still tell you what the BULBS are doing, which is a different question from what the toggle says: purple "ambient: holding" means every claimed light is confirmed lit at the chosen colour right now; red "ambient: partial" means Ambient should be holding but the last check found at least one light not actually lit (hover to see which bulbs, by name) — or there was nothing to hold at all; amber "ambient: yielding" means the music-pause checkbox is standing aside for music; grey "ambient: transitioning" means a hold or release is physically in flight. Each carries a "· Ns/m/h ago" suffix — how long ago the room was last actually confirmed, whether by a fresh write\'s own read-back or by the independent recheck that runs every 30 seconds regardless of whether anything changed. That recheck only ever READS the bridge; a bulb you turned off yourself is reported honestly, never fought or re-lit.',
          'Brightness comes from the colour you pick — a paler pick reads brighter, a darker pick reads dimmer — at either swatch. Non-Hue devices keep running the show under every setting; Ambient only ever touches Hue.',
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
      {
        id: 'force-color',
        title: 'Force Colour — hold one colour set',
        keywords: 'force colour color set group pin lock hold stay same palette stop changing freeze rotation gradient drift journey',
        body: [
          'The "Colour" button in the top bar. Force Scene\'s twin one axis over: that one pins WHICH SCENE plays, this pins WHICH COLOURS it wears. They are independent — turn on either, both, or neither.',
          'Turning it on (or picking a different colour set while it\'s already on) applies those colours to the room IMMEDIATELY — you don\'t wait for the next scene change or flare. From then on it holds: every colour the room would otherwise pick for itself wears the pinned one instead. That covers a scene fire\'s colours, the sequencer\'s own colour roll, a flare\'s colour jump, and a trigger that selects a colour set. The slow colour drift around the wheel stops walking too, and stays where the pin put it.',
          'Pinning a SET holds exactly those colours, every time. Pinning a GROUP holds the POOL, not one member — the group keeps rotating through its own members on each colour change, exactly as it does normally. That is what a group is; if you want one fixed palette, pin a set.',
          'It beats the drift Gradient while it is on. The gradient isn\'t changed or cleared — a badge says "gradient paused by the pin", and it picks up again on its own the moment you turn the pin off.',
          'Ambient is unaffected either way: a Hue light being held at the ambient colour is driven straight from the bridge, so a colour pin neither reaches it while it is held nor is blocked by it once it isn\'t.',
          'Your own explicit actions still work — applying a set from the Colours page, or its ▶ Preview. They land as normal, but the response names the contradiction ("overrode force colour") and does NOT clear the pin, so the pinned colours come back on the next automatic change.',
          'If nothing happens, look for the badge under the picker — it always says why: "applied" names the set that just landed (and, for a group, which member it rolled); "not applied" means nothing was pinned yet, the pinned card no longer exists, or a pinned group has no usable member left (every one of them disabled).',
          'Pinning a colour set you\'ve marked Disabled still applies it — you pressed the button, you mean it — but the badge adds "⚠ overriding disabled colour set", the same way Force Scene names a disabled scene.',
          'Turn it off to let the room choose freely again — nothing about the colour set you were holding is changed; the room simply keeps the colours it is wearing and picks normally from the next change onward.',
        ],
      },
    ],
  },
  {
    id: 'builder',
    title: 'Timeline (song profiles)',
    keywords: 'timeline canvas triggers place edit profile builder song',
    intro:
      'The song timeline from the SpotFX Profile Builder, carried into SPECTRA whole: build a song\'s lighting profile on a zoomable timeline. Arm an event on a palette key, then place triggers with the mouse; circles show intensity, triangles show timing. Reads and edits go straight to the SpotFX app\'s own APIs (same process) — profiles, waveform, librosa analysis, palettes, setlists, and the live playhead over its WebSocket. Since 2026-08-24 pressing Save here ALSO updates what SPECTRA actually fires — see "Where your Timeline edits land" below.',
    entries: [
      {
        id: 'builder-save-syncs-to-spectra',
        title: 'Where your Timeline edits land',
        keywords: 'save sync spectra triggers fired copy two copies my triggers only stale old triggers reconcile provenance profile',
        body: [
          'A hand-placed trigger lives in TWO places: this timeline\'s song profile (the file you edit here) and the store SPECTRA actually fires from. Pressing Save now updates both — every trigger on this timeline is written into SPECTRA\'s firing copy in the same action, so an edit takes effect on the next play instead of only after a migration. Moving a trigger, changing its intensity, disabling it or deleting it all carry across.',
          'Three things deliberately do NOT cross. Triggers SPECTRA generated for itself from a song\'s analysis are never written back here and are never deleted by a save. Triggers you authored on the "SPECTRA Triggers" card below (rather than on this timeline) are left alone — a Timeline save can only remove what a Timeline save put there. And a trigger SPECTRA has no equivalent for — a retired event, or a mark placed slightly BEFORE the song starts — is skipped rather than guessed at: it stays exactly as you wrote it here, and simply doesn\'t fire.',
          'Saving is no longer the only thing that lands. Since 2026-08-25 syncing is a property of WRITING your triggers, not something a particular button does: an analysed/AI import, the automatic generation after a fresh capture, and the timestamp shift after a re-capture all reach the firing copy on their own, and so does anything else that writes a song\'s triggers. Before that fix an import wrote only the profile file, so an imported song kept firing its old triggers — or none.',
          'With one deliberate asymmetry, because deleting must stay something you MEAN. Only an explicit Save here can remove a trigger from the firing copy. Everything automatic adds and updates but never deletes — a background job that carries a partial list can never quietly take your work off the show. Re-importing a song is safe for the same reason: an analysed mark keeps the same identity every time it is computed, so a second import updates the marks it recognises instead of replacing the lot, and by default it leaves any mark you have since moved, retuned or disabled exactly as you left it.',
          'If SPECTRA is restarting or unreachable when you press Save, the profile still saves normally and the response says so; the next save (or the operator\'s catch-up pass) lands the change. Note that once a song has any hand-authored trigger, the "My triggers only" scene-change setting fires YOURS exclusively for that song and silences SPECTRA\'s own analysed ones — so a song you have just hand-tuned will look different from one you have not.',
        ],
      },
    ],
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
          ['Fire update', 'A placeholder for a future, purpose-built Update effect (not built yet): fires the ACTIVE scene\'s own ordinary Flare response, at DOUBLE the chosen intensity (capped at 1.0) — no target to pick. Works on every scene that already has a Flare response; one with none declared at all is a silent no-op, same as an empty Fire response band.'],
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
        keywords: 'lead time alignment anchor early start middle end momentary flare scene transition drop explosion timing begins finishes midpoint offset relocate',
        body: [
          'A trigger\'s own stored timestamp is the moment on the clock — but what actually LANDS there depends on which kind of change is firing, because three different kinds of change anchor to the mark in three different places. His settled rule, 2026-08-20:',
          '• A MOMENTARY FLARE anchors its first switch\'s END to the mark — the switch fires early enough that it finishes exactly on the trigger, then holds, then flips back afterward. Starts before the mark, on purpose.',
          '• A SCENE TRANSITION (Fire scene) anchors its MIDDLE to the mark — a registered phased effect\'s own payoff point, or the plain half-way point of an ordinary crossfade, lands on the trigger. Also starts before the mark, on purpose.',
          '• A DROP/EXPLOSION anchors its START to the mark — the explosion begins ON the trigger, never before it. This is the newest of the three, added after Black Hole was tried and then withdrawn as a "the timing feels right" reference for drops specifically (his words: "an explosion begins on the trigger mark rather than before it").',
          'None of the three is more "correct" than the others — a flare\'s payoff and a scene\'s midpoint are SUPPOSED to start early; only a drop is supposed to start exactly on time. If a drop still looks early after the fire itself lands on the mark, the cause isn\'t this alignment — it\'s something inside the effect\'s own choreography (what it visibly does as its phase ramps from 0 to 1), a separate, ongoing question from where the trigger fires.',
          'A Fire scene trigger can also carry its own offset (trigger_offset_ms, same field and sign convention as a flare kind\'s preview marker: negative = fire earlier, positive = fire later, 0 = coincident with the stored timestamp) that RELOCATES the mark this alignment targets, before the scene-transition midpoint rule above ever runs — so the two stack rather than replace each other. There\'s no dialog field to set it yet (API-only today), the same way the flare preview\'s own drag gesture arrived before this scene-change equivalent did.',
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
  {
    id: 'av-sync-page',
    title: 'AV Sync — measure the audio/visual offset with your phone',
    keywords: 'av sync audio visual offset latency delay measure phone camera microphone calibrate lights ahead behind flash pattern',
    intro:
      'A phone-first page that MEASURES how far the lights are ahead of or behind the sound, instead of arguing it. Your phone stands where you stand: its microphone hears the room and its camera sees the lights; the page reduces both to number streams on the phone and SPECTRA correlates them against what it itself played and wrote. The result is a number AND a statement of how sure it is. Nothing measured here is written into any setting — it is shown for you to act on.',
    entries: [
      {
        id: 'av-sync-what-it-measures',
        title: 'What the number means',
        keywords: 'sign ahead behind lag lead ms statement offset definition',
        body: [
          '"Lights are N ms AHEAD of the sound" means a light change you can see reaches the phone N ms BEFORE the sound it was meant to land with; "BEHIND" means after. Precisely: light lag (phone sees the light − SPECTRA wrote it) minus audio lag (phone hears the sound − SPECTRA\'s own audio hub heard it). The phone/server clock difference cancels in that subtraction, so it does not matter that the two clocks disagree by days.',
          'The audio reference is what SPECTRA itself hears on snapcast.monitor (what the speakers are playing now), the same stream its audio-reactive effects use — not Spotify\'s reported position and not the stored song, so the wandering xcorr offset never touches this measurement. The light reference is either the flash pattern SPECTRA drives on purpose, or (passive mode) the show\'s own writes.',
          'The result is a MEASUREMENT of your room from where the phone stood. It is not applied anywhere: no setting changes because of it. The finished record (numbers + statement) is saved so you can compare runs; what to do with it is your call.',
        ],
      },
      {
        id: 'av-sync-phone-steps',
        title: 'Phone steps, in order',
        keywords: 'how to tap permission allow camera microphone aim still start measure stop',
        body: [
          '1. Open SPECTRA on the phone (the address you always use) and tap "AV Sync" in the top bar. If the page says camera & mic are blocked on this address, follow "Camera & mic need https" below first — nothing else will work until then.',
          '2. Play music through the room the normal way (the measurement needs real sound going through SPECTRA\'s speakers).',
          '3. Tap "📷 Start camera & mic". The browser asks for Camera — allow — then Microphone — allow. The camera is the back camera; the mic is left raw (no noise suppression) on purpose. A small live picture appears with two level bars: sound and light. Both should move.',
          '4. Aim the phone so the lights you care about fill a good part of the picture (the crystal, the sconces, the strips — whatever you are judging). Hold the phone still; prop it on something if you can. Moving the phone mid-measurement blurs the result.',
          '5. Tap "⚡ Flash-pattern measurement (12 s)". Every light turns white on/off at random for 12 seconds while the music keeps playing, then the room comes back exactly as it was. Keep still. The number appears within about two seconds of the flashing ending.',
          '6. Read the Result card: the big line is the answer; the sentence under it is the honesty. Run it two or three times — if the runs agree within their ± you have a good number; if they scatter more than that, trust the scatter.',
          '7. Tap "■ Stop camera & disconnect" when done — this also releases the microphone and camera. Closing the tab does the same.',
        ],
      },
      {
        id: 'av-sync-secure-context',
        title: 'Camera & mic need https (the one thing that blocks this)',
        keywords: 'secure context https http blocked getUserMedia mediaDevices undefined chrome flag unsafely treat insecure origin tailscale serve voice mic',
        body: [
          'Phone browsers only expose the camera and microphone to pages on a secure address — https, or localhost. SPECTRA today is reached over plain http (for example http://<host>:8000/spectra/), so the browser hides the camera/mic entirely — the same reason the Settings page\'s voice mic button does nothing on a phone. The page detects this and shows the exact address you are on.',
          'Tonight, Chrome on Android: open a new tab and go to chrome://flags/#unsafely-treat-insecure-origin-as-secure — paste the EXACT address the page shows (scheme, host and port, e.g. http://serenity.tailb5ca89.ts.net:8000), set it to Enabled, tap Relaunch, then come back. This tells Chrome to treat that one origin as secure. iPhone Safari has no such switch.',
          'The proper fix is HTTPS in front of SPECTRA — a deploy step for firstmate, not a phone step: on the tailnet, `tailscale serve` puts a real certificate in front of :8000 so every phone browser just works (and the voice mic with it). Nothing in this build turns that on.',
        ],
      },
      {
        id: 'av-sync-privacy',
        title: 'Privacy — where the audio and video go, what is written, how long it is kept',
        keywords: 'privacy camera microphone disk retention network cloud stored recording delete',
        body: [
          'Raw audio and raw video NEVER leave the phone. The page reduces them in the browser to two small number streams — a microphone loudness envelope (about 90 numbers per second) and a per-frame camera brightness (one mean plus a 4×4 grid of region means) — and sends only those.',
          'Every hop: phone browser → the same-origin WebSocket to SPECTRA (/spectra/api/av-sync/ws) → the spot-effects reverse proxy on :8000 → the SPECTRA process on :8010, all on whatever network you already reach SPECTRA over (if that is your tailnet, the numbers cross the tailnet — the media never does). Nothing is sent to any cloud or third-party service, ever.',
          'Written to disk: exactly one file, storage/spectra/av_sync_measurements.json — finished measurement RECORDS (the numbers, the confidence statement, phone capability flags such as "frame capture time available", the browser\'s name). Never audio, never video, never frames, never the number streams. It keeps the last 100 records; older ones fall off automatically. (storage/spectra/av_sync_pattern.json briefly holds the pre-flash light snapshot — effect settings, no media — and is deleted when the room is restored.)',
          'Kept in memory while connected: about 60 seconds of the two number streams; dropped the moment you disconnect. The frame tap (below) keeps at most 8 still frames in memory, cleared on disconnect.',
        ],
      },
      {
        id: 'av-sync-confidence',
        title: 'How sure the number is, and what the error bars depend on',
        keywords: 'confidence error bars sigma systematic statistical repeat peak ratio ambiguity refused weak',
        body: [
          'Two kinds of uncertainty are reported separately, on purpose. STATISTICAL (the ±): from re-reading the lag on several sub-windows of the same capture — how repeatable this capture was. SYSTEMATIC (the "could be up to X ms further ahead / Y ms further behind" sentence): terms the arithmetic cannot see, each named with its bound, its direction and what it depends on — the phone\'s camera pipeline (much smaller when the browser gives a real frame capture time), the phone\'s microphone pipeline (smaller when the browser reports its input latency), camera exposure (the edge is seen about half an exposure late), bulb rise time (Hue fades, WLED snaps — what is in frame matters), and SPECTRA\'s own audio input latency. These are constant for a given phone and room, so a CHANGE between two runs is far tighter than either absolute number.',
          'The measurement REFUSES rather than guesses: a weak correlation (nothing stands out of the noise — too quiet, phone too far, lights not in frame), an ambiguous one (two lags fit about equally — why the flash pattern is random, never a steady blink), an unstable one (the lag moved mid-capture), or no server audio reference (SPECTRA not driving the room) all show "No number yet" with the reason, never a plausible-looking value.',
          'Best practice: music with clear beats, the phone within a few metres of both speakers and lights, the lights filling the picture, the phone still, three runs.',
        ],
      },
      {
        id: 'av-sync-pattern-vs-passive',
        title: 'Flash pattern vs passive',
        keywords: 'flash pattern random white passive show writes paused revert restore 12 seconds',
        body: [
          'Flash pattern (recommended): SPECTRA switches every live light to white and flips it on/off with RANDOM holds of 150–450 ms for 12 s, recording the exact time of every flip, then restores each light to exactly what it was showing — the same snapshot-and-revert discipline the Colour Set Preview and flare preview use. The show\'s own automatic scene/response/set changes are paused for those seconds so nothing fights the pattern. Random holds are what make the answer unique; a steady blink would fit at every multiple of its period and is refused.',
          'Passive: nothing flashes. SPECTRA uses its own recent instant writes (jumps and short glides) as the light reference while the show plays. It is free and continuous — the shape a future always-on camera would use — but only as good as the show\'s own edges, and the confidence gate will often say "no number yet". When it does produce a number, the same statement applies.',
          'WHICH ONE ANSWERS "DID MY APPLIED LEAD WORK?" — passive, never the flash pattern. The flash pattern measures the RAW ROOM: the audio-to-light offset as the room physically is, speakers and bulbs and phone, with no show clock in it at all. Its flashes are written straight over the write seam and never travel the corrected clock the A/V-sync lead lives on, so an applied lead cannot show up in a pattern reading. That is by construction, not something waiting to be fixed — and it is why re-running the pattern after an apply gives you the same number back, correctly.',
          'Passive mode is the one that rides the corrected clock: it reads the show\'s own writes while the music plays, and those go out through the trigger engine with the applied lead already in them — so a passive reading after an apply reflects it. Read it for the DIRECTION of what is left over, not for a tight figure: passive is the loose one (the show\'s own edges are whatever the music gave it), the pattern is the tight one. Both are still subject to the same named systematics — the phone\'s camera and microphone pipelines, exposure, bulb rise time — which do not change between the two.',
          'A live stream rather than a one-shot: the phone keeps streaming while the page is open, the estimate refreshes every second over the most recent window, and a fixed camera on the same network would speak the same messages — that is the path to continuous calibration, not a rewrite.',
        ],
      },
      {
        id: 'av-sync-apply',
        title: 'Applying the result — the "Apply this to the room" button',
        keywords: 'apply offset button dialogue adjust update setting lead earlier later direction current proposed undo read-back av sync lead calibration',
        body: [
          'Measuring is one press; APPLYING is a second, separate one. Nothing is ever written when a measurement finishes — the "Apply this to the room…" button under the Result opens a dialogue that shows you what would change before anything does.',
          'WHAT IT WRITES: SPECTRA\'s own A/V-sync lead (the room control av_sync_lead_ms). This is the only authored number in SPECTRA\'s show clock, and it is applied at exactly one place — where the clock feeds the trigger engine — so every automatic scene change, trigger and flare moves together. Until your first apply it is "none yet": the room runs exactly as it always has.',
          'THE DIRECTION SENTENCE, and what it means: the dialogue never shows you a bare signed number to interpret. It says, in words, "Lights will fire 120 ms EARLIER than they do now" (or LATER). That sentence is the thing to read. It follows from what was measured: if the lights reached your phone BEHIND the sound, they need to fire earlier by that much; if they arrived AHEAD of it, they need to fire later.',
          'CURRENT vs PROPOSED: both are shown side by side. The measurement is ADDED to whatever lead is already in force, never assigned over it — a measurement is taken with the current calibration already running, so a residual of +120 ms on a room already 50 ms early means 170 ms, not 120. That is what makes re-measuring after an apply do the right thing instead of undoing the first one.',
          'NO NUMBER, NO APPLY: if the instrument refused this run (weak, ambiguous, unstable, no audio or light lock), the dialogue explains which and offers no apply path at all. It never falls back to a previous run\'s number — earlier runs are listed only so you can see how stable the room is measuring.',
          'DECIDING: the run-to-run wobble (the ±) and the named directional systematics are shown as separate lines because they mean different things, with the recent runs and their spread beside them. Comparing two runs on the same phone is far tighter than either absolute figure — if you are chasing a change, compare runs.',
          'AFTER YOU PRESS: the value is saved through the ordinary room-controls save path and then read back from the room; the dialogue states what was actually written, and says so plainly if the read-back disagrees. A "↺ Put back" button returns the previous value the same way for as long as the dialogue stays open.',
          'CHECKING IT LANDED: the read-back above proves the number was SAVED; it does not prove the room moved. To see the lead in a measurement, measure again in PASSIVE mode with the music playing — that mode reads the show\'s own writes, which carry the applied lead. Re-running the FLASH PATTERN will not show it: the pattern measures the raw room and its flashes never travel the corrected clock, so it reports the same offset as before, correctly (see "Flash pattern vs passive"). Passive is looser than the pattern, so read it for direction, not for a tight figure.',
          'WHAT THIS IS NOT: it is unrelated to SpotFX\'s "Audio Latency" setting (which aligns audio capture for song analysis) and to the legacy "LedFX Trigger Buffer" (which compensated a write path SPECTRA does not use, and is read only by the retired legacy engine). Those are different jobs — not earlier versions of this number — and this dialogue neither reads nor changes either of them.',
        ],
      },
      {
        id: 'av-sync-per-device',
        title: 'Per-device — lining the fixtures up with each other',
        keywords: 'per device latency hue wled strip slower faster equalize equalise timing offset difference reference slowest measure one device apply',
        body: [
          'Different fixtures reach the light at different times — a Hue bulb over the bridge, a WLED over wifi, a strip on the desk. This panel measures each one on its own and then tells you what would make them land together.',
          'MEASURING ONE DEVICE: press "⚡ Measure <name>" and only that device flashes; everything else keeps playing the show. Point the phone at that fixture and keep still, exactly as for a whole-room run. Do the same for each device you care about. Repeat runs on the same device are welcome — the panel takes the middle value and shows you how much they scattered.',
          'WHY THE DIFFERENCE IS THE REAL ANSWER: every run measures (this light\'s lag) minus (the sound\'s lag), and the sound\'s lag is the same in every run — the same microphone, the same speakers, the same audio path. Subtract one device\'s run from another\'s and all of that cancels, along with the camera and phone uncertainties the two runs share. So the DIFFERENCES between devices are much tighter than any single absolute figure, and they are all the equalization needs.',
          'THE PROPOSAL: the SLOWEST device — the one whose light arrives latest — sets the pace and is left alone; every other device is asked to WAIT for it. That is not a preference, it is the only physically possible direction: nothing can send a frame to a light before the picture has been drawn. So every proposed offset is zero or positive (later), never negative.',
          'APPLYING is one press per device, and nothing is written until you press it. The proposal already accounts for offsets you applied earlier — a measurement is taken with those delays in the light path, so they are subtracted back out. That means re-measuring after applying proposes keeping what you set, not doubling it.',
          'AFTERWARDS THE WHOLE ROOM SITS LATER, by exactly the spread you closed — that is what holding the fast fixtures back does. That global shift is not this panel\'s job: go back to the whole-room measurement, run it again, and apply the room A/V sync lead. Per-device offsets line the fixtures up with each other; the room lead puts the agreed-on room where the music is.',
          'A NOTE ON EXPECTATIONS: whether the Hue lights really are slower than the WLEDs is exactly what this measures. Nothing in it assumes anything about device types — the ordering comes out of the numbers.',
        ],
      },
      {
        id: 'av-sync-frame-tap',
        title: 'Frame tap — the hook for the future camera work (not built)',
        keywords: 'aruco tags led mapping vision frames jpeg seam hook future calibration patterns',
        body: [
          'The later ArUco-tag / LED-position / ambient-effect mapping work is NOT built here — on purpose. What is prepared is the seam it will plug into: with the frame tap switched on (Privacy card, off by default), the phone sends small JPEG stills of what the camera sees, each stamped with its capture time, to SPECTRA\'s memory only (GET /spectra/api/av-sync/frame/latest shows the newest; at most 8 are held; cleared on disconnect; nothing on disk). Nothing in SPECTRA inspects or recognises anything in a frame today.',
        ],
      },
    ],
  },
  {
    id: 'devices-page',
    title: 'Devices — create and edit the lights themselves',
    keywords: 'device devices create edit add new wled hue e131 ddp udp dummy ip address pixel count refresh rate name rename grouping category timing offset parameters ledfx settings',
    intro:
      'One page for the fixtures: every device the room has, every parameter its driver actually accepts, its name, which groupings its virtuals belong to, and its timing offset. Everything for a device is on ONE tab — grouped inside it, never behind sub-tabs. The list shows only the devices the room actually uses; "Show all devices" reveals the rest.',
    entries: [
      {
        id: 'devices-live-or-stored',
        title: 'Read the banner first: is the room running?',
        keywords: 'live stored running not running activation applies now later ownership handover',
        body: [
          'The banner at the top of the page says one of two things, and it changes what a save does.',
          'THE ROOM IS RUNNING — SPECTRA owns the lights and the light stack is up. A save goes straight through to the running device AND is written to the config in one step; the fixture follows immediately.',
          'THE ROOM IS NOT RUNNING — nothing is driving the lights right now. A save is still kept: it is validated the same way and written into SPECTRA\'s own light config, and it comes up the next time the room is taken back. The page says so on every save. An edit made while the room is dark is never lost, and never claimed to have reached a fixture when it did not.',
        ],
      },
      {
        id: 'devices-in-use',
        title: 'Only the devices you use are listed — showing the rest',
        keywords: 'in use unused hidden show all devices expansion expand duplicate gap dummy mask foreground background clean up list clutter',
        body: [
          'The list shows, by default, only the devices the room can actually light. Press "Show all devices" to reveal the rest; the button says how many there are, so a hidden device is a number you can see rather than a silent absence. The list starts collapsed every time you open the page.',
          'WHAT COUNTS AS IN USE: a device is in use when it backs a virtual the scene engine can actually address — one that belongs to a grouping, or that a saved scene names directly. Nothing else is consulted; in particular the device\'s TYPE is not. Two of the dummies are genuinely in use because real rendering runs through them, and several real-looking entries are not.',
          'THE REST are mostly machinery inherited from the old LedFX setup: gap placeholders, and the mask / foreground / background layers that belong to a mapped virtual. They are not broken and nothing is wrong with them — they simply are not something a scene points at.',
          'IT IS LIVE, NOT A LIST. The split is worked out fresh every time the page loads. Put a device\'s virtual in a grouping, or save a scene that targets it, and it appears in the default view the next time you open the page — there is nothing to tidy or migrate.',
          'DUPLICATES are flagged, not removed: a device with the same name and the same type as another one, backing nothing itself, is marked "duplicate of ..." in the expanded list. There is no delete on this page — removing a device would tear down its virtuals and rewrite scenes — so naming it is deliberately the whole of it.',
        ],
      },
      {
        id: 'devices-parameters',
        title: 'The parameters, and why the list is always right',
        keywords: 'parameters fields schema validator required default range choices ledfx tunable base type',
        body: [
          'The fields you see are not a list someone typed here — they are read off each device driver\'s own definition, the same definition that decides whether a value is accepted. So the page can never offer a parameter that does not exist, or hide one that does, and a value it lets you enter is a value the device will take. Each field carries the driver\'s own description underneath it.',
          'BASE is what every device type shares: name, icon, centre offset, refresh rate and (for networked devices) the IP address or hostname. The section under it is what THAT type adds — a WLED\'s sync mode and timeout, a Hue\'s entertainment group name and port, an E1.31\'s universe and priority, a DDP\'s destination id, a UDP device\'s packet type. A field marked * is required.',
          'Six device types are offered: wled, hue, e131, ddp, udp and dummy. Those are the drivers this app actually ships. LedFX has more; their code is not here, so a device of one of those types could never come up — offering it would be offering something that cannot work. Serial devices (com port, baud rate) are absent for the same reason.',
          'A save sends only the fields you changed; everything else is left exactly as it was. If the driver refuses a value, the page shows the driver\'s own reason rather than a generic failure.',
        ],
      },
      {
        id: 'devices-groupings',
        title: 'Groupings and naming',
        keywords: 'grouping groupings category categories name rename virtual matrix strips singles hue',
        body: [
          'NAMING is the "name" field in the Base section — the friendly name shown everywhere else in SPECTRA. Renaming changes only that: the device\'s identity, its virtuals and its groupings all stay put.',
          'GROUPINGS are the categories (Matrix, Strips, Singles, Hue, …) that scenes and effects address. They belong to VIRTUALS — the things that render onto a device — so the page lists each of the device\'s virtuals with a tick box per category. Tick and untick freely; a change saves immediately.',
          'Only categories that already exist are offered. The page will never create one from a typed name, because a mistyped category would file a light somewhere nothing ever looks for it.',
        ],
      },
      {
        id: 'device-timing-offset',
        title: 'Timing offset — making the fixtures land together',
        keywords: 'timing offset latency network delay earlier later equalize equalise per device sign convention negative ms sync align',
        body: [
          'Different fixtures reach the light at different times: a Hue bulb over the bridge, a WLED over wifi and a strip on the desk do not all change at the same instant. This field is how you pull them into line.',
          'THE SIGN: NEGATIVE means this device fires EARLIER; positive means later; 0 leaves it where it is. That is the same convention as every other offset you drag in SPECTRA (a flare\'s mark, a trigger\'s mark) — negative is earlier.',
          'ONLY DIFFERENCES MATTER. A fixture can only ever be made to WAIT — nothing can send a frame to a light before the picture has been drawn — so asking for one device to be earlier is carried out by delaying all the others. The earliest device is never delayed at all. That has a consequence worth knowing: shifting EVERY device by the same amount changes nothing whatsoever, and no combination of these numbers can move the whole room against the music.',
          'MOVING THE WHOLE ROOM is a different setting: the A/V sync lead on the AV Sync page, which has the OPPOSITE sign (there, positive means earlier). Use these per-device offsets to make the fixtures agree with each other, then measure the room once more and apply the room lead to put the agreed-on room where the music is.',
          'The page shows, under the field, how long this device is actually being held back right now to match the rest of the room. A change takes effect on the next rendered frame — nothing to restart.',
        ],
      },
      {
        id: 'devices-create',
        title: 'Creating a device',
        keywords: 'create new add device wled hue ddp e131 udp dummy required fields virtual segment',
        body: [
          'Press "+ New", pick a type, and fill in the fields; the required ones are marked *. Every type needs a name; networked types need an address; most need a pixel count.',
          'Creating a device also creates the virtual that renders onto it, covering the whole device, so it is usable straight away. With the room running the device comes up immediately; with the room down it comes up the next time the room is taken back.',
          'There is no delete. Removing a device would tear down its virtuals and rewrite the scenes that address them, which is a bigger and less reversible action than this page is for.',
        ],
      },
      {
        id: 'devices-sonic',
        title: 'Talking to Sonic about devices',
        keywords: 'sonic agent chat voice device rename timing offset grouping create settings console',
        body: [
          'Everything this page can set, Sonic can set too — "make the hue lights fire 80 ms earlier", "rename the back strip to Sofa", "put the tv mapper in Strips", "what parameters does a wled device have". Sonic reads the same driver definitions and writes through the same checks, and reports back whether the change reached the running room or was stored for the next activation.',
        ],
      },
    ],
  },
  {
    id: 'room-builder',
    title: 'Rooms — the measured light-field map',
    keywords: 'room builder map mapping light field footprint emitter sconce axis floor ceiling calibrate camera phone photograph exposure lock where it shines',
    intro:
      'A room is a set of fixtures plus a MEASURED map of where each one\'s light actually lands. The map never records where the LEDs are — it records where they SHINE, photographed with everything else dark. That is why a sconce\'s spill onto the ceiling and the floor costs nothing extra: it is simply part of what that sconce lights.',
    entries: [
      {
        id: 'room-builder-what',
        title: 'What a footprint is, and what it is not',
        keywords: 'footprint grid relative luminance weight axis profile pose meaning units lux',
        body: [
          'For each fixture the map stores a small picture of where its light landed — a 64×36 grid of relative brightness, as your phone camera saw it — plus that picture collapsed onto the room\'s floor-to-ceiling axis, plus one number for the total light it contributed. The thumbnails on this page are that picture, normalized to its own peak, so you can tell at a glance which fixtures are mapped and roughly what each one covers.',
          'The numbers are RELATIVE, not lux. A phone cannot give absolute units, and effects only ever need ratios. What makes them comparable is that they were all taken from the same phone position with the exposure locked — which is why the page refuses to map at all if the camera will not lock, and why moving the phone means re-mapping.',
          'Nothing here estimates where a strip physically is. There are no coordinates, no metres, and no room drawing — deliberately. The effects read the measurement.',
        ],
      },
      {
        id: 'room-builder-devices',
        title: 'Choosing what to map',
        keywords: 'devices carriers chips pick select in use sconce emitter granularity tv mapper layers virtuals',
        body: [
          'The list is the things you run effects on — what you address in SPECTRA, not the fixtures underneath. One of them can span several fixtures: the TV mapper reaches the backlight and both kitchen sconces, and it is mapped and waved along as one continuous thing. Tap one to put it in the room.',
          'Anything whose chain reaches no actual light is never offered — a dummy is genuinely in use (it sits in the crystal\'s mapper chain) and is still nothing a camera could photograph. The page names what it left out. The Devices page still lists every fixture, because it answers the other question: what backs something driven.',
          'One of these is not necessarily ONE emitter: it can be mapped in parts, so a wave can run along it. A strip wrapped round the television can be a dozen. The ceiling and floor between them need nothing of their own, because their light is already in the footprints.',
        ],
      },
      {
        id: 'room-mapping-granularity',
        title: 'Mapping in parts: whole fixtures, segments or blocks',
        keywords: 'granularity segment block pixels parts strip tv television wrap auto whole device split emitters resolution how many',
        body: [
          'A strip wrapped round a television spans the direction a wave travels. Mapped as ONE emitter it can only be dimmed all at once — so the "Map in" control chooses, for THIS run, how finely each fixture is measured. It is a choice per capture, not a setting the system carries around.',
          '"Auto" is the default and decides per thing: segments for a strip, the whole of it for a bulb — except a strip configured as ONE segment, which auto maps in Blocks instead, because segments there would give a single piece and a single piece cannot show a wave travelling. "Whole carrier" is one measurement each and the fastest run. "Segments" measures each configured run of a strip on its own — a television wrap is usually three or four. "Blocks" cuts every strip into equal pixel blocks regardless of how it happens to be configured, which is what gives a wrap a real up-and-down resolution; 30 pixels a block turns a 560-pixel wrap into about nineteen emitters.',
          'Finer costs TIME, not brightness: each emitter is its own four-second dark-room capture, so nineteen emitters means the room is dark for about seventy-five seconds. The page tells you the emitter count and the seconds before you press, and a run past 120 emitters is refused rather than attempted.',
          'What is stored for a part is the PIXEL RANGE it covers — "pixels 20 to 39 of this strip" — which comes straight out of the fixture\'s own configuration. It is still never a position in the room: where that range\'s light lands is measured with the camera, exactly like a whole fixture.',
          'Whenever a run would come out as ONE piece for something with many pixels, the page says so before you press — that map is still real and worth keeping (it is exactly what a room-level dimmer wants), it just cannot show a wave travelling along the strip. The warning names how many pieces Blocks would give instead.',
          'Some fixtures are addressed through something that copies one picture onto every run of the strip. That cannot be lit — or dimmed — in parts, so mapping goes through the fixture\'s own strip instead, waking it for the capture and putting it back afterwards. The page says when it did that. It is not a workaround: a wave cannot travel along a copied picture at all, so the same strip is what a wave drives too.',
          'Re-mapping a fixture replaces everything previously measured for it, so a strip is always at one granularity and never driven twice.',
          'Mapping in parts needs SPECTRA to be driving the lights. The lamp that lights one range lives inside SPECTRA; if the room has been handed to the other side, the run is refused with that reason rather than half-done. Whole-fixture mapping works either way.',
        ],
      },
      {
        id: 'room-mapping-axis',
        title: 'Calibrating the axis: two taps',
        keywords: 'axis calibration floor ceiling tap vertical direction wave direction',
        body: [
          'Start the camera, press "Calibrate axis", then tap the picture twice: once on the floor, once on the ceiling. That is the whole calibration. It defines the direction a wave travels — position 0 at your first tap, 1 at your second — as a direction in the picture, not a height in metres.',
          'Without it a wave still runs, using plain image height as its axis, and the page says the axis is not calibrated. Two taps are better: they let you point the axis at the wall you actually care about.',
        ],
      },
      {
        id: 'room-mapping-run',
        title: 'Running a mapping sync — what happens to the room',
        keywords: 'map run sync dark black white settle capture seconds held restore revert abandon refuse exposure',
        body: [
          'Press "Map this room" and, for each fixture in turn: the whole room goes dark for about half a second, that one fixture comes up full white for about two seconds while the camera watches, and then THE SHOW COMES BACK before the next fixture starts. About four seconds per fixture. Hold the phone still for the whole run — every footprint in a map is only comparable to the others taken from the same position.',
          'It runs on the same held-room machinery every preview in this app uses, so the room is snapshotted before the first fixture goes dark and handed back afterwards. A dropped phone, a closed tab or a SPECTRA restart mid-run all land in that same recovery — your show comes back on its own, without anything having to be pressed.',
          'If the camera will not lock its exposure and white balance, the run is REFUSED before a single light changes, and the message names which capability the phone is missing. That is deliberate: with auto-exposure live, every footprint would be scaled by an unknown, silently changing factor and the whole map would quietly lie. If a lock is lost part-way through, the run stops rather than finishing on a changed scale.',
          'A fixture reported "clipped" was too bright for the camera at that exposure — its SHAPE is still good, its weight understates it. A fixture reported as adding no measurable light is either out of shot or not the fixture you thought it was.',
          'If the lights are released to Home Assistant, or a handover is in flight, mapping says so and tells you to take the room back on the ownership bar — it never turns that into an error code. Lose the room part-way through and the run stops there as a stated partial: everything already measured is KEPT, so taking the room back and pressing again only does the rest. The same is true of the three-minute hold limit a long run can reach.',
        ],
      },
      {
        id: 'room-mapping-privacy',
        title: 'Privacy — the camera stays on this phone',
        keywords: 'privacy camera video frames stored disk retention network recording microphone audio',
        body: [
          'No microphone is opened by this page at all — mapping needs no sound, and there is no audio code in it to switch on.',
          'Each camera frame is reduced IN THE BROWSER to a 320×180 greyscale image and only those bytes cross the same-origin connection to SPECTRA, where they live in memory and are dropped the moment you disconnect. Nothing is sent anywhere else.',
          'The only thing written to disk is the derived map: the footprint grids, the axis profiles, the weights and the capture context (which pose, whether the exposure was locked, when). Never a frame, never an image, never audio.',
        ],
      },
    ],
  },
  {
    id: 'room-effects',
    title: 'Room effects — the Dim Wave',
    keywords: 'room effect dim wave wavelength speed depth travelling sine brightness gain compose dimmer fixtures chips',
    intro:
      'A Dim Wave is a sine travelling along the room\'s floor-to-ceiling axis. Each fixture\'s brightness is that wave AVERAGED over everything the fixture actually lights, read from its measured footprint — so a wide wall sconce swells softly and a narrow one snaps, and neither needs a smoothing knob. Only fixtures that have been mapped can be driven.',
    entries: [
      {
        id: 'room-effects-knobs',
        title: 'The three knobs',
        keywords: 'wavelength speed depth units cycles axis direction ceiling standing wave no-op',
        body: [
          'Wavelength is in axis units: 1.00 is one full cycle from floor to ceiling, 0.5 puts two waves in the room at once.',
          'Speed is cycles per second, and positive travels toward the ceiling. 0 is a standing wave — each fixture simply sits at its own fixed point of the pattern, which is a good way to see what the map thinks each fixture covers.',
          'Depth is how far the trough dips. 0 changes nothing at all — exactly nothing, not almost nothing — and 1 takes the trough to black. The crest is always the room\'s own brightness: a dim wave only ever takes light away.',
        ],
      },
      {
        id: 'room-effects-run',
        title: 'Running one — what it does to the room',
        keywords: 'run start stop held hold heartbeat ceiling three minutes compose dimmer show underneath watchdog write cost',
        body: [
          'The wave rides ON TOP of whatever the show is already doing: each fixture\'s gain multiplies onto the show\'s own brightness at the one write seam, exactly the way the room brightness dimmer does. It never fires a scene, never picks a colour, and never pauses your triggers — a Dim Wave over the fish is one button, not a scene rebuild.',
          'While it runs the room is HELD by the same machinery every preview uses, and this page keeps a heartbeat alive. Close the tab or lose the connection and the room hands itself back on its own within about seventeen seconds. There is also a hard three-minute ceiling that no amount of heartbeating extends, so a wave left running by mistake is a brief nuisance rather than a lost evening. Leaving one on all night is not something this build does yet.',
          'The Run panel reports the measured write cost — how long one tick actually takes and how many writes a second it is making — because "a wave ticking every fixture is more traffic than any current room mode" was a named risk, not an assumption.',
          'The parameter watchdog is told exactly which fixtures\' brightness the wave owns while it runs, so a travelling wave is never "repaired" back to a fixed value underneath you.',
        ],
      },
      {
        id: 'room-effects-along-a-strip',
        title: 'A wave ALONG one fixture',
        keywords: 'per pixel mask strip tv television wrap along vertical segment granularity gradient single device spans',
        body: [
          'A fixture mapped in PARTS is driven per pixel: each measured range takes its own place in the wave, so a strip wrapped round a television dims from the bottom up rather than all at once. That is the difference the "Map in" control on the Rooms page makes — nothing here needs setting.',
          'A fixture mapped as a WHOLE still takes one gain, exactly as before. Both can run in the same wave; the Run panel says which fixtures are per-pixel and over how many pixels.',
          'Per-pixel costs less, not more. A fixture driven per pixel needs no write to the light at all — its gain rides the frame that was already being drawn — so a television split nineteen ways makes fewer writes a second than one sconce does. The Run panel reports the measured figures either way.',
          'It needs SPECTRA to be driving the lights, because the gain is applied inside SPECTRA\'s own render loop. If the room has been handed over, a wave over a part-mapped fixture is refused with that reason rather than running invisibly.',
        ],
      },
      {
        id: 'room-effects-kinds',
        title: 'Why there is only one effect here',
        keywords: 'kinds four colour rotation implode explode not built interface future',
        body: [
          'The map serves four kinds of spatial effect through one calculation: this Dim Wave, a travelling colour rotation, an implosion and an explosion. Only the Dim Wave drives lights in this build — the other three exist as the interface and nothing else, which is why the map stores the whole two-dimensional footprint rather than only the up-down profile the wave needs. Building them is a separate decision, not a switch on this page.',
        ],
      },
    ],
  },
];
