import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
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
  },
});
