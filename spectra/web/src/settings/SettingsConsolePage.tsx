/** /settings — the settings console (standing order 5: "talk to the
 * software; do not build the Admiral a settings page"). The ONLY way
 * anything changes here is the chat — POST /settings-console/message,
 * which runs a small Sonnet-class model whose only two tools are
 * get_settings (read) and set_setting (one validated write). The
 * "Current settings" and "Recent changes" cards below are READ-ONLY
 * telemetry, deliberately not a form: see spectra/services/
 * settings_console.py for why the boundary lives in the mechanism, not
 * a UI convention.
 *
 * Voice: the mic button records with MediaRecorder and POSTs the clip to
 * POST /settings-console/transcribe (never the browser's built-in
 * SpeechRecognition, which would ship his voice to a third-party cloud
 * and foreclose ever routing it to a local transcriber instead). The
 * transcript lands in the text box for review, not auto-sent — one extra
 * seam against a mis-transcribed word before it ever reaches the model.
 * Server-side transcription is unwired tonight (services/transcription.py)
 * — the button is real; its current failure is a stated toast, not a
 * silent no-op. */
import { useEffect, useRef, useState } from 'react';
import { useToast } from '../components/Toast';
import HelpLink from '../help/HelpLink';
import { uuid } from '../lib/uid';
import {
  useSendSettingsMessage, useSettingsLog, useSettingsRegistry,
  useTranscribeSettingsAudio, useUndoLastSetting,
} from '../queries';
import type { SettingsChatMessage, SettingValue } from '../types';

function formatValue(spec: SettingValue): string {
  const { value, kind, unit } = spec;
  if (value == null) return '—';
  if (kind === 'bool') return value ? 'On' : 'Off';
  if (kind === 'enum') return String(value);
  if (kind === 'color') return String(value);
  if (kind === 'float' && spec.min === 0 && spec.max === 1) {
    return `${Math.round(Number(value) * 100)}%`;
  }
  return unit ? `${value} ${unit}` : String(value);
}

