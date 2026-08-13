/** Phase-5 WS wiring: auto-gen toasts, calibration targets, offset updates.
 * Handlers filter on the currently shown uri via a ref so the subscriptions
 * live for the page lifetime (no churn per song change). */
import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { onMessage } from '../../api/ws';
import { useToast } from '../../components/Toast';
import { useBuilderStore } from '../store';

export function useBuilderWs(uri: string | null) {
  const toast = useToast();
  const qc = useQueryClient();
  const uriRef = useRef(uri);
  uriRef.current = uri;

  useEffect(() => {
    const isMine = (msg: Record<string, unknown>) => msg.uri === uriRef.current;
    const refreshMeta = () => {
      qc.invalidateQueries({ queryKey: ['shape-meta', uriRef.current] });
    };
    const offs = [
      onMessage('auto_generate_started', (msg) =>
        toast(`Generating AI triggers for ${msg.artist} — ${msg.title}…`, 'info')),
      onMessage('auto_generate_complete', (msg) => {
        toast(`AI triggers ready: ${msg.count} suggestions for ${msg.artist} — ${msg.title}`, 'success');
        qc.invalidateQueries({ queryKey: ['profile'] });
      }),
      onMessage('auto_generate_failed', (msg) =>
        toast(`Auto-gen failed for ${msg.title}: ${msg.error}`, 'error')),

      onMessage('auto_offset_targeting', (msg) => {
        if (!isMine(msg)) return;
        const targets = [Number(msg.target_ms), ...((msg.candidates as number[]) ?? [])]
          .filter((v) => Number.isFinite(v));
        useBuilderStore.getState().setCalibrationTargets(targets);
      }),
      onMessage('offset_verified', (msg) => {
        if (!isMine(msg)) return;
        useBuilderStore.getState().setCalibrationTargets([]);
        refreshMeta();
        const off = Number(msg.offset_ms ?? 0);
        toast(`Timing auto-calibrated: ${off >= 0 ? '+' : ''}${off}ms`, 'success');
      }),
      onMessage('xcorr_final', (msg) => {
        if (!msg.saved || !isMine(msg)) return;
        refreshMeta();
        const off = Number(msg.offset_ms ?? 0);
        toast(`Auto-offset updated: ${off >= 0 ? '+' : ''}${off}ms`, 'info');
      }),
      onMessage('shape_offset_updated', (msg) => {
        if (!isMine(msg)) return;
        refreshMeta();
        const off = Number(msg.offset_ms ?? 0);
        const q = msg.quality != null ? `  Q=${Number(msg.quality).toFixed(2)}` : '';
        toast(`Offset calibrated: ${off >= 0 ? '+' : ''}${off}ms${q}`, 'info');
      }),
    ];
    return () => offs.forEach((off) => off());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
