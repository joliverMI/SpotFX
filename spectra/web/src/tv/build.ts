/** THE TV APP'S OWN BUILD ID (data/tv-display-plan/plan.html PR 1.1,
 * "build-id reload": "The server sends its build id on connect; a TV
 * holding an old build reloads itself — nobody stands at the TV to press
 * refresh"). `__TV_BUILD_ID__` is baked in at build time by
 * vite.tv.config.ts's own `define` (a fresh id per build, not a content
 * hash — it only has to differ across deploys).
 *
 * `shouldReload` is the pure half of that mechanism, built now so the
 * feed (PR 1.2, which actually receives the server's build id in its
 * hello/config exchange) has something to call rather than inventing its
 * own comparison. An empty/missing server id never triggers a reload — a
 * feed that hasn't told us its build yet is not evidence of staleness. */
declare const __TV_BUILD_ID__: string;

export const TV_BUILD_ID: string = __TV_BUILD_ID__;

export function shouldReload(serverBuildId: string | null | undefined): boolean {
  return !!serverBuildId && serverBuildId !== TV_BUILD_ID;
}
