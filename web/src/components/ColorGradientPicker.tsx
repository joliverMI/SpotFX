/** The one colour-choosing surface for SpotFX — wraps LedFX's own picker
 * component (`react-gcolor-picker`, MIT, the exact package LedFX's frontend
 * imports for every colour/gradient field) rather than a lookalike. Every
 * solid colour and every gradient in the app goes through this: same
 * widget, same solid/gradient tabs, same output grammar. */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import ReactGPicker from 'react-gcolor-picker';

/** LedFX's own gradient panel can emit a gradient with no leading angle
 * (`linear-gradient(#000 0%, #fff 100%)`). Both the vendored LedFX backend
 * (`ledfx/color.py`) and SpotFX's own `services/gradient_interpolation.py`
 * treat everything before the first comma as the angle, so an angle-less
 * value would silently swallow its first stop colour. Force one explicit
 * angle before it ever reaches state or the network — the same guard
 * LedFX's own frontend applies for the same reason. */
export function normalizeGradientAngle(value: string): string {
  if (!value || !value.includes('linear-gradient')) return value;
  if (/linear-gradient\s*\(\s*-?\d+deg/i.test(value)) return value;
  return value.replace(/linear-gradient\s*\(/i, 'linear-gradient(90deg, ');
}

export interface ColorGradientPickerProps {
  value: string;
  onChange: (value: string) => void;
  gradient?: boolean;
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
        style={{ width: swatchWidth, height: swatchHeight, background: value || '#ffffff' }}
        onClick={() => setOpen((o) => !o)}
      />
      {open && createPortal(
        <div
          ref={popoverRef}
          className="color-gradient-popover"
          style={{ top: pos?.top ?? -9999, left: pos?.left ?? -9999, visibility: pos ? 'visible' : 'hidden' }}
        >
          <ReactGPicker
            value={value}
            format="hex"
            showAlpha={false}
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
