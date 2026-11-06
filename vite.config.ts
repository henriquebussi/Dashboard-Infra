import path from 'node:path';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, loadEnv } from 'vite';

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');

  // Backend origin for the dev-proxy. Falls back to localhost:8000.
  const apiOrigin = env.VITE_API_BASE_URL || 'http://localhost:8000';

  return {
    plugins: [react(), tailwindcss()],

    resolve: {
      alias: {
        '@': path.resolve(import.meta.dirname, 'src'),
      },
    },

    server: {
      port: 5173,
      proxy: {
        // Proxy every /api call to the FastAPI backend during development.
        // This avoids CORS issues and matches the same-origin assumption
        // in src/lib/api.ts (VITE_API_BASE_URL left empty).
        '/api': {
          target: apiOrigin,
          changeOrigin: true,
          secure: false,
          // Rewrite is a no-op here (paths already start with /api).
          rewrite: (p) => p,
        },
      },
    },
  };
});
