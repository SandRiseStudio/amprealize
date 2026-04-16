#!/usr/bin/env node
/**
 * One-time manual Google OAuth capture.
 *
 * Opens a headed Chromium window pointed at the web console. The human
 * completes the Google login, then presses Enter in this terminal. We
 * persist the full storage state (cookies + localStorage, incl. the
 * `amprealize_auth` key) to `storageState.json`, which the journey
 * runner reuses on every subsequent benchmark.
 *
 * Re-run whenever the saved session expires.
 *
 * Usage:
 *   node auth-login.mjs [--base=http://localhost:5173] [--out=./storageState.json]
 */

import { chromium } from 'playwright';
import readline from 'node:readline';
import { writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const args = Object.fromEntries(
  process.argv
    .slice(2)
    .map((a) => a.replace(/^--/, ''))
    .map((a) => {
      const [k, v] = a.split('=');
      return [k, v ?? 'true'];
    }),
);

const BASE = args.base ?? process.env.AMPREALIZE_CONSOLE_URL ?? 'http://localhost:5173';
const OUT = resolve(args.out ?? './storageState.json');

function waitForEnter(prompt) {
  return new Promise((resolvePromise) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    rl.question(prompt, () => {
      rl.close();
      resolvePromise();
    });
  });
}

(async () => {
  console.log(`Opening ${BASE}`);
  const browser = await chromium.launch({ headless: false, args: ['--disable-blink-features=AutomationControlled'] });
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  console.log('\nSign in with Google in the opened window.');
  console.log('Once you are back on the Amprealize dashboard, press Enter here.\n');
  await waitForEnter('Press Enter after login is complete... ');

  const state = await context.storageState();
  writeFileSync(OUT, JSON.stringify(state, null, 2));
  const origins = state.origins?.length ?? 0;
  const cookies = state.cookies?.length ?? 0;
  console.log(`Saved storage state to ${OUT} (origins=${origins}, cookies=${cookies}).`);

  await browser.close();
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
