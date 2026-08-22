/** Route → help topic for the context-sensitive global "?" (App.tsx NavBar).
 * His complaint, verbatim: pressing "?" always dumped him on the help
 * index with a search box, wherever he was in the app. This maps the
 * current route to the topic that page's own HelpLinks already open —
 * NOT a new mapping invented for this feature, just the existing page-level
 * topic each page's own in-page HelpLink already uses (see e.g.
 * ScenesPage.tsx's "Scenes <HelpLink topic="scenes-page" />").
 *
 * Route-level only, matching how this app's routes are actually shaped
 * (ScenesPage's tabs are local component state, not the URL) — the global
 * "?" lands on the right PAGE's help, not necessarily the right TAB within
 * it. Add an entry whenever a new top-level route is added; a route with no
 * entry here falls back to the bare help index rather than guessing at a
 * topic that might not fit. */
const ROUTE_TOPICS: [prefix: string, topic: string][] = [
  ['/scenes', 'scenes-page'],
  ['/colorsets', 'colorsets-groups'],
  ['/timeline', 'builder'],
  ['/feedback', 'feedback-page'],
  ['/review', 'review-page'],
  ['/timing', 'timing-debug'],
  ['/avsync', 'av-sync-page'],
  ['/debug', 'timing-debug'],
  ['/settings', 'settings-console'],
  ['/status', 'status-page'],
];

/** Returns the help topic id for the current route, or null if this route
 * has no known page-level topic (the "?" should fall back to the plain
 * index rather than guess). */
export function topicForPath(pathname: string): string | null {
  if (pathname === '/') return 'scenes-page';
  const hit = ROUTE_TOPICS.find(([prefix]) => pathname.startsWith(prefix));
  return hit ? hit[1] : null;
}
