/** ModeChip.tsx's tap-vs-hold decision logic, pulled out pure so it can be
 * driven without a DOM (this repo carries no DOM/component-rendering test
 * harness — AGENTS.md's own "Tests" section — scripts/check_mode_chip_hold.mjs
 * transpiles this module with esbuild and drives it directly, the same
 * precedent scripts/check_testbed_edge_knobs.mjs/check_house_summary.mjs
 * already use).
 *
 * The component binds `useHoldToConfirm` (progress ring, fires `onConfirm`
 * once a ~1s hold completes) to a `<Link to="/house">`. A short tap must
 * still navigate; a completed hold must toggle house lighting and must
 * NOT also navigate — both are one gesture on one element. These two
 * functions are the exact swallow/navigate decision the component's
 * onClick-capture (pointer path) and onKeyUp (keyboard path) apply; see
 * ModeChip.tsx's own header comment for why each path needs its own
 * handler (a completed hold always produces a trailing pointer `click`,
 * but `useHoldToConfirm`'s `onKeyDown` already `preventDefault()`s the
 * native anchor activation, so the keyboard short-press case has no
 * native click left to navigate it). */

/** Pointer path: a click follows EVERY completed gesture (hold or not) —
 * swallow it only when the hold just fired. */
export function shouldNavigateOnClick(holdJustFired: boolean): boolean {
  return !holdJustFired;
}

/** Keyboard path: only Enter/Space release the hold's key-hold gesture,
 * and only when the hold did NOT complete does the short press still
 * need to navigate (there is no native click left to do it for us). */
export function shouldNavigateOnKeyUp(key: string, holdJustFired: boolean): boolean {
  return (key === 'Enter' || key === ' ') && !holdJustFired;
}

/** The tooltip text — the base chip title (house/houseSummary.ts's own
 * `chipLine().title`) plus the hold instruction, in one place so the
 * wording can't drift between the component and this module's own tests. */
export function holdTooltip(baseTitle: string): string {
  return `${baseTitle} — hold to turn house lighting on/off`;
}

/** The toast line for a successful toggle. */
export function toggleResultMessage(enabled: boolean): string {
  return enabled ? 'House lighting turned on' : 'House lighting turned off';
}

/** The toast line for a refused/failed write — never a silent or a faked
 * state; the API's own error message is what's shown. */
export function toggleErrorMessage(detail: string): string {
  return `Could not change house lighting: ${detail}`;
}

export interface HouseSettingsPutResult {
  settings: { enabled: boolean };
  lighting?: { enabled?: boolean } | null;
}

/** `PUT /house/settings` only echoes a `lighting` key when `enabled`
 * actually changed (spectra/api/house.py's `put_settings`) — fall back to
 * the plain `settings.enabled` it always returns, never assume a change
 * that didn't happen landed. */
export function resolveEnabledFromResponse(res: HouseSettingsPutResult): boolean {
  return res.lighting?.enabled ?? res.settings.enabled;
}
