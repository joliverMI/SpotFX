/** Cross-scene flare-kind clipboard — localStorage-backed (survives reload,
 * shared across tabs), same safe try/catch shape as unsavedGuard.ts /
 * useSticky.ts. Copy captures the kind's OWN declaration only (type / jump /
 * params / gain / hold_ms) — never which band(s) attached it, since a band
 * attachment is a per-scene, per-class relationship that has no counterpart
 * in an arbitrary target scene. Pasting always creates a fresh, independent
 * FlareKind entry (see scenes/tabs/flareKindOps.ts's pasteKind) — a flare
 * kind's identity is its name WITHIN one scene's flare_kinds list (models/
 * scene.py SceneV2.flare_kinds), so there is no shared object to reference
 * across scenes; this is a genuine port, not a live link back to the
 * original. Editing or deleting the source after a paste never touches the
 * pasted copy, and vice versa. */
import type { FlareKind } from '../types';

const KEY = 'spectra.flareKindClipboard.v1';

export interface FlareClipboardEntry {
  kind: FlareKind;
  sourceSceneName: string;
  copiedAt: number;
}

export function copyFlareKind(kind: FlareKind, sourceSceneName: string, now: number): void {
  try {
    const entry: FlareClipboardEntry = { kind, sourceSceneName, copiedAt: now };
    localStorage.setItem(KEY, JSON.stringify(entry));
  } catch {
    /* quota/private mode — non-fatal, paste button just won't appear */
  }
}

export function readFlareClipboard(): FlareClipboardEntry | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw === null ? null : (JSON.parse(raw) as FlareClipboardEntry);
  } catch {
    return null;
  }
}

export function clearFlareClipboard(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* non-fatal */
  }
}
