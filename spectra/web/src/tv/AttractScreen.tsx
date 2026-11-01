/** THE ATTRACT SCREEN (data/tv-display-plan/plan.html PR 1.5, §2.1/§2.2):
 * "a slow deck — join, top songs, now playing — over a very dim haze",
 * shown between nights or while a night runs but nothing has changed in
 * a while. Burn-in safety (burnIn.ts): the deck itself cycles every 15s,
 * the QR swaps corners every 10 minutes, and the whole card drifts up to
 * +-16px over 8 minutes — nothing here holds one position for the
 * 10-minute acceptance window. */
import { CSSProperties, useEffect, useRef, useState } from 'react';
import { attractCard, driftOffsetPx, qrCorner } from './burnIn';
import JoinQr from './JoinQr';
import { useFeed } from './useFeed';
import { byWords } from './partyLogic';

const CORNER_STYLE: Record<string, CSSProperties> = {
  tl: { top: '5%', left: '5%' },
  tr: { top: '5%', right: '5%' },
  br: { bottom: '5%', right: '5%' },
  bl: { bottom: '5%', left: '5%' },
};

export default function AttractScreen() {
  const feed = useFeed();
  const mountedAt = useRef(Date.now());
  const [, force] = useState(0);
  useEffect(() => {
    const id = setInterval(() => force((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);
  const elapsed = Date.now() - mountedAt.current;
  const card = attractCard(elapsed);
  const { dx, dy } = driftOffsetPx(elapsed);
  const corner = qrCorner(elapsed);
  const link = feed.jukebox?.link ?? null;
  const topSongs = feed.jukebox?.board?.songs?.slice(0, 4) ?? [];
  const now = feed.jukebox?.now ?? null;

  return (
    <div className="tv-attract">
      {link && (
        <div className="tv-attract-qr-corner" style={CORNER_STYLE[corner]}>
          <JoinQr link={link} />
        </div>
      )}
      <div className="tv-attract-card" style={{ transform: `translate(${dx}px, ${dy}px)` }}>
        {card === 'join' && (
          <>
            <div className="tv-info-title">Pick the music</div>
            <div className="tv-info-sub">
              {link ? 'Scan, add a song, vote ▲▼' : 'Ask the host for the link to join.'}
            </div>
          </>
        )}
        {card === 'top' && (
          <>
            <div className="tv-attract-label">Tonight's top songs</div>
            {topSongs.length === 0 && <div className="tv-info-sub">No ▲ yet tonight.</div>}
            {topSongs.map((s) => (
              <div className="tv-attract-song-line" key={s.uri}>
                {s.title} — {byWords(s.by)} · ▲ {s.ups}
              </div>
            ))}
          </>
        )}
        {card === 'now' && now && (
          <>
            <div className="tv-info-title">{now.title}</div>
            <div className="tv-info-sub">{now.artist}</div>
          </>
        )}
        {card === 'now' && !now && (
          <div className="tv-info-sub">Nothing playing right now.</div>
        )}
      </div>
    </div>
  );
}
