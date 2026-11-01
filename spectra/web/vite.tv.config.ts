import { writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The TV app (data/tv-display-plan/plan.html PR 1.1): its own small build —
// the guest page's own build is the precedent this copies — served by
// SPECTRA directly at /spectra/tv/ (spectra/app.py), never through the main
// SPA's 1.89 MB bundle. `base` is absolute, matching the main app's own
// vite.config.ts: both the direct :8010 port and the :8000 proxy serve
// SPECTRA's own routes under the identical /spectra/* prefix (see
// spectra/app.py::_standalone's own docstring), so there is no "relative to
// where it's mounted" ambiguity to resolve at request time the way the
// probe page's hand-written fetches (../api/...) had to.
//   cd spectra/web && npx vite build --config vite.tv.config.ts
//
// BUILD_ID: a fresh id baked in at build time (Date.now(), not a content
// hash — this only has to differ across deploys, not describe the content),
// exposed to the app as `__TV_BUILD_ID__`. PR 1.2's feed carries the
// server's own build id (read off the manifest below) in its `hello`/
// `config` exchange; the shell's job here is only to know its OWN id so
// that comparison (feed.ts, on every `config` message) has something to
// compare against.
const BUILD_ID = String(Date.now());

// A plain text manifest beside the build, read by spectra/services/
// tv_feed.py (PR 1.2) so the SERVER can tell a connecting TV what the
// currently-deployed build actually is — the client's own
// `shouldReload()` (build.ts) decides whether that differs from what it
// is running. A .js bundle isn't a convenient thing for the Python side
// to inspect; a one-line text file is.
function writeBuildIdManifest() {
  return {
    name: 'tv-build-id-manifest',
    writeBundle() {
      writeFileSync(resolve(__dirname, 'tv-dist', 'build-id.txt'), BUILD_ID);
    },
  };
}

export default defineConfig({
  plugins: [react(), writeBuildIdManifest()], root: 'tv', base: '/spectra/tv/',
  publicDir: 'public',
  define: { __TV_BUILD_ID__: JSON.stringify(BUILD_ID) },
  build: { outDir: '../tv-dist', emptyOutDir: true, assetsInlineLimit: 0 },
});
