/** THE PARTY SCREEN (data/tv-display-plan/plan.html PR 1.4, §2.1/§2.2) —
 * the song playing (cover art exactly as Spotify gives it, title, artist,
 * added by, live votes, progress on the show clock, "Music from
 * Spotify"), "Up next" with the next 3 and who added them, and the join
 * QR (only while the guest link is live — the plan's own Q5; "Ask the
 * host for the link" otherwise). The up-next callout (UpNextCallout.tsx)
 * overlays the last 30 s of a song once the next one is known.
 *
 * ART IS NEVER ALTERED (Spotify's Design & Branding Guidelines: no
 * cropping, overlays, animation, blurring) — `object-fit: contain` so the
 * whole image always shows, rounded corners only (CSS, not a filter), and
 * nothing is ever drawn on top of it. The coloured haze behind everything
 * (VisualPlane.tsx) is the room's own colour set, never sampled from the
 * art — SEPARATE layers, never composited together.
 *
 * TEXT SIZES already meet the room's reading-distance floors (plan
 * §2.4): body >= 32px, song lines >= 40px, the now-playing title
 * 64-80px, a 5% safe margin — tv.css's own `.tv-party-*` rules. */
import { useFeed } from './useFeed';
import { useTick } from './useTick';
import { interpolatedProgressMs, fmtMMSS, progressFraction, showCallout, byWords } from './partyLogic';
import JoinQr from './JoinQr';
import UpNextCallout from './UpNextCallout';

export default function PartyScreen() {
  useTick(500);
  const feed = useFeed();
  const jukebox = feed.jukebox;
  const now = jukebox?.now ?? null;
  const next = jukebox?.next ?? [];

  if (!now) {
    return (
      <div className="tv-party" role="status">
        <div className="tv-party-sub">Nothing playing right now.</div>
      </div>
    );
  }

  const progressMs = interpolatedProgressMs(now, feed.jukeboxReceivedAtMs, Date.now());
  const callout = showCallout(now, next, progressMs);

  return (
    <div className="tv-party">
      <section className="tv-party-now">
        <div className="tv-party-row">
          <img className="tv-party-art" src={now.image || now.thumb} alt=""
               referrerPolicy="no-referrer" />
          <div className="tv-party-now-words">
            <div className="tv-party-label">Playing now</div>
            <div className="tv-party-title">{now.title}</div>
            <div className="tv-party-artist">{now.artist}</div>
            <div className="tv-party-by">{byWords(now.by)}</div>
            <div className="tv-party-votes">
              <span className="tv-party-up">▲ {now.up}</span>
              <span className="tv-party-down">▼ {now.down}</span>
            </div>
          </div>
        </div>
        <div className="tv-party-bar"><i style={{ width: `${progressFraction(now, progressMs) * 100}%` }} /></div>
        <div className="tv-party-progress-row">
          <span>{fmtMMSS(progressMs)}</span>
          <a className="tv-party-spotify" href={now.open_url} target="_blank" rel="noopener noreferrer">
            Music from Spotify
          </a>
          <span>{fmtMMSS(now.duration_ms)}</span>
        </div>
      </section>
      <section className="tv-party-next" aria-label="Up next and how to join">
        <div className="tv-party-label">Up next</div>
        {next.map((item) => (
          <div className="tv-party-row tv-party-next-row" key={item.uri}>
            <img className="tv-party-mini-art" src={item.image || item.thumb} alt="" referrerPolicy="no-referrer" />
            <div>
              <div className="tv-party-next-title">{item.title}</div>
              <div className="tv-party-next-by">{byWords(item.by)}</div>
            </div>
          </div>
        ))}
        {jukebox?.link ? (
          <div className="tv-party-join">
            <JoinQr link={jukebox.link} />
            <div className="tv-party-join-words">Scan to add songs<br />and vote ▲▼</div>
          </div>
        ) : (
          <div className="tv-party-join-words">Ask the host for the link to join.</div>
        )}
      </section>
      {callout && next.length > 0 && <UpNextCallout item={next[0]} />}
    </div>
  );
}
