import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import type { Server } from 'http';
import path from 'path';
import { localXCallbackRelay } from './localXCallbackRelayPlugin';

/** Node ends a request whose body still arrives after 5 minutes: a slow 512 MB video upload. */
const longUploads: Plugin = {
  name: 'long-uploads',
  configureServer(server) {
    const http = server.httpServer as Server | null;
    if (http) http.requestTimeout = 0;
  },
};

export default defineConfig({
  plugins: [localXCallbackRelay(process.env), react(), longUploads],
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
    // Vite's own preflight answer would shadow the backend's open CORS on the MCP and OAuth paths.
    cors: false,
    port: 5173,
    allowedHosts: ['pumpkit.io', 'www.pumpkit.io'],
    proxy: {
      // compose.dev.yml points this at the backend service.
      '/api': process.env.API_PROXY_TARGET ?? 'http://localhost:8000',
      // OAuth discovery for MCP clients.
      '/.well-known': process.env.API_PROXY_TARGET ?? 'http://localhost:8000',
    },
  },
});
