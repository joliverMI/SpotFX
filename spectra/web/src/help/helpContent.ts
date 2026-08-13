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
          'S1 shipped the app and the full tabbed scene editor: bindings, dice, responses, drift declarations, colour journey, test-fire with dry-run compile. S2 added the evolution engine: drift and responses EXECUTE, fed read-only from spot-effects — dark, recording every move. S3 (this build) adds light ownership and the safe handover: the machinery for SPECTRA to take the room is built, proven offline, and GATED OFF — spot-effects owns the lights until the owner\'s word arms and runs the switch. Until then the real Fire button here writes through the same external LedFX service.',
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
      'Left pane: scene list with search; right pane: the tabbed editor. Drafts live locally until Save — an unsaved dot marks edited scenes and leaving the page asks first.',
    entries: [
      {
        id: 'editor-toolbar',
        title: 'Toolbar: Save, Duplicate, Test Fire, Fire, Delete',
        keywords: 'test fire dry run real fire intensity slider',
        body: [
          'The intensity slider picks the axis value a fire resolves against, so ⚡ scenes can be previewed anywhere on the axis. Test Fire compiles at that intensity WITHOUT touching devices and shows the resolved bindings, dice rolls, and per-virtual writes. Fire (live) sends the same writes to LedFX — it exists for the owner; use Test Fire for checking work.',
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
        id: 'tab-drift',
        title: 'Drift tab — declarations the engine runs',
        keywords: 'creep follow wander slow evolution profile inline live legs',
        body: [
          'Drift cards state what evolves on its own while the scene holds: creep (bounded wander between lo–hi, bouncing or wrapping) and follow (the value tracks the music\'s energy arc through a drawn intensity→value curve). Declarations use NAMED profiles — one edit retunes every scene using it — with inline one-offs as the escape hatch. Cards are adjusted by telling the agent; the one graphical piece is a follow curve\'s shape, drawn right on the card.',
          'Since S2 the engine EXECUTES these declarations: when this scene is the engine\'s active scene, each card shows a live ● chip per virtual with the creep\'s current wander position. See the Evolution engine section for how legs run (dark until S3).',
          'The colour journey card also lives here — see the colour journey section.',
        ],
      },
      {
        id: 'tab-flares',
        title: 'Flares tab — the band strip',
        keywords: 'flare bands gain curve patch response intensity strip',
        body: [
          'Bands over the intensity axis decide the response when a flare fires. Drag a band\'s edges to move its window, drag the dot to set gain, double-click to remove, click an empty gap to add. The curve select picks the envelope (pulse spikes and returns; linear/ease land and hold). Param patches (⚙) are agent-authored — the strip shows they exist, the agent edits them. Re-roll dice and colour-set jump are per-class flags shown as chips; tell the agent to change them.',
          'Since S2 these bands EXECUTE: any ordinary trigger fire from spot-effects is a flare at that fire\'s intensity, and the band containing it applies — see the Evolution engine section for the full pass (re-roll, patch, gain, colour jump, carry).',
        ],
      },
      {
        id: 'tab-phase',
        title: 'Phase Choreography tab',
        keywords: 'transition crossfade anchor descriptive',
        body: ['Descriptive card: transition length, mode, and the anchor fraction where the payoff lands. Adjusted by telling the agent — durations and modes are numbers, not shapes, so they get no sliders here.'],
      },
      {
        id: 'tab-sequencing',
        title: 'Sequencing tab',
        keywords: 'sequencer curve likelihood dwell affinity genre',
        body: [
          'As shipped in the sequencer increment: the scene\'s likelihood curve (named profile / inline / flat / not sequenced) is graphical; dwell weight, genre multipliers, and affinity render read-only — adjust them by telling the agent. The status strip shows the engine\'s state. The S2 bridge now feeds it song transitions, section-energy intensity, genre buckets, and deferrals — but the sequencer stays dark until its own enabled switch is flipped (ask the agent).',
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
          'The band strip here is the scene\'s COLOURING on top of that arc, same idiom as Flares: the band containing the fire\'s intensity adds gain, patches, and re-rolls. A track change releases a lingering charge/lull automatically.',
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
        keywords: 'flare band gain pulse patch reroll colour jump carry baseline',
        body: [
          'The bridge classifies every spot-effects trigger fire: charge/lull/drop stay themselves, scene changes are observations, everything else is a FLARE. The band containing the fire\'s intensity executes in one pass: the scene\'s 🎲 values re-roll (correlated dice stay correlated) and jump; the band\'s param patches jump (a key lands on every device whose effect has that param); gain shapes brightness (pulse spikes and returns; linear/ease lands and holds); flares with the colour-set jump roll the shipped selector and JUMP to the pick — the keep-current rung never forces churn, and the room journey resumes from the new wheel point.',
          'Surges CARRY: patches, re-rolls, held gains, and colour jumps move the baseline drift resumes from. A surge on a followed value is an impulse the follow re-asserts from smoothly over its slew.',
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
          'GET /spectra/api/ownership shows the owner, any in-flight handover step, and the history trail; the Status page and spot-effects\' Debug page (ledfx-health) surface the same record. States: spot-effects owns · spectra owns · handing-over.',
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
        keywords: 'quiesce activate commit rollback failure single owner armed latch',
        body: [
          'Two steps, strictly ordered: quiesce the current writer and VERIFY it stopped (Hue DTLS session released, DDP sending stopped), only then activate the other (SPECTRA\'s in-process device layer + the shared audio hub — or, in reverse, restart LedFX). Any failure lands back at the old owner automatically — never two writers, never a split. The API refuses entirely until the process is armed (SPECTRA_HANDOVER_ARMED=1).',
        ],
      },
    ],
  },
];
