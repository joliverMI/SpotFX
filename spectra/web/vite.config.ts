import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// SPECTRA is served at /spectra/ (mounted sub-app pre-S3; its own process
// after). Dev proxies both API namespaces to the shared local process.
export default defineConfig({
  plugins: [react()],
  base: '/spectra/',
  server: {
    proxy: {
      '/spectra/api': 'http://localhost:8000',
      '/api': 'http://localhost:8000',
      // The Timeline page listens on the SpotFX app's WebSocket (playhead,
      // trigger_fired, offset messages) — same origin in production.
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
  build: { outDir: 'dist' },
});
