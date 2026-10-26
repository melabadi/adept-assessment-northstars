import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// The API serves the built UI from its wwwroot folder. During `npm run dev`, Vite proxies
// API, health, OpenAPI, and Easy Auth routes to a locally running API.
const apiTarget = process.env.REQUESTHUB_API_URL ?? 'http://localhost:5080';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': apiTarget,
      '/health': apiTarget,
      '/openapi': apiTarget,
      '/.auth': apiTarget,
    },
  },
  build: {
    outDir: '../src/RequestHub.Api/wwwroot',
    emptyOutDir: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
    restoreMocks: true,
    unstubGlobals: true,
  },
});
