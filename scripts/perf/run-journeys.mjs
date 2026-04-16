#!/usr/bin/env node
/**
 * Play a set of cold/warm journeys against the web console and record:
 *  - navigation timing
 *  - all `window.__perfMarks` entries the app emits (`perfMark(...)`)
 *  - every HTTP response we observe, with per-phase timings
 *
 * One JSON file per run is written under `./out/<run-id>/run-<n>.json`, and
 * a final summary index `./out/<run-id>/summary.json` lists the run inputs
 * so `bench.sh` can pair them up with server-side logs captured at the same
 * wall-clock window.
 *
 * Usage:
 *   node run-journeys.mjs \
 *     --base=http://localhost:5173 \
 *     --project=<project-id> \
 *     --board=<board-id> \
 *     --runs=5 \
 *     --context=neon \
 *     [--storage=./storageState.json] \
 *     [--warm]           # include an extra warm sample per cold sample
 *     [--run-id=<slug>]  # defaults to <context>-<ts>
 *     [--timeout-ms=45000]
 */

import { chromium } from 'playwright';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';

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
const STORAGE = resolve(args.storage ?? './storageState.json');
const RUNS = Number(args.runs ?? 5);
const WARM = args.warm === 'true';
const TIMEOUT_MS = Number(args['timeout-ms'] ?? 45000);
const CONTEXT_NAME = args.context ?? 'unknown';
const PROJECT_ID = args.project ?? null;
const BOARD_ID = args.board ?? null;

// Perf A/B levers applied via localStorage on the context before navigation.
// Kept here so the same harness can compare on/off without code edits.
//   --disable-raze      → localStorage['amprealize.razeIngest'] = 'off'
//   --hydrate-sleep=0   → localStorage['amprealize.hydrateSleepMs'] = '0'
const DISABLE_RAZE = args['disable-raze'] === 'true';
const HYDRATE_SLEEP_MS = args['hydrate-sleep'] ?? null;

const ts = new Date().toISOString().replace(/[:.]/g, '-');
const RUN_ID = args['run-id'] ?? `${CONTEXT_NAME}-${ts}`;
const OUT_DIR = resolve(`./out/${RUN_ID}`);

if (!existsSync(STORAGE)) {
  console.error(`Auth storage state not found at ${STORAGE}. Run \`node auth-login.mjs\` first.`);
  process.exit(2);
}

mkdirSync(OUT_DIR, { recursive: true });

const JOURNEYS = [
  {
    id: 'cold_dashboard',
    description: 'Cold open of /; wait for dashboard.chrome_ready',
    path: '/',
    waitFor: ['dashboard.chrome_ready'],
    optionalWaitFor: ['dashboard.agent_panel_ready'],
  },
];
if (PROJECT_ID && BOARD_ID) {
  JOURNEYS.push({
    id: 'cold_board',
    description: 'Cold open of board page; wait for first items page then full hydration',
    path: `/projects/${PROJECT_ID}/boards/${BOARD_ID}`,
    waitFor: ['board.shell_ready', 'board.first_items_page_ready'],
    optionalWaitFor: ['board.full_hydration_ready'],
  });
}

