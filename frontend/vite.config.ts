import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  // The repo root's single .env; inside the dev container compose passes it as the environment.
  envDir: path.resolve(__dirname, '..'),
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    watch: {
      usePolling: true,
    },
    host: true, // Docker needs the dev server on all interfaces.
    strictPort: true,
    port: 5173,
    allowedHosts: ['pumpkit.io', 'www.pumpkit.io'],
    proxy: {
      // compose.dev.yml points this at the backend service.
      '/api': process.env.API_PROXY_TARGET ?? 'http://localhost:8000',
    },
  },
});
