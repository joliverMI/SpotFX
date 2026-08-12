import { useRef, useState } from 'react';
import { useToast } from './Toast';

/** Small ▶ button used at every level of the event editor (between ⧉ and ✕):
 * fires the given preview immediately, flashing ✔ on success. */
export default function PreviewButton({
  run,
  title = 'Preview — fire this now (unsaved draft state)',
  label,
  style,
}: {
  run: () => Promise<void>;
  title?: string;
  label?: string;
  style?: React.CSSProperties;
}) {
  const [state, setState] = useState<'idle' | 'busy' | 'ok'>('idle');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const toast = useToast();

  const onClick = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (state === 'busy') return;
    setState('busy');
    try {
      await run();
      setState('ok');
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setState('idle'), 800);
    } catch (err) {
      setState('idle');
      toast(`Preview failed: ${err instanceof Error ? err.message : err}`, 'error');
    }
  };

  return (
    <button title={title} style={{ padding: '2px 7px', fontSize: 12, ...style }} onClick={(e) => void onClick(e)}>
      {state === 'ok' ? '✔' : '▶'}{label ? ` ${label}` : ''}
    </button>
  );
}
