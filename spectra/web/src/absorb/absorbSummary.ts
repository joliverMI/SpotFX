/** Absorb Music's page, as WORDS — every sentence the page shows about a
 * run, the playlist or the schedule is decided here, kept free of React so
 * `scripts/check_absorb_page.mjs` can transpile it and drive the whole
 * table directly. The page (AbsorbPage.tsx) only lays these out.
 *
 * Nothing here invents a number: a head rate with no committed capture is
 * "none yet", never 0 %; a silence the run never proved is "not proven",
 * never a tick. A line that cannot be known says so. */
import type {
  AbsorbBrief, AbsorbConfig, AbsorbCounts, AbsorbHeadRate, AbsorbHeadTally, AbsorbParkedSong,
  AbsorbRealign, AbsorbRun, AbsorbRunSummary, AbsorbScheduleOutcome, AbsorbWindow,
} from './types';

export const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const;
export const DAY_SHORT: Record<string, string> = {
  mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu', fri: 'Fri', sat: 'Sat', sun: 'Sun',
};
export const DAY_LETTER: Record<string, string> = {
  mon: 'M', tue: 'T', wed: 'W', thu: 'T', fri: 'F', sat: 'S', sun: 'S',
};

/** The new window `+ Add a window` starts from — the report's own example
 * evening ("every night from nine thirty to half past midnight"). */
/** HH:MM, 00:00-23:59 — models/absorb.py's own `_HHMM`. */
const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

export const DEFAULT_WINDOW: AbsorbWindow = { days: [...DAYS], start: '21:30', end: '00:30' };

// ── the playlist link ──────────────────────────────────────────────────────

const PLAYLIST_RE = /(?:spotify:playlist:|open\.spotify\.com\/(?:intl-[a-z-]+\/)?playlist\/)([A-Za-z0-9]+)/;
const BARE_ID_RE = /^[A-Za-z0-9]{16,40}$/;

/** A pasted Spotify playlist link (URI, open.spotify.com URL with or
 * without its query string, or a bare id) as the canonical
 * `spotify:playlist:<id>`, or null — the same three shapes
 * services/absorb_spotify.py's `parse_playlist_id` accepts, so a link the
 * page offers to save is one the runner can read. */
export function parsePlaylistLink(link: string): string | null {
  const s = (link || '').trim();
  if (!s) return null;
  const m = PLAYLIST_RE.exec(s);
  if (m) return `spotify:playlist:${m[1]}`;
  if (BARE_ID_RE.test(s)) return `spotify:playlist:${s}`;
  return null;
}

// ── the run's state ────────────────────────────────────────────────────────

export type Tone = 'idle' | 'live' | 'ok' | 'warn' | 'bad';

export interface StateView {
  label: string;
  tone: Tone;
  /** One sentence: what it is doing, or why it is not. */
  detail: string;
}

const STAGE_WORDS: Record<string, [string, string]> = {
  opening: ['Opening', 'Silencing the house and proving it before the first song plays.'],
  warming_up: ['Warming up', 'Playing one song that is already captured, so the next song starts at a clean track boundary.'],
  capturing: ['Capturing', 'Playing the queue on Serenity with the house silent.'],
  draining: ['Finishing', 'The queue is empty — waiting for the last captures to land.'],
  finishing: ['Finishing the song', 'The window\'s time is up; the song being captured ends within the overrun grace, so it is finished first.'],
  closing: ['Closing', 'Pausing, letting the last capture land, then giving the house back.'],
};

/** What the Run card's badge says. `cfg` supplies the quiet clock's length
 * for a paused window ("comes back after 20 minutes of quiet"). */
