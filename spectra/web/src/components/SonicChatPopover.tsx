/** A floating "💬 Sonic" button + popover chat panel — the Admiral's own
 * ask: "I need to be able to chat with it directly from that page with
 * some kind of pop-up button or something," specifically for the Scenes
 * page (spectra/web/src/scenes/ScenesPage.tsx), which otherwise has no
 * chat surface of its own. Talks to the SAME POST /settings-console/
 * message endpoint the Settings page's embedded chat
 * (SettingsConsolePage.tsx) uses — Sonic is one backend
 * (spectra/services/settings_agent.py) now authorized over BOTH domains
 * (settings + scene/flare), reachable from either page; this component
 * doesn't know or care which domain a given message lands in.
 *
 * Voice works the same way as the Settings page: MediaRecorder records,
 * POSTs to /settings-console/transcribe, and the transcript lands in the
 * text box for review before sending (never auto-sent) — see
 * SettingsConsolePage.tsx's own header comment for the full wire-contract
 * rationale, unchanged here. */
import { useEffect, useRef, useState } from 'react';
import { useToast } from './Toast';
import HelpLink from '../help/HelpLink';
import { formatAppliedStatus, formatPreview, formatRejectedStatus } from '../lib/sonicPreview';
import { uuid } from '../lib/uid';
import { useSendSettingsMessage, useTranscribeSettingsAudio, useUndoLastSceneChange } from '../queries';
import type { SettingsChatMessage } from '../types';

export default function SonicChatPopover() {
  const toast = useToast();
  const send = useSendSettingsMessage();
  const transcribe = useTranscribeSettingsAudio();
  const undoScene = useUndoLastSceneChange();

  const [open, setOpen] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<SettingsChatMessage[]>([]);
  const [text, setText] = useState('');
  const [recording, setRecording] = useState(false);
  const mediaRef = useRef<{ recorder: MediaRecorder; chunks: BlobPart[] } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, open]);

  async function handleSend(overrideText?: string) {
    const toSend = (overrideText ?? text).trim();
    if (!toSend || send.isPending) return;
    setMessages((m) => [...m, { id: uuid(), role: 'user', text: toSend }]);
    setText('');
    try {
      const result = await send.mutateAsync({ session_id: sessionId, text: toSend });
      setSessionId(result.session_id);
      setMessages((m) => [...m, { id: uuid(), role: 'assistant', text: result.reply }]);
      // The definitive "did it work" line — built server-side from real
      // structured fields (SonicAppliedChange.summary / SonicRejectedChange
      // .reason), never from the model's own prose, and always shown
      // regardless of what result.reply says. This is the answer to "I
      // don't know if it actually completed the task" — one plain
      // sentence per attempted write, success or failure.
      const statusLines = [
        ...result.changes.map((c) => `✓ ${formatAppliedStatus(c)}`),
        ...(result.rejected ?? []).map((c) => `✗ ${formatRejectedStatus(c)}`),
      ];
      if (statusLines.length > 0) {
        setMessages((m) => [...m, { id: uuid(), role: 'status', text: statusLines.join('\n') }]);
      }
      if (result.changes.length > 0) {
        toast(result.changes.map(formatAppliedStatus).join(' '), 'success');
        // The preview line is a READ of the saved scene (scene_console.py's
        // _diff_scenes), not Sonic's own reply text — rendered as its own,
        // visually distinct message so a check-in never has to trust prose.
        const previewLines = result.changes.map(formatPreview).filter((p): p is string => !!p);
        if (previewLines.length > 0) {
          setMessages((m) => [...m, { id: uuid(), role: 'preview', text: previewLines.join('\n\n') }]);
        }
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
      // The plain, model-free button — POST /settings-console/scene-undo,
      // never routed through Sonic's chat loop (see queries.ts).
      const result = await undoScene.mutateAsync();
      setMessages((m) => [...m, {
        id: uuid(), role: 'assistant',
        text: `Undid the last change to "${result.scene_name ?? 'that scene'}".`,
      }]);
      const preview = formatPreview(result);
      if (preview) setMessages((m) => [...m, { id: uuid(), role: 'preview', text: preview }]);
      toast('Undid last scene change', 'success');
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
            toast('Voice request dropped — the transcriber ignored the vocabulary hint', 'error');
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
    <>
      <button
        className="primary sonic-popover-fab"
        title="Chat with Sonic — manage flares, scene settings, and create scenes"
        onClick={() => setOpen((o) => !o)}
        style={{
          position: 'fixed', right: 18, bottom: 18, zIndex: 60,
          width: 52, height: 52, borderRadius: '50%', fontSize: 20,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: '0 2px 10px rgba(0,0,0,0.35)',
        }}
      >
        {open ? '✕' : '💬'}
      </button>

      {open && (
        <div
          className="card sonic-popover-panel"
          style={{
            position: 'fixed', right: 18, bottom: 78, zIndex: 60,
            width: 340, maxWidth: 'calc(100vw - 36px)', height: 440,
            maxHeight: 'calc(100vh - 110px)', display: 'flex', flexDirection: 'column',
            boxShadow: '0 4px 24px rgba(0,0,0,0.45)',
          }}
        >
          <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            Sonic <HelpLink topic="sonic-scenes" />
            <button
              style={{ marginLeft: 'auto', fontSize: 11, padding: '2px 8px' }}
              title="Undo the most recent scene/flare change Sonic made — always available, no chat needed"
              onClick={() => void handleUndo()}
              disabled={undoScene.isPending}
            >
              ↺ Undo last
            </button>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
            flares · scene settings · new scenes · overwrite (backed up)
            {' '}<HelpLink topic="sonic-scene-backups" title="Backups, undo, and preview" />
          </div>
          <div className="settings-console-messages" ref={scrollRef} style={{ flex: 1, minHeight: 0 }}>
            {messages.length === 0 ? (
              <p className="empty-note">
                Tell it what to change — "add a Boom flare kind to this scene", "set the entry
                blend to 1.5 seconds", "create a new scene called Warm Fade".
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
              onClick={() => void toggleRecording()}
              disabled={send.isPending}
            >
              {recording ? '■' : '🎤'}
            </button>
            <input
              type="text"
              placeholder="Ask Sonic…"
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
      )}
    </>
  );
}
