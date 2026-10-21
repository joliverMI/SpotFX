/** ABSORB MUSIC (/absorb, Engine ▾ Absorb) — the interface for silent,
 * unattended capture of a linked Spotify playlist on Serenity
 * (data/absorb-music-plan/report.md §10 and phase 4; the runner is
 * SpotFX's services/absorb.py, reached same-origin through its own
 * /api/absorb routes — SPECTRA's backend is not involved).
 *
 * THREE CARDS, as the plan draws them:
 *   Run              the one he reads on a phone: what the window is doing,
 *                    the song it is on, the live counts (captured / skipped
 *                    / failed / requeued / head missed / parked), the
 *                    head-success rate — the first evening's measurement —
 *                    the silence proof, the light stand-down, Start now /
 *                    Skip this song / Stop, and the evening schedule.
 *   Playlist         the linked playlist by NAME, what a window would do
 *                    with it (already captured / to re-capture / to
 *                    capture), and the force-recapture switch with what it
 *                    now means spelled out beside it (§8.6).
 *   Needs attention  songs parked across runs (head_unreachable among
 *                    them) with a per-song Retry, and the songs whose
 *                    authored triggers a re-capture moved (§8.3 item 4).
 *
 * The floating 💬 Sonic (phase 5, spectra/services/absorb_console.py) is
 * the same chat as everywhere, scoped by its help topic to `sonic-absorb`;
 * it reaches these very routes, so it can never get around a gate this
 * page has.
 *
 * Every sentence is decided in absorbSummary.ts; this file only lays them
 * out. No visible help circle — each control's label explains itself on
 * hover / long-press and carries its own help topic (the one-help-"?"-per-
 * page rule; the menu row's "?" opens `absorb-music`). */
import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import Icon from '../components/Icon';
import InfoTip from '../components/InfoTip';
import PowerButton from '../components/PowerButton';
import SonicChatPopover from '../components/SonicChatPopover';
import { useToast } from '../components/Toast';
import {
  agoLabel, countTiles, DAY_LETTER, DAY_SHORT, DAYS, DEFAULT_WINDOW, forceRecaptureMeaning,
  headRateView, inLabel, lastOpenedRun, lightsLine, MODE_WORD, outcomeLine,
  parkedLine, parsePlaylistLink, progressLine, realignedSongs, realignLine, reasonsLine,
  recaptureHeadLine, sameWindows, silenceLines, sleepingLine, stateView, windowLabel,
  windowOpen, windowProblems, type ProofLine,
} from './absorbSummary';
import {
  ABSORB_QUERY_KEYS, useAbsorbConfig, useAbsorbParked, useAbsorbPreview, useAbsorbRun,
  useAbsorbSchedule, useRetryParked, useSaveAbsorbConfig, useSkipAbsorbSong,
  useSpotifyPlaylistOffers, useStartAbsorb, useStopAbsorb,
} from './queries';
import type {
  AbsorbBrief, AbsorbConfig, AbsorbParkedSong, AbsorbPreview, AbsorbRun, AbsorbRunSummary,
  AbsorbSchedule, AbsorbWindow,
} from './types';

const clock = (ms: number | null | undefined) =>
  ms ? new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';

/** A song as he reads it: its title, else the bare track id. */
const songWord = (title: string | null | undefined, uri: string) =>
  title || uri.replace(/^spotify:track:/, 'track ');

