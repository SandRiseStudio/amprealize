#!/usr/bin/env node
/**
 * Merge per-run Playwright output + api.perf.log into a markdown report.
 *
 * Usage: node build-report.mjs --run-dir=./out/<run-id>
 */

import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const args = Object.fromEntries(
  process.argv
    .slice(2)
    .map((a) => a.replace(/^--/, ''))
    .map((a) => {
      const [k, v] = a.split('=');
      return [k, v ?? 'true'];
    }),
);

const runDir = resolve(args['run-dir']);
if (!runDir || !existsSync(runDir)) {
  console.error(`--run-dir=<path> is required and must exist`);
  process.exit(2);
}

const summary = JSON.parse(readFileSync(join(runDir, 'summary.json'), 'utf8'));
const runs = readdirSync(runDir)
  .filter((f) => /^run-\d+\.json$/.test(f))
  .sort()
  .map((f) => JSON.parse(readFileSync(join(runDir, f), 'utf8')));

function quantile(arr, q) {
  if (!arr.length) return null;
  const sorted = [...arr].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.floor(q * (sorted.length - 1))));
  return sorted[idx];
}

function stats(values) {
  const nums = values.filter((v) => typeof v === 'number' && Number.isFinite(v));
  if (!nums.length) return { n: 0 };
  const sorted = [...nums].sort((a, b) => a - b);
  const avg = nums.reduce((s, v) => s + v, 0) / nums.length;
  return {
    n: nums.length,
    min: sorted[0],
    p50: quantile(nums, 0.5),
    p95: quantile(nums, 0.95),
    max: sorted[sorted.length - 1],
    avg: Math.round(avg * 10) / 10,
  };
}

function fmt(stat) {
  if (!stat || stat.n === 0) return '—';
  return `p50=${stat.p50} p95=${stat.p95} min=${stat.min} max=${stat.max} (n=${stat.n})`;
}

const perJourney = {};
for (const run of runs) {
  for (const r of run.journeys ?? []) {
    const key = r.journey;
    perJourney[key] ??= {
      ready: [],
      total: [],
      marks: {},
      apiCalls: {},
    };
    const readyMark = r.marks?.find((m) => r.description?.includes('board')
      ? m.name === 'board.first_items_page_ready'
      : m.name === 'dashboard.chrome_ready',
    );
    if (readyMark?.context?.elapsed_ms != null) {
      perJourney[key].ready.push(readyMark.context.elapsed_ms);
    }
    if (typeof r.totalMs === 'number') {
      perJourney[key].total.push(r.totalMs);
    }
    for (const m of r.marks ?? []) {
      const elapsed = m?.context?.elapsed_ms;
      if (typeof elapsed === 'number') {
        perJourney[key].marks[m.name] ??= [];
        perJourney[key].marks[m.name].push(elapsed);
      }
    }
    for (const resp of r.responses ?? []) {
      const urlPath = (() => {
        try {
          return new URL(resp.url).pathname;
        } catch {
          return resp.url;
        }
      })();
      const dur =
        resp.timing && typeof resp.timing.responseEnd === 'number'
          ? Math.round(resp.timing.responseEnd)
          : null;
      if (dur == null) continue;
      perJourney[key].apiCalls[urlPath] ??= [];
      perJourney[key].apiCalls[urlPath].push(dur);
    }
  }
}

const perfLines = (() => {
  const path = join(runDir, 'api.perf.log');
  if (!existsSync(path)) return [];
  return readFileSync(path, 'utf8').split('\n').filter(Boolean);
})();

const parsedPerf = perfLines
  .map((line) => {
    const match = line.match(/perf\s+(.*)$/);
    if (!match) return null;
    const tags = {};
    for (const kv of match[1].split(/\s+/)) {
      const [k, v] = kv.split('=');
      if (k && v !== undefined) {
        const num = Number(v);
        tags[k] = Number.isFinite(num) && v !== '' ? num : v;
      }
    }
    return tags;
  })
  .filter((x) => x && x.endpoint && typeof x.t_total_ms === 'number');

const byEndpoint = {};
for (const row of parsedPerf) {
  byEndpoint[row.endpoint] ??= [];
  byEndpoint[row.endpoint].push(row.t_total_ms);
}

let md = '';
md += `# Perf baseline report: ${summary.runId}\n\n`;
md += `- base: \`${summary.base}\`\n`;
md += `- context: \`${summary.context}\`\n`;
md += `- runs: ${summary.runs} (warm=${summary.warm})\n`;
md += `- project: \`${summary.projectId ?? '—'}\`\n`;
md += `- board: \`${summary.boardId ?? '—'}\`\n`;
md += `- started: ${new Date(summary.startedAtEpoch).toISOString()}\n\n`;

md += `## Client milestones (ms)\n\n`;
md += `| journey | ready | total (includes wait) |\n|---|---|---|\n`;
for (const [jk, jv] of Object.entries(perJourney)) {
  md += `| ${jk} | ${fmt(stats(jv.ready))} | ${fmt(stats(jv.total))} |\n`;
}

md += `\n## All client marks\n\n`;
for (const [jk, jv] of Object.entries(perJourney)) {
  md += `### ${jk}\n\n| mark | stats |\n|---|---|\n`;
  for (const [name, arr] of Object.entries(jv.marks).sort()) {
    md += `| ${name} | ${fmt(stats(arr))} |\n`;
  }
  md += `\n`;
}

md += `## API call latencies observed by the browser (responseEnd, ms)\n\n`;
for (const [jk, jv] of Object.entries(perJourney)) {
  md += `### ${jk}\n\n| path | stats |\n|---|---|\n`;
  const rows = Object.entries(jv.apiCalls)
    .map(([p, arr]) => ({ path: p, s: stats(arr) }))
    .sort((a, b) => (b.s.p50 ?? 0) - (a.s.p50 ?? 0));
  for (const r of rows) {
    md += `| ${r.path} | ${fmt(r.s)} |\n`;
  }
  md += `\n`;
}

md += `## Server perf log (from api container) grouped by endpoint\n\n`;
if (!parsedPerf.length) {
  md += `_No \`perf ...\` lines found. Ensure \`AMPREALIZE_PERF_LOG=1\` and the api container was restarted._\n`;
} else {
  md += `| endpoint | t_total_ms |\n|---|---|\n`;
  for (const [ep, arr] of Object.entries(byEndpoint).sort()) {
    md += `| ${ep} | ${fmt(stats(arr))} |\n`;
  }
}

md += `\n## Raw files\n\n`;
md += `- Playwright per-run JSON: \`run-1.json\` … \`run-${summary.runs}.json\`\n`;
md += `- Full api container logs: \`api.log\`\n`;
md += `- Filtered perf lines only: \`api.perf.log\`\n`;

writeFileSync(join(runDir, 'report.md'), md);
console.log(`wrote ${join(runDir, 'report.md')}`);
