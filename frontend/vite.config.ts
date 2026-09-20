/// <reference types="vitest/config" />
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  },
  // Vitest runs component tests under Node/jsdom; without this, Vite resolves
  // Svelte's server-side (SSR) entry points and `mount()` throws
  // `lifecycle_function_unavailable` for every component render. Forcing the
  // `browser` condition only under Vitest keeps `vite build`/`vite dev` on
  // their normal SSR-aware resolution. See:
  // https://svelte.dev/docs/svelte/testing#resolve-conditions
  resolve: process.env.VITEST ? { conditions: ['browser'] } : undefined,
  test: {
    environment: 'jsdom',
    globals: false,
    include: ['src/**/*.{test,spec}.{js,ts,svelte}'],
    setupFiles: ['./vitest.setup.ts']
  }
});
