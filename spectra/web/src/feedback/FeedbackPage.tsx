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
 * appends the entry immediately from the last-polled engine status (optimistic),
 * then a background GET /api/feedback/mark patches in the authoritative
 * wall_ms/uri/position_ms — unless the entry has already been nudged or
 * noted (`touched`), so a fast follow-up edit is never clobbered by a
 * slow capture response. A failed capture leaves the optimistic entry in
 * place rather than losing the mark.
 *
 * Server side: spectra/services/feedback.py + spectra/api/feedback.py. */
import { useState } from 'react';
import { useToast } from '../components/Toast';
import HelpLink from '../help/HelpLink';
import { useSticky } from '../lib/useSticky';
import { captureFeedbackMark, useEngineStatus, useSendFeedbackBatch } from '../queries';
import { newFeedbackEntry, type FeedbackEntry } from '../types';

const NUDGES_MS = [-5000, -1000, 1000, 5000];

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

export default function FeedbackPage() {
  const toast = useToast();
  const { data: eng } = useEngineStatus();
  const [queue, setQueue] = useSticky<FeedbackEntry[]>('feedback-queue', []);
  const [marking, setMarking] = useState(false);
  const send = useSendFeedbackBatch();

  const track = eng?.bridge?.track ?? null;

  async function handleMark() {
    const optimistic = newFeedbackEntry({
      wall_ms: Date.now(),
      uri: track?.uri ?? null,
      position_ms: track?.position_ms ?? null,
    });
    setQueue((q) => [optimistic, ...q]);
    setMarking(true);
    try {
      const captured = await captureFeedbackMark();
      setQueue((q) => q.map((e) => (e.id === optimistic.id && !e.touched
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
      ? { ...e, touched: true, position_ms: Math.max(0, e.position_ms + deltaMs) }
      : e)));
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
      id: e.id, wall_ms: e.wall_ms, uri: e.uri, position_ms: e.position_ms, note: e.note,
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
            ? <>Now: <strong>{track.title}</strong>{track.position_ms != null && ` @ ${fmtPos(track.position_ms)}`}</>
            : <span className="empty-note">
                No track playing{eng && !eng.bridge.connected && ' (bridge down)'}
              </span>}
        </div>
        <button className="primary feedback-mark-btn" onClick={handleMark} disabled={marking}>
          ● Mark
        </button>
      </div>

      <div className="card">
        <div className="card-title">Queue ({queue.length})</div>
        {queue.length === 0 ? (
          <p className="empty-note">Nothing marked yet — press Mark above when something happens.</p>
        ) : (
          <div className="feedback-queue">
            {queue.map((e, i) => (
              <div className="feedback-entry" key={e.id}>
                <div className="feedback-entry-head">
                  <span className="feedback-entry-pos">{fmtPos(e.position_ms)}</span>
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
