/** THE ABSORBING TAB (the Jukebox plan's phase 4, PR 4.3: "the Absorbing tab
 * with ETAs"; the Admiral's ask: "manage the absorbing queue — how many are
 * being analysed, when they will be ready"): what the hidden player
 * "Serenity Capture" is learning right now and how far through it is, the
 * songs waiting to be learned with when each will be ready, and the ones it
 * couldn't learn. Every decision and every estimate is SpotFX's
 * (services/jukebox/learning.py, GET /api/jukebox/learning); the words are
 * jukeboxLearning.ts. The host's buttons: let a waiting song play
 * un-analysed now, give one it couldn't learn fresh tries, or remove it. */
import InfoTip from '../components/InfoTip';
import { useToast } from '../components/Toast';
import {
  etaWords, failWords, headline, numbersWords, progress, rowActions, stateWords, tryWords,
} from './jukeboxLearning';
import { useJukeboxLearning, useLearningAction, useRemoveEntry } from './queries';
import type { JukeboxStatus, LearningRow } from './types';

const ACTION_WORDS = { unanalysed: 'Play un-analysed now', relearn: 'Learn again' } as const;

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function by(row: LearningRow): string {
  return row.added_by === 'host' ? 'added by the host' : 'added by a guest';
}

export default function AbsorbingTab({ status }: { status: JukeboxStatus | undefined }) {
  const toast = useToast();
  const running = !!status?.running;
  const learnQ = useJukeboxLearning(running);
  const act = useLearningAction();
  const remove = useRemoveEntry();
  const st = learnQ.data;
  const onError = (e: unknown) => toast(errText(e), 'error');
  const now = st?.queue.find((q) => q.state === 'learning');
  const waiting = st?.queue.filter((q) => q.state === 'waiting') ?? [];
  const frac = progress(st);

  const buttons = (row: LearningRow) => (
    <span className="jukebox-guest-actions">
      {rowActions(row).map((a) => (
        <button key={a} onClick={() => act.mutate({ entry_id: row.entry_id, action: a }, {
          onSuccess: (r) => {
            if (r.status === 'refused') toast("That song isn't waiting any more.", 'error');
          },
          onError,
        })}>{ACTION_WORDS[a]}</button>
      ))}
      {row.state === 'parked' && (
        <button onClick={() => remove.mutate(row.entry_id, { onError })}>Remove</button>
      )}
    </span>
  );

  return (
    <div className="jukebox-grid">
      <section className="card jukebox-card" data-testid="jukebox-absorbing-card">
        <div className="jukebox-card-head">
          <InfoTip topic="jukebox-absorbing"
            text="A song the lights haven't learned is learned first on the hidden player — inaudibly, on the second Spotify account — and plays once it is. It keeps its place in line meanwhile.">
            <span className="card-title jukebox-card-title">Learning new songs</span>
          </InfoTip>
        </div>
        <p className="jukebox-muted" data-testid="jukebox-absorbing-headline">{headline(st, running)}</p>

        {now && (
          <div className="jukebox-absorbing-now" data-testid="jukebox-absorbing-now">
            <div className="jukebox-item-words">
              <span className="jukebox-song-title">{now.title || now.uri}</span>
              <span className="jukebox-song-artist">
                {[now.artist, by(now), stateWords(now.state), tryWords(now), etaWords(now.eta_s)]
                  .filter(Boolean).join(' · ')}
              </span>
            </div>
            {frac !== null && (
              <div className="jukebox-absorbing-bar" role="progressbar" aria-label="How far through the song"
                aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(frac * 100)}>
                <span style={{ width: `${Math.round(frac * 100)}%` }} />
              </div>
            )}
            {buttons(now)}
          </div>
        )}

        {waiting.length > 0 && (
          <>
            <h3 className="jukebox-sub">Waiting to be learned</h3>
            <ol className="jukebox-next" data-testid="jukebox-absorbing-waiting">
              {waiting.map((row) => (
                <li key={row.entry_id} className="jukebox-item jukebox">
                  <span className="jukebox-item-words">
                    <span className="jukebox-song-title">{row.title || row.uri}</span>
                    <span className="jukebox-song-artist">
                      {[row.artist, by(row), tryWords(row), etaWords(row.eta_s), row.held ? 'on hold' : '']
                        .filter(Boolean).join(' · ')}
                    </span>
                  </span>
                  {buttons(row)}
                </li>
              ))}
            </ol>
          </>
        )}

        {st && st.parked.length > 0 && (
          <>
            <h3 className="jukebox-sub">Couldn't be learned</h3>
            <p className="jukebox-muted">
              These wait for you. A guest who paid for one has already had the price back.
            </p>
            <ol className="jukebox-next" data-testid="jukebox-absorbing-parked">
              {st.parked.map((row) => (
                <li key={row.entry_id} className="jukebox-item jukebox">
                  <span className="jukebox-item-words">
                    <span className="jukebox-song-title">{row.title || row.uri}</span>
                    <span className="jukebox-song-artist">
                      {[row.artist, by(row), failWords(row, st.sentences)].filter(Boolean).join(' · ')}
                    </span>
                  </span>
                  {buttons(row)}
                </li>
              ))}
            </ol>
          </>
        )}

        {st && running && <p className="jukebox-muted" data-testid="jukebox-absorbing-numbers">{numbersWords(st)}</p>}
      </section>
    </div>
  );
}
