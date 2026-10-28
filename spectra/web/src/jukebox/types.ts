/** The Jukebox's master-side wire shapes — SpotFX's own /api/jukebox routes
 * (routers/jukebox_router.py; the engine is services/jukebox/night.py, the
 * rules services/jukebox/program.py). Field names are the server's. */

export type SlotMode = 'auto' | 'jukebox_first' | 'manual';
export type RunOut = 'again' | 'jukebox_only' | 'end';

export interface ManualSlot {
  after_uri: string;
  count: number;
}

export interface ProgramConfig {
  playlist: string;
  mode: SlotMode;
  every: number;
  run: number;
  manual: ManualSlot[];
  run_out: RunOut;
  commit_lead_s: number;
  /** §4: a song played next plays straight after the song playing, ahead of the set */
  next_jumps_set?: boolean;
}

export interface SetItem {
  uri: string;
  title: string;
  artist: string;
  duration_ms: number;
}

/** One program item: a set song, a jukebox slot with the song filling it,
 * or an open slot (passes if nobody has a song waiting). */
export interface ProgramItem {
  kind: 'set' | 'jukebox' | 'open';
  uri: string;
  title: string;
  artist: string;
  duration_ms: number;
  set_index: number | null;
  entry_id: string;
  committed: boolean;
  starts_in_ms: number | null;
}

export interface Lap {
  set_songs: number;
  slots: number;
  unbounded: boolean;
  notes: string[];
}

export interface JukeboxPreview {
  status: 'ok' | 'refused';
  reason?: string;
  detail?: string;
  playlist_name?: string;
  playlist_uri?: string;
  set_songs?: number;
  set?: SetItem[];
  lap_items?: ProgramItem[];
  next?: ProgramItem[];
  manual_equivalent?: ManualSlot[];
  playhead?: number | null;
  lap?: Lap;
}

export type SignInState = 'no_token' | 'unknown' | 'ok' | 'soon' | 'expired' | 'refresh_failed' | 'unreadable';

export interface SpotifySignIn {
  state: SignInState;
  warning: string | null;
  authorized_at_ms?: number | null;
  expires_at_ms?: number | null;
  days_left?: number | null;
}

export interface NightBrief {
  id: string;
  state: 'running' | 'ended' | 'refused';
  started_ms: number;
  started_by: string;
  ended_ms: number | null;
  end_reason: string;
  end_detail: string;
  playlist_name: string;
  playlist_uri: string;
  played: number;
  jukebox_played: number;
}

export interface NowItem {
  kind: '' | 'set' | 'jukebox' | 'skipping' | 'foreign';
  uri: string;
  title: string;
  set_index: number | null;
  entry_id: string;
  started_ms: number | null;
}

export interface LineEntry {
  id: string;
  uri: string;
  title: string;
  artist: string;
  duration_ms: number;
  added_by: string;
  state: 'queued' | 'committed' | 'playing' | 'played' | 'removed' | 'skipped';
  doomed: boolean;
  commit_check: '' | 'next' | 'later' | 'missing' | 'unread';
  /** this was its adder's Nth song tonight (fair order: 1st songs first) */
  round?: number;
  /** the host is holding it: it keeps its place, slots pass it */
  held?: boolean;
  /** the lights already know it */
  known?: boolean;
  explicit?: boolean;
  /** places other guests have bumped it back tonight (free play) */
  pushed_back?: number;
  /** credits mode: what its adder paid, and whether it has had its play next */
  paid?: number;
  nexted?: boolean;
}

export interface JukeboxStatus {
  night: NightBrief | null;
  running: boolean;
  now: NowItem | null;
  remaining_ms?: number;
  next: ProgramItem[];
  line: LineEntry[];
  lap?: Lap;
  warnings: string[];
  spotify_auth?: SpotifySignIn;
  log: string[];
  history: NightBrief[];
  /** songs the host has kept from skips tonight (their URIs) */
  no_skip?: string[];
  /** Phones on tonight's guest page (services/jukebox/guests.py): every
   *  phone that opened the party link, and those that tapped Let's go. */
  guests?: { phones: number; joined: number; pending?: number };
}

/** The Live tab's economy panel (SpotFX GET /api/jukebox/economy,
 *  services/jukebox/economy_live.py): the credits right now, the prices a
 *  guest sees now, and the night's recent events. */
export interface EconomyEvent {
  at_ms: number; kind: string; who: string; what: string; credits: number; phones?: number;
}
export interface EconomyCredits {
  minted: number; held: number; held_per_guest: number | null; unspent_share: number | null;
  by_kind: Record<string, number>; adds: number; skips_hr: number | null; nexts_hr: number | null;
  tips_hr: number | null; add_price_median: number | null; votes: number; free: number;
}
export interface EconomyPrices {
  add_first: number; add_back: number; back_wait_min: number | null; skip_now: number | null;
  next_from: number; jail_fee: number;
}
export interface JukeboxEconomy {
  running: boolean; play_mode: 'free' | 'credits';
  crowd?: number; joined?: number; jailed?: number; votes?: number; time_outs?: number;
  credits?: EconomyCredits | null; prices?: EconomyPrices | null; events?: EconomyEvent[];
}

