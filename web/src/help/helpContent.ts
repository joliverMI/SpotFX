/** ═══════════════════════════════════════════════════════════════════════
 *  SpotFX in-app Help content — the single source of truth for user docs.
 *
 *  NOTE FOR FUTURE AGENTS (Claude/Opus & friends):
 *  Whenever you add or change a user-facing feature — a page, a keyboard
 *  shortcut, a mouse/long-press gesture, a filter syntax, a mode, a
 *  setting — UPDATE THIS FILE in the same change. This is part of "done".
 *  Rules of the road:
 *    • Keep entries short, imperative, and concrete ("Right-click places
 *      the armed event"), not marketing prose.
 *    • Shortcuts/gestures go in `table` rows with `kbd: true`; filter
 *      syntax in `table` rows with `kbd: false` (renders as one chunk).
 *    • `keywords` holds hidden search synonyms (e.g. "hotkey keybinding");
 *      the search is already typo-tolerant, so don't add misspellings.
 *    • `id`s are deep-link targets used by <HelpLink topic="..."/> buttons
 *      around the app — don't rename an id without updating its callers
 *      (grep for `topic="<id>"`).
 *    • Structure: top-level section per page/area → subsections → entries.
 *  ═══════════════════════════════════════════════════════════════════════ */

export type HelpRow = [keys: string, description: string];

