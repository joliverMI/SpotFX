import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The Jukebox's guest page (src/guest/, data/jukebox-plan/report.md §7):
// its own small build, served by its own process (jukebox_guest/, :8020) at
// the root of the guests' link — never part of SPECTRA's bundle, and nothing
// of SPECTRA's ships in it.
//   cd spectra/web && npx vite build --config vite.guest.config.ts
export default defineConfig({
  plugins: [react()], root: 'guest', base: '/', publicDir: 'public',
  build: { outDir: '../guest-dist', emptyOutDir: true, assetsInlineLimit: 0 },
});
