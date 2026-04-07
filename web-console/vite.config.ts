/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: ((): Record<string, string> => {
      const localFallback = resolve(__dirname, 'src/vendor/collab-client-dist/index.js');
      const candidates = [
        process.env.AMPREALIZE_REPO_ROOT,
        resolve(__dirname, '..'),
        resolve(__dirname),
      ].filter(Boolean) as string[];

      for (const base of candidates) {
        const srcEntry = resolve(base, 'packages/collab-client/src/index.ts');
        const distEntry = resolve(base, 'packages/collab-client/dist/index.js');
        if (existsSync(srcEntry)) {
          return {
            '@amprealize/collab-client': srcEntry,
            '@amprealize/collab-client': srcEntry,
          };
        }
        if (existsSync(distEntry)) {
          return {
            '@amprealize/collab-client': distEntry,
            '@amprealize/collab-client': distEntry,
          };
        }
      }

      if (existsSync(localFallback)) {
        return {
          '@amprealize/collab-client': localFallback,
          '@amprealize/collab-client': localFallback,
        };
      }

      return {};
    })(),
    // Ensure collab-client's optional peer dep on react resolves to
    // the web-console copy rather than a Vite optional-peer-dep stub.
    dedupe: ['react', 'react-dom'],
  },
  server: {
    fs: {
      allow: [
        ...(process.env.AMPREALIZE_REPO_ROOT ? [resolve(process.env.AMPREALIZE_REPO_ROOT)] : []),
        resolve(__dirname, '..'),
        resolve(__dirname),
      ],
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