export function stateView(b: AbsorbBrief | null | undefined, cfg?: Pick<AbsorbConfig, 'resume_after_quiet_min' | 'max_resumes_per_window'> | null): StateView {
  if (!b || b.state === 'idle') {
    return { label: 'Idle', tone: 'idle', detail: 'Nothing is running. Start a window now, or let the evening schedule open one.' };
  }
  if (b.state === 'running') {
    const [label, detail] = STAGE_WORDS[b.stage ?? ''] ?? ['Running', 'Absorb has the playlist playing on Serenity.'];
    return { label, tone: 'live', detail };
  }
  if (b.state === 'paused') {
    const quiet = cfg?.resume_after_quiet_min;
    const back = quiet ? `It comes back after ${quiet} minutes of confirmed quiet.` : 'It comes back once your music has been quiet for a while.';
    if (b.stage === 'waiting') {
      return { label: 'Waiting', tone: 'warn', detail: `${b.wait_detail || 'Your music was playing when the window opened.'} The house was not touched. ${back}` };
    }
    const cap = cfg ? ` (${b.resumes ?? 0} of ${cfg.max_resumes_per_window} comebacks used)` : '';
    return { label: 'Stepped aside', tone: 'warn', detail: `${b.wait_detail || 'Your music took over.'} The house volume was given back first. ${back}${cap}` };
  }
  if (b.state === 'refused') {
    return { label: 'Refused', tone: 'bad', detail: b.end_detail || 'The window would not open.' };
  }
  const good = b.end_reason === 'queue_done' || b.end_reason === 'window_closed' || b.end_reason === 'stopped'
    || b.end_reason === 'nothing_to_capture';
  return { label: 'Ended', tone: good ? 'idle' : 'warn', detail: b.end_detail || 'The window ended.' };
}

/** A window is OPEN while it runs or while it is paused (waiting for his
 * quiet) — Stop applies to both; Start to neither. */
export function windowOpen(b: AbsorbBrief | null | undefined): boolean {
  return !!b && (b.state === 'running' || b.state === 'paused');
}

/** "Song 14 of 203 · attempt 1" — the song now playing among the songs
 * this window still has work for (done + this one + the queue behind it).
 * A warm-up song is not work, and says what it is instead. */
export function progressLine(b: AbsorbBrief | null | undefined): string | null {
  const np = b?.now_playing;
  if (!b || !np) return null;
  if (np.mode === 'warmup') return 'Warm-up — already captured, played so the next song starts at a clean track boundary';
  const c = b.counts;
  const done = (c?.captured ?? 0) + (c?.parked ?? 0);
  const total = done + (b.queue_len ?? 0) + 1;
  return `Song ${done + 1} of ${total} · attempt ${np.attempt || 1}`;
}

export const MODE_WORD: Record<string, string> = {
  fresh: 'first capture', recapture: 're-capture', warmup: 'warm-up',
};

// ── the counts and the head rate ───────────────────────────────────────────

export interface CountTile {
  key: keyof AbsorbCounts;
  label: string;
  value: number;
  tone: Tone;
  title: string;
}

/** The six live counts, in the order he reads them: what got done, what
 * it walked past, what went wrong. */
export function countTiles(c: AbsorbCounts | null | undefined): CountTile[] {
  const v = (k: keyof AbsorbCounts) => c?.[k] ?? 0;
  return [
    { key: 'captured', label: 'Captured', value: v('captured'), tone: 'ok',
      title: 'Captures that committed AND landed their head — filed into Recently Captured and removed from the playlist.' },
    { key: 'skipped', label: 'Skipped', value: v('skipped'), tone: 'idle',
      title: 'Already captured (with their head) — filed into Recently Captured, tagged, never played.' },
    { key: 'failed', label: 'Failed', value: v('failed'), tone: v('failed') ? 'warn' : 'idle',
      title: 'Attempts that did not produce a usable capture (a gap, too short, rolled back, or committed without its head).' },
    { key: 'requeued', label: 'Requeued', value: v('requeued'), tone: 'idle',
      title: 'Put back in the queue right after the next song, to try again this window.' },
    { key: 'head_missed', label: 'Head missed', value: v('head_missed'), tone: v('head_missed') ? 'warn' : 'idle',
      title: 'Captures that committed but still started too late into the song — not counted as captured.' },
    { key: 'parked', label: 'Parked', value: v('parked'), tone: v('parked') ? 'bad' : 'idle',
      title: 'Songs that used up their attempts. They stay in the playlist and are listed under Needs attention.' },
  ];
}