function fmtAgo(tsMs: number): string {
  const s = Math.max(0, Math.round((Date.now() - tsMs) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
}

function fmtChangeValue(v: unknown): string {
  if (typeof v === 'boolean') return v ? 'On' : 'Off';
  if (v == null) return '—';
  return String(v);
}

export default function SettingsConsolePage() {
  const toast = useToast();
  const { data: registry } = useSettingsRegistry();
  const { data: log } = useSettingsLog();
  const send = useSendSettingsMessage();
  const undo = useUndoLastSetting();
  const transcribe = useTranscribeSettingsAudio();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<SettingsChatMessage[]>([]);
  const [text, setText] = useState('');
  const [recording, setRecording] = useState(false);
  const mediaRef = useRef<{ recorder: MediaRecorder; chunks: BlobPart[] } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  async function handleSend(overrideText?: string) {
    const toSend = (overrideText ?? text).trim();
    if (!toSend || send.isPending) return;
    setMessages((m) => [...m, { id: uuid(), role: 'user', text: toSend }]);
    setText('');
    try {
      const result = await send.mutateAsync({ session_id: sessionId, text: toSend });
      setSessionId(result.session_id);
      setMessages((m) => [...m, { id: uuid(), role: 'assistant', text: result.reply }]);
      if (result.changes.length > 0) {
        const labels = result.changes.map((c) => c.key ?? c.scene_name ?? c.flare_kind ?? c.op ?? 'something');
        toast(`Changed ${labels.join(', ')}`, 'success');
      }
    } catch {
      setMessages((m) => [...m, {
        id: uuid(), role: 'assistant',
        text: "Couldn't reach Sonic — see the toast for why.",
      }]);
      toast('Sonic unavailable — is ANTHROPIC_API_KEY configured?', 'error');
    }
  }

  async function handleUndo() {
    try {
      // undo_last_change() re-applies the previous value through
      // apply_change() itself, so the response IS a forward change: its
      // own new_value is what the setting is now, i.e. what we went
      // "back to" — old_value here is the (about-to-be-undone) value the
      // undo call saw on entry, not the target.
      const result = await undo.mutateAsync();
      toast(`Undid ${result.key}: back to ${fmtChangeValue(result.new_value)}`, 'success');
    } catch {
      toast('Nothing to undo', 'info');
    }
  }

  async function toggleRecording() {
    if (recording) {
      mediaRef.current?.recorder.stop();
      setRecording(false);
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      toast('This browser has no microphone access — type your request instead', 'info');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks: BlobPart[] = [];
      // Negotiate explicitly rather than trusting the browser default —
      // this IS the wire contract a second ship's local-Whisper bridge
      // builds against (see spectra/services/transcription.py's docstring):
      // webm/opus, and the Blob's type below is the recorder's own
      // negotiated mimeType, never a hardcoded guess that could drift
      // from what was actually encoded.
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus' : undefined;
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      recorder.ondataavailable = (e) => chunks.push(e.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
        try {
          const result = await transcribe.mutateAsync(blob);
          setText((t) => (t ? `${t} ${result.text}` : result.text));
        } catch (err) {
          const message = err instanceof Error ? err.message : '';
          if (message.includes('502')) {
            toast("Voice request dropped — the transcriber ignored the vocabulary hint", 'error');
          } else {
            toast("Voice isn't wired up yet — type your request", 'info');
          }
        }
      };
      mediaRef.current = { recorder, chunks };
      recorder.start();
      setRecording(true);
    } catch {
      toast('Microphone permission denied', 'error');
    }
  }

  return (
    <div className="settings-console">
      <div className="card settings-console-chat">
        <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          Sonic — settings console <HelpLink topic="settings-console" />
        </div>
        <div className="settings-console-messages" ref={scrollRef}>
          {messages.length === 0 ? (
            <p className="empty-note">
              Tell it what to change — "turn brightness down to 40%", "switch scene changes to
              transitions only", "turn ambient on and make it warm white". Sonic can also manage
              flares, scene settings, and create new scenes — chat with it from the Scenes page
              for that.
            </p>
          ) : (
            messages.map((m) => (
              <div key={m.id} className={`settings-console-msg settings-console-msg-${m.role}`}>
                {m.text}
              </div>
            ))
          )}
          {send.isPending && <div className="settings-console-msg settings-console-msg-assistant empty-note">…</div>}
        </div>
        <div className="settings-console-input-row">
          <button
            className={recording ? 'danger' : ''}
            title={recording ? 'Stop recording' : 'Record a voice request'}
            onClick={toggleRecording}
            disabled={send.isPending}
          >
            {recording ? '■' : '🎤'}
          </button>
          <input
            type="text"
            placeholder="Type a settings request…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') void handleSend(); }}
            disabled={send.isPending}
          />
          <button className="primary" onClick={() => void handleSend()} disabled={send.isPending || !text.trim()}>
            Send
          </button>
        </div>
      </div>

      <div className="card">
        <div className="card-title">Current settings</div>
        {!registry ? (
          <p className="empty-note">Loading…</p>
        ) : (
          <div className="settings-console-values">
            {registry.settings.map((s) => (
              <div className="settings-console-value" key={s.key} title={s.description}>
                <span className="settings-console-value-label">{s.label}</span>
                {s.kind === 'color' && s.value ? (
                  <span
                    className="settings-console-swatch"
                    style={{ background: String(s.value) }}
                  />
                ) : null}
                <span className="settings-console-value-num">{formatValue(s)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          Recent changes
          <button onClick={() => void handleUndo()} disabled={undo.isPending || !log?.length}>
            Undo last
          </button>
        </div>
        {!log?.length ? (
          <p className="empty-note">Nothing changed yet.</p>
        ) : (
          <div className="settings-console-log">
            {log.map((entry) => (
              <div className={`settings-console-log-row${entry.undone ? ' settings-console-log-undone' : ''}`} key={entry.id}>
                <span className="settings-console-log-key">{entry.key}</span>
                <span>{fmtChangeValue(entry.old_value)} → {fmtChangeValue(entry.new_value)}</span>
                <span className="settings-console-log-source">{entry.source}</span>
                <span className="settings-console-log-ago">{fmtAgo(entry.ts_ms)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
