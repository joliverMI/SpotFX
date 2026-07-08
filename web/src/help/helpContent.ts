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
        title: 'Triggerless & AI triggers',
        keywords: 'automatic machine learning generated suggestions',
        body: [
          'Songs without a hand-built profile can still react: Triggerless mode maps analyzed features (bass, snare, sections) to event slots, and AI Triggers can generate suggested trigger placements for review before applying them to a profile.',
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
          ['Song pickers', 'Track title or artist (Builder, Triggerless, AI Triggers).'],
          ['AI Triggers — saved runs', 'Title/artist, plus tabs: All / Not Applied / Unreviewed / Reviewed / Applied.'],
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
              ['Esc', 'Disarm the armed key (after clearing any selection).'],
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
              ['Right-click a trigger', 'Reassign that trigger to the armed event.'],
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
        ],
      },
      {
        id: 'builder-navigation',
        title: 'Navigation & view',
        entries: [
          {
            id: 'builder-pan-zoom',
            title: 'Pan, zoom & follow',
            keywords: 'middle drag scroll window playhead',
            table: [
              ['Middle-drag', 'Pan the zoom window (drag right → window moves right). Panning switches follow off.'],
              ['` (backtick)', 'Toggle follow mode (auto-scroll with playback) vs. manual zoom.'],
              ['Ctrl+F', 'Also toggles follow mode.'],
              ['Full-song bar', 'Drag the zoom region\'s center or edges to pan/resize; in follow mode this adjusts the look-ahead window.'],
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
              ['Right-click', 'Place the armed event (on a marker: reassign it).'],
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
            keywords: 'shift all offset resize canvas height live capture import setlist mode',
            table: [
              ['Shift all', 'Preview sliding every trigger by an offset, then apply. Double-click the slider to reset to 0.'],
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
          'Search matches name or labels; type chips narrow by kind. Row icons: 🔒 built-in (read-only), 🌳 composite tree, ⚡ energy level, AI = exposed to AI trigger generation. ▶ test-fires the event immediately.',
          'Create buttons: + Random / + Sequence / + Parallel start a new composite event with that root group.',
        ],
      },
      {
        id: 'events-editor',
        title: 'Editing an event',
        keywords: 'undo redo save fire duplicate drag reorder weight scope',
        body: [
          'Edits are drafts — Save writes to the server; ▶ Fire is disabled while dirty because firing uses the stored event. Drag cards to reorder; every action can be copied and pasted into any track of any event (cross-tab too).',
          'Group types: Sequence (children in order, ms or beat delays), Parallel (all at once, per-child offset), Random (weighted pick of one option). Scopes cascade: a child with no target inherits the nearest group/lane target.',
        ],
        table: [
          ['Ctrl+Z / Ctrl+Shift+Z', 'Undo / redo draft edits.'],
          ['Esc', 'Close the add-action dialog.'],
          ['Enter', 'In the add-action dialog, picks the action when the search narrows to one.'],
        ],
        kbd: true,
      },
      {
        id: 'events-actions',
        title: 'Action types',
        keywords: 'event_ref ledfx scene ambient transition effect param morph color device settings',
        table: [
          ['event_ref', "Fire another event's action pool."],
          ['morph_step', 'Multi-target aspect changes (brightness / reactivity / blur / color / bg color / effect / shape), absolute or nudge, with ramps.'],
          ['morph_color', 'Rotate the showing colors around the hue wheel (180° = complementary).'],
          ['set_color', 'Sets gradient + background + sparks together.'],
          ['ledfx_scene / ledfx_ambient', 'Activate a LedFX scene / ambient behavior.'],
          ['ledfx_ambient_color', 'Applies the complementary of the current ambient color.'],
          ['ledfx_global_transition / ledfx_effect_param', 'Set the global transition / a single effect parameter.'],
          ['device_settings', 'Apply raw device settings.'],
          ['sequence / parallel / random group', 'Containers — run children in order / at once / pick one by weight.'],
        ],
        kbd: false,
      },
      {
        id: 'events-bindings',
        title: 'Value bindings (⚡)',
        keywords: 'signal rms bass onset section energy trigger intensity threshold map',
        body: [
          'Any bindable field can swap its fixed value for a live music signal — rms_total, rms_bass, onset_score, section_energy, or trigger_intensity — with a beat averaging window, a mapped range or threshold steps, and a fallback for when the signal is missing.',
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
        keywords: 'activate pause dinner party ambient analyzed',
        table: [
          ['Activate', 'Master switch — pause/resume trigger firing.'],
          ['Dinner Party', 'Ignore song triggers; use automatic ambient lighting.'],
          ['Ambient', 'Hold the configured devices at a static full-brightness color (Hue REST) and exclude them from triggers.'],
          ['Analyzed', 'Use analyzed (auto-generated) triggers for songs without user triggers.'],
        ],
        kbd: false,
      },
      {
        id: 'now-source-badge',
        title: 'Trigger source badge',
        keywords: 'manual ai generated simple auto triggerless override',
        body: [
          'Shows where the current song\'s triggers come from: Manual (hand-built profile), AI Generated, Simple Triggerless (interval-based), Auto Triggerless (analyzed pipeline), or Analyzed Override.',
        ],
      },
      {
        id: 'now-shape',
        title: 'Audio shape & recapture',
        keywords: 'offset drift quality recapture badge realign self-correction triggers shift',
        body: [
          'The Audio Shape card shows the captured waveform with the live offset status ("start +Xms → now +Yms, Q=quality"). A "recapture suggested" badge appears when the stored offset keeps disagreeing with live audio; Recapture deletes the stored shape (audio + analysis) so the song re-records on its next play.',
          'Recapture self-corrects: when a song is force-recaptured, the new recording is cross-correlated against the old one and any timing shift between the two is applied automatically to the song\'s triggers (including per-Set-List overrides), pending AI suggestions, and learned offsets — so existing triggers keep landing on the same musical moments. If the shift can\'t be measured confidently, triggers are left untouched and offsets relearn from scratch.',
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
      'Named color palettes for events to draw from. A Set holds per-device/category entries (FG gradient or solid, BG color and mode, brightness, accent color, ramp). A Group plays Sets in a cycle (wrap/bounce) or weighted-random order.',
    entries: [
      {
        id: 'colorsets-workflow',
        title: 'Working with sets',
        keywords: 'import preview duplicate labels',
        table: [
          ['⤓ Import', 'Read the current FG/BG colors off selected LedFX devices into a new Set.'],
          ['▶ Preview', 'Apply the selected Set to LedFX right now.'],
          ['Labels', 'Comma-separated; label filters on triggers/actions pick which sets are eligible.'],
          ['Gradients', 'Live in a shared library — edit stops and direction, then "Update current" or "Save as new".'],
        ],
        kbd: false,
      },
    ],
  },

  /* ── Devices ─────────────────────────────────────────────────── */
  {
    id: 'devices',
    title: 'Devices',
    keywords: 'categories virtuals ledfx tree',
    intro:
      'Organizes LedFX virtuals into a category tree that events and color sets target. A category has a name, optional parent, a role (e.g. ambient), its LedFX virtual IDs, and a list of supported effects.',
    entries: [
      {
        id: 'devices-import',
        title: 'Importing virtuals',
        body: [
          'Use "Import from LedFX" to list live virtuals with pixel count, current effect, and any existing category assignment; the filter box matches the virtual id.',
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

  /* ── AI Triggers ─────────────────────────────────────────────── */
  {
    id: 'aitriggers',
    title: 'AI Triggers',
    keywords: 'claude generate suggestions review knn embedded haiku sonnet',
    intro:
      'Generate suggested trigger placements per song — via Claude (Haiku/Sonnet, costed) or the free local Embedded (KNN) model — then review, adjust, and apply them to the song\'s profile. Shown in the nav when "Show AI Triggers" is enabled in Settings.',
    entries: [
      {
        id: 'aitriggers-workflow',
        title: 'Workflow',
        keywords: 'training songs target generate cost confirm',
        body: [
          'Pick or create a Training Profile (vibe description + genres), add training songs (AI + Embedded are sent to Claude and used for KNN; Embedded Only songs feed KNN alone), add Target Songs (they need a captured audio shape), then Generate. Model buttons in the cost-confirm dialog require a 500 ms hold; Embedded runs free and locally.',
          'If a target song already has triggers you choose: keep them (AI suggests additions only, no duplicates) or hold the delete button for 2 seconds to wipe them first.',
        ],
      },
      {
        id: 'aitriggers-review',
        title: 'Review panel',
        keywords: 'approve reject apply markers confidence feedback',
        body: [
          'Suggestions appear as canvas markers: white = pending, green = approved, faded red = rejected, blue = manually added. Approve individually, or "✓ Approve ≥80%" by confidence, then Apply Approved to write them into the profile.',
        ],
        table: [
          ['Drag a marker', 'Move the suggestion in time (snapped); a plain click highlights its row.'],
          ['Double-click empty canvas', 'Add a manual suggestion there.'],
          ['Right-click canvas', 'Quick-add a suggestion with the last-used event.'],
          ['Middle-drag', 'Pan the view.'],
          ['Band chips', 'Click toggles the band fill; right-click toggles its rolling-average line.'],
        ],
        kbd: false,
      },
      {
        id: 'aitriggers-learning',
        title: 'Analyze & feedback',
        keywords: 'analyze learning refine profile description comments',
        body: [
          'Per-suggestion comments and the song feedback box are sent to Analyze Learning: "Analyze This Song" / "Analyze All" has Claude study what you approved and rejected and propose a refined profile description you can apply or discard.',
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
          'The saved shape draws upward from the centerline; live capture (25 ms bins) draws downward, so a good lock looks like a mirror image. Brackets mark the xcorr windows; magenta spikes are confirmed mismatches. Middle-drag pans; the timeline handles zoom.',
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
        id: 'settings-lastfm',
        title: 'Song source & Last.fm API key',
        keywords: 'spotify api credentials ledfx event driven genres lastfm how to',
        body: [
          'Song info comes from the Spotify API (needs client credentials from the Spotify Developer Dashboard) or from LedFX events, in which case genres are sourced from Last.fm.',
          'Getting a Last.fm API key: sign in at last.fm/api/account/create, enter any application name and description, leave callback and homepage blank, submit, then copy the API key into the field here. The key is free and rate-limited to 5 requests/second — well within SpotFX\'s usage. Your username is optional; SpotFX only uses it for future scrobbling features.',
        ],
      },
      {
        id: 'settings-ambient',
        title: 'Ambient mode',
        keywords: 'hue full brightness white temp category dinner',
        body: [
          'When the Now Playing (or Home Assistant) Ambient toggle is on, the chosen device category is held at the configured color at full brightness via the Hue REST API and excluded from music triggers.',
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