const pct = (n: number, d: number) => Math.round((n / d) * 100);

export interface HeadRateView {
  /** null when nothing has committed — never a made-up 0 %. */
  pct: number | null;
  text: string;
}

/** §8.4's number: of the captures that COMMITTED, how many landed their
 * head. Nothing committed yet is "none yet", not 0 %. `scope` says which
 * window the sentence is about: the one open now, or the last one. */
export function headRateView(t: AbsorbHeadTally | null | undefined, scope: 'current' | 'last' = 'current'): HeadRateView {
  const a = t?.attempted ?? 0;
  if (a <= 0) {
    return { pct: null, text: scope === 'current' ? 'No capture has committed yet this window.' : 'No capture committed in the last window.' };
  }
  const w = t?.with_head ?? 0;
  const when = scope === 'current' ? 'this window' : 'in the last window';
  return { pct: pct(w, a), text: `${w} of ${a} committed capture${a === 1 ? '' : 's'} landed ${a === 1 ? 'its' : 'their'} head ${when}.` };
}

/** The re-capture half of the head rate alone — the number that tells him
 * whether the backlog's re-captures are actually landing their heads. Only
 * the full run record carries the split. */
export function recaptureHeadLine(rate: AbsorbHeadRate | null | undefined): string | null {
  const r = rate?.by_mode?.recapture;
  if (!r || r.attempted <= 0) return null;
  return `Re-captures alone: ${r.with_head} of ${r.attempted} (${pct(r.with_head, r.attempted)}%).`;
}

// ── the silence proof and the lights ───────────────────────────────────────

export interface ProofLine {
  /** true = proven, false = a problem, null = not applicable / not proven. */
  ok: boolean | null;
  text: string;
}

/** The silence proof as Absorb itself recorded it — the last silence check,
 * the capture client as the window found it, the house volume it took down
 * and whether the restore read back. Never a tick it did not earn. */
export function silenceLines(b: AbsorbBrief | null | undefined, run: AbsorbRun | null | undefined): ProofLine[] {
  const out: ProofLine[] = [];
  if (!b || b.state === 'idle' || !run) {
    return [{ ok: null, text: 'Nothing is silenced. A window turns the house volume to 0, proves every room is silent and the capture client untouched, and only then plays the first song.' }];
  }
  if (b.restore_pending) {
    out.push({ ok: false, text: `The house may still be silent: ${b.restore_pending}` });
  }
  const opened = (run.opened_ms ?? 0) > 0 || !!run.pre_window?.capture;
  if (!opened) {
    out.push({ ok: null, text: run.state === 'refused'
      ? 'The window never opened, so the house was never touched.'
      : 'The house has not been silenced (the window has not opened).' });
    return out;
  }
  const vol = run.pre_window?.snap_volume;
  const cap = run.pre_window?.capture;
  const last = run.silence_checks?.length ? run.silence_checks[run.silence_checks.length - 1] : null;
  if (b.silent) {
    const extra = last?.detail && !/^(silent|open: the house is silent)$/i.test(last.detail) ? ` — ${last.detail}` : '';
    out.push(last
      ? { ok: last.ok, text: last.ok ? `Every room silent${extra}` : `Silence check failed: ${last.detail}` }
      : { ok: null, text: 'Silence not yet proven.' });
    if (cap) {
      const name = cap.name || 'the capture client';
      out.push(cap.muted
        ? { ok: false, text: `Capture client ${name} was muted — the capture would record silence` }
        : { ok: true, text: `Capture client ${name} left untouched at ${cap.percent ?? '?'} %` });
    }
    if (vol != null) out.push({ ok: true, text: `House volume ${vol} → 0, put back to ${vol} when the window closes` });
  } else if (run.restore?.at_ms) {
    out.push(run.restore.ok
      ? { ok: true, text: vol != null ? `House volume restored to ${vol} and read back` : 'House restored and read back' }
      : { ok: false, text: `The restore did not read back: ${run.restore.detail || 'unknown'}` });
  } else {
    out.push({ ok: null, text: 'The house is not silenced right now.' });
  }
  return out;
}

