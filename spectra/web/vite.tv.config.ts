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
// exposed to the app as `__TV_BUILD_ID__`. Phase 1.2's feed carries the
// server's own build id in its `hello`/`config` exchange; the shell's job
// here is only to know its OWN id so that comparison has something to
// compare against once the feed exists.
const BUILD_ID = String(Date.now());

export default defineConfig({
  plugins: [react()], root: 'tv', base: '/spectra/tv/', publicDir: 'public',
  define: { __TV_BUILD_ID__: JSON.stringify(BUILD_ID) },
  build: { outDir: '../tv-dist', emptyOutDir: true, assetsInlineLimit: 0 },
});
