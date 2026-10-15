import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';
// Five pages: index.html mounts the top strip, live.html the Live view,
// songstrip.html the song-layout-plan's global SongStrip, hometimeline.html
// Home's editable copy + its audio-shape canvas (mocked backend, no real
// process — scripts/check_song_strip_fps.py / check_home_timeline_fps.py's
// own harnesses), and fidelity.html the WHOLE chrome + Home against the
// approved artifact's own song data (scripts/check_ui_fidelity.py — the
// design-fidelity gate; it is also the only harness page that renders the
// EMPTY state, which is what the live app used to unmount).
export default defineConfig({
  plugins: [react()], root: 'harness', base: '/spectra/',
  build: {
    outDir: '../harness-dist', emptyOutDir: true,
    rollupOptions: { input: {
      index: resolve(__dirname, 'harness/index.html'),
      live: resolve(__dirname, 'harness/live.html'),
      songstrip: resolve(__dirname, 'harness/songstrip.html'),
      hometimeline: resolve(__dirname, 'harness/hometimeline.html'),
      fidelity: resolve(__dirname, 'harness/fidelity.html'),
    } },
  },
});