const STARTED_BY: Record<string, string> = {
  press: 'your press', schedule: 'the schedule', sonic: 'Sonic', ha: 'Home Assistant',
};

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export default function AbsorbPage() {
  const qc = useQueryClient();
  const cfgQ = useAbsorbConfig();
  const runQ = useAbsorbRun();
  const cfg = cfgQ.data ?? null;
  const brief = runQ.data?.brief ?? null;
  const run = runQ.data?.run ?? null;
  const earlier = runQ.data?.earlier ?? [];
  const open = windowOpen(brief);
  const linked = !!cfg?.source_playlist_uri?.trim();
  const previewQ = useAbsorbPreview(linked);
  const scheduleQ = useAbsorbSchedule();
  const parkedQ = useAbsorbParked(open);

  // A window ending changes what the playlist holds (songs filed, parked):
  // re-read the preview and the parked list once, on that edge.
  const wasOpen = useRef(open);
  useEffect(() => {
    if (wasOpen.current && !open) {
      void qc.invalidateQueries({ queryKey: ABSORB_QUERY_KEYS.preview });
      void qc.invalidateQueries({ queryKey: ABSORB_QUERY_KEYS.parked });
    }
    wasOpen.current = open;
  }, [open, qc]);

  const unreachable = cfgQ.isError || runQ.isError;

  return (
    <div className="absorb-page">
      <header className="absorb-head">
        <h2>
          <InfoTip topic="absorb-music"
            text="Plays a linked Spotify playlist on Serenity with the house silent, so every song's audio shape gets captured — fresh songs first, then the ones whose shape is missing its head. Captured songs move to Recently Captured.">
            <span className="absorb-title"><Icon name="absorb" size={20} /> Absorb Music</span>
          </InfoTip>
        </h2>
        <p className="absorb-sub">
          Plays your linked playlist on Serenity with every room silent, so each song&apos;s audio
          shape is captured from its very first second. Captured songs leave the playlist for
          Recently Captured; the ones that fail come back after the next song.
        </p>
      </header>

      {unreachable && (
        <div className="card absorb-error" role="alert">
          SpotFX didn&apos;t answer, so Absorb can&apos;t be read right now — it runs inside SpotFX
          (port 8000), not SPECTRA. {errText(cfgQ.error ?? runQ.error)}
        </div>
      )}

      <div className="absorb-grid">
        <RunCard brief={brief} run={run} earlier={earlier} cfg={cfg} linked={linked}
          schedule={scheduleQ.data ?? null} />
        <PlaylistCard cfg={cfg} linked={linked} open={open} brief={brief} run={run} earlier={earlier}
          preview={previewQ.data ?? null} previewLoading={previewQ.isFetching}
          previewError={previewQ.isError ? errText(previewQ.error) : null}
          onRefresh={() => void previewQ.refetch()} />
        <AttentionCard cfg={cfg} open={open} run={run} earlier={earlier}
          parked={parkedQ.data?.parked ?? null} />
      </div>
      <SonicChatPopover helpTopic="sonic-absorb" />
    </div>
  );
}

// ── Run ─────────────────────────────────────────────────────────────────────

