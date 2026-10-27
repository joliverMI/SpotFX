// The guest screens: Welcome (first visit), Now (the main screen: what is
// playing, its votes, the two big buttons, how close the room is to
// skipping it — in credits mode the tip and skip buttons and the jail card —
// the next few songs), Queue (your songs, then everything coming up, with ⇅
// on the songs you may move), Add, and the Shop (credits: the balance, what
// things cost, how to earn, the history).
import { useCallback, useEffect, useRef, useState } from 'react';
import type { Board, MySong, NextSong, RunningView, SearchResult, View, WalletView } from './types';
import {
  BOARD_POLL_MS, SEARCH_DEBOUNCE_MS, SEARCH_MIN, addOffer, addStatus, addedText, badges, boardSongLine,
  bonusCode, bumpOffer, bumpsLine, byLine, credits, jailCard, mmss, peopleCount, progressNow, signed,
  skipLine, skipOffer, tipOffer,
} from './logic';
import { Art, MyRow, OpenSpotify, SongRow, SpotifyIcon } from './bits';
import { api, boardOf, walletOf, type Found } from './api';

export function Welcome({ view, busy, onShuffle, onGo, error, bonusPending = false }: {
  view: RunningView; busy: boolean; error: string;
  onShuffle: () => void; onGo: (name: string) => void; bonusPending?: boolean;
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
      {view.start_credits !== undefined && (
        <p className="g-welcome-credits">🎟 You start with {credits(view.start_credits)} — free, for tonight only.</p>
      )}
      {bonusPending && (
        <p className="g-welcome-credits" data-testid="g-bonus-pending">🎁 Your bonus card&apos;s credits arrive when you tap Let&apos;s go.</p>
      )}
      <ul className="g-how">
        {view.how.map((t) => (
          <li key={t.title} className="g-how-tile">
            <span className="g-how-icon" aria-hidden="true">{t.icon === 'vote' ? '▲▼' : t.icon === 'queue' ? '☰' : t.icon === 'shop' ? '🎟' : '♪'}</span>
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

export function NowScreen({ view, elapsedMs, nowMs, busy, onVote, homeHint, onHomeHint, onTip,
                           onSkip, onChip, onBreakOut }: {
  view: RunningView; elapsedMs: number; nowMs: number; busy: boolean;
  onVote: (v: 'up' | 'down' | 'none') => void; homeHint: boolean; onHomeHint: () => void;
  onTip?: () => void; onSkip?: () => void; onChip?: () => void; onBreakOut?: () => void;
}) {
  const balance = view.me.credits ?? 0;
  const creditsOn = view.features.credits;
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
            {creditsOn && !!now.earn && <span className="g-vote-earn">+{now.earn} for voting</span>}
          </button>
          <button type="button" className={`g-vote g-vote-down${now.my_vote === -1 ? ' g-vote-on' : ''}`}
                  aria-pressed={now.my_vote === -1} disabled={busy} onClick={() => vote('down')}>
            <span className="g-vote-arrow" aria-hidden="true">{now.my_vote === -1 ? '✓' : '▼'}</span>
            <span>{now.my_vote === -1 ? 'Voted down' : 'Down'}</span>
            {creditsOn && !!now.earn && <span className="g-vote-earn">+{now.earn} for voting</span>}
          </button>
        </div>
      ) : (
        <p className="g-why-not">{now.why_not}</p>
      )}
      {creditsOn && now.mine && now.coming_in && (
        <p className="g-coming-in" aria-live="polite">
          Coming in: ▲ {credits(now.coming_in.ups)}{now.coming_in.tips ? ` · tips ${now.coming_in.tips}` : ''}
        </p>
      )}
      {/* in jail, the way out comes first: right under the votes */}
      {creditsOn && <JailCard view={view} busy={busy} onBreakOut={onBreakOut} />}
      {creditsOn && <CreditActions view={view} balance={balance} busy={busy}
                                   onTip={onTip} onSkip={onSkip} onChip={onChip} />}
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

export function QueueScreen({ view, elapsedMs, nowMs, onMove, onNext }: {
  view: RunningView; elapsedMs: number; nowMs: number; onMove: (song: NextSong) => void;
  onNext?: (song: MySong) => void;
}) {
  // the line about bumps shows wherever a song could move; ⇅ only where
  // THIS phone can move it now (not in a time-out, not out of bumps); in
  // credits mode a move is priced instead
  const balance = view.features.credits ? (view.me.credits ?? 0) : undefined;
  const movable = (s: NextSong) => !!bumpOffer(s, view.me.bumps, view.me.jail, balance);
  const canMove = (s: NextSong) =>
    balance !== undefined ? !!bumpOffer(s, view.me.bumps, view.me.jail, balance) && !view.me.jail?.in
      : !!bumpOffer(s, view.me.bumps, view.me.jail)?.can;
  return (
    <div className="g-queue">
      <section aria-label="Your songs">
        <h2 className="g-h2">Your songs</h2>
        {view.mine.length ? (
          <ul className="g-list">{view.mine.map((s) => (
            <MyRow key={s.entry_id} song={s} elapsedMs={elapsedMs} nowMs={nowMs}
                   credits={balance !== undefined} jail={view.me.jail} balance={balance ?? 0}
                   onMove={balance !== undefined && s.bump ? () => onMove(s as unknown as NextSong) : undefined}
                   onNext={onNext && s.next ? () => onNext(s) : undefined} />
          ))}</ul>
        ) : (
          <p className="g-muted">None in line yet — tap ＋ to add one.</p>
        )}
      </section>
      <section aria-label="Coming up">
        <h2 className="g-h2">Coming up</h2>
        {view.next.some(movable) && (
          <p className="g-muted g-small g-bumps-line">
            {balance !== undefined
              ? (view.me.jail?.in ? 'No moving songs while you\'re in jail.'
                : 'Tap ⇅ to move your song up, or someone else\'s down — each move has its price.')
              : bumpsLine(view.me.bumps, view.me.jail)}
          </p>
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
  const creditsOn = view.features.credits;

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

  const add = async (uri: string, price?: number) => {
    setAdding(uri);
    const r = await api.add(uri, price);
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
    const offer = addOffer(r);
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
            {creditsOn && !r.known && <span className="g-badge g-badge-learn">learn first +1</span>}
          </div>
          {why && !inLine && <div className="g-row-why">{why}</div>}
          {!why && !inLine && creditsOn && !offer.afford && (
            <div className="g-row-why">Needs {credits(r.price ?? 0)} — you have {view.me.credits ?? 0}</div>
          )}
        </div>
        <div className="g-result-actions">
          <button type="button" className="g-btn g-btn-primary g-add-btn"
                  disabled={!status.canAdd || !r.can_add || inLine || adding !== '' || !offer.afford}
                  aria-label={`Add ${r.title}${r.price !== undefined ? ` for ${credits(r.price)}` : ''}`}
                  onClick={() => void add(r.uri, r.price)}>
            {adding === r.uri ? '…' : inLine ? '✓' : offer.label}
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

/** Credits on the Now screen: tip the Adder (held a few seconds so a tap can
 *  be undone), skip (it asks once), chip in. */
function CreditActions({ view, balance, busy, onTip, onSkip, onChip }: {
  view: RunningView; balance: number; busy: boolean;
  onTip?: () => void; onSkip?: () => void; onChip?: () => void;
}) {
  const now = view.now;
  if (!now) return null;
  const tip = tipOffer(now.tip, balance);
  const skip = skipOffer(now.skip, balance);
  if (!tip && !skip) return null;
  return (
    <section className="g-credit-actions" aria-label="Credits">
      {tip && tip.label && (
        <button type="button" className="g-btn g-btn-tip" disabled={busy || !tip.can} onClick={onTip}>
          💛 {tip.label}
        </button>
      )}
      {tip && !tip.can && tip.why && <p className="g-muted g-small">{tip.why}</p>}
      {skip && (
        <>
          <div className="g-skip-row">
            <button type="button" className="g-btn g-btn-skip" disabled={busy || !skip.can} onClick={onSkip}>
              ⏭ {skip.label}
            </button>
            {now.skip?.chip_in && (
              <button type="button" className="g-btn g-btn-ghost" disabled={busy || !now.skip?.can_chip}
                      onClick={onChip}>Chip in</button>
            )}
          </div>
          <p className="g-muted g-small">{skip.why || skip.pot}</p>
        </>
      )}
    </section>
  );
}

function JailCard({ view, busy, onBreakOut }: { view: RunningView; busy: boolean; onBreakOut?: () => void }) {
  const card = jailCard(view.me.jail);
  if (!card) return null;
  return (
    <section className="g-jail-card" aria-label="Jail">
      <h2>{card.title}</h2>
      <p>{card.text}</p>
      <button type="button" className="g-btn g-btn-primary" disabled={busy || !view.me.jail?.can_break_out}
              onClick={onBreakOut}>
        Break out · {card.fee}
      </button>
      {!view.me.jail?.can_break_out && (
        <p className="g-small">You need {credits(card.fee)} — vote to earn +1 each.</p>
      )}
    </section>
  );
}

/** The Shop (credits): the balance and how it was earned, six tiles with
 *  tonight's prices, how to earn, the rule that credits are only for
 *  tonight, and the history. */
/** "Have a bonus card?": type the code printed on it (the join QR uses it
 *  by itself). One per phone a night; the server says why when it can't. */
function BonusField({ bonus, busy, onUse }: {
  bonus: NonNullable<WalletView['bonus']>; busy: boolean; onUse: (code: string) => void;
}) {
  const [text, setText] = useState('');
  if (bonus.used) {
    return <p className="g-muted g-small" data-testid="g-bonus-used">🎁 You&apos;ve used a bonus card tonight.</p>;
  }
  const code = bonusCode(text);
  return (
    <section className="g-bonus" aria-label="Bonus card">
      <h2 className="g-h2">Have a bonus card?</h2>
      <div className="g-name-row">
        <input className="g-input" value={text} maxLength={12} autoComplete="off" autoCapitalize="characters"
               spellCheck={false} placeholder="ABCD-EFGH" aria-label="Bonus card code"
               onChange={(e) => setText(e.target.value)} />
        <button type="button" className="g-btn g-btn-primary" disabled={busy || !code}
                onClick={() => { if (code) { onUse(code); setText(''); } }}>
          Use · +{bonus.amount}
        </button>
      </div>
      <p className="g-muted g-small">One card per phone tonight. The QR on the card does this for you.</p>
    </section>
  );
}

export function ShopScreen({ view, reload, busy = false, onBonus }: {
  view: RunningView; reload: number; busy?: boolean; onBonus?: (code: string) => void;
}) {
  const [wallet, setWallet] = useState<WalletView | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    void api.wallet().then((r) => {
      if (!live) return;
      if (r.ok) { setWallet(walletOf(r.data)); setError(''); }
      else setError(r.refusal.detail);
    });
    return () => { live = false; };
  }, [reload, view.me.credits]);
  const balance = wallet?.balance ?? view.me.credits ?? 0;
  const earned = wallet?.earned;
  return (
    <div className="g-shop">
      <section className="g-balance" aria-label="Your credits">
        <div className="g-balance-big">🎟 {balance}</div>
        <div className="g-muted">{credits(balance)} to spend tonight</div>
        {earned && (
          <ul className="g-earned">
            <li>Free {earned.free}</li><li>Votes {earned.votes}</li>
            <li>Your songs {earned['your songs']}</li><li>Tips {earned.tips}</li>
            <li>Spent {earned.spent}</li>
          </ul>
        )}
      </section>
      {error && <p className="g-error" role="alert">{error}</p>}
      {wallet?.bonus && onBonus && <BonusField bonus={wallet.bonus} busy={busy} onUse={onBonus} />}
      {wallet && (
        <>
          <ul className="g-tiles">
            {wallet.shop.map((t) => (
              <li key={t.id} className="g-tile">
                <strong>{t.title}</strong>
                <span className="g-tile-price">{t.price === null ? '—' : `🎟 ${t.price}`}</span>
                <span className="g-small g-muted">{t.note}</span>
              </li>
            ))}
          </ul>
          <h2 className="g-h2">How to earn</h2>
          <ul className="g-rules">{wallet.how_to_earn.map((h) => <li key={h}>{h}</li>)}</ul>
          <p className="g-disclaimer">{wallet.disclaimer}</p>
          <h2 className="g-h2">Your history</h2>
          {wallet.history.length ? (
            <ul className="g-history">
              {wallet.history.map((h) => (
                <li key={h.seq}>
                  <span className="g-history-what">{h.what}{h.detail ? <span className="g-muted"> · {h.detail}</span> : null}</span>
                  <span className={`g-history-delta${h.delta < 0 ? ' g-neg' : ''}`}>{signed(h.delta)}</span>
                </li>
              ))}
            </ul>
          ) : <p className="g-muted">Nothing yet.</p>}
        </>
      )}
    </div>
  );
}

/** The Board (report §1 rule 11, §2.2): "Tonight's top songs" — songs, not
 *  people, ranked by ▲ with who added each — and the people boards only when
 *  the host has turned them on. Asked again every BOARD_POLL_MS while open. */
export function BoardScreen() {
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    const load = () => void api.board().then((r) => {
      if (!live) return;
      if (r.ok) { setBoard(boardOf(r.data)); setError(''); }
      else setError(r.refusal.detail);
    });
    load();
    const t = window.setInterval(load, BOARD_POLL_MS);
    return () => { live = false; window.clearInterval(t); };
  }, []);
  if (error) return <div className="g-board"><p className="g-error" role="alert">{error}</p></div>;
  if (!board) return <div className="g-board"><p className="g-muted">Loading the board…</p></div>;
  return (
    <div className="g-board">
      <h2 className="g-h2">{board.title}</h2>
      {board.songs.length ? (
        <ol className="g-list g-board-songs">
          {board.songs.map((s, i) => (
            <li key={s.uri} className={`g-row${s.mine ? ' g-row-mine' : ''}`}>
              <span className="g-board-place" aria-hidden="true">{i + 1}</span>
              <Art song={s} size="small" />
              <div className="g-row-text">
                <div className="g-row-title">{s.title || 'A song'}</div>
                <div className="g-row-artist">{s.artist}</div>
                <div className="g-row-meta">{boardSongLine(s)}</div>
              </div>
              <OpenSpotify song={s} label={false} />
            </li>
          ))}
        </ol>
      ) : <p className="g-muted">{board.empty}</p>}
      {board.people.map((p) => (
        <section key={p.id} className="g-board-people" aria-label={p.title}>
          <h2 className="g-h2">{p.title}</h2>
          {p.rows.length ? (
            <ol className="g-board-names">
              {p.rows.map((r) => (
                <li key={r.name}><span>{r.name}</span><span className="g-muted">{peopleCount(r.value, p)}</span></li>
              ))}
            </ol>
          ) : <p className="g-muted">Nobody yet.</p>}
        </section>
      ))}
    </div>
  );
}