export interface SetMoveResult {
  status: 'moved' | 'refused';
  reason?: string;
  detail?: string;
  set?: SetItem[];
}

// ── the show settings (phase 3.3) ───────────────────────────────────────────

export type Preset = 'small' | 'medium' | 'large';

/** Every economy setting (models.jukebox.EconomyConfig), by key. */
export type EconomyConfig = Record<string, number | boolean>;

export type ExplicitRule = 'no' | 'extra' | 'after';

export interface ShowConfig {
  preset: Preset | null;
  approve_new_phones: boolean;
  economy: EconomyConfig;
  /** the guests' own rules (phase 2.2) — house time "HH:MM" */
  night_ends?: string;
  last_call_min?: number;
  explicit?: ExplicitRule;
  explicit_after?: string;
  max_phones?: number;
  renames_per_night?: number;
  word_filter?: boolean;
  /** free play (PR 2.3): the room's skip, bumps, play next, the jail */
  free_skip_downs?: number;
  free_skip_share?: number;
  free_bumps_per_hour?: number;
  free_play_next?: 'host' | 'off';
  free_jail_songs?: number;
  /** the guest page's mode (PR 3.2): credits, or free play */
  play_mode?: 'free' | 'credits';
}

/** One of the guests' rules as the page draws it (services/jukebox/show.py
 * `guest_fields`): its range and choices are the server's own. */
export interface GuestField {
  key: 'night_ends' | 'last_call_min' | 'explicit' | 'explicit_after' | 'max_phones'
    | 'renames_per_night' | 'word_filter' | 'free_skip_downs' | 'free_skip_share'
    | 'free_bumps_per_hour' | 'free_play_next' | 'free_jail_songs';
  card: string;
  label: string;
  unit: string;
  kind: 'time' | 'int' | 'choice' | 'bool';
  default: string | number | boolean;
  min: number | null;
  max: number | null;
  choices: { value: string; label: string }[] | null;
}

/** A phone at tonight's party, for the host (services/jukebox/guests.py
 * `phones`). */
export interface GuestPhone {
  id: string;
  name: string;
  joined: boolean;
  created_ms: number;
  joined_ms: number | null;
  renames: number;
  approved: boolean;
  blocked: boolean;
  name_locked: boolean;
  waiting: number;
  played: number;
  votes: number;
  /** the jail (free play): songs left in its time-out (0: not in one), the
   * net ▼ on its songs since the last one, the bar, and times jailed */
  jail_left?: number;
  jail_count?: number;
  jail_at?: number;
  jails?: number;
  /** credits mode: "breakout" (until they pay) instead of a song time-out */
  jail_kind?: 'timeout' | 'breakout';
  credits?: number;
  /** the names of phones the host merged into this one (§4 "merge two phones") */
  merged_from?: string[];
}

/** The board (SpotFX services/jukebox/board.py): tonight's top songs and
 *  every people board, each marked with whether guests see it. */
export interface BoardBy { kind: 'set' | 'host' | 'guest'; name: string }
export interface BoardSong {
  uri: string; title: string; artist: string; image: string; thumb: string; open_url: string;
  by: BoardBy; ups: number; downs: number; plays: number;
}
export interface PeopleBoard { id: string; title: string; unit: string; unit_one?: string; shown: boolean;
  rows: { name: string; value: number }[] }
export interface BoardSettings {
  board_on: boolean; board_top_pickers: boolean; board_top_voters: boolean;
  board_most_generous: boolean; board_on_tv: boolean;
}
export interface JukeboxBoardRead {
  running: boolean;
  settings: BoardSettings;
  board?: { title: string; empty: string; songs: BoardSong[]; people: PeopleBoard[] };
  now?: { uri: string; title: string; artist: string; image: string; thumb: string;
          open_url: string; by: BoardBy; up: number; down: number } | null;
}

/** The printed bonus cards' codes (SpotFX services/jukebox/bonus_codes.py). */
export interface BonusCodeRow {
  code: string; batch: string; created_ms: number; used: boolean; used_ms: number | null; used_name: string;
}
export interface BonusCodesRead { unused: number; used: number; codes: BonusCodeRow[]; made?: string[] }

/** What the printable card needs (SpotFX GET /api/jukebox/card). The Wi-Fi
 *  details are never here: they are typed on the card page and stay there. */
export interface CardRead {
  link: string | null; host: string | null; state: string; public_port: number;
  token_created_ms: number | null; unused: string[]; codes_error: string | null;
  qr_bonus: number; play_mode: 'free' | 'credits';
}

export interface GuestsRead {
  running: boolean;
  phones: GuestPhone[];
  pending?: number;
  jailed?: number;
  /** phones seen in the last 15 minutes: the crowd the jail's bar rises with */
  crowd?: number;
  play_mode?: 'free' | 'credits';
}

