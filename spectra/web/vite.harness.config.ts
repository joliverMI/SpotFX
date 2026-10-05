import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({ plugins: [react()], root: 'harness', base: '/spectra/', build: { outDir: '../harness-dist', emptyOutDir: true } });
