/** /avsync — measure the room's audio/visual offset WITH THE PHONE
 * instead of arguing it (docs/SPECTRA_TIMING_CONVENTIONS.md, failure
 * cases 1-2: a week of arguing an audio delay against his ears, a
 * wandering number from the wrong engine read as a measurement).
 *
 * The phone stands where he stands: its mic hears the room, its camera
 * sees the lights. Both are reduced ON THE PHONE to number streams
 * (avsync/capture.ts — raw audio/video never leave the device) and
 * streamed to SPECTRA, which correlates them against its own two
 * references (the live audio hub, and either a flash pattern it drives
 * or the show's own writes) and answers with A NUMBER AND HOW CONFIDENT
 * IT IS (spectra/services/av_sync_session.py). Nothing measured here is
 * written into any setting — the number is presented for him to accept.
 *
 * Phone-first, single column. The secure-context gate is the first thing
 * on the page because it is the first thing that will stop him: camera
 * and mic need an https address (or Chrome's per-origin override).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import HelpLink from '../help/HelpLink';
import { useToast } from '../components/Toast';
import { apiGet, apiPost } from '../api/client';
import { AvSyncClient, PhoneCapture, secureContextProblem, type Capabilities, type ServerMessage } from './capture';

type LagDict = { ok: boolean; lag_ms: number | null; sigma_ms: number | null; peak_ratio: number;
  ambiguity: number; overlap_s: number; reason: string; subwindow_lags_ms: number[] };
type Systematic = { term: string; bound_ms: number; direction: string; depends_on: string };
type Estimate = {
  ok: boolean; av_offset_ms: number | null; sigma_ms: number | null;
  light_lag: LagDict; audio_lag: LagDict; light_region: string;
  systematics: Systematic[]; systematic_bound_ms: number; systematic_later_ms: number;
  systematic_earlier_ms: number; reason: string; statement: string;
  light_ref: Record<string, unknown>; clock: { ready: boolean; rtt_ms: number | null; samples: number };
  window_s: number;
};
type Measurement = { id: string; at_iso: string; mode: string; ok: boolean; av_offset_ms: number | null;
  sigma_ms: number | null; statement: string; light_region: string };
type AudioRefStats = { available: boolean; running: boolean; frames_seen: number; reason: string | null;
  last_frame_age_s: number | null };
type Privacy = { raw_media_leaves_phone: boolean; sent: string; written_to_disk: string; retention: string; network: string };

const PATTERN_DURATION_S = 12;

function fmtOffset(ms: number | null): string {
  if (ms === null) return '—';
  return `${Math.abs(ms).toFixed(0)} ms ${ms > 0 ? 'BEHIND' : 'AHEAD'}`;
}

export default function AvSyncPage() {
  const toast = useToast();
  const problem = secureContextProblem();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const captureRef = useRef<PhoneCapture | null>(null);
  const clientRef = useRef<AvSyncClient | null>(null);
  const [phase, setPhase] = useState<'idle' | 'starting' | 'live' | 'error'>('idle');
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [connected, setConnected] = useState(false);
  const [audioRef, setAudioRef] = useState<AudioRefStats | null>(null);
  const [privacy, setPrivacy] = useState<Privacy | null>(null);
  const [level, setLevel] = useState({ db: -90, lum: 0 });
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [measuring, setMeasuring] = useState<null | 'pattern' | 'show'>(null);
  const [patternEdges, setPatternEdges] = useState<number | null>(null);
  const [results, setResults] = useState<Measurement[]>([]);
  const [history, setHistory] = useState<Measurement[] | null>(null);
  const [frameTap, setFrameTap] = useState<{ enabled: boolean; fps: number; width: number } | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [fpsNow, setFpsNow] = useState<number | null>(null);

  const pushError = useCallback((m: string) => setErrors((e) => [...e.slice(-4), m]), []);

  // level meters + measured fps refresh
  useEffect(() => {
    if (phase !== 'live') return;
    const id = setInterval(() => {
      const c = captureRef.current;
      if (!c) return;
      setLevel(c.level());
      setFpsNow(c.measuredFps());
    }, 200);
    return () => clearInterval(id);
  }, [phase]);

  const stopAll = useCallback(() => {
    clientRef.current?.close();
    clientRef.current = null;
    captureRef.current?.stop();
    captureRef.current = null;
    setConnected(false);
    setMeasuring(null);
    setPhase('idle');
  }, []);

  useEffect(() => () => stopAll(), [stopAll]);

  const handleMessage = useCallback((m: ServerMessage) => {
    switch (m.type) {
      case 'welcome':
        setAudioRef(m.audio_ref as AudioRefStats);
        setPrivacy(m.privacy as Privacy);
        setFrameTap(m.frame_tap as { enabled: boolean; fps: number; width: number });
        break;
      case 'estimate':
        setEstimate(m as unknown as Estimate);
        break;
      case 'measure_started':
        setMeasuring(m.mode as 'pattern' | 'show');
        setPatternEdges(null);
        break;
      case 'measure_done': {
        setMeasuring(null);
        const est = m.estimate as Estimate;
        setEstimate(est);
        const rec = m.measurement as Measurement | null;
        if (rec) setResults((r) => [rec, ...r]);
        if (m.aborted) toast('Pattern stopped early — room restored', 'info');
        else if (est.ok) toast(`Measured: lights ${fmtOffset(est.av_offset_ms)}`, 'success');
        else toast(`No number this time — ${est.reason}`, 'info');
        break;
      }
      case 'config': {
        const cfg = m.frame_tap as { enabled: boolean; fps: number; width: number };
        setFrameTap(cfg);
        captureRef.current?.setFrameTap(cfg);
        break;
      }
      case 'error':
        pushError(String(m.message));
        toast(String(m.message), 'error');
        break;
      default:
        break;
    }
  }, [pushError, toast]);

  const start = useCallback(async () => {
    if (problem || !videoRef.current) return;
    setPhase('starting');
    setErrors([]);
    const client = new AvSyncClient();
    const capture = new PhoneCapture(videoRef.current, {
      onAudio: (b) => client.send({ type: 'audio', t0_ms: b.t0Ms, hop_ms: b.hopMs, v: b.v }),
      onVideo: (samples) => client.send({
        type: 'video',
        t_ms: samples.map((s) => s.tMs),
        lum: samples.map((s) => s.lum),
        grid: samples.map((s) => s.grid),
      }),
      onFrame: (f) => client.send({ type: 'frame', captured_at_ms: f.capturedAtMs, width: f.width,
        height: f.height, mime: f.mime, data: f.b64 }),
      onError: pushError,
    });
    try {
      await capture.start();
    } catch (err) {
      capture.stop();
      setPhase('error');
      const msg = err instanceof Error ? err.message : String(err);
      pushError(msg.includes('Permission') || msg.includes('NotAllowed')
        ? 'Camera/microphone permission was denied — allow both and try again'
        : msg);
      return;
    }
    captureRef.current = capture;
    setCaps({ ...capture.caps });
    try {
      client.onMessage(handleMessage);
      client.onOpenChange(setConnected);
      await client.connect();
    } catch (err) {
      capture.stop();
      setPhase('error');
      pushError(err instanceof Error ? err.message : String(err));
      return;
    }
    clientRef.current = client;
    client.send({
      type: 'hello',
      user_agent: navigator.userAgent,
      origin: location.origin,
      secure_context: window.isSecureContext,
      audio: { sample_rate: capture.caps.sampleRate, latency_s: capture.caps.audioLatencyS,
        worklet: capture.caps.audioWorklet },
      video: { fps: capture.caps.fps, capture_time_available: capture.caps.captureTime,
        width: capture.caps.width, height: capture.caps.height, rvfc: capture.caps.rvfc,
        facing: capture.caps.facing },
    });
    setPhase('live');
  }, [problem, handleMessage, pushError]);

  const measure = (mode: 'pattern' | 'show') => {
    clientRef.current?.send({ type: 'measure', mode, duration_s: PATTERN_DURATION_S });
  };
  const stopMeasure = () => clientRef.current?.send({ type: 'stop' });

  const loadHistory = async () => {
    try {
      const d = await apiGet<{ measurements: Measurement[] }>('/av-sync/measurements?limit=12');
      setHistory([...d.measurements].reverse());
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), 'error');
    }
  };

  const toggleFrameTap = async () => {
    if (!frameTap) return;
    try {
      const d = await apiPost<{ frame_tap: { enabled: boolean; fps: number; width: number } }>(
        '/av-sync/frame-tap', { enabled: !frameTap.enabled, fps: 1, width: 320 });
      setFrameTap(d.frame_tap);
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), 'error');
    }
  };

  const origin = location.origin;

  return (
    <div style={{ maxWidth: 720, margin: '0 auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <h1 style={{ fontSize: 20, display: 'flex', alignItems: 'center', gap: 8 }}>
        AV Sync — measure the offset with your phone <HelpLink topic="av-sync-page" />
      </h1>

      {problem && (
        <div className="card" style={{ borderColor: 'var(--warning)' }}>
          <div className="card-title">Camera &amp; microphone are blocked on this address <HelpLink topic="av-sync-secure-context" /></div>
          <p style={{ marginBottom: 8 }}>{problem}</p>
          <p style={{ marginBottom: 8 }}>You are on <code>{origin}</code>. Browsers only allow camera/mic capture on an <b>https</b> address (or localhost). Two ways through:</p>
          <ol style={{ paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 6 }}>
            <li><b>Tonight, on Chrome for Android:</b> open a new tab, go to <code>chrome://flags/#unsafely-treat-insecure-origin-as-secure</code>, paste exactly <code>{origin}</code> into the box, set it to <b>Enabled</b>, tap <b>Relaunch</b>, come back here.</li>
            <li><b>The proper fix (firstmate's deploy, not a phone step):</b> put HTTPS in front of SPECTRA — on a tailnet, <code>tailscale serve</code> gives a real certificate and this page (and the Settings voice mic) work on every phone browser, no flag.</li>
          </ol>
        </div>
      )}

      {/* Step 1 — camera + mic */}
      <div className="card">
        <div className="card-title">1 · Point the phone at the lights <HelpLink topic="av-sync-phone-steps" /></div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <video ref={videoRef} style={{ width: 160, height: 120, background: '#000', borderRadius: 8,
            objectFit: 'cover', display: phase === 'live' || phase === 'starting' ? 'block' : 'none' }} muted playsInline />
          <div style={{ flex: 1, minWidth: 200, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {phase !== 'live' && (
              <button className="primary" disabled={!!problem || phase === 'starting'} onClick={() => void start()}
                style={{ padding: '12px 16px', fontSize: 16 }}>
                {phase === 'starting' ? 'Starting…' : '📷 Start camera & mic'}
              </button>
            )}
            {phase === 'live' && (
              <button className="danger" onClick={stopAll} style={{ padding: '10px 14px' }}>■ Stop camera &amp; disconnect</button>
            )}
            <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
              The browser will ask for <b>Camera</b> and <b>Microphone</b> — allow both. Aim so the lights you care about fill a good part of the picture; keep the phone still; let the music play.
            </div>
            {phase === 'live' && (
              <div style={{ display: 'grid', gridTemplateColumns: '70px 1fr 60px', gap: 6, alignItems: 'center', fontSize: 13 }}>
                <span>sound</span>
                <div className="energy-meter"><div className="energy-meter-fill" style={{ width: `${Math.max(0, Math.min(100, (level.db + 80) / 0.8))}%` }} /></div>
                <span>{level.db.toFixed(0)} dB</span>
                <span>light</span>
                <div className="energy-meter"><div className="energy-meter-fill" style={{ width: `${Math.max(0, Math.min(100, level.lum / 2.55))}%` }} /></div>
                <span>{level.lum.toFixed(0)}/255</span>
              </div>
            )}
            {caps && (
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <span className={`badge ${connected ? 'badge-purple' : 'badge-red'}`}>{connected ? 'connected' : 'disconnected'}</span>
                <span className="badge badge-gray">{fpsNow ?? caps.fps ?? '?'} fps</span>
                <span className={`badge ${caps.captureTime ? 'badge-purple' : 'badge-amber'}`}>{caps.captureTime ? 'frame capture time: yes' : 'frame capture time: no (wider error bar)'}</span>
                <span className={`badge ${caps.audioLatencyS !== null ? 'badge-purple' : 'badge-amber'}`}>{caps.audioLatencyS !== null ? `mic latency reported ${Math.round(caps.audioLatencyS * 1000)} ms` : 'mic latency not reported'}</span>
                <span className="badge badge-gray">{caps.audioWorklet ? 'AudioWorklet' : 'ScriptProcessor'}</span>
              </div>
            )}
            {audioRef && (
              <div style={{ fontSize: 13 }}>
                Server audio reference:{' '}
                {audioRef.available
                  ? <span className="badge badge-purple">live audio hub ({audioRef.frames_seen} frames)</span>
                  : <span className="badge badge-red" title={audioRef.reason ?? ''}>unavailable — {audioRef.reason}</span>}
              </div>
            )}
          </div>
        </div>
        {errors.length > 0 && (
          <div style={{ marginTop: 8, color: 'var(--danger)', fontSize: 13 }}>{errors.map((e, i) => <div key={i}>{e}</div>)}</div>
        )}
      </div>

      {/* Step 2 — measure */}
      <div className="card">
        <div className="card-title">2 · Measure <HelpLink topic="av-sync-pattern-vs-passive" /></div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button className="primary" disabled={phase !== 'live' || !connected || measuring !== null}
            onClick={() => measure('pattern')} style={{ padding: '12px 16px', fontSize: 15 }}>
            ⚡ Flash-pattern measurement ({PATTERN_DURATION_S} s)
          </button>
          <button disabled={phase !== 'live' || !connected || measuring !== null} onClick={() => measure('show')}
            style={{ padding: '12px 16px' }}>
            ◌ Passive (no flash, uses the show)
          </button>
          {measuring && <button className="danger" onClick={stopMeasure} style={{ padding: '12px 16px' }}>■ Stop</button>}
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 8 }}>
          The flash pattern turns every light white on/off at random for {PATTERN_DURATION_S} s while the music keeps playing, then puts the room back exactly as it was. The show&apos;s own automatic changes are paused for those seconds. Passive mode flashes nothing — it listens to the show&apos;s own changes and is much less certain; it says so.
        </div>
        {measuring === 'pattern' && <div className="badge badge-amber" style={{ marginTop: 8 }}>flashing… keep the phone still{patternEdges !== null ? ` (${patternEdges} edges)` : ''}</div>}
        {measuring === 'show' && <div className="badge badge-amber" style={{ marginTop: 8 }}>listening to the show…</div>}
      </div>

      {/* The number */}
      <div className="card">
        <div className="card-title">Result <HelpLink topic="av-sync-what-it-measures" /></div>
        {!estimate && <div className="empty-note">No estimate yet.</div>}
        {estimate && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: estimate.ok ? 'var(--accent2)' : 'var(--text-muted)' }}>
              {estimate.ok ? `Lights ${fmtOffset(estimate.av_offset_ms)}` : 'No number yet'}
              {estimate.ok && estimate.sigma_ms !== null && <span style={{ fontSize: 16, fontWeight: 500 }}> ±{estimate.sigma_ms.toFixed(0)} ms</span>}
            </div>
            <div style={{ fontSize: 14 }}>{estimate.statement}</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', fontSize: 12 }}>
              <span className={`badge ${estimate.light_lag.ok ? 'badge-purple' : 'badge-gray'}`}>light lag {estimate.light_lag.lag_ms ?? '—'} ms · peak {estimate.light_lag.peak_ratio}{estimate.light_lag.reason ? ` · ${estimate.light_lag.reason}` : ''}</span>
              <span className={`badge ${estimate.audio_lag.ok ? 'badge-purple' : 'badge-gray'}`}>audio lag {estimate.audio_lag.lag_ms ?? '—'} ms · peak {estimate.audio_lag.peak_ratio}{estimate.audio_lag.reason ? ` · ${estimate.audio_lag.reason}` : ''}</span>
              <span className="badge badge-gray">clock ±{estimate.clock.rtt_ms !== null ? (estimate.clock.rtt_ms / 2).toFixed(0) : '?'} ms</span>
              <span className="badge badge-gray">{estimate.light_ref.kind ? `ref: ${String(estimate.light_ref.kind)}` : 'no light ref'}</span>
              {estimate.light_region && <span className="badge badge-gray">region {estimate.light_region}</span>}
            </div>
            <details>
              <summary style={{ cursor: 'pointer', fontSize: 13 }}>Systematic terms this capture cannot see (bounds, direction, what they depend on) <HelpLink topic="av-sync-confidence" /></summary>
              <ul style={{ paddingLeft: 18, fontSize: 12, marginTop: 6, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {estimate.systematics.map((s, i) => (
                  <li key={i}><b>±{s.bound_ms} ms</b> — {s.term} <i>({s.direction.replace(/_/g, ' ')}; depends on {s.depends_on})</i></li>
                ))}
              </ul>
              <div style={{ fontSize: 12, marginTop: 4 }}>Net: the true value could be up to {estimate.systematic_later_ms} ms further AHEAD or {estimate.systematic_earlier_ms} ms further BEHIND than shown. A difference between two runs on this phone is far tighter than either absolute number.</div>
            </details>
          </div>
        )}
      </div>

      {/* Session results + history */}
      <div className="card">
        <div className="card-title">Measurements</div>
        {results.length === 0 && <div className="empty-note">Finished measurements from this session will list here (and are saved as numbers-only records).</div>}
        {results.map((r) => (
          <div key={r.id} style={{ fontSize: 13, padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
            <b>{r.ok ? `Lights ${fmtOffset(r.av_offset_ms)}` : 'no number'}</b>{r.sigma_ms !== null ? ` ±${r.sigma_ms.toFixed(0)}` : ''} · {r.mode} · {r.at_iso}
          </div>
        ))}
        <button onClick={() => void loadHistory()} style={{ marginTop: 8 }}>Show saved history</button>
        {history && history.map((r) => (
          <div key={r.id} style={{ fontSize: 12, color: 'var(--text-muted)', padding: '2px 0' }}>
            {r.at_iso} · {r.ok ? `${fmtOffset(r.av_offset_ms)}` : 'no number'} · {r.mode}
          </div>
        ))}
      </div>

      {/* Privacy — always visible */}
      <div className="card">
        <div className="card-title">Privacy — where this goes <HelpLink topic="av-sync-privacy" /></div>
        <ul style={{ paddingLeft: 18, fontSize: 13, display: 'flex', flexDirection: 'column', gap: 4 }}>
          <li><b>Raw audio and video never leave this phone.</b> The page reduces them here to two number streams — a microphone loudness envelope (~90 numbers/s) and a per-frame brightness (one mean + a 4×4 grid) — and sends only those.</li>
          <li><b>Where:</b> over this same-origin WebSocket to SPECTRA ({location.host}) — the network you are already reaching SPECTRA on, and nowhere else. Nothing is sent to any cloud or third party.</li>
          <li><b>Written to disk:</b> one file, <code>storage/spectra/av_sync_measurements.json</code> — finished measurement records (the numbers, the statement, phone capability flags, browser name). Never audio, video, frames, or the streams. Kept: last 100 records.{privacy ? '' : ''}</li>
          <li><b>Kept in memory while connected:</b> ~60 s of the two number streams; dropped when you disconnect.</li>
          <li><b>Frame tap (off):</b> <HelpLink topic="av-sync-frame-tap" /> the hook for the future camera/vision work. When switched on, small JPEG stills go to SPECTRA&apos;s memory only (≤8 held, cleared on disconnect). Nothing inspects them. {frameTap && <button onClick={() => void toggleFrameTap()} disabled={!connected} style={{ marginLeft: 6 }}>{frameTap.enabled ? 'turn frame tap OFF' : 'turn frame tap on'}</button>}</li>
        </ul>
      </div>
    </div>
  );
}