/** His Q3 answer — "nothing": the lights stand down while the house is
 * silent, so no light writes during a window. */
export function lightsLine(b: AbsorbBrief | null | undefined): ProofLine {
  if (b?.lights_held) return { ok: true, text: 'Lights standing down — SPECTRA writes nothing to a light while the house is silent' };
  if (windowOpen(b)) return { ok: null, text: 'Lights are not held right now (the house is not silenced)' };
  return { ok: null, text: 'Lights are SPECTRA\'s as usual — they stand down only while a window has the house silent' };
}

/** Whether the house was asleep when the window opened — his Q5 grant,
 * recorded rather than gating. */
export function sleepingLine(b: AbsorbBrief | null | undefined): string | null {
  if (!b || b.sleeping_at_open == null) return null;
  return b.sleeping_at_open ? 'The house was asleep when this window opened (allowed — the silence proof is what can stop it).'
    : 'The house was awake when this window opened.';
}

// ── reasons ────────────────────────────────────────────────────────────────

const REASONS: Record<string, string> = {
  gap: 'a gap in the audio',
  bad_timestamps: 'bad timestamps',
  coverage: 'could no longer cover enough of the song',
  too_short: 'too short',
  governor_drain: 'the audio buffer drained',
  no_capture: 'no capture started',
  no_outcome: 'the capture never reported back',
  no_frames: 'no audio arrived',
  head_missed: 'committed without its head',
  head_unreachable: 'its head never arrived',
  wav_librosa_failed: 'analysis failed',
  anchor_zero: 'rolled back (no anchors)',
  error: 'an error',
  skipped_by_you: 'skipped by you',
  interrupted: 'interrupted',
  left_device: 'playback moved off Serenity',
  failed: 'failed',
};

/** A failure or park tag as a few words. An unknown tag shows itself
 * rather than a guess. */
export function reasonLabel(code: string | null | undefined): string {
  if (!code) return 'unknown';
  return REASONS[code] ?? code.replace(/_/g, ' ');
}

const KIND_REASONS: Record<string, string> = {
  no_shape: 'no shape yet',
  failed_before: 'an earlier capture failed',
  incomplete: 'shape incomplete',
  capture_failed: 'last capture failed',
  no_npz: 'shape file missing',
  no_librosa: 'not analysed',
  needs_recapture: 'flagged for re-capture',
  unreadable_head: 'head unreadable',
  renders_nothing: 'renders nothing',
  headless: 'missing its head',
  force_recapture: 'force recapture is on',
};

/** Why the preview counted a song as to-capture or to-re-capture. */
export function kindReasonLabel(code: string): string {
  return KIND_REASONS[code] ?? code.replace(/_/g, ' ');
}

/** The preview's reason tallies as one line, biggest first. */
export function reasonsLine(reasons: Record<string, number> | null | undefined): string | null {
  const entries = Object.entries(reasons ?? {}).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return null;
  return entries.map(([k, n]) => `${kindReasonLabel(k)} (${n})`).join(' · ');
}

// ── force recapture ────────────────────────────────────────────────────────

/** Spelled out beside the switch (report §8.6): under his Q1 answer the
 * default run ALREADY re-captures every song missing its head, so the
 * switch now means the stronger thing. */
