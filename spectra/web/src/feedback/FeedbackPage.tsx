/** /feedback — Stage 2 of the owner's feedback sessions: timestamped
 * feedback captured DURING a played show, phone-first (his room usage is
 * phone). Binding requirements (spectra-design-decisions.md
 * "Feedback-session design requirements", his words):
 *
 *   MARK-THEN-NUDGE  a prominent Mark button captures wall time + song uri
 *                    + position from the live bridge state; +/-1s and
 *                    +/-5s nudges correct the captured POSITION before a
 *                    note is typed — he's always reacting to something he
 *                    already saw. Marking again never waits on a
 *                    half-typed note (each entry owns its own note field).
 *   BATCH QUEUE      marks/notes accumulate in this browser's localStorage
 *                    (useSticky — survives a reload), visible/correctable/
 *                    deletable/reorderable, and leave in ONE batch on
 *                    Send — never a mid-show round-trip. A failed Send
 *                    keeps the queue intact for a plain retry.
 *
 * Mark itself stays responsive under a slow/dropped network: pressing it
 * appends the entry immediately from the last-polled engine status
 * (optimistic, using useLivePosition's interpolated estimate rather than
 * the raw poll — see that hook's header), then a background
 * GET /api/feedback/mark patches in the authoritative wall_ms/uri/
 * position_ms. That correction always lands on the entry's ANCHOR
 * (position_ms) regardless of whether he's already nudged or typed a note
 * — his note text and his nudge offset live in separate fields
 * (note, nudge_offset_ms) that this patch never touches, so a fast
 * mark-then-nudge is never left holding a stale position (a nudge is a
 * relative correction on top of whatever the anchor turns out to be, not
 * a replacement for it). A failed capture leaves the optimistic entry in
 * place rather than losing the mark.
 *
 * Server side: spectra/services/feedback.py + spectra/api/feedback.py. */
import { useEffect, useRef, useState } from 'react';
import { useToast } from '../components/Toast';
import HelpLink from '../help/HelpLink';
import { fmtMsTenths } from '../lib/time';
import { useLivePosition } from '../lib/useLivePosition';
import { useSticky } from '../lib/useSticky';
import { captureFeedbackMark, useEngineStatus, useSendFeedbackBatch } from '../queries';
import { newFeedbackEntry, type FeedbackEntry } from '../types';

const NUDGES_MS = [-5000, -1000, 1000, 5000];
const FLASH_MS = 500;

