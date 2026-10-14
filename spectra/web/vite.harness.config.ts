import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';
// Three pages: index.html mounts the top strip, live.html the Live view,
// songstrip.html the song-layout-plan's global SongStrip (mocked backend,
// no real process — scripts/check_song_strip_fps.py's own harness).
export default defineConfig({
  plugins: [react()], root: 'harness', base: '/spectra/',
  build: {
    outDir: '../harness-dist', emptyOutDir: true,
    rollupOptions: { input: {
      index: resolve(__dirname, 'harness/index.html'),
      live: resolve(__dirname, 'harness/live.html'),
      songstrip: resolve(__dirname, 'harness/songstrip.html'),
    } },
  },
});
