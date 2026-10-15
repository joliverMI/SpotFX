/** A rich tooltip ON THE CONTROL ITSELF — hover (mouse) or long-press
 * (touch) over the wrapped control reveals a short description plus a
 * "Help" link into the full topic. UI declutter plan idea 5, "One help
 * '?' per page": the page-level "?" in the grouped menu (nav/NavBar.tsx,
 * context-sensitive via help/routeTopics.ts) is the one always-VISIBLE
 * help affordance in the chrome; every other control explains itself on
 * hover/long-press with NO circle of its own.
 *
 * IT RENDERS NO BUTTON AND NO GLYPH (design-fidelity pass, 2026-10-14).
 * The first build of this component drew its own 18px circled "ⓘ" button
 * beside each control, which was idea 5 implemented as a GLYPH SWAP: the
 * audit counted seven circles in the live chrome at 1440 — the plan's own
 * "before" number — where the approved mockup has exactly one, in the
 * menu row. So the trigger is now the control itself: callers WRAP their
 * control in `<InfoTip>`, and this component contributes only the
 * hover/long-press binding plus the panel. `children` is required for
 * that reason — an InfoTip with nothing to wrap would have nothing to
 * hover and would be invisible.
 *
 * The panel is a `position: fixed` PORTAL, placed off the wrapper's own
 * rect and clamped to the viewport, because the bar it most often sits in
 * (`.one-bar`) is an `overflow-x: auto` scroll container: an
 * absolutely-positioned panel inside it is clipped at the bar's own
 * bottom edge — the same reason TopBarGroupButton portals its own panel
 * (see that file's docstring). */
import { useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import HelpLink from '../help/HelpLink';

const PANEL_WIDTH = 240;
const VIEWPORT_MARGIN = 8;
/** Long-press to reveal, on touch. */
const HOLD_MS = 400;
/** A finger that travels further than this is scrolling, not holding. */
const HOLD_SLOP_PX = 8;

export default function InfoTip({
  text, topic, children, className,
}: {
  text: string;
  topic?: string;
  /** The control this tooltip describes — hovering/long-pressing IT is
   * what opens the panel. Required: see the module docstring. */
  children: React.ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const wrapRef = useRef<HTMLSpanElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** ITS OWN HOLD, NOT `useLongPress` — deliberately. That hook SWALLOWS
   * the click that follows a fired hold (its `onClickCapture`), which is
   * right for a button whose hold does something, and wrong here: this
   * wrapper sits around real LINKS (the house button, the song block, the
   * Light Show slot), and a capture-phase swallow on the wrapper would
   * eat the click before the link ever saw it. A slow tap — longer than
   * the reveal delay, shorter than a deliberate hold — would then show
   * the tooltip and silently fail to navigate. Revealing a tooltip is not
   * an action that consumes the tap, so nothing is swallowed here; the
   * context menu is still suppressed, which a held finger does want. */
  const hold = useRef<{ timer: ReturnType<typeof setTimeout>; x: number; y: number } | null>(null);
  const cancelHold = () => {
    if (hold.current) clearTimeout(hold.current.timer);
    hold.current = null;
  };

  const show = () => {
    if (closeTimer.current) { clearTimeout(closeTimer.current); closeTimer.current = null; }
    setOpen(true);
  };
  const hideSoon = () => {
    closeTimer.current = setTimeout(() => setOpen(false), 150);
  };

  useLayoutEffect(() => {
    if (!open) return;
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    const width = Math.min(PANEL_WIDTH, window.innerWidth - VIEWPORT_MARGIN * 2);
    const left = Math.max(
      VIEWPORT_MARGIN,
      Math.min(rect.left, window.innerWidth - VIEWPORT_MARGIN - width),
    );
    setPos({ top: rect.bottom + 6, left });
  }, [open]);

  return (
    <span
      ref={wrapRef}
      // NOT `.long-press-target` — that class carries `touch-action:
      // none`, which is right for a control whose hold DOES something
      // (it must not lose the gesture to a pan) and wrong here: this
      // wrapper now sits around ordinary labels, readouts and card
      // titles, and blocking `touch-action` on those would stop a finger
      // starting on them from scrolling the page at all. The hold above
      // cancels itself on movement instead, so a scroll just works.
      className={`info-tip${className ? ` ${className}` : ''}`}
      onMouseEnter={show}
      onMouseLeave={hideSoon}
      onFocusCapture={show}
      onBlurCapture={hideSoon}
      onPointerDown={(e) => {
        if (e.pointerType === 'mouse') return;
        cancelHold();
        hold.current = {
          x: e.clientX,
          y: e.clientY,
          timer: setTimeout(() => { hold.current = null; show(); }, HOLD_MS),
        };
      }}
      onPointerMove={(e) => {
        if (hold.current
          && Math.hypot(e.clientX - hold.current.x, e.clientY - hold.current.y) > HOLD_SLOP_PX) {
          cancelHold();
        }
      }}
      onPointerUp={cancelHold}
      onPointerCancel={cancelHold}
      onContextMenu={(e) => { if (open) e.preventDefault(); }}
    >
      {children}
      {open && pos && createPortal(
        <div
          className="info-tip-panel"
          role="tooltip"
          style={{ top: pos.top, left: pos.left, width: PANEL_WIDTH }}
          onMouseEnter={show}
          onMouseLeave={hideSoon}
        >
          <p>{text}</p>
          {topic && <HelpLink topic={topic} title="Full help topic" />}
        </div>,
        document.body,
      )}
    </span>
  );
}
