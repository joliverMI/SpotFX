/** Deep-link plumbing for the circled-"?" buttons.
 *
 * A "?" click must jump to (and flash) its Help section EVERY time, including
 * a re-click or a double-click on the same topic. The URL alone can't express
 * that: clicking the same "?" twice produces the identical `?topic=<id>`, so
 * nothing in the router state changes and the Help page's effect never
 * re-fires. So every click carries a fresh NONCE (`hl=`) that makes each
 * navigation distinct.
 *
 * The nonce is deliberately NOT regenerated on render — only on click — so
 * typing in the Help page's search box (which rewrites the query string while
 * preserving the other params) can never re-trigger a flash. */

export const HELP_NONCE_PARAM = 'hl';

let counter = 0;

/** The plain, shareable address of a topic (the anchor's href). */
export function helpTopicHref(topic?: string): string {
  return topic ? `/help?topic=${encodeURIComponent(topic)}` : '/help';
}

/** The address to actually navigate to on a click: same, plus a fresh nonce. */
export function helpTopicNavTo(topic?: string): string {
  const nonce = `${Date.now().toString(36)}${(counter = (counter + 1) % 1000)}`;
  return topic
    ? `${helpTopicHref(topic)}&${HELP_NONCE_PARAM}=${nonce}`
    : `/help?${HELP_NONCE_PARAM}=${nonce}`;
}
