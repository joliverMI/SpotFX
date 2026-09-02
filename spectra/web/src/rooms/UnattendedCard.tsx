/** THE UNATTENDED CAPTURE QUEUE, on the page — because a queue that runs
 * while everyone is asleep is READ, not watched.
 *
 * It is deliberately a REPORT and a Stop button, not a builder. A queue is
 * declared where it is started (a file on the capture machine, an ssh line,
 * a cron entry); what this page owes is the answer afterwards: which items
 * ran, which refused, and WHY IN A SENTENCE — `mapping_refusals`' own
 * wording, never a status word on its own. The three refusals that only
 * exist on this path (a capture machine with no camera, a session that
 * never arrived, a queue somebody stopped) all land here.
 *
 * It polls rather than subscribing: a capture run is minutes long and its
 * item boundaries are seconds apart, so a 2 s poll is the whole of what a
 * reader needs and adds no socket to a page that already holds one for the
 * camera. */
import { useCallback, useEffect, useState } from 'react';
import HelpLink from '../help/HelpLink';
import { apiGet, apiPost } from '../api/client';

type Attempt = {
  attempt: number; status: string; refusal: string; detail: string;
  mapped_count?: number | null; run_summary?: string | null; verdict?: string | null;
};
type Item = {
  index: number; name: string; kind: string; room_id: string; status: string;
  detail: string; refusal: string; attempts: number; pose_id: string;
  pose_changed: boolean; seconds: number;
  run: Record<string, unknown>; attempt_log?: Attempt[];
};
type Queue = {
  id: string; label: string; started_at: number; finished_at: number;
  running_index: number; stopped: boolean; declared: number;
  counts: Record<string, number>; summary: string; notes: string[];
  first_pose: string; items: Item[];
};
/** THE LEVER SELF-TEST'S VERDICT for a NATIVE session — whether this
 * camera's exposure control was measured to reach its sensor. Empty on a
 * browser session, which is untouched by that check; `native` says whether
 * the question is even asked, so "no verdict" never reads as "failed one".
 * See `spectra/services/lever_selftest.py`. */
type Lever = {
  verdict?: string; proven?: boolean; reason?: string;
  response_ratio?: number | null; commanded_factor?: number;
};
/** THE CAMERA HOST ITSELF — present, absent, or never seen. Three states
 * and not two, because "that machine is off" and "no client has ever
 * existed here" used to produce the identical silence and send a reader to
 * look at a plug for no reason. `sentence` is `mapping_refusals`' own
 * wording; this component composes none. It REPORTS: a run's own refusal is
 * `SessionView.refusal`, unchanged, and is shown separately below.
 * See `spectra/services/capture_health.py`. */
type CameraHost = {
  present: boolean; state: 'present' | 'absent' | 'never';
  sentence: string; absent_for_s: number | null;
  client: Record<string, unknown> | null;
};
type SessionView = {
  present: boolean; locked: boolean; session_id: string; pose_id: string;
  refusal: string | null; client: Record<string, unknown>;
  native?: boolean; lever?: Lever; host?: CameraHost;
};
type Body = { running: boolean; current: Queue | null; session: SessionView; recent: Queue[] };

/** ok / partial / refused / not_run / stopped — a partial is its own word on
 * purpose: "some of it landed" is a third thing, and it is what an
 * unattended queue produces most often. */
const TONE: Record<string, string> = {
  ok: 'ok', partial: 'warn', refused: 'warn', failed: 'warn',
  not_run: 'muted', stopped: 'muted',
};
const WORD: Record<string, string> = {
  ok: 'completed', partial: 'stopped part-way (kept)', refused: 'refused',
  not_run: 'did not run', stopped: 'stopped',
};

function when(ts: number): string {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleString();
}