export type HelpEntry = {
  id: string;
  title: string;
  /** Paragraphs of body text. */
  body?: string[];
  /** Two-column rows: shortcut/syntax → what it does. */
  table?: HelpRow[];
  /** true → first column rendered as keyboard keys (split on "+" and " / "). */
  kbd?: boolean;
  /** Hidden search synonyms. */
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
  /* ── Getting started ─────────────────────────────────────────── */
  {
    id: 'overview',
    title: 'Overview & Concepts',
    keywords: 'getting started intro basics what is',
    intro:
      'SpotFX turns Spotify playback into music-synced lighting. It analyzes each track (beats, onsets, sections, energy) and fires lighting events on LedFX/Hue devices at exactly the right moments.',
    entries: [
      {
        id: 'concept-events',
        title: 'Events',
        keywords: 'composite sequence parallel random scene morph',
        body: [
          'An event is a reusable lighting action — a single effect, a sequence of steps, a beat-synced sequence, a morph, or a scene. Events are built on the Events page as a nested tree (sequence / parallel / random groups containing actions), similar to Home Assistant automations.',
        ],
      },
      {
        id: 'concept-triggers',
        title: 'Triggers & profiles',
        keywords: 'song profile timestamp intensity',
        body: [
          'A trigger fires an event at a specific timestamp in a specific song, with an intensity (0–1). The set of triggers for a song is its profile. The Profile Builder is where you place and tune triggers on a timeline.',
        ],
      },
      {
        id: 'concept-intensity',
        title: 'Intensity & section energy',
        keywords: 'energy brightness level 0-1',
        body: [
          'Every trigger has an intensity from 0 to 1 that scales the event (brightness, size, speed — whatever the event maps it to). Librosa analysis assigns each song section an energy level; new triggers default to the energy of the section they land in.',
        ],
      },
      {
        id: 'concept-labels',
        title: 'Labels & color sets',
        keywords: 'tag tags palette colors filter',
        body: [
          'Events and color sets carry lowercase labels (e.g. "chorus", "quiet"). Label filters pick which color sets an event may draw from — see Filter syntax below. Color sets are named palettes managed on the Color Sets page.',
        ],
      },
      {
        id: 'concept-triggerless',
        title: 'Triggerless',
        keywords: 'automatic machine learning generated analyzed',
        body: [
          'Songs without a hand-built profile can still react: Triggerless mode maps analyzed features (bass, snare, sections) to event slots via the embedded pipeline and its training profiles.',
        ],
      },
    ],
  },

  /* ── Shared top bar ──────────────────────────────────────────── */
  {
    id: 'topbar',
    title: 'Top Bar (all pages)',
    keywords: 'status bar header play pause activate dinner party ambient scene color lock track time intensity',
    intro:
      'The slim bar under the navigation is shared by every page: the master controls plus live status, so you never have to switch to Now Playing to check or pause things.',
    entries: [
      {
        id: 'topbar-controls',
        title: 'Controls',
        keywords: 'play pause round button icon toggle dinner party ambient long press',
        table: [
          ['▶ / ⏸', 'Activate — master switch for trigger firing. Green ⏸ = active (click to pause), ▶ = paused (click to resume).'],
          ['🍽️', 'Dinner Party — ignore song triggers; use automatic ambient lighting.'],
          ['💡', 'Ambient Mode — hold the Hue groups at a static full-brightness color. Short press: all groups on/off. Long-press: pick individual groups (see "Ambient Hue groups").'],
          ['🌗', 'Display mode — cycles Default → 🌙 Dark → ☀️ Light. The icon flips immediately but the mode commits one second after the last click, so cycling past a mode never applies it. See "Dark / Light mode" under Settings.'],
        ],
        kbd: false,
      },
      {
        id: 'topbar-status',
        title: 'Status readouts',
        keywords: 'scene color set chip lock locked suspect recovering idle song artist truncated progress duration intensity score color coded',
        body: [
          'Chips show the active Scene and Color Set (dot = marker color; hover the scene chip for the active Scene Group). The lock indicator is the audio-sync monitor: green Locked, amber Suspect, red Recovering; gray "Lock idle" means an offset is held but the matcher is quiet, "No lock" means no live match data yet.',
          'The right side shows the current track ("Title — Artist", truncated when long) and position / duration.',
          'The ⚡ score is the intensity of the last fired trigger (0–100), color-coded cool blue (low) → hot red (high). It clears on track change.',
        ],
      },
    ],
  },

  /* ── Search & filters ────────────────────────────────────────── */
  {
    id: 'search-filters',
    title: 'Search & Filter Syntax',
    keywords: 'find query special characters',
    intro:
      'Search boxes across the app (Events, Color Sets, Set Lists, Devices, song pickers…) do live, case-insensitive substring matching over the listed fields — type any part of a name. Label-filter fields have extra syntax:',
    entries: [
      {
        id: 'filter-labels',
        title: 'Label filter syntax',
        keywords: 'exclude not minus comma separator negative',
        body: [
          'Used wherever you filter by labels — e.g. the trigger dialog\'s color-set filter and Triggerless event slots.',
        ],
        table: [
          ['chorus, big', 'Comma-separated labels: ALL listed labels must match.'],
          ['-quiet', 'Minus prefix excludes: matches anything NOT labeled "quiet".'],
          ['(blank)', 'No filtering — everything is eligible.'],
        ],
        kbd: false,
      },
      {
        id: 'filter-search-boxes',
        title: 'What each search box matches',
        body: ['Each page\'s search box matches these fields (case-insensitive, any substring):'],
        table: [
          ['Events', 'Event name or any label. Type chips (Single / Sequence / Beat Seq / Morphs / Scenes / Devices) narrow further.'],
          ['Color Sets', 'Set name or any label.'],
          ['Set Lists', 'Name or Spotify context URI.'],
          ['Devices', 'Category name; the import dialog filters by virtual id.'],
          ['Song pickers', 'Track title or artist (Builder, Triggerless).'],
          ['Comma lists', 'Label and genre inputs are comma-separated; whitespace is trimmed.'],
        ],
        kbd: false,
      },
    ],
  },

  /* ── Profile Builder ─────────────────────────────────────────── */
  {
    id: 'builder',
    title: 'Profile Builder',
    keywords: 'timeline canvas triggers place edit',
    intro:
      'Build a song\'s lighting profile on a zoomable timeline. Arm an event on a palette key, then place triggers with the mouse; circles show intensity, triangles show timing.',
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
              'When the picked event is the fixed Drop, a Drop 🎯 picker appears: choose a Scene Group the drop falls back to for this trigger instead of the global drop group (see "Charge / Lull / Drop events").',
              'The ↗ next to the event picker opens the chosen event\'s editor in a new tab, so the trigger you\'re editing stays put.',
            ],
          },
          {
            id: 'override-blend',
            title: 'Override Blend',
            keywords: 'blend ramp stretch scale slow fast transition next trigger no action paint brush bracket',
            body: [
              'A trigger with Override Blend on rescales its event\'s ramps and delays — proportionally — so the last ramp completes exactly at the next enabled trigger (or at song end when none follows). An event that would ramp 200 ms then 300 ms, fired 5 s before the next trigger, ramps 2 s then 3 s instead; if the next trigger comes sooner than the natural timing, ramps compress to fit.',
              'Beat-timed steps stay on their beats — only their ramps scale — so completion is exact only for ms-timed events. The event\'s fire offset (latency trim) is never scaled.',
              'Use the built-in "No Action" event on a trigger to end a blend span without changing the lights.',
              'On both timelines the blended span is tinted in the event\'s color from the blend trigger to the trigger that ends it.',
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
              'The Colors picker in the trigger dialog overrides which Color Group a Scene Group pulls its colors from — for that one trigger. While the trigger\'s fire resolves "Scene Group\'s Color Group" (the default on Set Color actions), the picked group is used instead of the group\'s designated one.',
              'Blank (the default) changes nothing — the group\'s normal colors apply. If the picked Color Group was deleted, the fire falls back to the normal choice instead of failing. The override lives on the trigger, so the same Scene Group can be blue at one trigger and gold at the next.',
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
              ['` (backtick)', 'Toggle follow mode (auto-scroll with playback) vs. manual zoom. Turning follow off freezes the current view in place; use Full Song to zoom out.'],
              ['Ctrl+F', 'Also toggles follow mode.'],
              ['Full-song bar', 'Drag the zoom region\'s center to pan — this switches follow off. Drag its edges to resize; in follow mode edge drags adjust the window size and look-ahead instead.'],
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
              ['Right-click', 'Place the armed event (on a marker: reassign it). With the blend brush armed ([ / ]), a marker right-click paints/clears Override Blend instead.'],
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
            title: 'Other builder controls',
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

  /* ── Events & Event Editor ───────────────────────────────────── */
  {
    id: 'events',
    title: 'Events & Event Editor',
    keywords: 'composite tree node actions morph scene sequence',
    intro:
      'The Events page lists every lighting event; the editor builds an event as a nested tree of groups and actions (Home-Assistant style).',
    entries: [
      {
        id: 'events-list',
        title: 'Events page',
        keywords: 'chips fire test lock fixed ai exposed',
        body: [
          'Search matches name or labels; type chips narrow by kind. Row icons: 🔒 built-in (body read-only — settings still editable), 🌳 composite tree, ⚡ energy level, AI = exposed to AI trigger generation. ▶ test-fires the event immediately.',
          'Create buttons: + Random / + Sequence / + Parallel / + Intensity start a new composite event with that root group; + Scene Group starts a group of Scene Updates (see "Scene Groups"). The Scenes chip includes Scene Groups.',
          '⤵ Import Scene converts a LedFX scene into a starter Morph Set event: pick the scene from the dropdown and the importer back-solves its live per-virtual state into editable morph lanes, then opens the new event.',
        ],
      },
      {
        id: 'events-editor',
        title: 'Editing an event',
        keywords: 'undo redo save fire duplicate preview drag reorder weight scope highlight flash glow green reference open link new tab',
        body: [
          'Edits are drafts — Save writes to the server; ▶ Fire is disabled while dirty because firing uses the stored event. ▶ Preview (between Duplicate and Delete) fires the CURRENT DRAFT as-is, without saving — it works on new and dirty events. Drag cards to reorder; every action can be copied and pasted into any track of any event (cross-tab too).',
          'Every level of the tree has its own ▶ preview between its ⧉ and ✕ buttons: an action card fires just that action; a Parallel lane fires immediately (offset ignored); a Sequence step fires with its delay skipped and no group revert; a Random option is force-picked (energy gate ignored); an Intensity Chooser lane is force-picked (threshold ignored); a morph/scene lane rolls one of its alternatives; a Scene Group member fires that member scene. Nothing is saved — previews use the live draft.',
          'The block you just added, edited, moved or pasted glows green and fades over 5 s, so you can spot where the change landed in a big tree.',
          'Cards that reference something else — an event_ref or a set_color — show a ↗ button that opens the referenced event or color set/group in a new tab (a new tab so your unsaved draft stays put).',
          'Group types: Sequence (children in order, ms or beat delays), Parallel (all at once, per-child offset), Random (weighted pick of one option), Intensity Chooser (the trigger\'s intensity picks one threshold lane — see "Intensity Chooser"). Scopes cascade: a child with no target inherits the nearest group/lane target.',
          'Sequence steps in ms mode can also wait for scene "updates": set "or N updates" next to the delay and the step fires after N scene-family fires (scene picks, Update/Reset Scene, flares, Scene Morph) OR after the ms delay — whichever comes first. Delay 0 waits on updates alone (a track change releases it). Beats mode and the classic sequence editor don\'t have this. Typical use: Scene Morph +1 → wait "4000 ms or 2 updates" → Scene Morph −1 back.',
        ],
        table: [
          ['Ctrl+Z / Ctrl+Shift+Z', 'Undo / redo draft edits.'],
          ['Esc', 'Close the add-action dialog.'],
          ['Enter', 'In the add-action dialog, picks the action when the search narrows to one.'],
        ],
        kbd: true,
      },
      {
        id: 'events-builtin',
        title: 'Built-in (🔒) events',
        keywords: 'built-in fixed lock read-only settings color name label energy offset reset charge lull drop update reset scene flare no action',
        body: [
          'The 🔒 events — Update Scene, Reset Scene, the three Flares, Charge / Lull / Drop, and No Action — have a body the app defines, so their tracks are read-only and they can\'t be deleted. Their "Event settings" panel is yours, though: name, timeline color, labels, energy level, AI-exposed and fire offset all save like any other event, and the timeline color is what the Builder paints their triggers with.',
          'Saved settings are stored as an override layer (storage/fixed_event_overrides.json) rather than a copy of the event, so app updates to the built-in behavior still reach you. "↺ Reset settings" in the editor header drops the overrides and restores the stock values; a field you set back to its stock value stops being stored at all.',
        ],
      },
      {
        id: 'events-actions',
        title: 'Action types',
        keywords: 'event_ref ledfx scene ambient transition effect param morph color device settings',
        table: [
          ['event_ref', "Fire another event's action pool."],
          ['morph_step', 'Multi-target aspect changes (brightness / reactivity / blur / color / bg color / effect / shape), absolute or nudge, with ramps. Shape sub-fields cover radial (star, twist, polygon) plus blackhole/orbits/fireworks (swirl, horizon size, field radius, blob size, offsets); "Edge / particle count" is one sub-field that lands on radial\'s polygon edges, orbits\' particle count, or fireworks\' burst size — whichever the running effect has. On radial (no reverse param), Reverse reverses the full perceived motion — it flips the sign of Spin AND of Twist (the twist sign drives the apparent rotation of the scrolling spiral): On = reversed = negative, toggle = negate; magnitudes are preserved and an explicit Twist in the same step wins. Flip stays rotation-only (sign of Spin, On = positive). The Reactivity aspect has a Shape-style per-param menu: add any reactivity param (Spawn Rate, Beat Burst, Accel, Edge Speed, …), set it exactly, bind it to a signal (⚡), or give it its own nudge — per-param entries win over the single spread slider. Nudge amounts are bindable too: ⚡ maps the magnitude to a music signal, 🎲 rolls a fresh random magnitude every fire, and the +/− toggle flips the nudge direction 50/50 per fire (works alongside bounce — see "Value bindings").'],
          ['morph_color', 'Rotate the showing colors around the hue wheel (180° = complementary). Degrees is bindable: ⚡ maps the rotation to a music signal, 🎲 rolls a fresh random rotation every fire, and the binding\'s +/− toggle randomizes direction (see "Value bindings"). "Morph background" (on by default) includes the BG color in the rotation; off leaves every effect\'s background untouched — FG and accent still rotate.'],
          ['scene_morph', 'Step the ACTIVE Scene Group forward/backward N scenes and fire the result (normal First/Rest). No-op when no group is active or Force Scene holds a single scene; advance 0 re-fires the current member (Rest lane).'],
          ['set_color', 'Apply a saved Color Set, or pick one from a Color Group. Instead of a specific card the picker also offers "Scene Group\'s Color Group" (default — pull from whatever Color Group the active Scene Group designates, falling back to the current group) and "Current Color Group" (re-use the last group any Set Color fired from).'],
          ['ledfx_scene / ledfx_ambient', 'Activate a LedFX scene / ambient behavior.'],
          ['ledfx_ambient_color', 'Applies the complementary of the current ambient color.'],
          ['ledfx_global_transition / ledfx_effect_param', 'Set the global transition / a single effect parameter.'],
          ['device_settings', 'Apply raw device settings.'],
          ['brightness', 'Set or nudge the per-device Brightness / BG Brightness multipliers that scale the Color Set values. See "Brightness action".'],
          ['sequence / parallel / random group', 'Containers — run children in order / at once / pick one by weight (random options can be energy-gated and tilted).'],
          ['intensity_chooser', 'Container — the firing trigger\'s intensity picks exactly one threshold lane; that lane\'s actions fire together. See "Intensity Chooser".'],
          ['light_mode_chooser', 'Container — the room\'s resolved Dark/Light mode picks exactly one 🌙/☀️ lane, re-checked at fire time. See "Light Mode Chooser".'],
        ],
        kbd: false,
      },
      {
        id: 'events-scene-groups',
        title: 'Scene Groups',
        keywords: 'scene group rotate cycle bounce wrap weighted random start members force scene morph active color group designate palette',
        body: [
          'A Scene Group is an event holding an ordered set of Scene Updates. Firing the group advances its cursor one member and fires that scene with normal First/Rest lanes — a newly rotated-to scene runs First, a repeat runs Rest. The picked member becomes the "last scene", so flares and Update/Reset Scene act on it as usual.',
          'Modes mirror Color Groups: Cycle steps in order (wrap loops around, bounce reverses at the ends) and never re-lands on the scene already showing; Random (weighted) picks every member randomly by weight — with "exclude current from next" on (the default) it never repeats the scene just shown. The cursor lives in memory and keeps rotating across songs (unlike Color Group cursors, which reset per track).',
          'Cycle mode\'s "random start" checkbox randomizes where the cycle begins: whenever the group is freshly called (it wasn\'t the active scene group), the first pick is a random member and cycling continues from there, instead of resuming the persisted cursor.',
          'The group that fired last (or is held by Force Scene) is the ACTIVE group — Scene Morph actions step it. Picking a plain Scene Update directly clears the active group. Members that were deleted or are no longer Scene Updates are skipped automatically.',
          'A Scene Group can also designate a Color Group (the "color group" picker in its editor). Set Color actions left on "Scene Group\'s Color Group" (the default for new ones) pull from that group while this Scene Group is active — so switching Scene Groups re-themes the room\'s palette without editing any events. When no group is active, or the active one designates nothing, those actions fall back to the current (last-fired) Color Group.',
          'Dark/Light: the "mode 🌗" select is the group\'s default display mode (see "Dark / Light mode" under Settings), and the 🌙/☀️ group pickers swap in a different Color Group while the resolved mode is Dark or Light — so a group can carry a dimmer palette for dark evenings and a fuller one for light.',
          'Ramp: the group\'s "Ramp" override (Event settings) forces one transition speed on every member scene fire; a member scene\'s own override still wins. Bindable ⚡/🎲 — see "Ramp overrides".',
        ],
      },
      {
        id: 'charge-lull-drop',
        title: 'Charge / Lull / Drop events',
        keywords: 'charge lull drop phase buildup build payoff snap fixed built-in ramp rockets horizon implode explode spin-up',
        body: [
          'Three fixed built-in events (🔒 Charge, Lull, Drop) drive a build→hold→payoff choreography on the phase-capable effects — Blackhole, Orbits, Radial, Fireworks, Squiggles, Dancer and Eye. Fire Charge on a buildup, Lull at the peak hush, Drop at the impact: every SpotFX device currently running one of those effects plays its own version of the arc. Devices on other effects are untouched.',
          'Per effect — Blackhole: charge forces inward infall while the event horizon swells until it swallows the whole panel black (the halo ring sweeps ahead of the dark, brightening and thickening as it grows); lull holds the black; drop pinches the horizon to a point, explodes a burst of blobs from the center and eases the horizon back. Orbits: charge grows the population to 10 blobs then sheds down to a single one; lull sends that blob slowly spiraling into the center, shrinking; drop is a big 3× explosion — triple the configured population erupts from the center, two thirds blast fully off the panel as ballistic ejecta while the boost decays (~2.4 s), and the remaining third settles into orbit. Radial: charge spins the pattern up in its set direction; lull implodes it to a held center point (same warp as the transition implode); drop blooms it back out. Fireworks: charge raises the launch rate while shrinking the bursts; lull goes near-dark except for 3 slow rockets crossing from the edges past the center, dimming with comet trails; drop explodes each rocket into a giant firework in its own color.',
          'Squiggles: charge makes the silhouette walls solid — chains bounce back inward instead of exiting — while the population climbs; lull is an old-TV switch-off (the picture squashes vertically to a bright line, the line pinches to a held phosphor dot); drop erupts a fan of chains from the center and everything returns to normal. Dancer: the arc is part of the dancing — charge intensifies the moves themselves, lull sinks the dancers into a coiled deep-squat setup, and the drop is a spectacular payoff stunt per dancer: a huge star jump, a leap landing in the splits (ballet/tango/salsa/tai chi), or a low breakdance freeze-spin (hip hop/kpop/robot/floss), with impact flames on the landing. Eye: charge reverses the flames — they stream in from outside and are absorbed while the iris swells ~30% and the pupil shrinks to half; lull sends the gaze back to center and both eyelids close together from above and below (a little fast at first, slowing, pausing just as they overlap the iris, then shutting to a lash line); drop snaps the lids open with a huge flame explosion.',
          'The 1D strips play the same arc: Blackhole Strip\'s growing horizon sweeps a brightening white halo flash through the sample ring then swallows the strip black (phosphor dot lull, sweep-back + blob eruption on the drop); Orbits Strip swells to 10 blobs, sheds to one that falls to the strip middle, then bursts back with each re-added blob\'s implosion fragments; Fireworks Strip ramps its launches, goes dark behind two slow rockets crossing from the strip ends, and explodes each into layered giant pairs. One Charge/Lull/Drop fire drives every phase-capable device — matrices and strips — together.',
          'The build is ramp-driven: Charge maxes exactly at the end of its ramp (Settings → phase_charge_ramp_ms, default 4000; lull 2500, drop 400). Better: give the Charge/Lull trigger Override Blend — the phase ramp then stretches to exactly the gap to the NEXT trigger, so the charge peaks the instant the lull fires and the lull finishes coiling the instant the drop hits. All migrated Charge/Lull triggers (and triggerless-generated ones) have it on; Drop never blends — it stays a snap. A Drop resets the effect back to normal by itself, so repeated Drops always re-fire.',
          'Nothing can stay stuck mid-arc: every effect carries an orphan watchdog — a charge or lull whose payoff never arrives (lost write, skipped track, no drop trigger) quietly releases itself ~12 s after its build completed (60 s absolute cap), each effect via its gentlest exit: the blackhole pinches out without the burst, orbits ease back to their ring, radial blooms back open, the rockets burn out, squiggle walls reopen, the dancers rise from the crouch, the eye\'s lid slides back open without the explosion. SpotFX also clears any un-dropped charge/lull on track change, and stale phase values can never ride along on ordinary color/param writes.',
          'Drop also resolves a fallback Scene Group (settings → drop_scene_group_id; blank = the group named "Drop"). If the current scene — the one that charged and lulled — is already a member, the drop transitions cleanly: the group becomes the active one (cursor on that scene) and the room repaints from the group\'s designated Color Group, with no scene switch. If it isn\'t a member, a weighted-random member fires instead — the scene switch IS the payoff. Per-trigger override: the Drop 🎯 picker in the Builder trigger dialog swaps in a different scene group for that fire.',
          'Scene Updates gained three matching pinned lanes — Charge, Lull and Drop (older scenes: "+ Add Charge / Lull / Drop lanes" in the editor). Each phase event also re-runs its lane of the last Scene Update, so a scene can layer its own extras on top of the hard-coded choreography: reactivity tweaks, color changes, spawn-rate or direction morphs. Empty lanes are skipped.',
          'Testing: the "▶ Charge → Lull → Drop cycle" button (in a Scene Update\'s lane editor, and on the fixed events\' own pages) fires the whole arc automatically, spaced by the configured ramps — it acts on the ACTIVE scene\'s lanes, so fire the scene first if you want its extras included. For frame-by-frame tuning of one effect\'s look, open the effect in the LedFX UI: `phase` and `phase progress` are advanced params there — pick a phase and drag the progress slider by hand (the drop payoff still auto-completes ~½ s after it pinches).',
        ],
        kbd: false,
      },
      {
        id: 'random-energy',
        title: 'Random options: energy gate & tilt',
        keywords: 'random group weight energy floor ceiling scale tilt intensity eligible',
        body: [
          'Each option of a Random group can be gated and scaled by the firing trigger\'s energy (its intensity, 0–1; machine-generated triggers default to section energy). "energy ≥" sets a floor and "≤" a ceiling — outside that window the option is never picked. If every option is gated out, the group fires nothing.',
          'Within the window, "tilt" bends the option\'s weight with energy: 0 is flat, +1 ramps from 0× weight at the floor to 2× at the ceiling (favors high energy), −1 is the inverse (favors low energy). An empty floor/ceiling counts as 0/1 for the tilt ramp.',
          'Manual ▶ test fires carry no energy, so gates and tilt are skipped — every option stays pickable.',
        ],
        table: [
          ['energy ≥ 0.6', 'Option only fires in sections with energy 0.6 or higher.'],
          ['≤ 0.3', 'Option only fires in quiet sections (energy 0.3 or lower).'],
          ['tilt +1', 'Weight grows with energy across the window (0× → 2×).'],
          ['tilt −1', 'Weight shrinks as energy rises (2× → 0×).'],
        ],
        kbd: false,
      },
      {
        id: 'intensity-chooser',
        title: 'Intensity Chooser',
        keywords: 'intensity chooser threshold lane dot slider default deterministic energy level pick scale',
        body: [
          'An Intensity Chooser is a container that fires exactly ONE of its lanes, chosen deterministically by the firing trigger\'s intensity (0–1, after the song\'s intensity scale is applied). Lanes are lower-bound thresholds on a slider: drag the numbered dots to move lane boundaries; everything left of the first dot is the Default lane. The highest dot at or below the intensity wins; two dots on the same value resolve to the higher lane.',
          'The Default lane also fires when the trigger has no intensity (manual ▶ test fires) and when no dots are defined. Deleting a lane merges its actions into the lane to its left. Lanes hold a full action list (all fire together), plus per-lane target scope and filter labels — same as Parallel lanes. Choosers nest anywhere an action is allowed (depth-capped like other groups).',
          'Versus Random energy gates: a Random group rolls weighted dice among energy-eligible options; a Chooser is a deterministic switch — same intensity, same lane, every time.',
          'The Ramp row (parent/override) forces one ramp on everything the chosen lane fires — through event refs, scene groups and scene lanes. Bind it ⚡ to trigger intensity (0 → slow, 1 → fast) or 🎲 to randomize per fire; see "Ramp overrides".',
          'Test at ⚡: the row under the threshold strip previews the whole chooser at any intensity you dial in — the engine fires the lane that value would pick (raw 0–1, no song scaling; the → label shows which lane before you fire). Each lane also keeps its own ▶ to fire it directly.',
        ],
      },
      {
        id: 'light-mode-chooser',
        title: 'Light Mode Chooser',
        keywords: 'dark light mode chooser lane 🌗 moon sun default branch scene group pick display',
        body: [
          'A Light Mode Chooser fires exactly ONE of its lanes, chosen by the room\'s resolved Dark/Light mode — the Now Playing 🌗 toggle, then the firing trigger, the active Scene Group, and the current Scene (see "Dark / Light mode" under Settings). Each lane is tagged 🌙 Dark or ☀️ Light; when nothing in the cascade forces a mode, the lane picked as the default (the "When mode is Default" select) runs.',
          'Lanes hold a full action list plus per-lane target scope and filter labels, exactly like Intensity Chooser lanes — so an event can, say, fire one Scene Group by day and a dimmer one after dark. Add one from any "+ Add action" dialog, or create a whole event around one with "+ Light Mode" on the Events page.',
          'The lane is re-checked at fire time (not locked at plan time), so flipping the TopBar 🌗 applies from the very next trigger. Note the color levels below Set Color (Color Group / Color Set cards) can\'t influence the pick — the chooser resolves before any colors are chosen.',
          'Each lane\'s ▶ previews that lane directly, ignoring the current mode.',
          'The Ramp row (parent/override) works exactly like the Intensity Chooser\'s — see "Ramp overrides".',
        ],
      },
      {
        id: 'brightness-action',
        title: 'Brightness action',
        keywords: 'brightness bg background multiplier dim keep change nudge scale random intensity color set group 🔆',
        body: [
          'The 🔆 Brightness action dims (or restores) devices without touching the authored look: each targeted device carries two multipliers — Brightness and BG Brightness — that scale whatever the Color Set / Color Group pipeline writes (final value = set value × multiplier). Both run 0–1 and default to 1 (= the set as authored). Firing applies the result immediately to the device\'s current effect AND to every later Set Color, until the multipliers reset to 1 on track change.',
          'Each parameter independently keeps, changes, or nudges its multiplier. Keep leaves it alone; change sets it to a value — a fixed number, or ⚡/🎲 bound (e.g. trigger intensity → 0.3–1.0 so quiet triggers dim the room); nudge adds a delta per fire, with a bindable amount, an intensity scale (0 = ignore the beat, 1 = full), a ± random-sign flip, a bounce option that reflects off the range ends, and optional lo/hi limits inside 0–1.',
          'Targeting works like Morph targets: pick devices/categories, or leave it on parent to inherit the nearest group/lane Target (empty = all devices). Ramp blank = the global smooth ramp; 0 = instant. A Color Set entry that doesn\'t define a brightness value keeps following the effect\'s own level — the multiplier only scales values the color pipeline actually writes (plus the immediate apply on fire). In a revert-enabled sequence, the revert restores both the visible params and the multipliers.',
        ],
      },
      {
        id: 'ramp-override',
        title: 'Ramp overrides (scenes / groups / choosers)',
        keywords: 'ramp override parent transition speed ms scene group chooser intensity trigger random cascade force',
        body: [
          'Scene Updates, Scene Groups, and both chooser types (Intensity / Light Mode) carry an optional Ramp with a parent/override toggle — the same idiom as Target. On parent (the default) the level adds nothing: every action keeps its own authored ramp, or inherits an override from further up. On override, the ramp you set is FORCED on everything that fire runs — through event references, scene group members, scene lanes, Set Color entry ramps and per-target morph ramps — so one number controls how fast the whole scene change lands.',
          'The deepest override wins: a scene\'s own Ramp beats its Scene Group\'s, which beats the chooser\'s. So the Intensity Scene chooser can set a room-wide default while one group or scene opts into its own speed.',
          'The value is bindable like any ramp: ⚡ maps it to a music signal — most usefully trigger intensity, e.g. 0 → 1500 ms and 1 → 250 ms so hard hits snap and quiet passages glide (the Intensity Scene event ships with exactly that) — and 🎲 rolls a fresh ramp every fire. Manual ▶ fires carry no intensity, so an intensity-bound ramp uses its fallback (or the mid value).',
          'Two paths deliberately ignore an inherited override: beat-timed sequences (their ramps are compressed to fit the beat grid — that choreography stays authoritative) and the atomic scene-override fast path (bypassed while an override is active, so the ramp actually applies via normal dispatch).',
        ],
      },
      {
        id: 'events-bindings',
        title: 'Value bindings (⚡ / 🎲)',
        keywords: 'signal rms bass onset section energy trigger intensity threshold map random dice sign plus minus flip',
        body: [
          'Any bindable field can swap its fixed value for a live music signal — rms_total, rms_bass, onset_score, section_energy, or trigger_intensity — with a beat averaging window, a mapped range or threshold steps, and a fallback for when the signal is missing.',
          'The 🎲 button next to ⚡ binds the field to a random roll instead: every fire picks a fresh uniform value in the "random value" range (or, on toggle fields, rolls against the threshold steps — a single ≥ 0.5 step is a 50/50 coin flip). Each 🎲-bound field rolls independently, even within one morph step, and Random is also available in the signal dropdown of any existing binding.',
          'The +/− toggle on numeric bindings randomly flips the sign of the result: half the fires come out negative — e.g. map intensity to twist 1–4 and get ±1–4, so direction varies while magnitude still tracks the music. The flip happens before the field\'s own clamping, so fields that only accept 0..1 just floor at 0.',
        ],
      },
    ],
  },

  /* ── Matrix dancers / GIF effects ────────────────────────────── */
  {
    id: 'matrix-gifs',
    title: 'Matrix Dancers, GIFs, Blackhole & Orbits',
    keywords: 'dancing stick figure gif keybeat animation matrix crystal dancer asset blackhole orbits particles',
    intro:
      'Animated GIFs (like the dancing stick figure) run on matrix devices via LedFX\'s keybeat2d effect: frames tagged as "beat frames" land on musical beats and LedFX interpolates between them, so the figure dances to the music with no per-beat traffic from SpotFX. Silence freezes the dance.',
    entries: [
      {
        id: 'gif-params',
        title: 'Dancer parameters',
        keywords: 'dance gif beat frames tint dancer color position stretch half beat',
        table: [
          ['Dance GIF', 'Which asset plays (dropdown lists the manifest; "(missing!)" = not uploaded to LedFX). Always change together with Beat Frames.'],
          ['Beat Frames', 'Frame indices that land on beats — comes from the asset manifest; never hand-edit for stock dances.'],
          ['Dancer Color', 'Runtime tint of the white master GIF (keybeat2d tint param). Ramps smoothly.'],
          ['Dancer X / Y', 'Position offset on the matrix (% of width/height).'],
          ['Dancer Width / Height', 'Stretch (100 = fit). Used by the flare stretch burst.'],
          ['Half Beat', 'Dance at half speed — nice for mellow sections.'],
        ],
        kbd: false,
      },
      {
        id: 'gif-dancer-event',
        title: 'The "Dancer" scene',
        keywords: 'scene update flare big move fallback burst style disco wave',
        body: [
          'The seeded "Dancer" Scene Update switches the Matrix to keybeat2d (First lane). Scene updates (Rest lane) randomly swap dance style (basic / disco / wave), shuffle position, toggle half-beat or flip, or recolor. Shape/Combo flares fire a BIG move — an exaggerated 4-beat GIF burst or a stretch burst — using a "Fallback (s)" burst: LedFX itself restores whatever was dancing before after the burst, so the normal dance always comes back. Color flares change the dancer tint.',
          'Re-seed or update with scripts/seed_dancer_event.py.',
        ],
      },
      {
        id: 'native-dancer',
        title: 'The Dancer effect & "Dancers" scene',
        keywords:
          'dancer effect native dance type tai chi ballet cowboy robot moonwalk floss worm hip hop salsa tango partner somersault stage angle burst threshold third color intensity bands',
        body: [
          'The native LedFX "dancer" effect (no GIFs) renders one or two procedural stick figures that dance to the beat engine: key poses land on beats, moves chain randomly from each dance\'s move set, and every change — dance type, partner, rotation, even effect switches — blends through choreography instead of cutting. Ten dances ship: tai chi (default — rebuilt as Avatar-style bending forms: big arm swirls, rooted fire strikes, low horizontal stretches), ballet (realistic vocabulary: port de bras, pirouettes, penchée, grand jeté, pas de deux), cowboy line dance, robot, moonwalk, flossing, the worm, hip hop, salsa, tango and k-pop (synchronized pop-and-lock formation). Big stretch poses that land inside a beat window HOLD as a synced flourish while an amplified flame burst fires from the stretched limb.',
          'The skeleton has a two-segment spine, a neck, and 3D yaw — chest pops and worm waves bend through the spine, heads nod and snap, and spins (pirouettes, chaîné turns, spin-freezes, underarm turns) really rotate the figure with foreshortening. In "together" dances (ballet, salsa, tango) the pair genuinely holds hands: both held arms re-solve to a shared clasp point, releasing only for turns, leaps and swaps.',
          'The dance runs on a surge clock: it progresses steadily at "Dance Speed" and lunges forward on every beat — harder on loud hits, so big flourishes accelerate straight into the flame bursts. A beat-locked groove layer (pendulum arm swing, shoulder and hip counter-sway, head bob, a lift into every beat) keeps the whole body moving BETWEEN key poses, scaled by each dance\'s energy and the music; fluid dances ease with follow-through so limbs overshoot and settle instead of parking. Colors: each dancer is one solid color — the foreground Gradient sampled 120° after its center (the partner sits 120° before it); "Third Color" shows in stunt flashes (near-black, the default, uses the gradient instead); BG Color stays a normal background layer.',
          'Flames are THROWN by the dance: on beats louder than "Burst Threshold", the flourishing limb — whichever extremity is actually moving fastest — fires a plume mid-swing along its own motion, inheriting its momentum (a still body radiates from the chest instead). Plumes are buoyant with minor vortices, grab one random third of the gradient, grow in size/brightness/life with loudness, and a hot ember trickle follows the moving limb between beats. Mirrored dancers\' plumes collide at the midline and flare upward like meeting flame fronts.',
          '"Partner" (the family\'s Reverse toggle: 2 dancers = reversed) adds the second dancer. Mirror dances (tai chi, robot, moonwalk, floss, worm, hip hop): the lead steps aside and the partner drops in Matrix-Neo style, and leaves with a superman takeoff + burst. Together dances (ballet, salsa, tango): the partner falls from the top into a catch, and leaves spun off screen. "Stage Angle" changes of 20°+ make the dancers somersault into the new orientation — in Shape morphs it rides the shared Twist sub-field (absolute or nudge, with lo/hi/wrap), so twist nudges literally flip the dancers; Dance Speed / Dance Intensity / Burst Threshold are per-param nudgeable under the Reactivity aspect. "Trail Length" is the shared particle-family trail.',
          'Transitions are choreographed: to/from the particle effects the dancers somersault-tuck and dissolve into (or assemble from) particles; radial sucks them in / blooms them out; when Pacman comes in they run away from it. The phased-transition lead fires these switches early so the payoff lands on the trigger.',
          'The seeded "Dancers" scene (member of Mid Group and Drop Group) picks the dance by trigger intensity — 0-4 calm (tai chi, ballet), 4-7 mid (cowboy, salsa, moonwalk, worm), 7-10 high (hip hop, robot, tango, floss, worm) — then randomly within the band; shape flares re-roll the dance, toggle the partner, or somersault the stage. Re-seed with scripts/seed_dancers_scene.py; author new dances via tools/dancesmith (see its README).',
        ],
      },
      {
        id: 'matrix-blackhole',
        title: 'Blackhole effect',
        keywords: 'swirl vortex spiral blobs gradient infall reverse trail comet',
        body: [
          'A custom LedFX matrix effect: gradient-colored blobs spawn at the perimeter, spiral into the center, speed up and stretch into comet trails as they fall, and blend where they overlap. Fully audio-reactive without SpotFX traffic.',
        ],
        table: [
          ['Swirl', 'Spiral amount; sign sets direction, 0 = straight infall.'],
          ['Reverse Flow', 'Blobs erupt from the center outward instead.'],
          ['Field Radius', 'Where blobs spawn, as a fraction of the panel edge.'],
          ['Trail Length', '0 = crisp dots, 1 = long comet smear.'],
          ['Spawn Rate / Beat Burst', 'Continuous blobs per second + extras on each beat.'],
          ['Max Blobs / Edge Speed', 'Density controls: hard cap on live blobs, and rim speed as a fraction of center speed (low = blobs linger and crowd the rim).'],
          ['Accel / Kill Radius / Horizon Hold', 'Speed-curve exponent (higher = slower rim, harder fall), the radius where blobs are consumed, and how long a blob orbits the horizon before fading.'],
          ['Audio Spawn / Audio Speed', 'How much the chosen Audio Band boosts spawning / infall speed. Audio Speed goes to 5, multiplying speed by up to 1 + 2×value on a full-power hit (11× at max) — above ~2 the swirl saturates at its 3 rev/s cap, so extra value goes into radial motion.'],
          ['Color Mode', 'wheel: gradient wraps the circle and rotates with Gradient Spin (direction follows the swirl); band: lows/mids/highs pick gradient positions; random: uniform (spin invisible).'],
          ['Horizon Size / Horizon Audio', 'Event horizon: blobs fall into orbit at this radius (grows with sound when Horizon Audio is positive), turn the Accent Color while circling, then fade. The disc inside shows the BG color. 0 = classic fall-to-center.'],
          ['X / Y Offset', 'Move the center point around the matrix — same sub-fields as radial and orbits, so one morph step can steer whichever of the three is running.'],
          ['Particle handoff', 'Switching between Blackhole and Orbits (either direction, or recreating the same effect) hands the on-screen particles, trails AND the live gradient to the incoming effect — blobs become orbiting particles and vice versa instead of vanishing, and colors stay continuous until the next SpotFX color action repaints. The spin direction and blob size carry over too: the incoming effect flips its swirl/reverse sign to keep rotating the same way, and eases from the old blob size to its own. Coming from Orbits, EVERY particle is kept and starts swirling in (or erupting out) like a native blob; Handoff Ease sets how many seconds they take to wind up to full speed.'],
          ['Radial handoff', 'Switching to Radial: over the first half of the crossfade every blob breaks orbit and spirals into the radial\'s center, pinching bright; the ring pattern then STRETCHES outward from that point like an explosion (a real zoom of the pattern — the background color just fades in separately), with Twist sign flipped so the spiral keeps rotating the same way. Switching FROM Radial: the pattern converges onto the handover point — with an event horizon everything INSIDE the ring stretches outward to it while everything OUTSIDE collapses onto it, the whole pattern compressing into a narrow band at the ring that dissolves as blobs burst from it; without a horizon it collapses to a point and the burst fires from the center — native outflow in Reverse mode; in infall mode the burst arcs outward, stalls, and falls back in. Longer effect-switch ramps (≥1.2 s) give the two phases room to read.'],
          ['Morph Steps', 'The Shape aspect sub-fields Swirl, Horizon size, Blob size, X/Y offset (absolute or nudge, bindable) and Reverse (tri-state) morph the vortex from scene lanes and flares like any other shape. The Reactivity aspect\'s per-param menu reaches everything else: Spawn Rate, Beat Burst, Infall Speed, Accel, Edge Speed, Max Blobs, Horizon Hold, Impulse Decay….'],
        ],
        kbd: false,
      },
      {
        id: 'matrix-eye',
        title: 'Eye effect & "Eye" scene',
        keywords:
          'eye iris pupil gaze flames blink eyelid snap stare drift search spin flicker charge lull drop',
        body: [
          'A custom LedFX matrix effect: a big eye — black pupil inside a gradient-wheel iris — that watches the room. The gaze drifts among 9 positions (center + 8 on a ring at Gaze Radius), wandering curvy, orbit-like paths when the music is calm and darting straight and angular when it\'s hot; energetic music also searches faster and homes in closer (the "close enough" boundary breathes, so it sometimes locks right onto a spot and sometimes gives up early). Beats louder than Snap Threshold make the gaze dart — fluidly, just very fast — to a new ring position and hold the stare (Snap Hold, longer on bigger hits). The iris rotates at Spin (Spin Audio adds music boost; 0 = constant) and Flames turns on flickering flame tongues growing from the iris rim — an extension of the iris in the same gradient, with flame intensity, randomness AND flicker speed all growing with the music via Flame Audio.',
        ],
        table: [
          ['Iris / Pupil Size', 'Radii as a fraction of the panel. The shared Field Radius shape sub-field lands on the iris, Blob Size on the pupil, so generic size morphs work.'],
          ['Gaze Radius', 'The ring the 8 look-at positions sit on.'],
          ['Gaze Depth', '3D eyeball illusion: as the eye looks away from center the iris foreshortens into an ellipse and the pupil leads into the gaze, so it reads as physically looking AT a spot. 0 = flat googly eye.'],
          ['Drift Speed / Audio Speed', 'Base search speed and how hard the Audio Band boosts it.'],
          ['Snap Threshold / Snap Hold', 'Impulse a beat needs to snap the gaze (0 = every beat), and the base stare length after a snap.'],
          ['Spin / Spin Audio', 'Iris rotation (rev/s, sign = direction) and its independent music boost.'],
          ['Flames / Flame Audio', 'Flame amount from the rim (0 = off) and how much music grows the tongues, their chaos and their flicker rate.'],
          ['Charge / Lull / Drop', 'Charge streams the flames inward to be absorbed while the iris swells and the pupil shrinks; Lull looks back to center and closes both eyelids from above and below (fast start, pause just overlapping the iris, then shut to a lash line); Drop snaps the eye open with a huge flame explosion.'],
          ['The "Eye" scene', 'Seeded member of Mid Group, Drop Group and Dark Hype: First fires the Eye Scene Setter (tuned matrix look with flames riding trigger intensity, Strips on Blackhole Strip, Singles power, scene-group color); Shape fires a temporary flame flare (LedFX restores it after a few seconds), a pupil dilation, a gaze widen or a spin flip; Color cycles the "Orbits" color group or an ambient flip. Re-seed with scripts/seed_eye_scene.py.'],
        ],
        kbd: false,
      },
      {
        id: 'matrix-orbits',
        title: 'Orbits effect',
        keywords: 'orbits particles tether ring jiggle trail spin color jump fly in off',
        body: [
          'A custom LedFX matrix effect, sibling of Blackhole: a fixed set of particles (default 6) stays on the matrix permanently. Each is tethered to a point on a ring around the center and orbits it with comet trails; the ring itself spins. Changing the particle count animates — a removed particle flies off in a random direction, a new one flies in and the rest re-space around the ring.',
        ],
        table: [
          ['Particles', 'How many particles live on the matrix (1–16). Morphable via the Shape aspect\'s "Edge / particle count" sub-field (shared with radial\'s polygon edges).'],
          ['X / Y Offset & Field Radius', 'Center point and overall scale — same params as radial/blackhole, so shape morphs steer all three.'],
          ['Tether Radius', 'Ring the tether points sit on (the Horizon size shape sub-field). 0 = everything orbits the center.'],
          ['Orbit Radius / Particle Size', 'Radius of each particle\'s path around its tether, and its drawn size in pixels.'],
          ['Ring Spin / Orbit Speed / Reverse Spin', 'Ring rotation (fraction of base speed), base orbit revolutions per second, and direction flip (the Reverse shape sub-field).'],
          ['Jiggle', '0 = clean synchronized orbits; 1 = each particle wanders smoothly and randomly within its orbit radius, and audio reactions fully decorrelate between particles.'],
          ['Tether Scatter', '0 = tether points perfectly equidistant around the ring; 1 = each tether sits at its own random ring position (no equidistance bias).'],
          ['Reactivity (master)', 'One knob, exposed to the Reactivity aspect spread: multiplies Speed Jump Max, Speed Jump Jog, Brightness Audio and Size Audio — balance those once, then scale the whole response with this.'],
          ['Speed Jump Max / Speed Jump Jog', 'Cap on the music-driven speed boost, and how hard onsets/beats knock particles off course (a decaying bounce).'],
          ['Brightness / Size Audio', 'Music pumps particle brightness and inflates particle size.'],
          ['Colors', 'Particles sample the gradient at evenly spaced points; Gradient Spin rolls the colors over time; trails are each particle\'s own color fading out, exactly like Blackhole.'],
          ['Particle handoff', 'Switching from Blackhole adopts its brightest blobs: they glide from where they are into tether orbits over Enter Time seconds, colors morphing from carried-over to slot colors, spin direction and blob size carrying over (Reverse flips to keep rotating the same way; size eases to its own). If Blackhole had fewer blobs than Particles, the deficit spawns in fast (~half a second) from the Blackhole\'s spawn zone — the center when it was erupting, the rim when infalling; the brightest surplus blobs (up to ~12) fly out along the Blackhole\'s flow (outward off-panel, or sucked into the center, fading exactly as they arrive), while horizon-captured blobs and the dim remainder simply fade out in place via the carried-over trails. Trails survive in both directions.'],
          ['Radial handoff', 'Switching to Radial: the particles spiral into the radial\'s center over the first half of the crossfade, then the ring pattern stretches outward from that point like an explosion (Twist sign flipped to keep rotating the same way; the background color fades in separately). Switching FROM Radial: the pattern zooms down into the center, then the full particle set spawns bright AT the center and visibly shoots out to its orbits, with Reverse adopted so the spin continues the radial\'s apparent rotation.'],
          ['Enter Time', 'Seconds a new or adopted particle takes to glide into its orbit — governs count-increase fly-ins and the Blackhole→Orbits handoff.'],
          ['Color Jump', 'Integer slot rotation of the particle→color assignment. Nudge it +1 from a morph step (Reactivity per-param menu) to make colors jump A,B,C → C,A,B on cue.'],
          ['Morph Steps', 'Shape aspect: X/Y offset, Horizon size (= tether radius), Field radius, Edge / particle count (= Particles), Blob size (= Particle Size) and Reverse apply directly. Reactivity per-param menu reaches Jiggle, Tether Scatter, Ring Spin, Orbit Speed, the jump/jog/brightness/size reactivities and Color Jump.'],
          ['The "Orbits" scene', 'Seeded scene mirroring Black Hole: First fires the Orbits Scene Setter (tuned matrix look, Strips on Orbits Strip, Singles power, and an "Orbits" color-group pick); Shape randomly reverses spin or adds/removes a particle — matrix and strips together; Color randomly color-jumps (matrix + strips) or cycles the "Orbits" color group. Chill Orbits follows the same pattern with its "Calm" color group. scripts/seed_orbits_scene.py is the original seed (pre-strips — re-running it reverts Strips to melt).'],
        ],
        kbd: false,
      },
      {
        id: 'matrix-fireworks',
        title: 'Fireworks effect',
        keywords: 'fireworks burst explode particles spawn center trail fade volume',
        body: [
          'A custom LedFX matrix effect, third sibling of Blackhole and Orbits: fireworks burst from random points (weighted toward the center), their particles flying apart, decelerating and fading with comet trails. All particles of one firework share a color; each firework picks its own at random from the gradient. Music volume drives brightness, burst size and launch speed; spawn pacing mirrors Blackhole (Spawn Rate + Beat Burst + Audio Spawn, capped by Max Particles).',
        ],
        table: [
          ['Burst Size / Speed / Life / Drag', 'Particles per firework, base explosion speed, particle lifetime, and how hard they decelerate after the burst. Audio Burst Size sets how much volume grows each firework\'s particle count (0 pins it at Burst Size).'],
          ['Reverse', 'Implode instead of explode: particles are born dim at their flight distance and BRIGHTEN as they converge onto the burst point — a near-perfect time reversal of the explosion. Same Reverse morph sub-field as Blackhole/Orbits, so shared shape morphs flip all siblings together. Works on the strip too — the pair races toward each other, brightening into the meet.'],
          ['Spawn Rate / Beat Burst / Audio Spawn', 'Continuous fireworks per second + extras on each beat + band-driven boost — the same pacing model as Blackhole.'],
          ['Audio Speed / Audio Brightness', 'How much volume boosts explosion speed and brightness.'],
          ['X / Y Offset & Field Radius / Blob Size / Trail Length', 'Shared shape sub-fields — one morph step steers whichever sibling is running.'],
          ['Particle handoff', 'Switching to Blackhole or Orbits hands the live firework particles over — they become infalling blobs / orbiting particles. Switching INTO Fireworks: from Blackhole the event horizon explodes (a safe number of captured blobs) and the stray blobs fly away too; from Orbits every particle explodes as its own firework in its own color; from Radial the pattern implodes and then goes up as one grand firework from the center. To Radial it shares the particle gather-then-bloom transition.'],
          ['The "Fireworks" scene', 'Seeded scene mirroring Black Hole (scripts/seed_fireworks_scene.py, re-runnable): First fires the Fireworks Scene Setter — Matrix→Fireworks and Strips→Fireworks Strip with the looks captured from the LedFX "default" presets (stored as the SpotFX catalog defaults, so every switch starts from the full tuned config), Singles→power, plus the same starter color picks as Black Hole; the Matrix burst size and Beat Burst ride the trigger intensity. Rest = palette morph + Color Flare; Shape randomly reverses (implosion fireworks, matrix + strips together) or nudges burst size ±2; Color cycles the "Orbits" group or fires Ambient Flip and Back.'],
        ],
        kbd: false,
      },
      {
        id: 'matrix-pacman',
        title: 'Pacman effect',
        keywords: 'pacman ms pac-man maze ghosts dots power pellet fright reverse chase wipe arcade game',
        body: [
          'A custom LedFX matrix effect: a mini Ms. Pac-Man game tuned for the crystal ball. She eats dots through a bold 18×18 single-lane maze with wrap-around tunnel openings; up to four classic-colored ghosts chase her. A lone ghost can never catch her — it stumbles (white blink) and scrambles away — but two ghosts cornering her at once DO catch her: she blinks out and respawns at the start while all ghosts return to the center house. Ghosts (re)spawn from the house doors with ~1s of can\'t-be-eaten invulnerability, so camping their spawn in fright mode doesn\'t pay. Eating one of the four power dots frightens the ghosts: they flash blue, flee, and she hunts them down. Clearing every dot flashes the maze white and refills it. Characters are soft glow blobs, not sprites — color and motion tell the story at LED resolution.',
          'Audio: she jumps forward on every beat (Beat Jump cells), her speed rides the selected Audio Band (Pacman Speed + Speed Audio), and the maze walls are one uniform color from the gradient that rolls through it over time — faster when the music is loud (Wall Color Roll + Wall Roll Audio).',
          'Switching effects on the matrix plays a transition gag: a big chomping Ms. Pac-Man sweeps across the panel, eating the old effect away (wipe out) or revealing the maze behind her (wipe in). It rides the LedFX crossfade, so the virtual\'s transition time sets the sweep duration.',
        ],
        table: [
          ['Reverse', 'Forces permanent power-dot mode: ghosts stay blue and flee, she hunts and eats them, and eaten ghosts respawn already frightened. Same Reverse morph sub-field name as the particle siblings.'],
          ['Fright Time', 'Seconds ghosts stay frightened after a power dot (blue/white flashing near the end). Ignored while Reverse is forced.'],
          ['Ghosts / Ghost Speed', 'How many ghosts (1–4, classic red/pink/cyan/orange) and their speed as a fraction of hers — capped below 1, and only a two-ghost pincer can catch her. Changing the count live despawns/respawns via the center house.'],
          ['Pacman Speed / Speed Audio / Beat Jump', 'Baseline speed in maze cells per second, how much music intensity boosts it, and how many cells she skips ahead on each beat (eating dots along the way).'],
          ['Wall Gradient / Wall Color Roll / Wall Roll Audio / Wall Brightness', 'All walls share one color sampled from the gradient; the sample point bounces back and forth through the gradient (no snap at the ends) at the base rate plus a music-level boost.'],
          ['Dot Brightness / Blob Size', 'Pellet brightness (power dots pulse on the beat) and the character glow radius in pixels. Blob Size shares the same shape morph sub-field as the particle effects\' blob size; Ghosts shares the Edge / Particle Count sub-field.'],
          ['Trail Length', 'Comet trails behind her and the ghosts, exactly like Orbits: 0 = crisp blobs, 1 = long smears. Walls and dots stay crisp.'],
          ['Smooth Motion', 'On (default): rendered positions ease toward the true game positions, so beat jumps and stumble recoils glide instead of teleporting. Purely cosmetic — collisions and eating use the real positions; tunnel wraps still snap across.'],
          ['Audio Band / Impulse Decay', 'Which frequency band drives speed and wall roll, and its smoothing decay — same reactivity plumbing as Blackhole/Orbits.'],
          ['Morph Steps', 'Shape aspect reaches Reverse, Ghosts, Blob Size, Wall Color Roll and Fright Time; the Reactivity per-param menu reaches Pacman Speed, Speed Audio, Beat Jump, Wall Roll Audio, Ghost Speed and Impulse Decay. Color morphs steer the wall gradient.'],
          ['Transitions', 'Switching to Blackhole, Orbits, Fireworks or Squiggles skips the wipe and plays in two phases: first the maze walls and dots fade to black while the characters keep playing, then — at ~45% of the crossfade — each character becomes a particle, its own exploding firework, or a wriggling squiggle, keeping its color (she flies off yellow, frightened ghosts blue) and comet trails. Every other switch into or out of Pacman plays the big-pacman wipe (except Pacman→Pacman config recreations).'],
          ['The "Pacman" scene', 'Seeded scene mirroring Fireworks (scripts/seed_pacman_scene.py, re-runnable): First fires the Pacman Scene Setter — Matrix→Pacman with the full Default-preset look asserted (ghost count rides trigger intensity 2–4, Beat Jump rides it 0.8–3.0), Strips→Orbits Strip, Singles→power, plus the same starter color picks as Fireworks. Rest = palette morph + Color Flare; Shape randomly toggles Fright! (reverse) or adds/removes a ghost; Color cycles the "Orbits" group or fires Ambient Flip and Back.'],
        ],
        kbd: false,
      },
      {
        id: 'phased-transition-lead',
        title: 'Phased transitions land on the beat',
        keywords: 'transition lead phase bloom erupt morph handoff early fire anchor payoff radial particles pacman crossfade timing',
        body: [
          'Some effect switches are two-phase choreographies riding the crossfade: particles→Radial gathers first and BLOOMS at ~45%, Radial→particles implodes first and ERUPTS at ~45%, and Pacman→particles fades the maze first before the characters morph at ~45%. Left alone, the switch instant would land on the trigger and the visual payoff would arrive noticeably late.',
          'The trigger engine compensates automatically: when a planned morph step switches between such a pair (registry: services/transition_phases.py), the whole fire is scheduled EARLY by that fraction of the crossfade — the bloom / eruption / character-morph lands on the trigger\'s timestamp instead of the switch. The crossfade length is the effect-switch ramp for scene-override fires, or the virtual\'s configured transition time otherwise; fire logs show the shift as "transition_lead=NNNms".',
          'Scene Groups get this too: the planner peeks which member the rotation will pick (weighted rolls and random-start seeds are locked in at plan time — rotation cursors still only advance when the fire actually happens), rolls its First/Rest lane, follows the lane\'s event_ref into the scene setter, and shifts the fire by the setter\'s switch lead. The Now Playing preview names the peeked member; if anything moves the rotation between planning and firing (another group fire, a Scene Morph, Force Scene, an edit), the fire safely re-rolls fresh instead of honoring the stale pick.',
          'Only switches firing at the event\'s anchor time shift the schedule — a switch buried in a delayed sequence step or a staggered lane never drags the rest of the event early. Editor previews fire immediately, so no lead applies there.',
        ],
        kbd: false,
      },
      {
        id: 'matrix-squiggles',
        title: 'Squiggles effect',
        keywords: 'squiggles chains hex zigzag wriggle collide bounce explode firework straight',
        body: [
          'A custom LedFX matrix effect, fourth member of the particle family, fitted to the crystal ball\'s real LED lattice: chains walk the device\'s live-LED grid (diagonal neighbors + two-row verticals — six directions, none horizontal), so every lit pixel of a chain is a physical LED and nothing is lost to the ball\'s mask. A step may turn only one slot (never straight through a vertex, never reverse) while error-diffusion steering keeps each chain\'s center of mass on a straight line; headings stay a configurable buffer away from horizontal.',
          'Spawn pacing mirrors Blackhole (Spawn Rate + Beat Burst + Audio Spawn, capped by Max Chains), but there is no attractor: chains are born ON the crystal\'s silhouette edge with a few segments already laid inward (visible immediately), aimed at the center ±30°; they fly straight through, leave the silhouette and delete. When two chains meet head-on (more than 90° between headings) both explode into a firework of sparks in their own colors; a shallower contact bounces them apart elastically.',
        ],
        table: [
          ['Step Size / Step Count', 'Hex edge length in pixels (the minimum step, default 2) and chain length in steps. Audio Length grows chains with the music.'],
          ['Blob Size', 'Chain thickness (0.5–6) — shares the family Blob Size morph sub-field, so one shape morph steers all the particle siblings.'],
          ['Jiggle', 'Like Orbits: 0 = uniform chains, 1 = each chain wanders its own step size and thickness.'],
          ['Horizontal Gap', 'Degrees the flight heading must stay away from horizontal (default 25) — the "distinctly not horizontal" rule.'],
          ['Speed / Audio Speed / Brightness Audio', 'Center-of-mass speed in px/s, its music boost, and audio-pumped brightness.'],
          ['Reverse', 'Every chain turns around and retraces its path back out; new chains keep entering from the edge.'],
          ['Particle handoff', 'Switching between Squiggles and Blackhole/Orbits/Fireworks hands the live chains over: each chain head becomes a blob / orbiting particle / its own exploding firework, and adopted particles become new chains flying across. From Pacman it inherits the two-phase morph: the maze fades, then her and the ghosts sprout squiggle tails in their own colors. Radial handoffs are choreographed both ways: FROM Radial, the pattern implodes and then bursts into one chain per radial edge/segment flying out of its center; TO Radial, two envoy chains race in from opposite edges, collide at the radial\'s center in a spark explosion, and the radial blooms out of it — retimed every frame so the blast lands on the payoff point the transition planner anchors to the trigger.'],
          ['The "Squiggles" scene', 'Seeded scene mirroring Black Hole (scripts/seed_squiggles_scene.py, re-runnable): First fires the Squiggles Scene Setter (full tuned look, beat bursts ride trigger intensity 1–5, Strips→Orbits Strip, Singles→power, same starter color picks); Rest = palette morph + Color Flare; Shape randomly reverses or flips chain length long/short; Color cycles the "Orbits" group. The scene is a member of every scene group that includes Black Hole (weight 1).'],
        ],
        kbd: false,
      },
      {
        id: 'strip-blackhole-orbits',
        title: 'Blackhole Strip & Orbits Strip (1D)',
        keywords: 'strip 1d linear blackhole orbits particles ring overlap blend explode split hue midpoint',
        body: [
          'Both matrix effects have 1D siblings for LED strips — best on circular strips with connected ends, since positions wrap around. They share the 2D effects\' parameter names, so the same SpotFX shape/reactivity morphs, color actions and scene sets steer them.',
          'Blackhole Strip is the 2D Blackhole seen through a 1-pixel ring stretched out to the strip: blobs keep their spiral physics, appear at their angle, brighten as they approach the sample ring, peak passing through and trail away (Approach Width tunes that envelope; Field Radius picks where along the fall the ring sits). Swirl slides blobs along the strip, Gradient Spin rotates the whole pattern at a baseline speed, and Reverse erupts blobs from the center outward. There is no event horizon in 1D.',
          'Orbits Strip flattens the particle system onto the strip: a fixed set of particles tethered to evenly-spaced points on a spinning ring, oscillating around their tethers with the same Jiggle wander as 2D Orbits. Jiggle stacks onto every random decision: near 0 all particles roll the same outcome together, at 1 each rolls independently.',
          'Fireworks Strip: each firework spawns TWO particles at a random strip position (no center weighting) that race away from each other, trailing and fading like a removed Orbits Strip particle. Both share one randomly-picked gradient color per firework; volume drives brightness and separation speed, and spawn pacing (Spawn Rate / Beat Burst / Audio Spawn / Max Particles) mirrors the 2D Fireworks.',
          'The scenes use them: Black Hole runs Blackhole Strip on the Strips category (its global swirl/reverse morphs steer strips and matrix together), and Orbits / Chill Orbits run Orbits Strip — each Scene Setter applies the effect\'s Default-preset tuning and the strips take their gradients from the scene\'s color group (the "Orbits" group for Black Hole and Orbits, "Calm" for Chill Orbits).',
        ],
        table: [
          ['Overlap Blend', 'What happens where blobs overlap: 1 = constructive interference (brightness fully adds), 0 = no brightness gain — colors meet at their hue midpoint instead. 0.5 adds half the extra brightness.'],
          ['Jog Reverse Chance', 'On each music spike/beat, the chance a particle\'s speed jump runs BACKWARD until the next spike (replaces the 2D jog kick, which reads poorly in 1D).'],
          ['Bounce Chance', 'On each spike/beat, the chance a particle bounces and travels backward along the strip — its tether drifts against the ring spin until a later bounce turns it forward again (default 0.2).'],
          ['Implode Fade / Implode Reach', 'Adding a particle implodes it into existence: two half-brightness fragments, hue-rotated ±120° from its color, start Implode Reach of the strip away on either side and converge over Implode Fade seconds, brightening as the particle fades in.'],
          ['X Offset', 'Rotates the whole pattern/ring around the strip (the same shape sub-field that moves the 2D center).'],
          ['Not carried over from 2D', 'Y Offset, particle handoff, the event horizon and (on Orbits Strip) Tether Radius / Enter Time don\'t exist in 1D; everything else morphs identically.'],
        ],
        kbd: false,
      },
      {
        id: 'gif-assets',
        title: 'Creating new dance GIFs (agents)',
        keywords: 'gifsmith toolkit render preview publish poses skill claude',
        body: [
          'Assets are authored procedurally with the gifsmith toolkit (tools/gifsmith; see .claude/skills/led-gif-assets/SKILL.md): compose poses → render → mask-aware preview → publish to LedFX\'s asset store + the manifest (storage/gif_assets.json). The hex matrix only lights ~1/3 of its grid cells, so the toolkit previews assets through the real-pixel mask — ask Claude to "add a new dance style" and it takes it from there.',
          'Fallback burst editing: on a ledfx_effect_param action, setting "Fallback (s)" makes it fire as a burst that auto-reverts.',
        ],
      },
    ],
  },

  /* ── Now Playing ─────────────────────────────────────────────── */
  {
    id: 'nowplaying',
    title: 'Now Playing',
    keywords: 'dashboard live playback countdown',
    intro: 'The listener dashboard: what\'s playing, what will fire next, and the master toggles.',
    entries: [
      {
        id: 'now-controls',
        title: 'Control toggles',
        keywords: 'activate pause dinner party ambient analyzed force scene',
        body: [
          'Activate (play/pause), Dinner Party and Ambient moved to the shared top bar — see "Top Bar (all pages)". The remaining page toggles:',
        ],
        table: [
          ['Analyzed', 'Use analyzed (auto-generated) triggers for songs without user triggers.'],
          ['Force Scene', 'Hold one scene: whenever a new scene would be picked, reassert the forced scene instead. See "Force Scene" below.'],
        ],
        kbd: false,
      },
      {
        id: 'ambient-groups',
        title: 'Ambient Hue groups',
        keywords: 'long press hold hue group room dining living picker per-group transition fade home assistant',
        body: [
          'Long-press the Ambient button to pick which Hue groups (one per Hue entertainment room) are held in ambient. Each checkbox applies immediately; the button shows a count (e.g. "1/2") when only some groups are held. A short press still toggles all groups at once.',
          'Turning a group off runs a two-stage handoff: a quick fade on the Hue bridge to the wake scene\'s look ("Fade to wake" in Settings → Ambient Mode), then a slow ease from that look back to the current music scene ("Catch-up to current scene") — no snap at the next trigger. Turning on ramps up over the fade time.',
          'Home Assistant: POST /api/control/ambient-mode?enabled=true&groups=dining-hues&transition_s=2&catchup_s=10 — `groups` is a comma-separated list of group ids (GET /api/control/ambient-groups lists them); omit it to affect all groups. enabled=true adds the groups to the held set, enabled=false removes them. `transition_s` / `catchup_s` optionally override the configured fade / catch-up for that call.',
        ],
      },
      {
        id: 'now-force-scene',
        title: 'Force Scene',
        keywords: 'force scene hold pin lock reset first lane override picker search group rotate',
        body: [
          'When enabled, every Scene Update fire — the moment SpotFX would pick a new scene — reasserts the scene chosen in the picker instead: its First lane when it isn\'t the active scene yet, then its Rest lane on repeats, exactly like a natural fire of that scene. The room stays on it for as long as the toggle is on; flares (Shape/Color/Combo) and Update/Reset Scene keep running against it, so the lights still move with the music.',
          'The picker lists Scene Update events AND Scene Groups ("(group)" suffix); type to filter by name or label. Holding a group rotates instead of pinning: every scene pick advances the group one member per its mode (cycle wrap/bounce or weighted), running that member\'s normal First/Rest lanes. Flares keep hitting the current member, and Scene Morph actions step the held group.',
          'Turning the toggle on (with a scene chosen) or picking a different entry asserts it immediately — for a group that means one advance right away. Manual fires of other Scene Updates are redirected too while the toggle is on. The setting persists across restarts and is OFF by default; with no scene chosen it does nothing.',
        ],
      },
      {
        id: 'intensity-scale',
        title: 'Intensity scale (per song)',
        keywords: 'intensity scale slider percent 200 boost quiet loud song profile genre auto normalize library rank',
        body: [
          'The ⚡ Intensity scale slider (Controls card) multiplies EVERY trigger\'s intensity for the current song — 0–200%, applied before energy gates, Intensity Chooser lanes and trigger_intensity bindings (the result stays clamped to 0–1). It saves to the song\'s profile immediately and takes effect on the next fire, no track change needed. The ⚡ readout in the top bar shows the scaled value.',
          'The chip shows where the value comes from: "user" = this slider (never overwritten automatically); "auto" = the computed starting value — the genre base nudged ±10% by how the song\'s bass (level, bass ratio, bass-onset density) ranks against the analyzed library; "genre" = the genre base alone (songs without captured audio). Automatic values never exceed 125% — only this slider can go higher. The × button clears a user value back to the automatic one.',
          'The genre slider on a Triggerless training profile is a RELATIVE energy dial, not the final percentage: it maps to a song starting value as 0.6 × slider + 0.1 (so 185% → ~121%, 70% → ~52%, capped 30–125%). scripts/backfill_intensity_scale.py re-stamps every non-user song from the current sliders (backs up first; run it after retuning genres).',
        ],
      },
      {
        id: 'now-next-changes',
        title: 'Next-changes board',
        keywords: 'next trigger preview flare combo shape color lane steps board upcoming',
        body: [
          'Below the control toggles, the board previews the next trigger down to the LEAF changes: event-ref chains and random branches are followed all the way, so each row shows the actual morph — which parameters change, to what values, and the ramp time (e.g. "effect → radial, star → 0.3, edges → 6 (1.5s)"). Intermediate event names (the route) are dropped; the row tag is the deepest lane/child/branch name. Named Morph Steps show their name; color swatches appear for color changes; hover a row for the untruncated description.',
          'Everything is locked in when the preview appears — lane picks AND every random branch inside referenced events — so the trigger fires exactly what the board shows. Flares (Shape/Color/Combo) resolve against the currently active Scene Update; if a different Scene Update fires in between, the engine re-rolls at fire time so stale picks never run.',
          'Devices receiving the identical change are merged into one row with combined tags. Color Group cycles deliberately show only the step count ("+2 steps in “Party”") — the destination Set stays a surprise. Rows firing off the trigger point show their offset ("+0.5s"); more rows than fit are summarized as "+N more" (hover for the full list).',
        ],
      },
      {
        id: 'now-source-badge',
        title: 'Trigger source badge',
        keywords: 'manual ai generated simple auto triggerless override guest',
        body: [
          'Shows where the current song\'s triggers come from: Manual (hand-built profile), AI Generated, Simple Triggerless (interval-based), Auto Triggerless (analyzed pipeline), or Analyzed Override.',
          'Guest playback (see "Guest source") always runs Simple Triggerless — a guest session has no saved profile, so the badge shows Simple Triggerless while a guest owns the speakers.',
        ],
      },
      {
        id: 'guest-source',
        title: 'Guest source (Snapcast / AirPlay)',
        keywords: 'guest snapcast airplay librespot connect visitor stream triggerless',
        body: [
          'When someone plays to the "Serenity Guest" Spotify Connect device or the AirPlay target, their session belongs to their account — the Spotify API shows nothing, so SpotFX watches the local snapserver instead. While a watched guest stream is playing, SpotFX synthesizes a track from the stream\'s metadata (title/artist when snapserver can read them) and runs simple triggerless lighting for it; a title change counts as a new song.',
          'The host\'s own Spotify always wins: an actively playing real track takes over immediately, and a paused or idle Spotify answer never interrupts a guest session. Guest tracks are never saved — no song profiles are created and no audio-shape capture runs for them.',
          'Settings (env/config): guest_source_enabled, snapcast_rpc_url, guest_streams (stream ids in priority order), guest_poll_interval_s.',
        ],
      },
      {
        id: 'now-shape',
        title: 'Audio shape & recapture',
        keywords: 'offset drift quality recapture badge realign self-correction triggers shift zoom follow pan playhead',
        body: [
          'The shape view follows the playhead. Drag to pan and inspect elsewhere in the song ("Follow playhead" snaps back); following always resumes when the song changes or the page reopens.',
          'The Audio Shape card shows the captured waveform with the live offset status ("start +Xms → now +Yms, Q=quality"). A "recapture suggested" badge appears when the stored offset keeps disagreeing with live audio; Recapture deletes the stored shape (audio + analysis) so the song re-records on its next play.',
          'Recapture self-corrects: when a song is force-recaptured, the new recording is cross-correlated against the old one and any timing shift between the two is applied automatically to the song\'s triggers (including per-Set-List overrides) and learned offsets — so existing triggers keep landing on the same musical moments. If the shift can\'t be measured confidently, triggers are left untouched and offsets relearn from scratch.',
        ],
      },
    ],
  },

  /* ── Color Sets ──────────────────────────────────────────────── */
  {
    id: 'colorsets',
    title: 'Color Sets',
    keywords: 'palette gradients colors groups',
    intro:
      'Named color palettes for events to draw from. A Set holds per-device/category entries (FG gradient or solid, BG color and mode, brightness, accent color, ramp). A Group plays Sets in a cycle (wrap/bounce) or weighted-random order, and can layer its own per-device overrides on top of whichever Set it picks.',
    entries: [
      {
        id: 'colorsets-workflow',
        title: 'Working with sets',
        keywords: 'import preview duplicate labels',
        table: [
          ['⤓ Import', 'Read the current FG/BG colors off selected LedFX devices into a new Set.'],
          ['▶ Preview', 'Apply the selected Set to LedFX right now.'],
          ['Labels', 'Comma-separated, applied when the field loses focus; label filters on triggers/actions pick which sets are eligible.'],
          ['Members', "A Group's member picker is a searchable dropdown — type to filter Sets by name."],
          ['Gradients', 'Live in a shared library — edit stops and direction, then "Update current" or "Save as new".'],
        ],
        kbd: false,
      },
      {
        id: 'colorsets-copy-entries',
        title: 'Copying entries between sets',
        keywords: 'copy paste clipboard multi-select shift click entries overrides',
        body: [
          'Entry boxes (and Group overrides) support multi-select: Shift+click a box to select it, Shift+click again to deselect, Esc to clear. Copied entries land on the same clipboard the event editor uses, so they survive reloads and work across tabs — open another Set or Group and paste to append them.',
        ],
        table: [
          ['Shift+click', 'Toggle an entry box in/out of the selection.'],
          ['Ctrl+C', 'Copy the selected entries to the clipboard.'],
          ['Ctrl+V', 'Append the copied entries to the open Set (or Group overrides) — same as the 📋 Paste button.'],
          ['Esc', 'Clear the selection.'],
        ],
        kbd: true,
      },
      {
        id: 'colorsets-group-overrides',
        title: 'Group overrides',
        keywords: 'override layer bg brightness nested category subset clamp merge',
        body: [
          'A Group can carry its own entries (the "Overrides" list). When the Group fires, one member Set is picked as usual, then every field an override defines — color, BG color, BG mode, brightness, BG brightness, third color, ramp — replaces the Set\'s value on the devices the override\'s scope resolves to. Unset fields keep the Set\'s values.',
          'Merging happens per device: an override scoped to a sub-category (or single device) inside a Set entry\'s scope only changes those nested devices, while the Set keeps applying to the rest. If the override\'s scope covers everything the Set touches, it simply wins everywhere. Devices in an override\'s scope that the picked Set doesn\'t cover still get the override\'s explicit fields — so a Group-level clamp (e.g. BG brightness on one category) behaves the same no matter which member is picked.',
          'Third color: a Set clears the accent to black on devices where it leaves it undefined; an override only touches the accent when set explicitly (set it to black to force-clear).',
        ],
      },
      {
        id: 'colorsets-mode-lanes',
        title: 'Mode Lanes (groups)',
        keywords: 'dark light mode lane variant 🌗 moon sun members overrides pool swap dim',
        body: [
          'A Group can carry a 🌙 Dark and/or ☀️ Light lane — what the group does while the room\'s resolved mode matches (see "Dark / Light mode" under Settings). Default mode always uses the base group exactly as authored.',
          'Each lane has two optional parts. Members: when non-empty, they REPLACE the base member pool for the pick (with their own cycle position — the base cursor doesn\'t move); empty keeps the base members. Overrides: layered on top of the group\'s own overrides — a lane override only needs the fields that should differ (e.g. a lower BG brightness for dark evenings).',
          'The mode is resolved from everything above the member set — TopBar, trigger, scene group, scene, the Set Color step, and this group card\'s own Mode — so the picked member set\'s card mode can\'t change which pool it was picked from.',
        ],
      },
      {
        id: 'colorsets-palette-sync',
        title: 'Palette Sync (groups)',
        keywords: 'sync synced hue shared cursor position family disjointed devices categories together',
        body: [
          'Normally each Group cycles from its own private position — so when different Groups drive different devices or scenes (e.g. one for strips, one for Hue lamps, one per scene family), each fires from wherever ITS cycle last sat and the room\'s palettes drift apart.',
          'Palette Sync (Group Settings checkbox) makes a Group follow the room instead: every Set application publishes a room-wide "current palette" (the applied Set itself, plus a hue derived from its card swatch color, falling back to its FG colors). A synced Group starts its pick from the member matching that palette — the exact Set when it\'s a member, else the nearest member by hue — then advances from there as the fire requests. Enable it on all the Groups you want moving as one color family.',
          'The hue comes from the card\'s swatch color first, so give parallel families matching swatches (e.g. "Mid - Ice" and "Power - Ice" the same cyan) for exact correspondences. Sets with no usable hue — brightness-only cards, white/grey swatches with rainbow gradients — neither move nor disturb the shared palette.',
          'A Set Color step with Advance 0 stays put instead of moving: on a synced Group it repaints the scoped devices in the room\'s current family — handy in scene-set events so entering a scene re-themes without shifting the palette.',
        ],
      },
    ],
  },

  /* ── Scenes (SceneV2) ────────────────────────────────────────── */
  {
    id: 'scenes-v2',
    title: 'Scenes',
    keywords: 'spectra scene v2 device configuration flare choreography wheel rainbow',
    intro:
      'The Scenes page (SPECTRA SceneV2) authors full device-aware scenes: each scene states outright what every targeted device shows — effect, params, colors, brightness — per category or per virtual, plus flare response bands and phase choreography. One scene may combine different effects across devices. This is separate from the legacy scene events on the Events page; both exist side by side during the migration.',
    entries: [
      {
        id: 'scenes-v2-devices',
        title: 'Device entries',
        keywords: 'category virtual effect params override brightness',
        body: [
          'Each entry targets a category (including its sub-categories) or a single virtual, and picks an effect plus number/toggle params to pin (other param types have no pin editor yet). An entry targeting a virtual overrides a category entry covering the same virtual. Colors either come from the active Color Set at fire time ("Colors from active Color Set") or are fixed on the scene. Unset params/brightness leave the device\'s current values alone.',
        ],
      },
      {
        id: 'scenes-v2-flare',
        title: 'Flare response & choreography',
        keywords: 'intensity band curve gain anchor transition payoff',
        body: [
          'Flare bands shape how the scene answers flares by trigger intensity: each band covers an intensity range (bands may not overlap) with a curve and gain. Phase choreography sets the transition length/mode and the anchor fraction — where in the crossfade the visual payoff lands, so the engine can fire early and put the payoff on the beat. Both are stored now and take effect when the SceneV2 engine integration lands.',
        ],
      },
      {
        id: 'scenes-v2-set-filter',
        title: 'Color Set filter',
        keywords: 'accept opt out narrow eligible wheel position rainbow',
        body: [
          'Filtering works both ways: a Color Set can opt out of ALL scenes (the "opt out" button — global, affects every scene), and a scene can narrow which of the remaining sets it accepts by unticking "Accept every Color Set" and checking specific sets. A set\'s wheel dot shows its computed color-wheel position (the saturation- and value-weighted circular mean of its gradient hues); sets whose hues span more than 180° are 🌈 rainbow and have no single position.',
        ],
      },
      {
        id: 'scenes-v2-test-fire',
        title: 'Test Fire (dry run)',
        keywords: 'compile preview writes simulate dry',
        body: [
          '▶ Test Fire saves the scene, compiles it to the per-virtual LedFX writes it would send, and shows them below the editor — nothing is sent to the devices. Use it to check which virtuals a scene resolves to and what config each would receive.',
        ],
      },
      {
        id: 'curve-editor',
        title: 'Curve editor lab (dev preview)',
        keywords: 'sequencer likelihood curve intensity draggable points histogram weight dwell',
        body: [
          'The collapsed "Curve editor lab" card at the bottom of the Scenes page previews the sequencer\'s likelihood-curve editor: a curve over intensity (0–1) whose height at the current intensity is how likely a thing is to be picked. A flat line at 0.7 is exactly a weight of 0.7; a region drawn at zero is a hard "never here".',
          'Click empty space to add a point, drag a point to move it (a point can\'t cross its neighbors; two points at the same intensity make a step), double-click a point to remove it. Straight lines connect the points; outside the outermost points the curve continues flat.',
          'The faint grey bars are the honesty underlay: a histogram of every trigger intensity in your profile library. Most of the library fires in the top half of the axis, so shape your curves where the bars are — a carefully drawn region where nothing ever fires does nothing.',
          'This is a dev preview: edits stay on the page and attach to nothing. Attaching curves to scenes, colour sets, and flares lands with the sequencer once its open design decisions are made; relationships (genre fit, what-follows-what, dwell pace) will be adjusted by telling the agent, not by forms.',
        ],
      },
    ],
  },

  /* ── Devices ─────────────────────────────────────────────────── */
  {
    id: 'devices',
    title: 'Devices',
    keywords: 'categories virtuals ledfx tree',
    intro:
      'Organizes LedFX virtuals into a category tree that events and color sets target. A category has a name, optional parent, a role (e.g. ambient), its LedFX virtual IDs, and a list of supported effects. Targeting a parent category includes every descendant category\'s devices.',
    entries: [
      {
        id: 'devices-import',
        title: 'Importing virtuals',
        body: [
          'Use "Import from LedFX" to list live virtuals with pixel count, current effect, and any existing category assignment; the filter box matches the virtual id.',
        ],
      },
      {
        id: 'shape-maps',
        title: 'Shape maps (shaped matrices)',
        keywords: 'geometry silhouette crystal hex resample kernel parity serpentine bootstrap',
        body: [
          'A shape map tells LedFX which cells of a matrix virtual\'s render grid are real LEDs (and in what strip order), so effects render across the full silhouette and get kernel-resampled onto just the physical LEDs. Without one, effects are point-sampled. Click the ⬡ on a virtual chip in the category editor to open the map for that virtual.',
          'The map is plain text in the `shape v1` format. Validate runs a dry-run compile on LedFX — errors come back with line numbers; on success the canvas preview shows real LEDs as dots, each LED\'s resample catchment as a tinted patch, and orphan cells dark. Apply pushes the map: LedFX regenerates the virtual\'s segments from it and turns resampling on. The line above the editor shows the current state (LED count, grid, whether the map is in sync with the live segments).',
        ],
        table: [
          ['shape v1', 'Required header line.'],
          ['grid 72 x 37', 'Render grid size, width × height.'],
          ['device crystal', 'Physical output device id.'],
          ['gap gap-crystal-mapper', 'Dummy device id used for dead cells.'],
          ['parity odd', 'Live iff (col+row)%2==1 (even: ==0; none: every cell).'],
          ['row 0: 17-51 holes 21,23', 'Row 0: parity-matching cols in [17,51], minus the holes.'],
          ['rows 5-7: 12-58', 'Same extent applied to a row range.'],
          ['cell +10,3', 'Escape hatch: force one cell live (+) or dead (-).'],
          ['order: … explicit 1,16 0,17', 'Strip-order block: exact row,col walk for irregular sections.'],
          ['serpentine rows 2-34 first desc', 'Order complete rows, alternating direction. No order block = serpentine over all rows, row 0 ascending.'],
        ],
      },
      {
        id: 'shape-maps-bootstrap',
        title: 'Bootstrapping a map from live segments',
        keywords: 'decode round-trip verify apply crystal-mapper',
        body: [
          'scripts/bootstrap_shape_map.py decodes an already-hand-mapped virtual\'s live gap/LED segments back into shape v1 text — pole holes and interleaved strip order included — so you don\'t re-author an existing device. --verify recompiles the text and asserts the regenerated segments equal the live ones exactly, then dry-runs it through LedFX; --apply pushes the map (idempotent when in sync).',
        ],
      },
    ],
  },

  /* ── Set Lists ───────────────────────────────────────────────── */
  {
    id: 'setlists',
    title: 'Set Lists',
    keywords: 'playlist spotify context slots',
    intro:
      'A Set List tracks a Spotify playlist (by context URI) and customizes behavior while it plays. It also gives each song an alternate trigger list ("slot") editable in the Builder — the slot shows Default until its first edit, then copies it.',
    entries: [
      {
        id: 'setlists-behavior',
        title: 'Per-list behavior',
        keywords: 'auto activate analyzed genre blending notes discovered',
        table: [
          ['Auto-activate', 'Turn the engine on when this playlist starts.'],
          ['Force Analyzed', 'Use analyzed triggers for songs without profiles while this list plays.'],
          ['Genre blending', 'Override the global genre-blending setting for this list.'],
          ['Recently observed', 'Playlists SpotFX has seen you play — click one to start tracking it.'],
        ],
        kbd: false,
      },
      {
        id: 'setlists-xcorr',
        title: 'Timing (xcorr) options',
        keywords: 'per-play cut buffer drift offset mixed dj',
        body: [
          'Per-play xcorr re-aligns each song against its stored audio shape while the list plays — useful for DJ-mixed playlists where songs start mid-track or cut early. Disable it for non-mixed playlists where you\'ve already dialed in good per-song offsets; the stored offset is then used as-is.',
          'Cut buffer: the xcorr search range is base + max(0, captured − polled duration) + buffer — the buffer absorbs small inaccuracies in the duration delta.',
          'The drift warning box lists songs whose stored offset keeps disagreeing with recent playback (anti-correlation count); recapturing those songs usually fixes it.',
        ],
      },
    ],
  },

  /* ── Triggerless ─────────────────────────────────────────────── */
  {
    id: 'triggerless',
    title: 'Triggerless (Training Profiles)',
    keywords: 'analyzed auto genre training knn embedded',
    intro:
      'Genre-keyed profiles that drive lighting for songs with no hand-built triggers. Simple mode fires scenes/flares on intervals; Analyzed mode places events on librosa features (drops, lulls, charges, quiet sections, flares).',
    entries: [
      {
        id: 'triggerless-slots',
        title: 'Event slots',
        keywords: 'drop lull charge quiet scene fill flare beat start scene update burst',
        body: [
          'Each slot maps a musical moment to an event; blank slots are skipped. Examples: Drop fires at the bass re-entry after a gap; Lull at the peak before an energy drop; Charge during buildups; Scene Fill at energy upticks/downbeats; Flare tiers at harmonic moments of low/mid/high energy. Flare Scene is a fourth tier above Flare High: assign a scene-update event and it fires on the most extreme flare moments (onset/snare bursts) with wide spacing — leave it blank to disable. Label filters support the same "-exclude" syntax as everywhere else.',
          'The Charge / Lull / Drop slots now default to the fixed phase events (see "Charge / Lull / Drop events" under Events) — the effect choreography plus the active scene\'s phase lanes replace per-genre scene picking. All stock genre profiles were repointed 2026-08-07; cached analyzed triggers regenerate automatically on each song\'s next play (the training-profile hash changed).',
        ],
      },
      {
        id: 'triggerless-current-match',
        title: 'Current-song highlight',
        keywords: 'active match highlight current song profile genre default dinner party badge',
        body: [
          'The profile list highlights which profile the engine resolved for the CURRENT song, using the engine\'s own resolution order: Dinner Party mode → genre overlap → the default profile. A solid ACTIVE badge means the song is actually playing on synthetic triggerless triggers right now; a subtle MATCH badge means the song has its own triggers, but this is the profile that would take over if it didn\'t (or if Dinner Party is toggled on). Hover the badge for the match reason; the line above the list names the song it applies to. Refreshes every ~15 s.',
        ],
      },
      {
        id: 'triggerless-training',
        title: 'Training',
        keywords: 'train cancel f1 score tune parameters placement intensity snap onset',
        body: [
          'Click Train to open the training dialog: run immediately, or schedule it. A progress banner shows the phase (scene → flare → placement); holding Cancel (500 ms) aborts. Results show the F1 score baseline → tuned, a per-category breakdown (precision/recall/weight, plus intensity error where scored), and the best parameters found — improvements apply automatically.',
          'The placement phase tunes bass-onset snapping (drops, scenes, and flares snap to the nearest bass onset, matching how Builder right-click placement snaps), the Flare Scene threshold, and intensity blending. Generated triggers carry an intensity: section energy by default, boosted for drops, capped low for quiet/lull, and optionally blended with the flare\'s own strength.',
        ],
      },
      {
        id: 'triggerless-schedule',
        title: 'Scheduling training',
        keywords: 'schedule later evening queue after time chain history error log',
        body: [
          'From the Train dialog, "Schedule at" queues the run for the next occurrence of that time (today if still ahead, otherwise tomorrow — time only, no date). When a run is active or already scheduled, "Queue right after" chains this profile behind it, so several profiles can train back-to-back overnight.',
          'The pending queue is listed above the editor with a × to remove entries; it is stored on disk and survives restarts. Every run — immediate or scheduled — lands in the tuning history; if a run fails, the error shows on the page and the full log (with traceback) is in storage/tune_runs.log.',
        ],
      },
    ],
  },

  /* ── Timing & Debug ──────────────────────────────────────────── */
  {
    id: 'timing-debug',
    title: 'Timing & Debug',
    keywords: 'sync diagnostics xcorr offset latency',
    intro:
      'Advanced diagnostics. Timing (nav-gated by "Show advanced") is a read-only xcorr/anchor dump; Debug shows the live sync state.',
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
          'A trigger\'s actual fire time = Spotify song position + shape_offset (from xcorr) + LedFX trigger buffer + LedFX RTT; audio latency shifts where the playhead is drawn, not when triggers fire. The Timing page shows each measured term for the playing song — xcorr only controls the shape_offset term.',
        ],
      },
      {
        id: 'debug-analyzed-override',
        title: 'Analyzed override',
        keywords: 'force analyzed triggerless test training profile stored manual triggers',
        body: [
          'The "Analyzed override" toggle (track header) makes the current song ignore its stored triggers and run the analyzed-triggerless pipeline instead — useful for testing a tuned training profile against songs that already have hand-built profiles. Now Playing shows the source as "Analyzed Override" while it\'s on. The song needs librosa data and a genre-matching training profile; already-passed triggers re-evaluate from the current position when toggled.',
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
          ['[ / ]', 'Nudge the LedFX trigger buffer −50 / +50 ms live.'],
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

  /* ── Settings ────────────────────────────────────────────────── */
  {
    id: 'settings',
    title: 'Settings',
    keywords: 'config global options',
    intro:
      'Global configuration. "Show AI Triggers" and "Show advanced" gate extra nav pages and advanced cards. The Restart SpotFX button needs a 500 ms hold.',
    entries: [
      {
        id: 'settings-timing',
        title: 'Latency & display',
        keywords: 'audio latency buffer ramp graph scales averaging',
        body: [
          'Audio latency shifts the drawn playhead to the audible moment; the LedFX trigger buffer delays fires to absorb network jitter (nudgeable live on Debug with [ and ]). Graph layer scales and averaging widths set defaults for the builder canvas — both are also adjustable live via the builder\'s layer-button gestures.',
        ],
      },
      {
        id: 'hue-blend-transitions',
        title: 'Hue-rotation color blending',
        keywords: 'color wheel rotate gradient transition gray desaturate rgb hsv blend tween ramp',
        body: [
          'Controls how color and gradient transitions travel between two colors. On (default), colors rotate around the hue wheel (HSV, shortest arc) — red→cyan sweeps through magenta/blue or yellow/green at full saturation. Off, colors take the straight RGB path, which desaturates through gray/muddy midpoints on distant hues (the classic washed-out mid-transition).',
          'Applies everywhere SpotFX ramps a color: morph steps, Set Color actions, gradient params on any effect, both the LedFX server-side tween and the legacy client-side ramp loop. Grays, black, and white have no hue, so blends into or out of them fade saturation in place instead of picking an arbitrary rotation.',
        ],
      },
      {
        id: 'settings-lastfm',
        title: 'Song source & Last.fm API key',
        keywords: 'spotify api credentials ledfx event driven genres lastfm how to target device name multiple comma',
        body: [
          'Song info comes from the Spotify API (needs client credentials from the Spotify Developer Dashboard) or from LedFX events, in which case genres are sourced from Last.fm.',
          'Target Device Name(s) lists the Spotify Connect devices SpotFX reacts to — comma-separate multiple names (e.g. "Serenity, Living Room"). Playback on any listed device counts; anything else shows the Wrong Device badge on Now Playing and triggers stay quiet.',
          'Getting a Last.fm API key: sign in at last.fm/api/account/create, enter any application name and description, leave callback and homepage blank, submit, then copy the API key into the field here. The key is free and rate-limited to 5 requests/second — well within SpotFX\'s usage. Your username is optional; SpotFX only uses it for future scrobbling features.',
        ],
      },
      {
        id: 'display-modes',
        title: 'Dark / Light mode',
        keywords: 'dark mode light mode display background black force shield singles cascade override topbar moon sun ledfx lock',
        body: [
          'One room-wide mode — Dark, Light, or Default — decided by a cascade where the FIRST level that isn\'t "Default" wins: 1) the 🌗 TopBar toggle, 2) the firing trigger, 3) the active Scene Group, 4) the current Scene, 5) the Set Color step, 6) the Color Group card, 7) the Color Set card. "Default" at a level just defers to the next one down; if every level defers, backgrounds behave exactly as authored.',
          'Dark forces every background black on affected devices. This is hard-locked inside LedFX itself (a per-virtual "dark_lock"), so no write path — ramps, scenes, morphs — can relight a background while dark. Light keeps authored backgrounds and fills in the default light background (color + brightness set here in Settings) on devices whose Color Set entry doesn\'t define one.',
          'Shielded devices are exempt from both: they always keep their authored backgrounds. Shield whole categories with the checkboxes (default: Singles — single-color lamps should usually stay lit) or individual virtual ids in the text field.',
          'Scene Groups can additionally designate a 🌙 Dark and ☀️ Light variant Color Group — see "Scene Groups" on the Events page help. To BRANCH on the mode, use a Light Mode Chooser action (Events help) — it fires a different lane per mode; Color Groups can also carry per-mode Mode Lanes (Color Sets help).',
        ],
      },
      {
        id: 'settings-ambient',
        title: 'Ambient mode',
        keywords: 'hue full brightness white temp category dinner transition fade wake scene',
        body: [
          'When the Now Playing (or Home Assistant) Ambient toggle is on, the chosen device category\'s Hue groups are held at the configured color at full brightness via the Hue REST API while the music stream is muted for them. Long-press the Now Playing Ambient button to hold only some groups.',
          'Turning off runs in two stages. "Fade to wake" quickly fades the bulbs toward the wake scene\'s color on the bridge before the music stream takes back over ("Fade-out brightness" is the level it lands on); then "Catch-up to current scene" slowly eases the bulbs from the wake look back to the music scene that\'s currently playing, instead of snapping at the next trigger. Set either to 0 for the old instant behavior.',
        ],
      },
    ],
  },

  /* ── UI conventions ──────────────────────────────────────────── */
  {
    id: 'conventions',
    title: 'UI Conventions',
    keywords: 'patterns hold long press sticky',
    intro: 'Patterns that repeat across the app.',
    entries: [
      {
        id: 'conv-hold',
        title: 'Hold-to-confirm buttons',
        keywords: 'long press 500ms destructive train restart delete generate',
        body: [
          'Destructive or costly actions require holding the button (usually 500 ms, with a fill animation): Restart SpotFX, Train / Cancel training, the Haiku/Sonnet generate buttons, palette edit, and the 2-second "delete all triggers" hold.',
        ],
      },
      {
        id: 'conv-sticky',
        title: 'Sticky UI state',
        keywords: 'localstorage persist collapse remember',
        body: [
          'Collapsed cards, active palettes, layer toggles, and similar view state persist per browser via localStorage — they\'ll be as you left them.',
        ],
      },
      {
        id: 'conv-autosave',
        title: 'Saving models',
        keywords: 'draft dirty autosave undo',
        body: [
          'The Builder auto-saves profiles (debounced, with undo history). Everything else — events, color sets, set lists, settings, training profiles — is draft-based: edit, then Save; a ● dot marks unsaved changes.',
        ],
      },
    ],
  },
];
