// The guest screens: Welcome (first visit), Now (the main screen: what is
// playing, its votes, the two big buttons, the next few songs), and Queue
// (your songs, then everything coming up).
import { useState } from 'react';
import type { RunningView } from './types';
import { byLine, mmss, progressNow } from './logic';
import { Art, OpenSpotify, SongRow, SpotifyIcon } from './bits';

export function Welcome({ view, busy, onShuffle, onGo, error }: {
  view: RunningView; busy: boolean; error: string;
  onShuffle: () => void; onGo: (name: string) => void;
}) {
  const [name, setName] = useState(view.me.name);
  const [edited, setEdited] = useState(false);
  const shown = edited ? name : view.me.name;
  return (
    <div className="g-welcome">
      <h1 className="g-welcome-title">Welcome to the Jukebox</h1>
      <p className="g-welcome-lead">Vote on every song tonight. No sign-in, nothing to install.</p>
      <label className="g-field-label" htmlFor="g-name">Your name tonight</label>
      <div className="g-name-row">
        <input id="g-name" className="g-input" value={shown} maxLength={20} autoComplete="off"
               onChange={(e) => { setName(e.target.value); setEdited(true); }} />
        <button type="button" className="g-btn g-btn-ghost" disabled={busy}
                onClick={() => { setEdited(false); onShuffle(); }} aria-label="Pick another fun name">
          🎲 Shuffle
        </button>
      </div>
      {error && <p className="g-error" role="alert">{error}</p>}
      <ul className="g-how">
        {view.how.map((t) => (
          <li key={t.title} className="g-how-tile">
            <span className="g-how-icon" aria-hidden="true">{t.icon === 'vote' ? '▲▼' : t.icon === 'queue' ? '☰' : '♪'}</span>
            <strong>{t.title}</strong>
            <span>{t.text}</span>
          </li>
        ))}
      </ul>
      <h2 className="g-h2">House rules</h2>
      <ul className="g-rules">{view.house_rules.map((r) => <li key={r}>{r}</li>)}</ul>
      <p className="g-privacy">{view.privacy}</p>
      <div className="g-welcome-go">
        <button type="button" className="g-btn g-btn-primary g-btn-go" disabled={busy}
                onClick={() => onGo(shown.trim())}>
          Let's go
        </button>
      </div>
    </div>
  );
}

export function NowScreen({ view, elapsedMs, nowMs, busy, onVote, homeHint, onHomeHint }: {
  view: RunningView; elapsedMs: number; nowMs: number; busy: boolean;
  onVote: (v: 'up' | 'down' | 'none') => void; homeHint: boolean; onHomeHint: () => void;
}) {
  const now = view.now;
  if (!now) {
    return <div className="g-empty"><p>The music is starting…</p></div>;
  }
  const at = progressNow(now.progress_ms, now.duration_ms, now.is_playing, elapsedMs);
  const pct = now.duration_ms ? (at / now.duration_ms) * 100 : 0;
  const vote = (v: 'up' | 'down') => onVote(now.my_vote === (v === 'up' ? 1 : -1) ? 'none' : v);
  return (
    <div className="g-now">
      <section className={`g-now-card${now.mine ? ' g-now-mine' : ''}`} aria-label="Playing now">
        <div className="g-now-top">
          <Art song={now} size="big" className="g-now-art" />
          <div className="g-now-text">
            <div className="g-now-label">{now.mine ? '🎉 Your song is playing' : 'Playing now'}</div>
            <h1 className="g-now-title">{now.title || 'A song'}</h1>
            <div className="g-now-artist">{now.artist}</div>
            <div className="g-now-by">{byLine(now.by, now.mine)}</div>
          </div>
        </div>
        <div className="g-progress" aria-label={`${mmss(at)} of ${mmss(now.duration_ms)}`}>
          <div className="g-progress-bar"><div style={{ width: `${pct}%` }} /></div>
          <div className="g-progress-times"><span>{mmss(at)}</span><span>{mmss(now.duration_ms)}</span></div>
        </div>
        <div className="g-attribution">
          <span className="g-attribution-from"><SpotifyIcon size={18} /> Music from Spotify</span>
          <OpenSpotify song={now} />
        </div>
      </section>
      <div className="g-tally" aria-live="polite">
        <span className="g-tally-up">▲ {now.votes.up}</span>
        <span className="g-tally-down">▼ {now.votes.down}</span>
      </div>
      {now.can_vote ? (
        <div className="g-votes">
          <button type="button" className={`g-vote g-vote-up${now.my_vote === 1 ? ' g-vote-on' : ''}`}
                  aria-pressed={now.my_vote === 1} disabled={busy} onClick={() => vote('up')}>
            <span className="g-vote-arrow" aria-hidden="true">{now.my_vote === 1 ? '✓' : '▲'}</span>
            <span>{now.my_vote === 1 ? 'Voted up' : 'Up'}</span>
          </button>
          <button type="button" className={`g-vote g-vote-down${now.my_vote === -1 ? ' g-vote-on' : ''}`}
                  aria-pressed={now.my_vote === -1} disabled={busy} onClick={() => vote('down')}>
            <span className="g-vote-arrow" aria-hidden="true">{now.my_vote === -1 ? '✓' : '▼'}</span>
            <span>{now.my_vote === -1 ? 'Voted down' : 'Down'}</span>
          </button>
        </div>
      ) : (
        <p className="g-why-not">{now.why_not}</p>
      )}
      {homeHint && (
        <button type="button" className="g-btn g-btn-ghost g-home-hint" onClick={onHomeHint}>
          ＋ Add to Home Screen
        </button>
      )}
      {view.next.length > 0 && (
        <section aria-label="Up next">
          <h2 className="g-h2">Up next</h2>
          <ul className="g-list">
            {view.next.slice(0, 3).map((s) => <SongRow key={`${s.place}-${s.uri}`} song={s} elapsedMs={elapsedMs} nowMs={nowMs} />)}
          </ul>
        </section>
      )}
    </div>
  );
}

export function QueueScreen({ view, elapsedMs, nowMs }: { view: RunningView; elapsedMs: number; nowMs: number }) {
  const mine = view.next.filter((s) => s.mine);
  return (
    <div className="g-queue">
      <section aria-label="Your songs">
        <h2 className="g-h2">Your songs</h2>
        {mine.length ? (
          <ul className="g-list">{mine.map((s) => <SongRow key={`m-${s.place}`} song={s} elapsedMs={elapsedMs} nowMs={nowMs} />)}</ul>
        ) : (
          <p className="g-muted">{view.mine.length ? 'Your song is further down the line.' : 'None in line tonight yet.'}</p>
        )}
      </section>
      <section aria-label="Coming up">
        <h2 className="g-h2">Coming up</h2>
        {view.next.length ? (
          <ul className="g-list">{view.next.map((s) => <SongRow key={`${s.place}-${s.uri}`} song={s} elapsedMs={elapsedMs} nowMs={nowMs} />)}</ul>
        ) : (
          <p className="g-muted">Nothing lined up yet.</p>
        )}
        <p className="g-muted g-small">The host's set plays in order (🔒). A song marked “sent to Spotify” plays next whatever happens.</p>
      </section>
    </div>
  );
}
