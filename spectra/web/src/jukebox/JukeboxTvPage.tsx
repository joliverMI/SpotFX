/** THE BOARD ON THE TV (/jukebox/tv; the plan's §4 Board card "On the TV",
 * D1 (a)): the song playing with its live ▲▼, and the board — tonight's top
 * songs and only the people boards guests see too — full screen, with none
 * of SPECTRA's bars, for his TV or the wall kiosk on the house network. It
 * reads SpotFX's own /api/jukebox/board (LAN :8000), never the guest port,
 * and shows nothing until "On the TV" is on. */
import { useEffect } from 'react';
import BoardLists from './BoardLists';
import { byWords, tvOffLine, tvPeople } from './jukeboxBoard';
import { useJukeboxBoard } from './queries';

export default function JukeboxTvPage() {
  const q = useJukeboxBoard(true);
  useEffect(() => {
    document.body.classList.add('jukebox-tv-body');
    return () => document.body.classList.remove('jukebox-tv-body');
  }, []);
  const data = q.data;
  const off = tvOffLine(data?.settings);
  return (
    <main className="jukebox-tv" data-testid="jukebox-tv">
      {q.isError && <p className="jukebox-tv-note">The board couldn't be read from SpotFX.</p>}
      {!data && !q.isError && <p className="jukebox-tv-note">Reading the board…</p>}
      {data && off && <p className="jukebox-tv-note" data-testid="jukebox-tv-off">{off}</p>}
      {data && !off && !data.running && (
        <p className="jukebox-tv-note">The Jukebox isn't playing right now.</p>
      )}
      {data && !off && data.running && (
        <>
          {data.now && (
            <section className="jukebox-tv-now" data-testid="jukebox-tv-now">
              {data.now.image || data.now.thumb
                ? <img className="jukebox-tv-art" src={data.now.image || data.now.thumb} alt="" />
                : <span className="jukebox-tv-art jukebox-board-art-empty" aria-hidden="true">♪</span>}
              <div className="jukebox-tv-now-words">
                <div className="jukebox-tv-label">Playing now</div>
                <div className="jukebox-tv-title">{data.now.title}</div>
                <div className="jukebox-tv-artist">{data.now.artist}</div>
                <div className="jukebox-tv-by">{byWords(data.now.by)}</div>
                <div className="jukebox-tv-votes">
                  <span className="jukebox-tv-up">▲ {data.now.up}</span>
                  <span className="jukebox-tv-down">▼ {data.now.down}</span>
                </div>
                {data.now.open_url && (
                  <a className="jukebox-board-spotify" href={data.now.open_url} target="_blank"
                     rel="noopener noreferrer">Music from Spotify · Open Spotify</a>
                )}
              </div>
            </section>
          )}
          {data.board && <BoardLists board={data.board} people={tvPeople(data.board.people)} tv />}
        </>
      )}
    </main>
  );
}
