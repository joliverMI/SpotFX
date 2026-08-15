/** /review — Stage 3 of the owner's feedback sessions: a played show
 * reconstructed from the durable SHOW LOG (Stage 1,
 * spectra/services/fire_history.py) with his feedback notes (Stage 2,
 * spectra/services/feedback.py) pinned against it at their timestamps.
 * Extends the ported timeline surface family (BuilderPage's TimelineBar /
 * SpectraTriggerBar lane pattern, PR 29 + PR 44) rather than inventing a
 * parallel one: events render as a lane (ReviewLaneBar) with notes pinned
 * on it, backed by a phone-friendly vertical twin (ReviewEntryList) and a
 * click-through detail panel (ReviewNoteDetail) for "see this note with
 * the surrounding events" + Prev/Next note jumping.
 *
 * A session is one sent feedback batch (Stage 2's "hit send" unit); a
 * session names the songs it has notes for, and the review is always
 * picked per-song within a session — see
 * spectra/services/show_reconstruction.py for the merge/window rule this
 * mirrors. This is a desk-review surface first (his own framing: notes go
 * in from the phone during the show, reviewed later at a desk) but stays
 * usable at phone width — judged honestly at both, not just built for one
 * and shrunk. */
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import CollapsibleCard from '../components/CollapsibleCard';
import HelpLink from '../help/HelpLink';
import { useReviewSessions, useReviewTimeline } from '../queries';
import { useProfileByUri } from '../timeline/queries';
import type { ReviewSession } from '../types';
import ReviewEntryList from './components/ReviewEntryList';
import ReviewLaneBar from './components/ReviewLaneBar';
import ReviewNoteDetail from './components/ReviewNoteDetail';

function fmtSessionLabel(s: ReviewSession): string {
  const when = new Date(s.received_ms);
  const date = when.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  const time = when.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  return `${date} ${time} — ${s.note_count} note${s.note_count === 1 ? '' : 's'}`;
}

function SongPickerButton({
  uri, active, onClick,
}: { uri: string; active: boolean; onClick: () => void }) {
  const { data: profile } = useProfileByUri(uri);
  const label = profile?.title
    ? `${profile.title}${profile.artist ? ` — ${profile.artist}` : ''}`
    : uri.split(':').pop()?.slice(0, 14) ?? uri;
  return (
    <button className={active ? 'primary' : ''} onClick={onClick} title={uri}>
      {label}
    </button>
  );
}

export default function ReviewPage() {
  const { data: sessions } = useReviewSessions();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [uri, setUri] = useState<string | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);

  // First load / new data: default to the newest session.
  useEffect(() => {
    if (sessionId !== null || !sessions || sessions.length === 0) return;
    setSessionId(sessions[0].session_id);
  }, [sessions, sessionId]);

  const session = sessions?.find((s) => s.session_id === sessionId) ?? null;

  // Default song: the session's first one, and re-pick whenever the
  // session changes to one that doesn't have the currently chosen song.
  useEffect(() => {
    if (!session) return;
    if (uri && session.uris.includes(uri)) return;
    setUri(session.uris[0] ?? null);
  }, [session, uri]);

  const { data: timelineData, isLoading } = useReviewTimeline(sessionId, uri);
  const { data: profile } = useProfileByUri(uri);
  const timeline = useMemo(() => timelineData?.timeline ?? [], [timelineData]);

  const noteIndices = useMemo(
    () => timeline.map((item, i) => (item.type === 'note' ? i : -1)).filter((i) => i >= 0),
    [timeline],
  );

  // Selection resets whenever the reconstructed timeline changes under it.
  useEffect(() => {
    setSelectedIndex(noteIndices.length > 0 ? noteIndices[0] : null);
  }, [timelineData, noteIndices]);

  const maxPositionMs = useMemo(
    () => timeline.reduce((max, item) => Math.max(max, item.position_ms ?? 0), 0),
    [timeline],
  );
  const durationMs = profile?.duration_ms || (maxPositionMs > 0 ? maxPositionMs * 1.05 : 1);

  return (
    <div>
      <div className="card">
        <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          Review <HelpLink topic="review-page" />
        </div>

        {!sessions ? (
          <p className="empty-note">Loading sessions…</p>
        ) : sessions.length === 0 ? (
          <div className="empty-card">
            <span className="empty-card-icon">📝</span>
            <div>
              <div className="empty-card-title">No feedback sessions yet</div>
              <Link to="/feedback" className="empty-card-action">Go mark something →</Link>
            </div>
          </div>
        ) : (
          <>
            <div className="review-picker-label">Session</div>
            <div className="review-session-picker">
              {sessions.map((s) => (
                <button
                  key={s.session_id}
                  className={s.session_id === sessionId ? 'primary' : ''}
                  onClick={() => { setSessionId(s.session_id); setUri(null); }}
                >
                  {fmtSessionLabel(s)}
                </button>
              ))}
            </div>

            {session && session.uris.length > 0 && (
              <div className="review-song-picker">
                {session.uris.map((u) => (
                  <SongPickerButton key={u} uri={u} active={u === uri} onClick={() => setUri(u)} />
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {uri && (
        <>
          <CollapsibleCard
            id="review-lane"
            title="Show + notes"
            headerExtra={
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {timeline.length} item{timeline.length === 1 ? '' : 's'}
              </span>
            }
          >
            {isLoading ? (
              <p className="empty-note">Reconstructing…</p>
            ) : (
              <>
                <ReviewLaneBar
                  durationMs={durationMs}
                  playedThroughMs={maxPositionMs}
                  timeline={timeline}
                  selectedIndex={selectedIndex}
                  onSelect={setSelectedIndex}
                />
                <ReviewEntryList
                  timeline={timeline}
                  selectedIndex={selectedIndex}
                  onSelect={setSelectedIndex}
                />
              </>
            )}
          </CollapsibleCard>

          {selectedIndex != null && timeline[selectedIndex] && (
            <div className="card">
              <ReviewNoteDetail
                timeline={timeline}
                selectedIndex={selectedIndex}
                noteIndices={noteIndices}
                onSelect={setSelectedIndex}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}
