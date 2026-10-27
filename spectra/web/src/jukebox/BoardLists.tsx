/** The board's lists — "Tonight's top songs" and the people boards — drawn
 * the same way on the Guests tab's Board card and the TV page
 * (JukeboxTvPage.tsx). The cover art is Spotify's own, shown as it is, with
 * an "Open Spotify" link beside every song (the plan's §2.3 attribution). */
import { boardSongLine, peopleHeading } from './jukeboxBoard';
import type { JukeboxBoardRead, PeopleBoard } from './types';

export default function BoardLists({ board, people, tv = false }: {
  board: NonNullable<JukeboxBoardRead['board']>; people: PeopleBoard[]; tv?: boolean;
}) {
  return (
    <div className={`jukebox-board${tv ? ' jukebox-board-tv' : ''}`}>
      <h3 className="jukebox-board-title">{board.title}</h3>
      {board.songs.length ? (
        <ol className="jukebox-board-songs" data-testid="jukebox-board-songs">
          {board.songs.map((s, i) => (
            <li key={s.uri} className="jukebox-board-song">
              <span className="jukebox-board-place">{i + 1}</span>
              {s.thumb || s.image
                ? <img className="jukebox-board-art" src={s.thumb || s.image} alt="" loading="lazy" />
                : <span className="jukebox-board-art jukebox-board-art-empty" aria-hidden="true">♪</span>}
              <span className="jukebox-item-words">
                <span className="jukebox-song-title">{s.title || 'A song'}</span>
                <span className="jukebox-song-artist">{[s.artist, boardSongLine(s)].filter(Boolean).join(' · ')}</span>
              </span>
              {s.open_url && (
                <a className="jukebox-board-spotify" href={s.open_url} target="_blank" rel="noopener noreferrer"
                   aria-label={`Open ${s.title || 'this song'} in Spotify`}>Open Spotify</a>
              )}
            </li>
          ))}
        </ol>
      ) : <p className="jukebox-muted">{board.empty}</p>}
      {people.map((p) => (
        <section key={p.id} className="jukebox-board-people" data-testid={`jukebox-board-${p.id}`}>
          <h3 className="jukebox-board-title">{tv ? `${p.title} — ${p.unit}` : peopleHeading(p)}</h3>
          {p.rows.length ? (
            <ol className="jukebox-board-names">
              {p.rows.map((r) => <li key={r.name}><span>{r.name}</span><span>{r.value}</span></li>)}
            </ol>
          ) : <p className="jukebox-muted">Nobody yet.</p>}
        </section>
      ))}
    </div>
  );
}
