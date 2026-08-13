/** Cross-page unsaved-changes guard (the UI-hardening answer, carried into
 * SPECTRA). A page with unsaved edits registers a message while they exist;
 * NavBar consults it before in-app navigation and beforeunload covers tab
 * close/refresh. */
let message: string | null = null;

export function setUnsavedGuard(msg: string | null): void {
  message = msg;
}

/** true = safe to leave (nothing unsaved, or the user confirmed). */
export function confirmLeave(): boolean {
  return message == null || confirm(message);
}

window.addEventListener('beforeunload', (e) => {
  if (message != null) e.preventDefault();
});