async function runJourney({ browser, journey, warm }) {
  const context = await browser.newContext({ storageState: STORAGE });
  // Apply A/B levers on the context's origin before any page script runs.
  await context.addInitScript(
    ({ disableRaze, hydrateSleepMs }) => {
      try {
        if (disableRaze) {
          window.localStorage.setItem('amprealize.razeIngest', 'off');
        }
        if (hydrateSleepMs !== null && hydrateSleepMs !== undefined) {
          window.localStorage.setItem('amprealize.hydrateSleepMs', String(hydrateSleepMs));
        }
      } catch {
        /* ignore */
      }
    },
    { disableRaze: DISABLE_RAZE, hydrateSleepMs: HYDRATE_SLEEP_MS },
  );
  const responses = [];
  const pageErrors = [];
  const consoleErrors = [];
  const page = await context.newPage();

  page.on('response', (response) => {
    try {
      const request = response.request();
      const url = response.url();
      if (!url.includes('/api/') && !url.includes('/v1/')) return;
      const timing = request.timing ? request.timing() : null;
      responses.push({
        url,
        status: response.status(),
        method: request.method(),
        fromCache: response.fromServiceWorker?.() ?? false,
        timing,
      });
    } catch {
      // ignore response inspection errors
    }
  });
  page.on('pageerror', (err) => pageErrors.push(String(err?.message ?? err)));
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 300));
  });

  const target = `${BASE}${journey.path}`;
  const startedAtEpoch = Date.now();
  const t0 = performance.now();
  let errorMsg = null;

  const snapshot = async () => {
    const marks = await page.evaluate(() => window.__perfMarks ?? []).catch(() => []);
    const navTiming = await page
      .evaluate(() => {
        const entries = performance.getEntriesByType('navigation');
        const nav = entries[0];
        return nav
          ? {
              startTime: nav.startTime,
              domInteractive: nav.domInteractive,
              domContentLoadedEventEnd: nav.domContentLoadedEventEnd,
              loadEventEnd: nav.loadEventEnd,
              responseEnd: nav.responseEnd,
              transferSize: nav.transferSize,
              encodedBodySize: nav.encodedBodySize,
              decodedBodySize: nav.decodedBodySize,
            }
          : null;
      })
      .catch(() => null);
    const finalUrl = page.url();
    return { marks, navTiming, finalUrl };
  };

  try {
    await page.goto(target, { waitUntil: 'domcontentloaded', timeout: TIMEOUT_MS });
    for (const name of journey.waitFor) {
      await page.waitForFunction(
        (markName) => (window.__perfMarks ?? []).some((m) => m.name === markName),
        name,
        { timeout: TIMEOUT_MS },
      );
    }
    for (const name of journey.optionalWaitFor ?? []) {
      try {
        await page.waitForFunction(
          (markName) => (window.__perfMarks ?? []).some((m) => m.name === markName),
          name,
          { timeout: 10000 },
        );
      } catch {
        // optional; proceed
      }
    }
  } catch (err) {
    errorMsg = String(err?.message ?? err);
  }

  const { marks, navTiming, finalUrl } = await snapshot();
  const totalMs = Math.round(performance.now() - t0);

  let warmResult = null;
  if (warm) {
    // Navigate somewhere neutral, then back -> measures warm-cache revisit.
    const warmT0 = performance.now();
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: TIMEOUT_MS });
    await page.goto(target, { waitUntil: 'domcontentloaded', timeout: TIMEOUT_MS });
    for (const name of journey.waitFor) {
      await page.waitForFunction(
        (markName) => (window.__perfMarks ?? []).some((m) => m.name === markName && m.__warm === true),
        name,
        { timeout: TIMEOUT_MS },
      ).catch(() => {});
    }
    warmResult = { totalMs: Math.round(performance.now() - warmT0) };
  }

  await context.close();

  return {
    journey: journey.id,
    description: journey.description,
    target,
    finalUrl,
    startedAtEpoch,
    totalMs,
    marks,
    navTiming,
    responses,
    warmResult,
    pageErrors,
    consoleErrors,
    error: errorMsg,
  };
}

(async () => {
  console.log(`Run ${RUN_ID} against ${BASE} (context=${CONTEXT_NAME}, runs=${RUNS}, warm=${WARM})`);
  const browser = await chromium.launch({ headless: true });
  const index = {
    runId: RUN_ID,
    base: BASE,
    context: CONTEXT_NAME,
    runs: RUNS,
    warm: WARM,
    projectId: PROJECT_ID,
    boardId: BOARD_ID,
    startedAtEpoch: Date.now(),
    journeys: JOURNEYS.map((j) => j.id),
    files: [],
  };

  for (let i = 1; i <= RUNS; i++) {
    const runRecord = { run: i, journeys: [] };
    for (const journey of JOURNEYS) {
      let result;
      try {
        result = await runJourney({ browser, journey, warm: WARM });
      } catch (err) {
        result = {
          journey: journey.id,
          error: String(err?.message ?? err),
          marks: [],
          responses: [],
        };
      }
      runRecord.journeys.push(result);
      if (result.error) {
        console.error(
          `  run ${i}/${RUNS} ${journey.id}: ERROR ${result.error} finalUrl=${result.finalUrl ?? '?'}`,
        );
      } else {
        const readyMark = (result.marks ?? []).find((m) => journey.waitFor.includes(m.name));
        const elapsed = readyMark?.context?.elapsed_ms ?? result.totalMs;
        console.log(`  run ${i}/${RUNS} ${journey.id}: ready_ms=${elapsed} total_ms=${result.totalMs}`);
      }
    }
    const file = join(OUT_DIR, `run-${i}.json`);
    writeFileSync(file, JSON.stringify(runRecord, null, 2));
    index.files.push(file);
  }

  index.finishedAtEpoch = Date.now();
  writeFileSync(join(OUT_DIR, 'summary.json'), JSON.stringify(index, null, 2));
  await browser.close();
  console.log(`\nResults in ${OUT_DIR}`);
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
