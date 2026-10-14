/** The kiosk view's sizing — ONE place, easy to change (song-layout-plan,
 * data/ui-layout-plan/report.md's kiosk section + River's 2026-10-14
 * inbox reply). The wall kiosk is a Raspberry Pi 7in touchscreen, 800x480
 * landscape, scale 1.0, Chromium at 100% zoom, touch-only (on-screen
 * keyboard, no mouse) — Home Assistant's own dashboard chrome (~56px
 * header) eats part of that, leaving ~800x424 usable for SPECTRA's own
 * content. These are CSS custom properties (`--kiosk-*`), not hardcoded
 * pixel values sprinkled through kiosk.css, so a real measurement from
 * the deployed Pi later is a one-line change here, not a grep-and-replace.
 *
 * Audio shape: at this size the plan prioritises bar + timeline + quick
 * runs — the audio shape may compact or be dropped if it cannot fit
 * legibly (River's own words); `KIOSK_SHOW_AUDIO_SHAPE` is the one
 * switch for that, read by home/HomeTimeline.tsx's `compact` prop. */
export const KIOSK_WIDTH_PX = 800;
export const KIOSK_HEIGHT_PX = 480;
export const HA_HEADER_HEIGHT_PX = 56;
export const KIOSK_USABLE_HEIGHT_PX = KIOSK_HEIGHT_PX - HA_HEADER_HEIGHT_PX;

/** Below this, the audio shape is dropped rather than squeezed illegible. */
export const KIOSK_SHOW_AUDIO_SHAPE = false;

/** Minimum touch target (song-layout-plan §10: 38-40px under
 * `pointer: coarse`) — the kiosk is touch-only, so this always applies
 * there regardless of the shared app's own pointer-media breakpoints. */
export const KIOSK_TOUCH_TARGET_PX = 44;

export function applyKioskSizeVars(el: HTMLElement): void {
  el.style.setProperty('--kiosk-width', `${KIOSK_WIDTH_PX}px`);
  el.style.setProperty('--kiosk-usable-height', `${KIOSK_USABLE_HEIGHT_PX}px`);
  el.style.setProperty('--kiosk-touch-target', `${KIOSK_TOUCH_TARGET_PX}px`);
}

export function isKioskRequested(search: string): boolean {
  return new URLSearchParams(search).get('kiosk') === '1';
}