function fmtPos(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function fmtAgo(wallMs: number): string {
  const s = Math.max(0, Math.round((Date.now() - wallMs) / 1000));
  if (s < 60) return `${s}s ago`;
  return `${Math.round(s / 60)}m ago`;
}

function shortUri(uri: string | null): string {
  if (!uri) return 'no track';
  const parts = uri.split(':');
  return parts[parts.length - 1].slice(0, 10);
}

/** Stable per-song colour for the queue's colour bar — a plain string hash
 * into a hue, no lookups, so a long multi-song queue reads by song at a
 * glance instead of by truncated Spotify URI. */
function uriHue(uri: string | null): number {
  if (!uri) return 0;
  let h = 0;
  for (let i = 0; i < uri.length; i += 1) h = (h * 31 + uri.charCodeAt(i)) >>> 0;
  return h % 360;
}

/** An entry's position for display/send — the captured anchor plus
 * whatever nudge offset he's applied on top of it. */
function entryPosition(e: FeedbackEntry): number {
  return Math.max(0, e.position_ms + e.nudge_offset_ms);
}

export default function FeedbackPage() {
  const toast = useToast();
  const { data: eng } = useEngineStatus();
  const [queue, setQueue] = useSticky<FeedbackEntry[]>('feedback-queue', []);
  const [marking, setMarking] = useState(false);
  const [justMarked, setJustMarked] = useState(false);
  const [flashedId, setFlashedId] = useState<string | null>(null);
  const send = useSendFeedbackBatch();
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const markFlashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const track = eng?.bridge?.track ?? null;
  const livePos = useLivePosition(track);

  useEffect(() => () => {
    if (flashTimer.current) clearTimeout(flashTimer.current);
    if (markFlashTimer.current) clearTimeout(markFlashTimer.current);
  }, []);

  function flashEntry(id: string) {
    setFlashedId(id);
    if (flashTimer.current) clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(() => setFlashedId(null), FLASH_MS);
  }

  async function handleMark() {
    const optimistic = newFeedbackEntry({
      wall_ms: Date.now(),
      uri: track?.uri ?? null,
      position_ms: livePos ?? track?.position_ms ?? null,
    });
    setQueue((q) => [optimistic, ...q]);
    setMarking(true);
    setJustMarked(true);
    if (markFlashTimer.current) clearTimeout(markFlashTimer.current);
    markFlashTimer.current = setTimeout(() => setJustMarked(false), FLASH_MS);
    try {
      const captured = await captureFeedbackMark();
      setQueue((q) => q.map((e) => (e.id === optimistic.id
        ? {
            ...e,
            wall_ms: captured.wall_ms,
            uri: captured.uri,
            position_ms: Math.max(0, captured.position_ms ?? e.position_ms),
          }
        : e)));
    } catch {
      toast('Mark captured offline — position may be approximate', 'info');
    } finally {
      setMarking(false);
    }
  }

  function nudge(id: string, deltaMs: number) {
    setQueue((q) => q.map((e) => (e.id === id
      ? { ...e, touched: true, nudge_offset_ms: Math.max(-e.position_ms, e.nudge_offset_ms + deltaMs) }
      : e)));
    flashEntry(id);
  }

  function setNote(id: string, note: string) {
    setQueue((q) => q.map((e) => (e.id === id ? { ...e, touched: true, note } : e)));
  }

  function remove(id: string) {
    setQueue((q) => q.filter((e) => e.id !== id));
  }

  function move(id: string, dir: -1 | 1) {
    setQueue((q) => {
      const idx = q.findIndex((e) => e.id === id);
      const swap = idx + dir;
      if (idx < 0 || swap < 0 || swap >= q.length) return q;
      const copy = [...q];
      [copy[idx], copy[swap]] = [copy[swap], copy[idx]];
      return copy;
    });
  }

  async function handleSend() {
    if (queue.length === 0) return;
    const payload = queue.map((e) => ({
      id: e.id, wall_ms: e.wall_ms, uri: e.uri, position_ms: entryPosition(e), note: e.note,
    }));
    try {
      const result = await send.mutateAsync(payload);
      setQueue([]);
      toast(`Sent ${result.count} note${result.count === 1 ? '' : 's'}`, 'success');
    } catch {
      toast('Send failed — queue kept, tap Send to retry', 'error');
    }
  }

  return (
    <div>
      <div className="card">
        <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          Feedback session <HelpLink topic="feedback-page" />
        </div>
        <div className="feedback-now">
          {track?.title
            ? <>Now: <strong>{track.title}</strong>{livePos != null && (
                <span className="feedback-now-pos"> @ {fmtMsTenths(livePos)}</span>
              )}</>
            : <span className="empty-note">
                No track playing{eng && !eng.bridge.connected && ' (bridge down)'}
              </span>}
        </div>
        <button
          className={`primary feedback-mark-btn ${justMarked ? 'flash' : ''}`}
          onClick={handleMark}
          disabled={marking}
        >
          {justMarked ? 'Marked!' : '● Mark'}
        </button>
      </div>

      <div className="card">
        <div className="card-title">Queue ({queue.length})</div>
        {queue.length === 0 ? (
          <p className="empty-note">Nothing marked yet — press Mark above when something happens.</p>
        ) : (
          <div className="feedback-queue">
            {queue.map((e, i) => (
              <div
                className="feedback-entry"
                key={e.id}
                style={{ borderLeft: `4px solid hsl(${uriHue(e.uri)} 65% 55%)` }}
              >
                <div className="feedback-entry-head">
                  <span className={`feedback-entry-pos ${flashedId === e.id ? 'flash' : ''}`}>
                    {fmtPos(entryPosition(e))}
                  </span>
                  <span className="feedback-entry-track" title={e.uri ?? undefined}>{shortUri(e.uri)}</span>
                  <span className="feedback-entry-ago">{fmtAgo(e.wall_ms)}</span>
                  <div className="feedback-entry-actions">
                    <button title="Move up" disabled={i === 0} onClick={() => move(e.id, -1)}>▲</button>
                    <button title="Move down" disabled={i === queue.length - 1} onClick={() => move(e.id, 1)}>▼</button>
                    <button className="danger" title="Delete" onClick={() => remove(e.id)}>✕</button>
                  </div>
                </div>
                <div className="feedback-entry-nudges">
                  {NUDGES_MS.map((d) => (
                    <button key={d} onClick={() => nudge(e.id, d)}>
                      {d > 0 ? '+' : ''}{d / 1000}s
                    </button>
                  ))}
                </div>
                <textarea
                  className="feedback-entry-note"
                  placeholder="What happened here?"
                  value={e.note}
                  onChange={(ev) => setNote(e.id, ev.target.value)}
                  rows={2}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      <button
        className="primary feedback-send-btn"
        onClick={handleSend}
        disabled={queue.length === 0 || send.isPending}
      >
        {send.isPending ? 'Sending…' : `Send all (${queue.length})`}
      </button>
    </div>
  );
}
