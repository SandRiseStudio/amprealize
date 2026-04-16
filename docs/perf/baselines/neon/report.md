# Perf baseline report: neon-2026-04-16T18-14-18Z

- base: `http://localhost:5173`
- context: `neon`
- runs: 5 (warm=false)
- project: `proj-b575d734aa37`
- board: `523b3a4f-4157-4fd1-b5e9-93437eca6009`
- started: 2026-04-16T18:14:18.771Z

## Client milestones (ms)

| journey | ready | total (includes wait) |
|---|---|---|
| cold_dashboard | — | p50=6569 p95=6633 min=4654 max=6952 (n=5) |
| cold_board | p50=5943 p95=6961 min=4368 max=7556 (n=5) | p50=17438 p95=18089 min=16195 max=20187 (n=5) |

## All client marks

### cold_dashboard

| mark | stats |
|---|---|
| dashboard.agent_panel_ready | p50=6066 p95=6162 min=4173 max=6466 (n=5) |
| dashboard.chrome_ready | p50=3497 p95=3571 min=2927 max=3671 (n=5) |

### cold_board

| mark | stats |
|---|---|
| board.first_items_page_ready | p50=5943 p95=6961 min=4368 max=7556 (n=5) |
| board.shell_ready | p50=6960 p95=7598 min=3516 max=9693 (n=5) |

## API call latencies observed by the browser (responseEnd, ms)

### cold_dashboard

| path | stats |
|---|---|
| /api/v1/projects/agents | p50=5796 p95=5887 min=3893 max=6187 (n=5) |
| /api/v1/projects | p50=3486 p95=3561 min=2918 max=3655 (n=5) |
| /api/v1/runs | p50=3309 p95=3653 min=2914 max=4883 (n=5) |
| /api/v1/capabilities | p50=3087 p95=4161 min=2555 max=4889 (n=10) |
| /api/v1/platform/runtime | p50=3084 p95=3651 min=2565 max=4148 (n=5) |
| /api/v1/modules | p50=2633 p95=3044 min=2577 max=3085 (n=5) |
| /api/v1/dashboard/stats | p50=2627 p95=3039 min=2550 max=3081 (n=5) |
| /api/v1/boards | p50=2470 p95=3327 min=2464 max=3327 (n=8) |
| /src/api/modules.ts | p50=14 p95=15 min=5 max=22 (n=5) |
| /src/api/client.ts | p50=11 p95=11 min=4 max=31 (n=5) |
| /src/api/platformRuntime.ts | p50=10 p95=15 min=7 max=17 (n=5) |
| /src/api/capabilities.ts | p50=8 p95=9 min=5 max=12 (n=5) |
| /src/api/dashboard.ts | p50=7 p95=7 min=2 max=11 (n=5) |
| /src/api/agentRegistry.ts | p50=7 p95=12 min=4 max=12 (n=5) |
| /src/api/executions.ts | p50=7 p95=10 min=5 max=15 (n=5) |
| /src/api/boards.ts | p50=7 p95=8 min=5 max=12 (n=5) |

### cold_board

| path | stats |
|---|---|
| /api/v1/capabilities | p50=11039 p95=14462 min=2617 max=14979 (n=23) |
| /api/v1/projects/agents | p50=11030 p95=11036 min=10660 max=11452 (n=5) |
| /api/v1/boards/523b3a4f-4157-4fd1-b5e9-93437eca6009 | p50=6909 p95=7553 min=3491 max=9596 (n=5) |
| /api/v1/boards | p50=6242 p95=6320 min=4293 max=7188 (n=5) |
| /api/v1/projects/proj-b575d734aa37 | p50=6208 p95=6911 min=4365 max=7555 (n=5) |
| /api/v1/projects | p50=4369 p95=6210 min=3253 max=6914 (n=5) |
| /api/v1/agents | p50=4366 p95=5868 min=3249 max=6209 (n=5) |
| /api/v1/logs/ingest | p50=4076 p95=6891 min=2189 max=7204 (n=10) |
| /api/v1/boards/523b3a4f-4157-4fd1-b5e9-93437eca6009/progress-rollups | p50=4047 p95=4465 min=3465 max=5238 (n=5) |
| /api/v1/platform/runtime | p50=3634 p95=4368 min=2643 max=5862 (n=5) |
| /api/v1/projects/proj-b575d734aa37/participants | p50=3264 p95=3934 min=3098 max=7074 (n=4) |
| /api/v1/modules | p50=3254 p95=3499 min=2619 max=3636 (n=5) |
| /api/v1/work-items | p50=1845 p95=5858 min=917 max=7551 (n=28) |
| /api/v1/executions | p50=1818 p95=2240 min=872 max=2286 (n=7) |
| /src/api/conversations.ts | p50=18 p95=19 min=17 max=20 (n=5) |
| /src/api/modules.ts | p50=13 p95=16 min=9 max=19 (n=5) |
| /src/api/platformRuntime.ts | p50=10 p95=13 min=7 max=13 (n=5) |
| /src/api/boards.ts | p50=8 p95=8 min=7 max=12 (n=5) |
| /src/api/capabilities.ts | p50=8 p95=10 min=6 max=13 (n=5) |
| /src/api/client.ts | p50=7 p95=13 min=3 max=17 (n=5) |
| /src/api/dashboard.ts | p50=7 p95=7 min=3 max=8 (n=5) |
| /src/api/agentRegistry.ts | p50=6 p95=6 min=2 max=7 (n=5) |
| /src/api/executions.ts | p50=6 p95=8 min=4 max=8 (n=5) |
| /src/api/projects.ts | p50=4 p95=4 min=3 max=8 (n=5) |

## Server perf log (from api container) grouped by endpoint

| endpoint | t_total_ms |
|---|---|
| boards.get | p50=895.5 p95=895.6 min=882.5 max=898.9 (n=5) |
| boards.list | p50=451.3 p95=459.9 min=443.3 max=461.8 (n=20) |
| dashboard.stats | p50=695.5 p95=763.4 min=612.7 max=1247.2 (n=5) |
| work_items.list | p50=611.3 p95=1130.6 min=593.3 max=1134.5 (n=33) |

## Raw files

- Playwright per-run JSON: `run-1.json` … `run-5.json`
- Full api container logs: `api.log`
- Filtered perf lines only: `api.perf.log`