export function forceRecaptureMeaning(on: boolean): string {
  return on
    ? 'On: re-capture even the ones that pass. Every song in the playlist plays and is captured again, head or no head — nothing is skipped.'
    : 'Off: songs that already pass (captured, analysed, head within the first second) are filed straight into Recently Captured without playing. Songs missing their head, unanalysed or flagged are re-captured anyway.';
}

// ── needs attention ────────────────────────────────────────────────────────

/** "Its head never arrived · 3 attempts · last: committed without its head". */
export function parkedLine(p: AbsorbParkedSong): string {
  const parts = [reasonLabel(p.reason)];
  if (p.lifetime_attempts) parts.push(`${p.lifetime_attempts} attempt${p.lifetime_attempts === 1 ? '' : 's'}`);
  if (p.last_failure && p.last_failure !== p.reason) parts.push(`last: ${reasonLabel(p.last_failure)}`);
  return parts.join(' · ');
}

/** Every song whose authored triggers a committed re-capture moved, across
 * this run and the earlier runs the page has — newest first, one row per
 * song. A realign that moved nothing (no triggers, or not applied) is not
 * news and is left out. */
export function realignedSongs(run: AbsorbRun | null | undefined, earlier: AbsorbRunSummary[] | null | undefined): AbsorbRealign[] {
  const all = [...(run?.realigned ?? []), ...(earlier ?? []).flatMap((r) => r.realigned ?? [])];
  const best = new Map<string, AbsorbRealign>();
  for (const e of all) {
    if (!(e.triggers > 0) || e.status !== 'applied') continue;
    const prev = best.get(e.uri);
    if (!prev || e.at_ms > prev.at_ms) best.set(e.uri, e);
  }
  return [...best.values()].sort((a, b) => b.at_ms - a.at_ms);
}

/** "6 of your triggers moved +240 ms (match 0.92)". */
export function realignLine(e: AbsorbRealign): string {
  const sign = e.shift_ms > 0 ? '+' : '';
  return `${e.triggers} of your trigger${e.triggers === 1 ? '' : 's'} moved ${sign}${e.shift_ms} ms (match ${e.r.toFixed(2)})`;
}

// ── the schedule ───────────────────────────────────────────────────────────

/** The days a window starts on, in his words. */
export function daysLabel(days: string[]): string {
  const set = new Set(days);
  const ordered = DAYS.filter((d) => set.has(d));
  if (ordered.length === 7) return 'Every day';
  if (ordered.length === 5 && ['mon', 'tue', 'wed', 'thu', 'fri'].every((d) => set.has(d))) return 'Weekdays';
  if (ordered.length === 2 && set.has('sat') && set.has('sun')) return 'Weekends';
  if (!ordered.length) return 'No days';
  return ordered.map((d) => DAY_SHORT[d]).join(', ');
}

const minutesOf = (hhmm: string) => {
  const [h, m] = hhmm.split(':').map(Number);
  return h * 60 + m;
};

/** "3 h" / "2 h 30 min" — how long a window runs, across midnight. */
export function windowLength(w: AbsorbWindow): string {
  if (!HHMM.test(w.start) || !HHMM.test(w.end)) return '';
  let d = minutesOf(w.end) - minutesOf(w.start);
  if (d <= 0) d += 24 * 60;
  const h = Math.floor(d / 60), m = d % 60;
  return h && m ? `${h} h ${m} min` : h ? `${h} h` : `${m} min`;
}

/** "Every day 21:30–00:30 · 3 h, ends the next morning". */
export function windowLabel(w: AbsorbWindow): string {
  const crosses = HHMM.test(w.start) && HHMM.test(w.end) && minutesOf(w.end) < minutesOf(w.start);
  const len = windowLength(w);
  return `${daysLabel(w.days)} ${w.start}–${w.end}${len ? ` · ${len}` : ''}${crosses ? ', ends the next day' : ''}`;
}


