import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';
// Two pages: index.html mounts the top strip, live.html the Live view.
export default defineConfig({
  plugins: [react()], root: 'harness', base: '/spectra/',
  build: {
    outDir: '../harness-dist', emptyOutDir: true,
    rollupOptions: { input: { index: resolve(__dirname, 'harness/index.html'), live: resolve(__dirname, 'harness/live.html') } },
  },
});
