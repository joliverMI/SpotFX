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
        title: 'What works today (increment S1)',
        keywords: 'roadmap s1 s2 s3 engine bridge ownership',
        body: [
          'S1 (this build) ships the app and the full tabbed scene editor: bindings, dice, responses, drift declarations, colour journey, test-fire with dry-run compile. S2 adds the evolution engine that actually animates drift and responses, fed read-only from spot-effects. S3 hands SPECTRA the lights (owner\'s call). Until S3, spot-effects owns the room; the real Fire button here writes through the same external LedFX service.',
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
        title: 'Drift tab — declarations, adjusted via the agent',
        keywords: 'creep follow wander slow evolution profile inline',
        body: [
          'Drift cards state what evolves on its own while the scene holds: creep (bounded wander between lo–hi, bouncing or wrapping) and follow (the value tracks the music\'s energy arc through a drawn intensity→value curve). Declarations use NAMED profiles — one edit retunes every scene using it — with inline one-offs as the escape hatch. Cards are adjusted by telling the agent; the one graphical piece is a follow curve\'s shape, drawn right on the card.',
          'The colour journey card also lives here — see the colour journey section.',
        ],
      },
      {
        id: 'tab-flares',
        title: 'Flares tab — the band strip',
        keywords: 'flare bands gain curve patch response intensity strip',
        body: [
          'Bands over the intensity axis decide the response when a flare fires. Drag a band\'s edges to move its window, drag the dot to set gain, double-click to remove, click an empty gap to add. The curve select picks the envelope (pulse spikes and returns; linear/ease land and hold). Param patches (⚙) are agent-authored — the strip shows they exist, the agent edits them. Re-roll dice and colour-set jump are per-class flags shown as chips; tell the agent to change them.',
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
          'As shipped in the sequencer increment: the scene\'s likelihood curve (named profile / inline / flat / not sequenced) is graphical; dwell weight, genre multipliers, and affinity render read-only — adjust them by telling the agent. The status strip shows the engine\'s state; the sequencer stays dark until enabled and its music feed arrives with S2.',
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
        keywords: 'charge lull drop event classes bands',
        body: ['The other three event classes, same band-strip idiom as Flares. The classes fire from the music (via the S2 bridge); each class carries its own bands, re-roll flag, and (flares only, typically) colour-set jump.'],
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
    title: 'Colour journey (room + override)',
    keywords: 'wheel walk rotate palette drift creep hue override room',
    intro:
      'The room owns ONE continuous colour journey — a slow walk of the palette around the colour wheel (default: blue toward purple). Scenes ride it by default.',
    entries: [
      {
        id: 'journey-inherit',
        title: 'Inherit (default) and pace',
        body: ['An inheriting scene rides the room\'s walk, scaled by its pace factor — 0 holds the walk while that scene shows. Adjusted by telling the agent.'],
      },
      {
        id: 'journey-override',
        title: 'Override — a scene takes the pen',
        keywords: 'custody transition into out of snap',
        body: [
          'A scene may override the room journey outright: its own pace and direction while it holds. The override takes CUSTODY of the wheel, never a fork: entering, the scene\'s journey starts from wherever the room\'s walk had reached (no snap — the palette change itself rides the normal scene crossfade). Leaving, the room\'s own journey resumes from wherever the override left the wheel — it never snaps back. One continuous story; only who steers changes.',
        ],
      },
      {
        id: 'journey-rainbow',
        title: 'Rainbow sets pause the walk',
        body: ['Rainbow and achromatic palettes have no wheel position, so the walk pauses while one is live and resumes when a chromatic set returns.'],
      },
    ],
  },
  {
    id: 'status-page',
    title: 'Status page',
    keywords: 'health ownership bridge liveness',
    intro:
      'A placeholder status surface for S1: scene count, light ownership (spot-effects until the S3 handover), bridge state, sequencer state, and the room journey. The real liveness endpoint — per-virtual frame-flush freshness — ships with S3.',
  },
];