/** What the save would be refused for, by name — the same rules
 * models/absorb.py's validators and absorb_schedule.problems() apply, so
 * the page never offers a save the server would 422. */
export function windowProblems(windows: AbsorbWindow[]): string[] {
  const out: string[] = [];
  windows.forEach((w, i) => {
    const n = `Window ${i + 1}`;
    if (!w.days.length) out.push(`${n} has no days`);
    if (!HHMM.test(w.start)) out.push(`${n}'s start "${w.start}" is not a time`);
    if (!HHMM.test(w.end)) out.push(`${n}'s end "${w.end}" is not a time`);
    if (HHMM.test(w.start) && w.start === w.end) out.push(`${n} starts and ends at ${w.start}`);
  });
  return out;
}

export function sameWindows(a: AbsorbWindow[], b: AbsorbWindow[]): boolean {
  const norm = (ws: AbsorbWindow[]) => JSON.stringify(ws.map((w) => ({
    days: DAYS.filter((d) => w.days.includes(d)), start: w.start, end: w.end,
  })));
  return norm(a) === norm(b);
}

/** "in 3 h 12 min" / "in 12 min" / "now". */
export function inLabel(seconds: number | null | undefined): string {
  if (seconds == null) return '';
  if (seconds < 60) return 'now';
  const mins = Math.round(seconds / 60);
  if (mins < 60) return `in ${mins} min`;
  const h = Math.floor(mins / 60), m = mins % 60;
  if (h >= 48) return `in ${Math.round(h / 24)} days`;
  return m ? `in ${h} h ${m} min` : `in ${h} h`;
}

/** "3 min ago" / "2 h ago" / "yesterday" — for a time already past. */
export function agoLabel(ms: number | null | undefined, now: number): string {
  if (!ms) return '';
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 60) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  return d === 1 ? 'yesterday' : `${d} days ago`;
}

const OUTCOME_WORDS: Record<string, string> = {
  opened: 'opened',
  waiting: 'waited for your music to stop',
  refused: 'refused',
  ended: 'opened and ended at once',
  joined: 'joined the window already open',
  already_running: 'your own window was already running',
  too_late: 'too little of the window was left',
  interrupted: 'SpotFX restarted while it was open',
};

/** What the schedule did with one evening, and what became of it. */
export function outcomeLine(o: AbsorbScheduleOutcome): string {
  const what = OUTCOME_WORDS[o.outcome] ?? o.outcome.replace(/_/g, ' ');
  const parts = [`${o.label}: ${what}`];
  if (o.outcome === 'refused' && o.detail) parts[0] += ` — ${o.detail}`;
  const r = o.run;
  if (r?.counts && (r.opened_ms ?? 0) > 0) {
    const c = r.counts;
    const bits = [`${c.captured} captured`];
    if (c.skipped) bits.push(`${c.skipped} skipped`);
    if (c.parked) bits.push(`${c.parked} parked`);
    const h = headRateView(r.head_rate);
    if (h.pct != null) bits.push(`${h.pct}% landed their head`);
    parts.push(bits.join(', '));
  }
  if (r?.state && r.state !== 'running' && r.state !== 'paused' && r.end_detail && o.outcome !== 'refused') {
    parts.push(r.end_detail);
  }
  return parts.join(' · ');
}

/** The last FINISHED window that actually opened — for the Playlist card's
 * "last window" head rate. A window still open is the Run card's business
 * (its own rate, "this window"), so it is passed over here: the latest run
 * counts only once it has ended. */
export function lastOpenedRun(run: AbsorbRun | null | undefined, earlier: AbsorbRunSummary[] | null | undefined): AbsorbRun | AbsorbRunSummary | null {
  if (run && (run.opened_ms ?? 0) > 0 && run.state !== 'running' && run.state !== 'paused') return run;
  return (earlier ?? []).find((r) => (r.opened_ms ?? 0) > 0 && r.id !== run?.id) ?? null;
}
