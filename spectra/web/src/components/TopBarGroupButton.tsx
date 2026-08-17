/** One pressable button that expands into a viewport-clamped panel growing
 * downward from the button, never sideways off the screen — same
 * defensive placement math as ColorGradientPicker's popover (measure the
 * trigger's rect, clamp the panel's left edge to stay on-screen, `position:
 * fixed` via a `document.body` portal so no ancestor's overflow/z-index can
 * clip it, and the top is always `rect.bottom` — never flipped above the
 * trigger, unlike ColorGradientPicker's own popover).
 *
 * Two interaction shapes, chosen per button by `holdToExpand`:
 * - true (Mode, Ambient): a short tap fires `onShortPress` (cycle mode /
 *   toggle ambient); holding ~500ms opens the panel instead. Built on
 *   useLongPress, the same hook ColorSetsPage's own tap-vs-hold Preview
 *   button uses — its onClickCapture swallows the click that follows a
 *   fired hold, so the tap handler never double-fires.
 * - false (Scenes): every tap just opens/closes the panel — no cycle
 *   behaviour to protect, so no hold gesture is needed or bound.
 *
 * Touch safety: `touch-action: manipulation` + `-webkit-touch-callout:
 * none` + `user-select: none` (CSS, .top-bar-group-btn) plus an
 * onContextMenu guard keep a real held finger from triggering the
 * browser's own text-selection / long-press context menu / iOS callout
 * instead of (or on top of) this button's own hold gesture — verified
 * under emulated touch input, not just a mouse-down, since that class of
 * bug only shows up on a real touch path. */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useLongPress } from '../lib/useLongPress';

const VIEWPORT_MARGIN = 8;
const PANEL_WIDTH = 320;

export interface TopBarGroupButtonProps {
  className?: string;
  title?: string;
  /** Accessible name — needed on any button whose visible content is a
   * colour/icon alone rather than text (the Mode button, since its fill
   * carries the mode with no label). Falls back to `title` when omitted. */
  ariaLabel?: string;
  style?: React.CSSProperties;
  holdToExpand: boolean;
  onShortPress?: () => void;
  panelTitle?: React.ReactNode;
  panel: React.ReactNode;
  children: React.ReactNode;
}

export default function TopBarGroupButton({
  className, title, ariaLabel, style, holdToExpand, onShortPress, panelTitle, panel, children,
}: TopBarGroupButtonProps) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const longPress = useLongPress(500);

  const place = () => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const panelWidth = Math.min(PANEL_WIDTH, window.innerWidth - VIEWPORT_MARGIN * 2);
    let left = rect.left;
    if (left + panelWidth > window.innerWidth - VIEWPORT_MARGIN) {
      left = Math.max(VIEWPORT_MARGIN, window.innerWidth - VIEWPORT_MARGIN - panelWidth);
    }
    // Always downward from the trigger, never flipped above it even near
    // the bottom of the viewport — his rule ("expansion goes down, never
    // off the side") reads as "never off the TOP either" here.
    const top = rect.bottom + 6;
    setPos({ top, left });
  };

  useLayoutEffect(() => {
    if (open) place();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDocDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (panelRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    const onViewport = () => place();
    document.addEventListener('mousedown', onDocDown);
    document.addEventListener('keydown', onKey);
    window.addEventListener('resize', onViewport);
    window.addEventListener('scroll', onViewport, true);
    return () => {
      document.removeEventListener('mousedown', onDocDown);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', onViewport);
      window.removeEventListener('scroll', onViewport, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const handleClick = () => {
    if (holdToExpand) { onShortPress?.(); return; }
    setOpen((o) => !o);
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`top-bar-group-btn${className ? ` ${className}` : ''}`}
        title={title}
        aria-label={ariaLabel ?? title}
        style={style}
        onClick={handleClick}
        onContextMenu={(e) => e.preventDefault()}
        {...(holdToExpand ? longPress(() => setOpen(true)) : {})}
      >
        {children}
      </button>
      {open && createPortal(
        <div
          ref={panelRef}
          className="top-bar-group-panel"
          style={{ top: pos?.top ?? -9999, left: pos?.left ?? -9999, visibility: pos ? 'visible' : 'hidden' }}
        >
          {panelTitle && <div className="top-bar-group-panel-title">{panelTitle}</div>}
          {panel}
        </div>,
        document.body,
      )}
    </>
  );
}
