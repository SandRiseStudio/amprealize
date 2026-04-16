/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

function normalizeModuleId(id: string): string {
  return id.replace(/\\/g, '/');
}

function manualChunkForId(id: string): string | undefined {
  const normalized = normalizeModuleId(id);

  if (
    normalized.includes('/node_modules/tldraw/')
    || normalized.includes('/node_modules/@tldraw/')
    || normalized.includes('/node_modules/yjs/')
    || normalized.includes('/node_modules/y-protocols/')
    || normalized.includes('/node_modules/lib0/')
  ) {
    return 'whiteboard-vendor';
  }

  if (
    normalized.includes('/node_modules/react-markdown/')
    || normalized.includes('/node_modules/remark-gfm/')
    || normalized.includes('/node_modules/unified/')
    || normalized.includes('/node_modules/remark-')
    || normalized.includes('/node_modules/mdast-')
    || normalized.includes('/node_modules/micromark')
    || normalized.includes('/node_modules/hast-')
    || normalized.includes('/node_modules/unist-')
  ) {
    return 'markdown-vendor';
  }

  if (
    normalized.includes('/packages/collab-client/')
    || normalized.includes('/src/vendor/collab-client-dist/')
  ) {
    return 'collab-vendor';
  }

  return undefined;
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 2000, // whiteboard-vendor is ~1.8 MB but fully deferred + prefetch-aware
    rollupOptions: {
      output: {
        manualChunks(id) {
          return manualChunkForId(id);
        },
      },
    },
  },
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
          };
        }
        if (existsSync(distEntry)) {
          return {
            '@amprealize/collab-client': distEntry,
          };
        }
      }

      if (existsSync(localFallback)) {
        return {
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
    environment: 'happy-dom',
    setupFiles: './src/test/setup.ts',
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
