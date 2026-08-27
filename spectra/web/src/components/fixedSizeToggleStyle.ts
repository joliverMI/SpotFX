import type { CSSProperties } from 'react';

/** Shared shape for a small toggle button that cycles its own label/icon on
 * tap and must never change size while doing so (row-jump is the defect —
 * see PowerButton.tsx / ModeAvailabilityToggle.tsx). A fixed pixel width
 * alone does not guarantee that: without `white-space: nowrap` a bolder or
 * longer label can still wrap onto a second line at the same width and grow
 * the button (and the row) taller. Both toggles build their `style` object
 * by spreading this first. */
export function fixedSizeToggleStyle(width: number): CSSProperties {
  return {
    fontSize: 12,
    width,
    flexShrink: 0,
    textAlign: 'center',
    whiteSpace: 'nowrap',
  };
}