export default function UnattendedCard() {
  const [body, setBody] = useState<Body | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setBody(await apiGet<Body>('/rooms/capture-queue'));
    } catch {
      /* the page is still useful without it */
    }
  }, []);

  useEffect(() => {
    void load();
    const t = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(t);
  }, [load]);

  const queue = body?.current ?? null;
  const session = body?.session;
  const recent = (body?.recent ?? []).filter((q) => q.id !== queue?.id).slice(0, 3);

  return (
    <section className="card unattended-card">
      <h3>
        Unattended capture <HelpLink topic="unattended-capture" />
      </h3>
      <p className="muted small">
        A declared list of map and commissioning runs, executed end to end by a capture
        client on a machine with a camera — nothing is pressed here. Start one with{' '}
        <code>python -m spectra.capture_client --url … --queue yours.json</code>.
        Every run goes through exactly the same gates as the buttons above.
      </p>

      <p className={session?.locked ? 'ok small' : 'muted small'}>
        {session?.present
          ? `Camera session: ${session.locked ? 'locked and ready' : 'connected, NOT locked'}`
          : 'Camera session: none connected'}
        {session?.present && (session.client?.host as string)
          ? ` · ${session.client.host as string}` : ''}
        {session?.present && (session.client?.pose_name as string)
          ? ` · ${session.client.pose_name as string}` : ''}
        {session?.present && (session.client?.client_version as string)
          ? ` · client ${session.client.client_version as string}` : ''}
        {session?.pose_id ? ` · pose ${session.pose_id}` : ''}
      </p>
      {/* WHICH MACHINE, AND WHEN IT WAS LAST HERE. The line above says
        * whether a session exists; without this one, a camera host that has
        * been off since Tuesday and one that was never installed read the
        * same. Only shown when there is no session — while one is connected
        * the line above already names the machine. */}
      {session && !session.present && session.host?.sentence && (
        <p className="warn small">
          {session.host.sentence} <HelpLink topic="camera-host" />
        </p>
      )}
      {session && !session.locked && session.refusal && (
        <p className="warn small">{session.refusal}</p>
      )}
      {/* A DRIVER THAT HOLDS A SETTING IS NOT A SENSOR THAT OBEYS IT. The
        * line above says the camera reported itself locked; this one says
        * whether that was ever MEASURED. A browser session shows nothing
        * here, because nothing is asked of it. */}
      {session?.native && session.lever?.verdict && (
        <p className={session.lever.proven ? 'ok small' : 'warn small'}>
          {session.lever.proven
            ? `Exposure lever: measured real${
                session.lever.response_ratio
                  ? ` (${session.lever.response_ratio}× light for a commanded ${
                      session.lever.commanded_factor}×)` : ''}`
            : session.lever.reason || 'Exposure lever: not proven'}{' '}
          <HelpLink topic="lever-self-test" />
        </p>
      )}

      {queue && (
        <div className="run-result">
          <strong>
            {queue.label || 'queue'} — {queue.finished_at ? 'finished' : 'running'}
          </strong>
          <p className="muted small">
            {queue.summary} · started {when(queue.started_at)}
            {queue.finished_at ? ` · finished ${when(queue.finished_at)}` : ''}
          </p>
          <ul>
            {queue.items.map((item) => (
              <li key={item.index} className={TONE[item.status] ?? 'muted'}>
                <strong>{item.name}</strong>: {WORD[item.status] ?? item.status}
                {item.attempts > 1 ? ` (${item.attempts} attempts)` : ''}
                {item.seconds ? ` · ${item.seconds}s` : ''}
                {/* The SENTENCE, always — a status word on its own is what
                  * made "item 3 failed" useless at breakfast. */}
                {item.detail && <div className="small">{item.detail}</div>}
                {(item.attempt_log ?? []).length > 1 && (
                  <div className="muted small">
                    {(item.attempt_log ?? []).map((a) => (
                      <span key={a.attempt}>
                        {a.attempt > 1 ? ' · ' : ''}
                        attempt {a.attempt}: {a.status}
                        {a.run_summary ? ` (${a.run_summary})` : ''}
                      </span>
                    ))}
                  </div>
                )}
              </li>
            ))}
            {queue.running_index >= 0 && queue.items.length <= queue.running_index && (
              <li className="muted">running item {queue.running_index + 1}…</li>
            )}
          </ul>
          {queue.notes?.length ? (
            <ul className="warn small">
              {queue.notes.map((n) => <li key={n}>{n}</li>)}
            </ul>
          ) : null}
          {!queue.finished_at && (
            <button
              className="danger"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await apiPost('/rooms/capture-queue/stop', {});
                  await load();
                } finally {
                  setBusy(false);
                }
              }}
            >
              Stop after this run
            </button>
          )}
        </div>
      )}

      {!queue && <p className="muted small">No queue has run yet.</p>}

      {recent.length > 0 && (
        <details>
          <summary className="muted small">Earlier queues</summary>
          <ul className="muted small">
            {recent.map((q) => (
              <li key={q.id}>
                {q.label || q.id} — {q.summary} · {when(q.started_at)}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
