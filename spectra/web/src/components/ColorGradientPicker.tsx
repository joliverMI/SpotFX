/** The one colour-choosing surface for SPECTRA — wraps LedFX's own picker
 * component (`react-gcolor-picker`, MIT, the exact package LedFX's frontend
 * imports for every colour/gradient field) rather than a lookalike. Every
 * solid colour and every gradient in the app goes through this: same
 * widget, same solid/gradient tabs, same output grammar.
 *
 * Phone-first: the popover is viewport-clamped (`position: fixed`,
 * measured off the trigger's rect) so it never runs off a narrow screen —
 * layout only; the picker's own behaviour is untouched. */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import ReactGPicker from 'react-gcolor-picker';

/** Every linear-gradient in this app is HORIZONTAL by convention: the
 * angle before the first comma is `90deg`, and nothing downstream reads it
 * (SPECTRA's own `spectra/models/gradient2d.py::parse_stops` discards that
 * head segment entirely, `spectra/services/color_rotate.py` passes it
 * through verbatim, and the vendored render pipeline's `fx/color.py`
 * parses it into an `angle` attribute no effect ever reads). What it DOES
 * decide is how a value paints as CSS — including this picker's own swatch
 * strip, which is a wide, 22px-tall bar in `GradientEditor2D`: a vertical
 * angle paints across the bar's short axis instead of along its length.
 *
 * Two things this guards, both real:
 *  - an angle-LESS gradient (`linear-gradient(#000 0%, #fff 100%)`, which
 *    LedFX's own panel can emit) would have its first stop colour silently
 *    swallowed by every parser above, which reads before-the-first-comma
 *    as the angle;
 *  - a WRONG angle. Since PR #171 hid the picker's angle dial
 *    (`showGradientAngle={false}`), react-gcolor-picker still bakes its own
 *    angle into everything it emits and there is no longer any control to
 *    correct it: its built-in quick-pick gradients carry 0/45/270/315deg
 *    (measured live against the real widget — see
 *    `scripts/check_gradient_angle_canonicalization.mjs`), and converting a
 *    solid to a gradient starts from its internal 180deg default. Picking
 *    one of those used to stick, painting his edge strips vertically.
 *
 * So every emitted linear-gradient is CANONICALIZED to 90deg — the angle
 * is rewritten, not merely supplied when missing. This is input
 * canonicalization into the app's one grammar, not a reinterpretation of
 * stored data: no stored value changes meaning, because no consumer of the
 * angle exists. Solid colours and anything that isn't a linear-gradient
 * pass through untouched. */
const CANONICAL_ANGLE = '90deg';

/** The head segment of a linear-gradient is a DIRECTION only when it looks
 * like one (`45deg`, `.5turn`, `to bottom right`); otherwise it is already
 * the first colour stop and the angle is simply missing. */
const DIRECTION_RE = /^\s*(?:[+-]?\d*\.?\d+(?:deg|grad|rad|turn)|to\s+(?:top|bottom|left|right)(?:\s+(?:top|bottom|left|right))?)\s*$/i;

export function normalizeGradientAngle(value: string): string {
  if (!value || !value.includes('linear-gradient')) return value;
  const open = /linear-gradient\s*\(/i.exec(value);
  if (!open) return value;
  const start = open.index + open[0].length;
  const comma = value.indexOf(',', start);
  if (comma < 0) return value;
  const head = value.slice(start, comma);
  if (DIRECTION_RE.test(head)) {
    return `${value.slice(0, start)}${CANONICAL_ANGLE}${value.slice(comma)}`;
  }
  return `${value.slice(0, start)}${CANONICAL_ANGLE}, ${value.slice(start)}`;
}

export interface ColorGradientPickerProps {
  value: string;
  onChange: (value: string) => void;
  /** Enables the gradient tab alongside solid. Ambient stays solid-only —
   * a Hue entertainment stream only ever takes one colour. */
  gradient?: boolean;
  /** Saved colours/gradients shown as quick-pick swatches. */
  defaultColors?: string[];
  title?: string;
  disabled?: boolean;
  swatchWidth?: number | string;
  swatchHeight?: number;
}

const VIEWPORT_MARGIN = 8;

export default function ColorGradientPicker({
  value,
  onChange,
  gradient = false,
  defaultColors,
  title,
  disabled,
  swatchWidth = 40,
  swatchHeight = 26,
}: ColorGradientPickerProps) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  const place = () => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const popoverWidth = popoverRef.current?.offsetWidth ?? 300;
    let left = rect.left;
    if (left + popoverWidth > window.innerWidth - VIEWPORT_MARGIN) {
      left = Math.max(VIEWPORT_MARGIN, window.innerWidth - VIEWPORT_MARGIN - popoverWidth);
    }
    let top = rect.bottom + 4;
    const popoverHeight = popoverRef.current?.offsetHeight ?? 380;
    if (top + popoverHeight > window.innerHeight - VIEWPORT_MARGIN) {
      top = Math.max(VIEWPORT_MARGIN, rect.top - popoverHeight - 4);
    }
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
      if (popoverRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
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

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="color-gradient-swatch"
        title={title ?? (gradient ? 'Pick a colour or build a gradient' : 'Pick a colour')}
        disabled={disabled}
        // Display-only: the swatch paints a 90deg-re-angled copy of the
        // stored value, so a strip stored with a stray vertical angle
        // (anything saved between PR #171 and this fix) still paints ALONG
        // this bar rather than across it — without rewriting his storage.
        style={{ width: swatchWidth, height: swatchHeight, background: normalizeGradientAngle(value) || '#ffffff' }}
        onClick={() => setOpen((o) => !o)}
      />
      {open && createPortal(
        <div
          ref={popoverRef}
          className="color-gradient-popover"
          style={{ top: pos?.top ?? -9999, left: pos?.left ?? -9999, visibility: pos ? 'visible' : 'hidden' }}
          // This popover is its own document.body portal, a DOM sibling of
          // whatever panel it was opened from rather than a descendant —
          // an enclosing panel's own outside-click dismissal (e.g.
          // TopBarGroupButton) can't see this subtree in its containment
          // check and reads every tap inside here (the Solid/Gradient tab,
          // the hue/saturation area, the hex field) as an outside click,
          // closing the enclosing panel out from under the user. Stop the
          // mousedown here so it never reaches any ancestor's document
          // listener — this picker's own onDocDown below already excludes
          // clicks inside popoverRef, so nothing here relied on the event
          // still bubbling.
          onMouseDown={(e) => e.stopPropagation()}
        >
          <ReactGPicker
            // Same display-only canonicalization as the swatch: the widget
            // previews a value the way this app paints it. Feeding the
            // picker a prop never writes anything back — only onChange does.
            value={normalizeGradientAngle(value)}
            format="hex"
            showAlpha={false}
            // Linear only — no radial/linear mode toggle, no angle dial (his
            // ask: "I do not need the shape dialog for the gradient"). Every
            // gradient this app stores or produces is linear-gradient, so
            // hiding these costs nothing; showGradientPosition is the
            // radial-only position picker, pointless with mode hidden.
            showGradientMode={false}
            showGradientAngle={false}
            showGradientPosition={false}
            debounce
            debounceMS={200}
            solid
            gradient={gradient}
            popupWidth={280}
            defaultColors={defaultColors}
            onChange={(next: string) => onChange(normalizeGradientAngle(next))}
          />
        </div>,
        document.body,
      )}
    </>
  );
}
