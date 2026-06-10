#!/usr/bin/env node
/**
 * Post-build bundle audit for web-console (guideai-1158).
 *
 * Scans dist/assets for JS/CSS sizes and parses dist/index.html for entry scripts
 * and modulepreload hints. Warns when oversized chunks or eager preload of deferred vendors.
 *
 * Usage:
 *   npm run build && node scripts/audit_bundle.mjs
 *   npm run audit:bundle   (expects an existing dist/ from a prior build)
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');
const DIST = join(ROOT, 'dist');
const INDEX = join(DIST, 'index.html');
const ASSETS = join(DIST, 'assets');

const WARN_JS_BYTES = 800 * 1024;
const WARN_CSS_BYTES = 150 * 1024;

function fmtKb(bytes) {
  return `${(bytes / 1024).toFixed(1)} KB`;
}

function main() {
  let errors = 0;

  try {
    readFileSync(INDEX);
  } catch {
    console.error(`audit_bundle: missing ${INDEX} — run npm run build first`); // gitleaks:allow
    process.exit(1);
  }

  const html = readFileSync(INDEX, 'utf8');
  const modulePreloads = [...html.matchAll(/<link[^>]+rel="modulepreload"[^>]+href="([^"]+)"/gi)].map((m) => m[1]);

  const deferredHeavyInPreload = modulePreloads.filter(
    (href) =>
      href.includes('whiteboard-vendor')
      || href.includes('markdown-vendor')
      || href.includes('WhiteboardCanvas'),
  );
  if (deferredHeavyInPreload.length > 0) {
    console.error(
      'audit_bundle: FAIL — modulepreload still references heavy deferred vendors:',
      deferredHeavyInPreload.join(', '),
    );
    errors += 1;
  }

  const stylesheets = [...html.matchAll(/<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"/gi)].map(
    (m) => m[1],
  );
  const eagerWhiteboardCss = stylesheets.filter(
    (href) => href.includes('whiteboard-vendor') || href.includes('WhiteboardCanvas'),
  );
  if (eagerWhiteboardCss.length > 0) {
    console.error(
      'audit_bundle: FAIL — index.html must not eagerly load whiteboard/tldraw CSS:',
      eagerWhiteboardCss.join(', '),
    );
    errors += 1;
  }

  const scripts = [...html.matchAll(/<script[^>]+src="([^"]+)"/gi)].map((m) => m[1]);
  console.log('audit_bundle: entry scripts:', scripts.join(', ') || '(none)');
  console.log('audit_bundle: modulepreload count:', modulePreloads.length);
  if (modulePreloads.length) {
    console.log('audit_bundle: modulepreloads:', modulePreloads.join(', '));
  }

  let files = [];
  try {
    files = readdirSync(ASSETS);
  } catch {
    console.warn(`audit_bundle: no ${ASSETS}`); // gitleaks:allow
    process.exit(errors ? 1 : 0);
  }

  const js = [];
  const css = [];
  for (const name of files) {
    const p = join(ASSETS, name);
    if (!statSync(p).isFile()) continue;
    const st = statSync(p);
    if (name.endsWith('.js')) js.push({ name, bytes: st.size });
    if (name.endsWith('.css')) css.push({ name, bytes: st.size });
  }

  js.sort((a, b) => b.bytes - a.bytes);
  css.sort((a, b) => b.bytes - a.bytes);

  console.log('\nTop JS chunks (raw size):');
  for (const row of js.slice(0, 15)) {
    const line = `  ${fmtKb(row.bytes).padStart(10)}  ${row.name}`;
    console.log(line);
    if (row.bytes >= WARN_JS_BYTES && row.name.includes('vendor')) {
      console.warn(`  ^ warn: ${row.name} >= ${fmtKb(WARN_JS_BYTES)} — ensure route-level lazy load only`);
    }
  }

  console.log('\nTop CSS chunks (raw size):');
  for (const row of css.slice(0, 10)) {
    console.log(`  ${fmtKb(row.bytes).padStart(10)}  ${row.name}`);
    if (row.bytes >= WARN_CSS_BYTES) {
      console.warn(`  ^ warn: ${row.name} >= ${fmtKb(WARN_CSS_BYTES)}`);
    }
  }

  const totalJs = js.reduce((s, x) => s + x.bytes, 0);
  const largest = js[0];
  console.log('\nSummary:');
  console.log(`  JS files: ${js.length}, total raw ${fmtKb(totalJs)}`);
  if (largest) {
    console.log(`  Largest JS chunk: ${largest.name} (${fmtKb(largest.bytes)})`);
  }

  process.exit(errors ? 1 : 0);
}

main();