function RunCard({ brief, run, earlier, cfg, linked, schedule }: {
  brief: AbsorbBrief | null; run: AbsorbRun | null; earlier: AbsorbRunSummary[];
  cfg: AbsorbConfig | null; linked: boolean; schedule: AbsorbSchedule | null;
}) {
  const toast = useToast();
  const start = useStartAbsorb();
  const stop = useStopAbsorb();
  const skip = useSkipAbsorbSong();
  const sv = stateView(brief, cfg);
  const open = windowOpen(brief);
  const np = brief?.now_playing ?? null;
  const progress = progressLine(brief);
  const isCurrent = open;
  const ran = !!brief && brief.state !== 'idle';
  const head = ran ? headRateView(brief?.head_rate, isCurrent ? 'current' : 'last')
    : { pct: null, text: 'No window has run yet — the first one measures how many re-captures land their head.' };
  const recap = recaptureHeadLine(run?.head_rate);
  const busy = start.isPending || stop.isPending || skip.isPending;

  const onStart = async () => {
    if (!window.confirm('Start Absorb Music now? It turns the house volume to 0 (the capture client is left alone), proves every room is silent, then plays the linked playlist on Serenity until the queue is done or you press Stop.')) return;
    try {
      const r = await start.mutateAsync({ started_by: 'press' });
      if (r.status === 'refused' || r.status === 'already_running') toast(r.detail || 'Absorb did not start', 'error');
      else if (r.status === 'running') toast('Absorb started', 'success');
      else toast(r.detail || `Absorb: ${r.status}`, 'info');
    } catch (e) {
      toast(errText(e), 'error');
    }
  };
  const onStop = async () => {
    try {
      const r = await stop.mutateAsync(undefined);
      toast(r.status === 'ended' ? 'Absorb stopped — the house is given back' : 'Absorb was not running', 'info');
    } catch (e) {
      toast(errText(e), 'error');
    }
  };
  const onSkip = async () => {
    try {
      const r = await skip.mutateAsync(undefined);
      toast(r.status === 'skipped' ? 'Skipped — it comes back after the next song' : 'Nothing was playing', 'info');
    } catch (e) {
      toast(errText(e), 'error');
    }
  };

  const meta: string[] = [];
  if (brief && brief.state !== 'idle') {
    if (brief.started_by) meta.push(`started by ${STARTED_BY[brief.started_by] ?? brief.started_by}`);
    if (brief.opened_ms) meta.push(`opened ${clock(brief.opened_ms)}`);
    else if (brief.started_ms) meta.push(`${brief.state === 'refused' ? 'tried' : 'started'} ${clock(brief.started_ms)}`);
    if (brief.window?.label) meta.push(brief.window.label);
    if (brief.window?.end && open) meta.push(`ends ${clock(brief.window.end)}`);
    if (!open && brief.ended_ms) meta.push(`ended ${clock(brief.ended_ms)}`);
  }
  const sleeping = sleepingLine(brief);
  const proof: ProofLine[] = [...silenceLines(brief, run), lightsLine(brief)];

  return (
    <section className="card absorb-card absorb-run-card" aria-label="Run">
      <div className="absorb-card-head">
        <InfoTip topic="absorb-music"
          text="The window playing now (or the last one): what it is doing, the song it is on, and what it has done so far.">
          <span className="card-title absorb-card-title">Run</span>
        </InfoTip>
        <span className={`absorb-state absorb-tone-${sv.tone}`} data-testid="absorb-state">{sv.label}</span>
        <div className="absorb-actions">
          {!open && (
            <button type="button" className="primary absorb-start" disabled={!linked || busy || !cfg}
              title={linked ? 'Open a window now' : 'Link a playlist first'} onClick={() => void onStart()}>
              <Icon name="play" size={14} /> Start now
            </button>
          )}
          {open && brief?.state === 'running' && np && (
            <button type="button" disabled={busy} onClick={() => void onSkip()}
              title="Move on now; this song comes back after the next one and the skip is not counted as an attempt">
              Skip this song
            </button>
          )}
          {open && (
            <button type="button" className="danger absorb-stop" disabled={busy} onClick={() => void onStop()}
              title="End the window now — the house volume comes back at once">
              <Icon name="pause" size={14} /> Stop
            </button>
          )}
        </div>
      </div>
      <p className="absorb-state-detail">{sv.detail}</p>
      {!open && cfg && !linked && (
        <p className="absorb-meta" data-testid="absorb-link-first">Link a playlist first (in the Playlist card) — Start plays it.</p>
      )}
      {meta.length > 0 && <p className="absorb-meta">{meta.join(' · ')}</p>}

      <div className="absorb-run-body">
        <div className="absorb-run-main">
          {np && open && (
            <div className="absorb-now" data-testid="absorb-now">
              <div className="absorb-now-label">Now {np.mode === 'warmup' ? 'warming up' : 'capturing'}</div>
              <div className="absorb-now-title">{songWord(np.title, np.uri)}</div>
              <div className="absorb-now-line tabular-nums">
                <span className={`absorb-mode absorb-mode-${np.mode}`}>{MODE_WORD[np.mode] ?? np.mode}</span>
                {progress && <span>{progress}</span>}
              </div>
            </div>
          )}

          <div className="absorb-section">
            <InfoTip topic="absorb-failures"
              text="What this window did. Failed attempts are requeued right after the next song; a capture that commits without its head counts as head missed, not captured; a song is parked once it uses up its attempts.">
              <span className="absorb-section-title">{isCurrent ? 'This window' : ran ? 'Last window' : 'Counts'}</span>
            </InfoTip>
            <div className="absorb-tiles">
              {countTiles(brief?.counts).map((t) => (
                <div key={t.key} className={`absorb-tile absorb-tone-${ran ? t.tone : 'idle'}`} title={t.title}
                  data-testid={`absorb-count-${t.key}`}>
                  <span className="absorb-tile-value tabular-nums">{ran ? t.value : '—'}</span>
                  <span className="absorb-tile-label">{t.label}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="absorb-section">
            <InfoTip topic="absorb-already-captured"
              text="Of the captures that committed, how many landed their head — the first second of the song. This is the number that says whether the re-captures are actually fixing the headless shapes.">
              <span className="absorb-section-title">Head-success rate</span>
            </InfoTip>
            <div className="absorb-headrate" data-testid="absorb-headrate">
              <span className="absorb-headrate-pct tabular-nums">{head.pct == null ? '—' : `${head.pct}%`}</span>
              <div className="absorb-headrate-text">
                <div className="absorb-bar" aria-hidden="true">
                  <span style={{ width: `${head.pct ?? 0}%` }} />
                </div>
                <span>{head.text}</span>
                {recap && <span className="absorb-dim">{recap}</span>}
              </div>
            </div>
          </div>

          <EarlierRuns earlier={earlier} />
        </div>

        <div className="absorb-run-side">
          <div className="absorb-section">
            <InfoTip topic="absorb-silence"
              text="How Absorb keeps the house silent: the house volume goes to 0, the capture client is left exactly as it was, every room is read back and re-checked every minute, and the volume is put back and read back when the window ends.">
              <span className="absorb-section-title">Silence proof</span>
            </InfoTip>
            <ul className="absorb-proof" data-testid="absorb-proof">
              {proof.map((l) => <ProofItem key={l.text} line={l} />)}
            </ul>
            {sleeping && <p className="absorb-dim absorb-note">{sleeping}</p>}
          </div>
          {cfg && <ScheduleSection cfg={cfg} schedule={schedule} />}
        </div>
      </div>
    </section>
  );
}

function ProofItem({ line }: { line: ProofLine }) {
  const cls = line.ok === true ? 'ok' : line.ok === false ? 'bad' : 'none';
  return (
    <li className={`absorb-proof-${cls}`}>
      <span className="absorb-dot" aria-hidden="true" />
      <span>
        {line.text}
        <span className="absorb-sr">{line.ok === true ? ' (proven)' : line.ok === false ? ' (problem)' : ''}</span>
      </span>
    </li>
  );
}

function EarlierRuns({ earlier }: { earlier: AbsorbRunSummary[] }) {
  const now = Date.now();
  const shown = earlier.filter((r) => r.state !== 'refused' || r.end_detail).slice(0, 3);
  if (!shown.length) return null;
  return (
    <div className="absorb-section">
      <span className="absorb-section-title">Earlier windows</span>
      <ul className="absorb-list absorb-earlier">
        {shown.map((r) => {
          const h = headRateView(r.head_rate);
          const bits = r.state === 'refused' ? [`refused — ${r.end_detail}`] : [
            `${r.counts.captured} captured`, `${r.counts.skipped} skipped`,
            ...(r.counts.parked ? [`${r.counts.parked} parked`] : []),
            ...(h.pct != null ? [`${h.pct}% heads`] : []),
          ];
          return (
            <li key={r.id}>
              <span className="absorb-list-main">{agoLabel(r.started_ms, now)}{r.window?.label ? ` · ${r.window.label}` : ''}</span>
              <span className="absorb-dim">{bits.join(' · ')}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ── the schedule (inside Run: "window state and the next window") ───────────

function ScheduleSection({ cfg, schedule }: { cfg: AbsorbConfig; schedule: AbsorbSchedule | null }) {
  const toast = useToast();
  const save = useSaveAbsorbConfig();
  const [draft, setDraft] = useState<AbsorbWindow[] | null>(null);
  const windows = draft ?? cfg.windows;
  const dirty = draft != null && !sameWindows(draft, cfg.windows);
  const problems = windowProblems(windows);

  const edit = (fn: (ws: AbsorbWindow[]) => AbsorbWindow[]) =>
    setDraft((d) => fn((d ?? cfg.windows).map((w) => ({ ...w, days: [...w.days] }))));

  const put = async (patch: Partial<AbsorbConfig>, ok: string) => {
    try {
      await save.mutateAsync(patch);
      toast(ok, 'success');
      return true;
    } catch (e) {
      toast(errText(e), 'error');
      return false;
    }
  };

  const saveWindows = async () => {
    if (!draft || problems.length) return;
    if (await put({ windows: draft }, 'Schedule saved')) setDraft(null);
  };

  const next = schedule?.next ?? null;
  const openNow = schedule?.open_now?.[0] ?? null;
  const outcomes = (schedule?.outcomes ?? []).slice(0, 3);

  return (
    <div className="absorb-section absorb-schedule" data-testid="absorb-schedule">
      <InfoTip topic="absorb-schedule"
        text="Windows in house time (New York) that open Absorb on their own — only while the schedule is switched on and at least one window is set. A window that finds your music playing waits for it to go quiet.">
        <span className="absorb-section-title">Evening schedule</span>
      </InfoTip>
      <div className="absorb-switch-row">
        <PowerButton on={cfg.enabled} ariaLabel="the Absorb schedule" size={24}
          title={cfg.enabled ? 'The schedule is ON — press to switch it off (a window already open is not stopped)' : 'The schedule is OFF — nothing opens on its own. Press to switch it on.'}
          onChange={(on) => void put({ enabled: on }, on ? 'Schedule on' : 'Schedule off')} />
        <span>Schedule {cfg.enabled ? 'on' : 'off'}</span>
      </div>
      <p className="absorb-dim absorb-note" data-testid="absorb-next">
        {openNow ? `Open now: ${openNow.label}.`
          : schedule?.active && next ? `Next: ${next.label} (house time), ${inLabel(next.in_s)}.`
            : !cfg.enabled ? 'Nothing opens on its own while the schedule is off.'
              : 'Add a window below — with none, nothing opens on its own.'}
      </p>

      <ul className="absorb-windows">
        {windows.map((w, i) => (
          <li key={i} className="absorb-window" data-testid="absorb-window">
            <div className="absorb-days" role="group" aria-label={`Window ${i + 1} days`}>
              {DAYS.map((d) => {
                const on = w.days.includes(d);
                return (
                  <button key={d} type="button" className="absorb-day" aria-pressed={on} title={DAY_SHORT[d]}
                    aria-label={DAY_SHORT[d]}
                    onClick={() => edit((ws) => {
                      const x = ws[i];
                      x.days = on ? x.days.filter((y) => y !== d) : DAYS.filter((y) => y === d || x.days.includes(y));
                      return ws;
                    })}>{DAY_LETTER[d]}</button>
                );
              })}
            </div>
            <div className="absorb-times">
              <input type="time" aria-label={`Window ${i + 1} start`} value={w.start}
                onChange={(e) => edit((ws) => { ws[i].start = e.target.value; return ws; })} />
              <span className="absorb-dim">to</span>
              <input type="time" aria-label={`Window ${i + 1} end`} value={w.end}
                onChange={(e) => edit((ws) => { ws[i].end = e.target.value; return ws; })} />
              <button type="button" className="absorb-icon-btn" aria-label={`Remove window ${i + 1}`}
                title="Remove this window" onClick={() => edit((ws) => ws.filter((_, j) => j !== i))}>
                <Icon name="trash" size={15} />
              </button>
            </div>
            <div className="absorb-dim absorb-window-label">{windowLabel(w)}</div>
          </li>
        ))}
      </ul>
      {problems.length > 0 && <ul className="absorb-problems">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      <div className="absorb-row-actions">
        <button type="button" onClick={() => edit((ws) => [...ws, { ...DEFAULT_WINDOW, days: [...DEFAULT_WINDOW.days] }])}>
          <Icon name="plus" size={14} /> Add a window
        </button>
        {dirty && (
          <>
            <button type="button" className="primary" disabled={!!problems.length || save.isPending}
              onClick={() => void saveWindows()}>Save schedule</button>
            <button type="button" onClick={() => setDraft(null)}>Cancel</button>
          </>
        )}
      </div>

      <div className="absorb-switch-row absorb-sleeping">
        <PowerButton on={cfg.run_while_sleeping} ariaLabel="running while the house sleeps" size={24}
          title={cfg.run_while_sleeping
            ? 'On — a window keeps going after the house goes to sleep, as long as the silence stays proven. Press to stop windows while the house sleeps.'
            : 'Off — a window will not run while the house is asleep. Press to allow it.'}
          onChange={(on) => void put({ run_while_sleeping: on }, on ? 'Absorb may run while the house sleeps' : 'Absorb stops while the house sleeps')} />
        <InfoTip topic="absorb-sleeping"
          text="Your Q5 grant: Absorb may keep running after the house goes to sleep — for Absorb only — because it is silent. The silence is re-proven every minute; if it ever fails, or anything could be audible, the window stops.">
          <span>Keep going while the house sleeps</span>
        </InfoTip>
      </div>

      {outcomes.length > 0 && (
        <ul className="absorb-list absorb-outcomes" aria-label="What the schedule did">
          {outcomes.map((o) => (
            <li key={`${o.occurrence_start_ms}-${o.at_ms}`} className={o.outcome === 'refused' ? 'absorb-outcome-refused' : ''}>
              {outcomeLine(o)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Playlist ────────────────────────────────────────────────────────────────

function PlaylistCard({ cfg, linked, open, brief, run, earlier, preview, previewLoading, previewError, onRefresh }: {
  cfg: AbsorbConfig | null; linked: boolean; open: boolean; brief: AbsorbBrief | null;
  run: AbsorbRun | null; earlier: AbsorbRunSummary[]; preview: AbsorbPreview | null;
  previewLoading: boolean; previewError: string | null; onRefresh: () => void;
}) {
  const toast = useToast();
  const save = useSaveAbsorbConfig();
  const [editing, setEditing] = useState(false);
  const [paste, setPaste] = useState('');
  const picking = editing || (!!cfg && !linked);
  const offers = useSpotifyPlaylistOffers(picking);
  const name = preview?.playlist?.name
    || (brief?.source_playlist_uri === cfg?.source_playlist_uri ? brief?.source_playlist_name : '')
    || '';
  const c = preview?.counts;
  const last = lastOpenedRun(run, earlier);
  const lastHead = last ? headRateView(last.head_rate, 'last') : null;
  const reasons = reasonsLine(preview?.reasons);

  const link = async (uri: string, label?: string) => {
    try {
      await save.mutateAsync({ source_playlist_uri: uri });
      setEditing(false);
      setPaste('');
      const when = open ? ' — it takes effect at the next window' : '';
      toast(uri ? `Linked ${label || 'the playlist'}${when}` : `Playlist unlinked${when}`, 'success');
    } catch (e) {
      toast(errText(e), 'error');
    }
  };

  const onPaste = () => {
    const uri = parsePlaylistLink(paste);
    if (!uri) {
      toast('That is not a Spotify playlist link', 'error');
      return;
    }
    void link(uri);
  };

  const setForce = async (on: boolean) => {
    if (on && !window.confirm('Turn force recapture on? Every song in the playlist will play and be captured again — even the ones that already pass, head and all.')) return;
    try {
      await save.mutateAsync({ force_recapture: on });
      toast(on ? 'Force recapture on' : 'Force recapture off', 'success');
    } catch (e) {
      toast(errText(e), 'error');
    }
  };

  return (
    <section className="card absorb-card absorb-playlist-card" aria-label="Playlist">
      <div className="absorb-card-head">
        <InfoTip topic="absorb-already-captured"
          text="The playlist Absorb plays, and what a window would do with it: songs that already pass are filed without playing, the rest are captured or re-captured.">
          <span className="card-title absorb-card-title">Playlist</span>
        </InfoTip>
        {linked && (
          <div className="absorb-actions">
            <button type="button" className="absorb-icon-btn" aria-label="Read the playlist again"
              title="Read the playlist again" disabled={previewLoading} onClick={onRefresh}>
              <Icon name="sync" size={15} />
            </button>
            <button type="button" onClick={() => setEditing((v) => !v)}>{editing ? 'Cancel' : 'Change'}</button>
          </div>
        )}
      </div>

      {!cfg && <p className="absorb-dim">Reading…</p>}
      {cfg && linked && (
        <div className="absorb-linked" data-testid="absorb-linked">
          <span className="absorb-linked-name">{name || 'Linked playlist'}</span>
          {c && <span className="absorb-dim tabular-nums">{c.total} song{c.total === 1 ? '' : 's'}</span>}
        </div>
      )}

      {cfg && picking && (
        <div className="absorb-link" data-testid="absorb-link">
          {!linked && <p className="absorb-dim">No playlist is linked yet. Pick one you played recently, or paste its link.</p>}
          {(offers.data ?? []).length > 0 && (
            <div className="absorb-offers">
              {(offers.data ?? []).slice(0, 6).map((o) => (
                <button key={o.context_uri} type="button" disabled={save.isPending || o.context_uri === cfg.source_playlist_uri}
                  onClick={() => void link(o.context_uri, o.name)}>
                  <Icon name="plus" size={13} /> {o.name || o.context_uri}
                </button>
              ))}
            </div>
          )}
          <div className="absorb-paste">
            <input type="text" placeholder="Paste a Spotify playlist link" value={paste}
              aria-label="Spotify playlist link" onChange={(e) => setPaste(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') onPaste(); }} />
            <button type="button" className="primary" disabled={!paste.trim() || save.isPending} onClick={onPaste}>Link</button>
          </div>
          {linked && (
            <button type="button" className="absorb-link-btn" disabled={save.isPending}
              onClick={() => void link('')}>Unlink this playlist</button>
          )}
        </div>
      )}

      {cfg && linked && (
        <div className="absorb-section" data-testid="absorb-preview">
          <InfoTip topic="absorb-already-captured"
            text="A song already passes when its shape is complete, analysed, not flagged, and starts within the first second of the song. Those are filed into Recently Captured, tagged, without playing.">
            <span className="absorb-section-title">What a window would do</span>
          </InfoTip>
          {previewError && <p className="absorb-problem-line">{previewError}</p>}
          {!preview && !previewError && <p className="absorb-dim">Reading the playlist…</p>}
          {preview && preview.resolved === false && <p className="absorb-problem-line">{preview.detail}</p>}
          {c && (
            <>
              <SplitBar counts={c} />
              <div className="absorb-tiles absorb-tiles-3">
                <PreviewTile k="skip" label="Already captured" value={c.skip}
                  title="Pass the bar — filed into Recently Captured, tagged, never played" />
                <PreviewTile k="recapture" label="To re-capture" value={c.recapture}
                  title="Have a shape that fails the bar (missing its head, unanalysed or flagged) — captured again" />
                <PreviewTile k="fresh" label="To capture" value={c.fresh}
                  title="No usable shape yet — captured for the first time, first in the queue" />
              </div>
              {c.parked > 0 && <p className="absorb-dim">{c.parked} parked — left out until you retry them under Needs attention.</p>}
              {reasons && <p className="absorb-dim absorb-reasons">Why: {reasons}</p>}
            </>
          )}
          {lastHead && <p className="absorb-dim">Head-success rate: {lastHead.pct == null ? lastHead.text : `${lastHead.pct}% — ${lastHead.text}`}</p>}
        </div>
      )}

      {cfg && (
        <div className="absorb-section">
          <div className="absorb-switch-row">
            <PowerButton on={cfg.force_recapture} ariaLabel="force recapture" size={24}
              title={cfg.force_recapture ? 'Force recapture is ON — press to switch it off' : 'Force recapture is OFF (the default) — press to switch it on'}
              onChange={(on) => void setForce(on)} />
            <InfoTip topic="absorb-already-captured"
              text="Off by default. Under the head rule the default window already re-captures every song missing its head — so this switch now means re-capture even the songs that already pass.">
              <span>Force recapture {cfg.force_recapture ? 'on' : 'off'}</span>
            </InfoTip>
          </div>
          <p className="absorb-meaning" data-testid="absorb-force-meaning">{forceRecaptureMeaning(cfg.force_recapture)}</p>
        </div>
      )}

      {cfg && (
        <p className="absorb-dim absorb-note">
          Captured songs — and, tagged, the ones skipped as already captured — go on top of
          “{cfg.captured_playlist_name}”, newest first, keeping the newest {cfg.recently_captured_max}.
        </p>
      )}
    </section>
  );
}

function SplitBar({ counts }: { counts: { skip: number; recapture: number; fresh: number; parked: number } }) {
  const total = counts.skip + counts.recapture + counts.fresh + counts.parked;
  if (!total) return null;
  const seg = (n: number) => `${(n / total) * 100}%`;
  return (
    <div className="absorb-split" aria-hidden="true">
      <span className="absorb-split-skip" style={{ width: seg(counts.skip) }} />
      <span className="absorb-split-recapture" style={{ width: seg(counts.recapture) }} />
      <span className="absorb-split-fresh" style={{ width: seg(counts.fresh) }} />
      <span className="absorb-split-parked" style={{ width: seg(counts.parked) }} />
    </div>
  );
}

function PreviewTile({ k, label, value, title }: { k: string; label: string; value: number; title: string }) {
  return (
    <div className={`absorb-tile absorb-kind-${k}`} title={title} data-testid={`absorb-preview-${k}`}>
      <span className="absorb-tile-value tabular-nums">{value}</span>
      <span className="absorb-tile-label">{label}</span>
    </div>
  );
}

// ── Needs attention ─────────────────────────────────────────────────────────

function AttentionCard({ cfg, open, run, earlier, parked }: {
  cfg: AbsorbConfig | null; open: boolean; run: AbsorbRun | null; earlier: AbsorbRunSummary[];
  parked: AbsorbParkedSong[] | null;
}) {
  const toast = useToast();
  const retry = useRetryParked();
  const realigned = realignedSongs(run, earlier);
  const now = Date.now();

  const onRetry = async (uri: string, title: string) => {
    try {
      const r = await retry.mutateAsync(uri);
      toast(r.unparked
        ? `${songWord(title, uri)} will be tried again ${open ? 'in this window' : 'at the next window'}`
        : 'That song was no longer parked', r.unparked ? 'success' : 'info');
    } catch (e) {
      toast(errText(e), 'error');
    }
  };

  return (
    <section className="card absorb-card absorb-attention-card" aria-label="Needs attention">
      <div className="absorb-card-head">
        <InfoTip topic="absorb-failures"
          text="Songs Absorb gave up on for now, and songs whose triggers a re-capture moved. A parked song stays in the playlist until you retry it.">
          <span className="card-title absorb-card-title">Needs attention</span>
        </InfoTip>
      </div>

      <div className="absorb-section" data-testid="absorb-parked">
        <span className="absorb-section-title">Parked songs{parked && parked.length ? ` · ${parked.length}` : ''}</span>
        {parked == null && <p className="absorb-dim">Reading…</p>}
        {parked && parked.length === 0 && (
          <p className="absorb-dim">
            Nothing is parked. A song is parked after {cfg?.max_attempts ?? 3} attempts that do not land —
            including a re-capture whose head never arrives — and waits here for you.
          </p>
        )}
        {parked && parked.length > 0 && (
          <ul className="absorb-list absorb-parked-list">
            {parked.map((p) => (
              <li key={p.uri} className={p.reason === 'head_unreachable' ? 'absorb-parked-head' : ''}>
                <div className="absorb-list-text">
                  <span className="absorb-list-main">{songWord(p.title, p.uri)}</span>
                  <span className="absorb-dim">{parkedLine(p)}{p.parked_ms ? ` · ${agoLabel(p.parked_ms, now)}` : ''}</span>
                </div>
                <button type="button" disabled={retry.isPending} onClick={() => void onRetry(p.uri, p.title)}
                  title="Un-park it: it is captured again from the next window, or right away if a window is running">
                  Retry
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="absorb-section" data-testid="absorb-realigned">
        <span className="absorb-section-title">Triggers moved by a re-capture{realigned.length ? ` · ${realigned.length}` : ''}</span>
        {realigned.length === 0 && (
          <p className="absorb-dim">
            None yet. When a re-capture lands, your hand-placed triggers on that song are moved to follow
            the new capture&apos;s timing — every song where that happened is listed here.
          </p>
        )}
        {realigned.length > 0 && (
          <ul className="absorb-list">
            {realigned.map((e) => (
              <li key={e.uri}>
                <div className="absorb-list-text">
                  <span className="absorb-list-main">{songWord(e.title, e.uri)}</span>
                  <span className="absorb-dim">{realignLine(e)} · {agoLabel(e.at_ms, now)}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

