/** THE LIGHT SHOW's PLAYLIST CARD (Run view) and BANNER (every view).
 *
 * Show Playlists follow the Spotify playlist he plays
 * (spectra/services/show_playlists.py): when its playlist plays, a program
 * arms each song's steps as the song starts. This card shows what it is
 * doing right now — the program, the song and each of its steps (armed,
 * fired, missed), what is up next and what its entry will arm — with Stop
 * following, Skip this song's entry, and Fire now per step. When nothing
 * follows it still says where the music is playing from (phase 0).
 *
 * Everything shown is the server's (`GET /light-show/playlist-run`,
 * polled); no rule of the runner is copied here. */
import { useCallback, useEffect, useState } from 'react';
import { apiGet, apiPost } from '../api/client';
import Icon from '../components/Icon';
import HelpLink from '../help/HelpLink';
import { TIMING_ICON, entryWord, outcomeLine, runHeadline, songWord } from './playlistOps';
import type { PlaylistStatus, PlaylistTiming, StepOutcome } from './types';

type Toast = (msg: string, kind?: 'success' | 'error') => void;

/** The playlist run, polled — one hook so the banner and the card agree. */
export function usePlaylistStatus(intervalMs = 1500) {
  const [status, setStatus] = useState<PlaylistStatus | null>(null);
  const reload = useCallback(
    () => void apiGet<PlaylistStatus>('/light-show/playlist-run').then(setStatus).catch(() => undefined), []);
  useEffect(() => {
    reload();
    const t = window.setInterval(reload, intervalMs);
    return () => window.clearInterval(t);
  }, [reload, intervalMs]);
  return { status, reload };
}

/** "Following 40! Lightshow — Stop": shown on every Light Show view while a
 * program follows, so he never has to ask what changed his room. */
export function PlaylistBanner({ status, onChange, toast }: {
  status: PlaylistStatus | null; onChange: () => void; toast: Toast;
}) {
  const r = status?.run;
  if (!r?.active) return null;
  const stop = async () => {
    await apiPost('/light-show/playlist-run/stop').catch((e) => toast(String(e), 'error'));
    onChange();
  };
  return (
    <div className="light-show-playlist-banner" role="status">
      <span>♫ {runHeadline(r)}{r.song_title ? ` — ${songWord(r.song_title, r.song_artist)}` : ''}</span>
      <button type="button" onClick={() => void stop()}>Stop following</button>
      <HelpLink topic="show-playlist-run" />
    </div>
  );
}

export default function PlaylistRunCard({ status, onChange, toast }: {
  status: PlaylistStatus | null; onChange: () => void; toast: Toast;
}) {
  const [busy, setBusy] = useState(false);
  if (!status) return null;
  const r = status.run;
  const active = Boolean(r?.active);
  const from = status.playing_from;

  const call = async (path: string, body?: unknown) => {
    setBusy(true);
    try {
      await apiPost(`/light-show/playlist-run/${path}`, body);
    } catch (e) {
      toast(String(e), 'error');
    } finally {
      setBusy(false);
      onChange();
    }
  };

  return (
    <div className="card light-show-playlist-card">
      <div className="light-show-armed-head">
        <strong>Playlist</strong> <HelpLink topic="show-playlist-run" />
        {!status.follow_enabled && <span className="muted"> · following is switched off</span>}
      </div>
      {from && (
        <p className="light-show-playlist-from">
          Playing from: <b>{from.name || from.uri}</b>
          {from.program ? <span className="muted"> · program “{from.program}”</span>
            : <span className="muted"> · no program answers to it</span>}
        </p>
      )}
      {!active && (
        <p className="muted">
          {r ? `${runHeadline(r)}${r.end_reason ? ` — ${r.end_reason}` : ''}` : 'No playlist program is following.'}
        </p>
      )}
      {active && r && (
        <>
          <p className="light-show-playlist-head"><b>{runHeadline(r)}</b>
            {r.state === 'paused' && r.paused_reason && <span className="muted"> — {r.paused_reason}</span>}</p>
          {r.song_uri && (
            <p>Now: <b>{songWord(r.song_title, r.song_artist, r.song_uri)}</b>
              <span className="muted"> — {entryWord(r.entry_source)}</span></p>
          )}
          {r.start_steps.length > 0 && (
            <div className="light-show-playlist-steps">
              <span className="muted">On start</span>
              <StepRows steps={r.start_steps} busy={busy || r.state !== 'following'}
                onFire={(id) => void call('fire-step', { step_id: id })} />
            </div>
          )}
          {r.song_steps.length > 0 && (
            <StepRows steps={r.song_steps} busy={busy || r.state !== 'following'}
              onFire={(id) => void call('fire-step', { step_id: id })} />
          )}
          <div className="show-seq-controls">
            {r.state === 'paused'
              ? <button className="big primary" disabled={busy} onClick={() => void call('resume')}>▶ Resume</button>
              : <button className="big" disabled={busy || !r.song_steps.some((o) => o.status === 'armed' || o.status === 'pending')}
                  onClick={() => void call('skip-song')} title="Disarm this song's steps; the program carries on">
                  Skip this song’s entry</button>}
            <button className="big danger" disabled={busy} onClick={() => void call('stop')}
              title="Disarm the program's arms; holds and settings stay as the sets left them">■ Stop following</button>
          </div>
        </>
      )}
      {status.up_next && (
        <p className="light-show-playlist-next">
          Up next: <b>{status.up_next.title}</b>
          {active && status.up_next.entry_source && (
            <span className="muted"> — {status.up_next.summary
              ? `will arm ${status.up_next.summary}` : entryWord(status.up_next.entry_source)}</span>
          )}
        </p>
      )}
      {r && r.log.length > 0 && (
        <details className="show-seq-log">
          <summary>History ({r.log.length})</summary>
          <ul>
            {r.log.map((e, i) => (
              <li key={i}><span className="muted">{new Date(e.at_ms).toLocaleTimeString()}</span> {e.what.replace(/_/g, ' ')}{e.detail ? ` — ${e.detail}` : ''}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function StepRows({ steps, busy, onFire }: {
  steps: StepOutcome[];
  busy: boolean; onFire: (stepId: string) => void;
}) {
  return (
    <ul className="light-show-playlist-step-list">
      {steps.map((o) => (
        <li key={o.step_id} className={`light-show-playlist-step ${o.status}`}>
          <Icon name={TIMING_ICON[o.on as PlaylistTiming] ?? 'bolt'} size={16} />
          <span>{outcomeLine(o)}</span>
          {(o.status === 'armed' || o.status === 'pending') && (
            <button type="button" className="light-show-run-set-icon-btn fire" disabled={busy}
              title="Fire now" aria-label={`Fire ${o.set_name} now`} onClick={() => onFire(o.step_id)}>
              <Icon name="bolt" size={18} />
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
