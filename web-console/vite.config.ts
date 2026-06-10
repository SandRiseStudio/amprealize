/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { flattenWhiteboardVendorCssPlugin } from './vite-plugin-flatten-whiteboard-css';

function normalizeModuleId(id: string): string {
  return id.replace(/\\/g, '/');
}

function manualChunkForId(id: string): string | undefined {
  const normalized = normalizeModuleId(id);

  // Own chunk for React so tldraw never "owns" shared React copies in a route-only async chunk
  // (avoids the entry graph importing tldraw's chunk for re-exports).
  if (/\/node_modules\/(react|react-dom|scheduler)(\/|$)/.test(normalized)) {
    return 'react-vendor';
  }

  // @tanstack/react-virtual is used by BoardPage (virtualizer hook) and also by tldraw; if it lives in
  // whiteboard-vendor, Rollup puts shared helpers there and the entry chunk imports tldraw CSS + JS.
  if (
    normalized.includes('/node_modules/@tanstack/react-virtual/')
    || normalized.includes('/node_modules/@tanstack/virtual-core/')
  ) {
    return 'tanstack-virtual-vendor';
  }

  // tldraw / @tldraw are only reachable from lazy WhiteboardCanvas — do NOT manual-chunk them into
  // `whiteboard-vendor`. A dedicated vendor chunk caused Rolldown/Vite to attach shared CSS/runtime
  // wiring to that chunk so index.html + index.js eagerly imported tldraw CSS/bytes on every route.

  if (
    normalized.includes('/node_modules/yjs/')
    || normalized.includes('/node_modules/y-protocols/')
    || normalized.includes('/node_modules/lib0/')
  ) {
    return 'yjs-vendor';
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
  plugins: [react(), flattenWhiteboardVendorCssPlugin()],
  build: {
    chunkSizeWarningLimit: 2000, // lazy WhiteboardCanvas chunk includes tldraw (~1.6 MB deferred until route)
    // Do not modulepreload heavy route-owned vendors on first HTML paint — they load on navigation.
    // (guideai-1158: dashboard usability before whiteboard/markdown chunks.)
    modulePreload: {
      resolveDependencies(_filename, deps) {
        return deps.filter(
          (dep) =>
            !dep.includes('whiteboard-vendor')
            && !dep.includes('markdown-vendor')
            && !dep.includes('WhiteboardCanvas'),
        );
      },
    },
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
