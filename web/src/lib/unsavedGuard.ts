/** Cross-page unsaved-changes guard. A page with unsaved edits registers a
 * message while they exist (null when clean / on unmount); NavBar consults it
 * before in-app navigation and beforeunload covers tab close/refresh. */
let message: string | null = null;

export function setUnsavedGuard(msg: string | null): void {
  message = msg;
}

/** true = safe to leave (nothing unsaved, or the user confirmed the discard).
 * Does not disarm the guard — the leaving page's unmount does that. */
export function confirmLeave(): boolean {
  return message == null || confirm(message);
}

window.addEventListener('beforeunload', (e) => {
  if (message != null) e.preventDefault();
});