/** One economy setting as the page draws it; the range is the server's
 * own model bound, never typed twice. */
export interface EconomyField {
  key: string;
  card: string;
  label: string;
  unit: string;
  kind: 'int' | 'float' | 'bool';
  default: number | boolean;
  min: number | null;
  max: number | null;
}

export interface PresetInfo {
  name: Preset;
  guests: string;
  why: string;
  approve_new_phones: boolean;
}

export interface ShowRead {
  show: ShowConfig;
  fields: EconomyField[];
  guest_fields?: GuestField[];
  presets: PresetInfo[];
  play_modes?: { value: string; label: string }[];
}

export interface PriceCheck {
  guests: number;
  add: { wait_min: number; price: number }[];
  add_long: { duration_min: number; price: number };
  add_not_learned: number;
  skip: { line_min: number; downs: number; price: number }[];
  play_next: { jump_min: number; price: number }[];
  bump_up: { behind: number; price: number }[];
  bump_down: { ahead: number; price: number }[];
  jail: { threshold: number; fee: number };
  start: { now: number; later: number; after_min: number };
  topup: { every_min: number; pauses_at: number };
  tips: { on: boolean; max_per_song: number; double_first: number };
  songs_in_line: number;
}

// ── the party simulator (phase 3.4; services/jukebox/simulator.py) ──────────

export type SimEventKind = 'add' | 'skip' | 'jail' | 'jail_out' | 'tip' | 'next' | 'bump_up' | 'bump_down'
  | 'too_late' | 'refund';

export interface SimEvent {
  t: number;
  kind: SimEventKind;
  g?: number;
  price?: number;
  wait?: number;
  rnd?: number;
  payers?: number[];
  of?: number | null;
  to?: number;
  amt?: number;
  bonus?: number;
  fee?: number;
  jump?: number;
  downs?: number;
}

/** The state of the night at a moment: every guest's credits, the line,
 * the wait and the add price at the back of it, who is in jail. */
export interface SimFrame {
  t: number;
  song: number;
  cr: number[];
  back: number;
  price: number;
  line: number;
  jailed: number[];
}

export interface SimSong {
  t: number;
  dur: number;
  by: number | null;
  ups?: number;
  downs?: number;
  skipped?: number | null;
}

export interface SimGuest {
  id: number;
  kind: 'regular' | 'middle' | 'quiet';
  arrive: number;
  leave: number;
  played: number;
  added: number;
  earned: number;
  spent: number;
  tips_given: number;
  jails: number;
  end_credits: number;
}

export interface SimNight {
  minutes: number;
  last_call: number;
  guests: SimGuest[];
  songs: SimSong[];
  frames: SimFrame[];
  events: SimEvent[];
  summary: Record<string, unknown>;
}

export type SimUnit = 'share' | 'count' | 'min' | 'credits' | 'rate';

export interface SimRow {
  key: string;
  label: string;
  unit: SimUnit;
  yours: number | null;
  tuned: number | null;
}

export interface SimCheck {
  key: string;
  label: string;
  target: string;
  value: number | null;
  ok: boolean | null;
}

export interface SimResult {
  guests: number;
  nights: number;
  seed: number;
  program: string;
  program_source: 'saved' | 'preset';
  mix: { set_per_slot: number; juke_per_slot: number };
  plan_preset: Preset;
  mix_is_plans: boolean;
  same_as_tuned: boolean;
  night: SimNight;
  rows: SimRow[];
  checks: SimCheck[];
}

// ── the post-party report (services/jukebox/night_report.py) ─────────────────

export interface ReportNight {
  id: string;
  state: 'running' | 'ended' | 'refused';
  playlist: string | null;
  started_ms: number | null;
  ended_ms: number | null;
  end_reason: string | null;
  end_detail: string | null;
  hours: number | null;
  played: { set: number; jukebox: number; skipped: number; foreign: number };
  jukebox_share: number | null;
  songs_per_hour: number | null;
  line: { added: number; by_host: number; by_guests: number; played: number; removed: number;
    skipped: number; playing_at_end: number; waiting_at_end: number };
  add_to_play_median_min: number | null;
  warnings_at_end: string[];
}

export interface ReportCredits {
  phones: number;
  minted: number;
  held_at_end: number;
  unspent_share: number | null;
  adds: number;
}

export interface ReportRow {
  key: string;
  label: string;
  unit: SimUnit;
  this_night: number | null;
  why: string | null;
  yours?: number | null;      // the model's nights (comparison rows only)
}

export interface NightReport {
  status: 'ok' | 'none';
  summary: string;
  night?: ReportNight;
  credits?: ReportCredits | null;
  integrity?: string[] | null;
  rows?: ReportRow[];
  comparison?: { guests: number; nights: number; program: string; rows: ReportRow[] } | null;
  guests?: number | null;
  guests_from?: 'you' | 'the ledger' | 'the guest book' | null;
}
