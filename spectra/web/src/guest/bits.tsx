// Small pieces every guest screen uses: the album art (Spotify's own image,
// shown as it is — never cropped, blurred or drawn over), the Spotify mark
// with its link back, a song row, and the bottom sheet.
import { useEffect, type ReactNode } from 'react';
import type { MySong, NextSong, Song } from './types';
import { byLine, clockAt, inWords, myStatus } from './logic';

export function Art({ song, size, className = '' }: { song: Song; size: 'big' | 'small'; className?: string }) {
  const src = size === 'big' ? (song.image || song.thumb) : (song.thumb || song.image);
  if (!src) {
    return <div className={`g-art g-art-${size} g-art-empty ${className}`} aria-hidden="true">♪</div>;
  }
  return <img className={`g-art g-art-${size} ${className}`} src={src} alt=""
              loading={size === 'big' ? 'eager' : 'lazy'} decoding="async" />;
}

/** Spotify's mark (the official icon) — the attribution rule: shown beside
 *  the music it supplies. */
export function SpotifyIcon({ size = 20 }: { size?: number }) {
  return (
    <svg className="g-spotify-icon" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#1ED760" d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z" />
    </svg>
  );
}

export function OpenSpotify({ song, label = true }: { song: Song; label?: boolean }) {
  if (!song.open_url) return null;
  return (
    <a className={`g-open-spotify${label ? '' : ' g-open-spotify-icon'}`} href={song.open_url}
       target="_blank" rel="noopener noreferrer"
       aria-label={`Open ${song.title} in Spotify`}>
      <SpotifyIcon />
      {label && <span>Open Spotify</span>}
    </a>
  );
}

export function SongRow({ song, elapsedMs, nowMs, onMove }: {
  song: NextSong; elapsedMs: number; nowMs: number; onMove?: () => void;
}) {
  const left = song.starts_in_ms === null ? null : Math.max(0, song.starts_in_ms - elapsedMs);
  const when = left === null ? '' : `${inWords(left)} · ~${clockAt(nowMs, left)}`;
  return (
    <li className={`g-row${song.kind === 'set' ? ' g-row-set' : ''}${song.mine ? ' g-row-mine' : ''}`}>
      <Art song={song} size="small" />
      <div className="g-row-text">
        <div className="g-row-title">{song.title || 'A song'}</div>
        <div className="g-row-artist">{song.artist}</div>
        <div className="g-row-meta">
          <span>{byLine(song.by, song.mine)}</span>
          {when && <span> · {when}</span>}
          {song.committed && <span className="g-chip">sent to Spotify</span>}
          {song.kind === 'set' && <span className="g-chip g-chip-dim" title="The host's set plays in order">🔒 set</span>}
        </div>
      </div>
      {onMove && (
        <button type="button" className="g-move-btn" onClick={onMove}
                aria-label={`Move ${song.title || 'this song'} ${song.bump === 'up' ? 'up' : 'down'}`}>
          ⇅
        </button>
      )}
      <OpenSpotify song={song} label={false} />
    </li>
  );
}

/** One of your own songs on the Queue, with where it stands. */
export function MyRow({ song, elapsedMs, nowMs }: { song: MySong; elapsedMs: number; nowMs: number }) {
  const waiting = song.jailed || song.held;
  return (
    <li className={`g-row g-row-mine${waiting ? ' g-row-waiting' : ''}`}>
      <Art song={song} size="small" />
      <div className="g-row-text">
        <div className="g-row-title">{song.title || 'A song'}</div>
        <div className="g-row-artist">{song.artist}</div>
        <div className={`g-row-meta${song.jailed ? ' g-row-jailed' : ''}`}>
          <span>{myStatus(song, elapsedMs, nowMs)}</span>
          {song.committed && <span className="g-chip">sent to Spotify</span>}
        </div>
      </div>
      <OpenSpotify song={song} label={false} />
    </li>
  );
}

export function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="g-sheet-backdrop" onClick={onClose}>
      <div className="g-sheet" role="dialog" aria-modal="true" aria-label={title}
           onClick={(e) => e.stopPropagation()}>
        <div className="g-sheet-head">
          <h2>{title}</h2>
          <button type="button" className="g-icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}
