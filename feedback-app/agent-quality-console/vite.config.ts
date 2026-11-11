import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig} from 'vite';

export default defineConfig(() => {
  if (process.env.VITE_AUTH_MODE === 'demo_admin') throw new Error('Standalone demo auth is retired. Build the existing google_iam app and use the Demo Admin application role.');
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      host: true,
      allowedHosts: true as const,
      cors: true,
      proxy: {
        '/api': {
          target: 'http://localhost:8001',
          changeOrigin: true,
        },
        '/healthz': {
          target: 'http://localhost:8001',
          changeOrigin: true,
        },
      },
      // HMR is disabled in AI Studio via DISABLE_HMR env var.
      // Do not modifyâfile watching is disabled to prevent flickering during agent edits.
      hmr: process.env.DISABLE_HMR !== 'true',
      // Disable file watching when DISABLE_HMR is true to save CPU during agent edits.
      watch: process.env.DISABLE_HMR === 'true' ? null : {},
    },
  };
});
