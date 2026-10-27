// The guest screens: Welcome (first visit), Now (the main screen: what is
// playing, its votes, the two big buttons, how close the room is to
// skipping it, the next few songs), Queue (your songs, then everything
// coming up, with ⇅ on the songs you may move) and Add.
import { useCallback, useEffect, useRef, useState } from 'react';
import type { NextSong, RunningView, SearchResult, View } from './types';
import {
  SEARCH_DEBOUNCE_MS, SEARCH_MIN, addStatus, addedText, badges, bumpOffer, bumpsLine, byLine, mmss,
  progressNow, skipLine,
} from './logic';
import { Art, MyRow, OpenSpotify, SongRow, SpotifyIcon } from './bits';
import { api, type Found } from './api';

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
      {skipLine(now.skip, now.votes.down) && (
        <p className="g-skip-line" aria-live="polite">{skipLine(now.skip, now.votes.down)}</p>
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

export function QueueScreen({ view, elapsedMs, nowMs, onMove }: {
  view: RunningView; elapsedMs: number; nowMs: number; onMove: (song: NextSong) => void;
}) {
  // the line about bumps shows wherever a song could move; ⇅ only where
  // THIS phone can move it now (not in a time-out, not out of bumps)
  const movable = (s: NextSong) => !!bumpOffer(s, view.me.bumps, view.me.jail);
  const canMove = (s: NextSong) => !!bumpOffer(s, view.me.bumps, view.me.jail)?.can;
  return (
    <div className="g-queue">
      <section aria-label="Your songs">
        <h2 className="g-h2">Your songs</h2>
        {view.mine.length ? (
          <ul className="g-list">{view.mine.map((s) => <MyRow key={s.entry_id} song={s} elapsedMs={elapsedMs} nowMs={nowMs} />)}</ul>
        ) : (
          <p className="g-muted">None in line yet — tap ＋ to add one.</p>
        )}
      </section>
      <section aria-label="Coming up">
        <h2 className="g-h2">Coming up</h2>
        {view.next.some(movable) && (
          <p className="g-muted g-small g-bumps-line">{bumpsLine(view.me.bumps, view.me.jail)}</p>
        )}
        {view.next.length ? (
          <ul className="g-list">{view.next.map((s) => (
            <SongRow key={`${s.place}-${s.uri}`} song={s} elapsedMs={elapsedMs} nowMs={nowMs}
                     onMove={canMove(s) ? () => onMove(s) : undefined} />
          ))}</ul>
        ) : (
          <p className="g-muted">Nothing lined up yet.</p>
        )}
        <p className="g-muted g-small">The host's set plays in order (🔒). A song marked “sent to Spotify” plays next whatever happens.</p>
      </section>
    </div>
  );
}

export function AddScreen({ view, onAdded }: {
  view: RunningView; onAdded: (v: View, text: string) => void;
}) {
  const [query, setQuery] = useState('');
  const [found, setFound] = useState<Found | null>(null);
  const [error, setError] = useState('');
  const [searching, setSearching] = useState(false);
  const [adding, setAdding] = useState('');
  const [added, setAdded] = useState<Set<string>>(new Set());
  const seq = useRef(0);
  const status = addStatus(view.requests, view.me.approved, view.me.jail);

  const run = useCallback(async (q: string, offset: number) => {
    const mine = ++seq.current;
    setSearching(true);
    const r = await api.search(q, offset);
    if (mine !== seq.current) return;                 // a newer search is under way
    setSearching(false);
    if (!r.ok || !r.found) { setError(r.ok ? '' : r.refusal.detail); return; }
    setError('');
    const f = r.found;
    setFound((prev) => (offset > 0 && prev ? { ...f, results: [...prev.results, ...f.results] } : f));
  }, []);

  useEffect(() => {
    const q = query.trim();
    if (q.length < SEARCH_MIN) { seq.current += 1; setFound(null); setSearching(false); return undefined; }
    const t = window.setTimeout(() => { void run(q, 0); }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [query, run]);

  const add = async (uri: string) => {
    setAdding(uri);
    const r = await api.add(uri);
    setAdding('');
    if (r.ok) {
      setAdded((s) => new Set(s).add(uri));
      onAdded(r.view, addedText(r.added?.starts_in_ms ?? null, Date.now()));
    } else {
      setError(r.refusal.detail);
    }
  };

  const results = found?.results ?? [];
  const ready = results.filter((r) => r.library);
  const rest = results.filter((r) => !r.library);
  const row = (r: SearchResult) => {
    const inLine = r.in_line || added.has(r.uri);
    const why = r.why_not;
    return (
      <li key={r.uri} className="g-row g-result">
        <Art song={{ ...r, kind: 'jukebox', by: { kind: 'other', name: '' }, mine: false }} size="small" />
        <div className="g-row-text">
          <div className="g-row-title">{r.title}</div>
          <div className="g-row-artist">{r.artist}</div>
          <div className="g-badges">
            {badges({ ...r, in_line: inLine }).map((b) => (
              <span key={b.kind} className={`g-badge g-badge-${b.kind}`}>{b.label}</span>
            ))}
          </div>
          {why && !inLine && <div className="g-row-why">{why}</div>}
        </div>
        <div className="g-result-actions">
          <button type="button" className="g-btn g-btn-primary g-add-btn"
                  disabled={!status.canAdd || !r.can_add || inLine || adding !== ''}
                  aria-label={`Add ${r.title}`} onClick={() => void add(r.uri)}>
            {adding === r.uri ? '…' : inLine ? '✓' : 'Add'}
          </button>
          <OpenSpotify song={{ ...r, kind: 'jukebox', by: { kind: 'other', name: '' }, mine: false }} label={false} />
        </div>
      </li>
    );
  };
  return (
    <div className="g-add">
      <label className="g-field-label" htmlFor="g-search">Find a song</label>
      <input id="g-search" className="g-input" type="search" inputMode="search" autoComplete="off"
             placeholder="A song or an artist" value={query} maxLength={60}
             onChange={(e) => setQuery(e.target.value)} />
      <p className={`g-add-status${status.canAdd ? '' : ' g-add-status-off'}`}>{status.text}</p>
      {error && <p className="g-error" role="alert">{error}</p>}
      {searching && <p className="g-muted g-small">Searching…</p>}
      {ready.length > 0 && (
        <section aria-label="Ready">
          <h2 className="g-h2">Ready: the lights already know these</h2>
          <ul className="g-list">{ready.map(row)}</ul>
        </section>
      )}
      {rest.length > 0 && (
        <section aria-label="From Spotify">
          <h2 className="g-h2 g-h2-spotify"><SpotifyIcon size={16} /> From Spotify</h2>
          <ul className="g-list">{rest.map(row)}</ul>
        </section>
      )}
      {found && results.length === 0 && <p className="g-muted">Nothing found for “{found.query}”.</p>}
      {found?.more && (
        <button type="button" className="g-btn g-btn-ghost g-more" disabled={searching}
                onClick={() => void run(found.query, found.next_offset)}>More from Spotify</button>
      )}
    </div>
  );
}
