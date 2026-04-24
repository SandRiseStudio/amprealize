/**
 * Cloudflare Worker: CORS Preflight Handler
 *
 * Deployed on route: api.amprealize.ai/*
 *
 * Problem this solves:
 *   Cloudflare's DDoS L7 ruleset was issuing browser challenges (managed
 *   challenges / JS challenges) on CORS preflight OPTIONS requests that
 *   carried browser-specific headers (Sec-Fetch-Mode: cors,
 *   Sec-Fetch-Site: cross-site, browser User-Agent). Because OPTIONS
 *   responses have no body, Cloudflare's challenge injection fails silently
 *   and returns HTTP 520 to the browser. The browser then aborts the
 *   cross-origin fetch with "Failed to fetch", breaking Google sign-in and
 *   any other cross-origin API call.
 *
 * Solution:
 *   This Worker intercepts all traffic for api.amprealize.ai. OPTIONS
 *   requests are answered immediately at the Cloudflare edge with a 204 +
 *   correct CORS headers — before any WAF/DDoS layer runs. All other
 *   methods are forwarded to the origin unchanged, with CORS headers added
 *   to the response for allowed origins.
 *
 * Deployment:
 *   Managed via Cloudflare API. See infra/cloudflare/deploy-worker.sh for
 *   the deploy script.
 *
 *   Worker name:  amprealize-api-cors
 *   Zone:         amprealize.ai
 *   Route:        api.amprealize.ai/*
 */

const ALLOWED_ORIGINS = [
  "https://app.amprealize.ai",
  "https://amprealize.ai",
  "http://localhost:3000",
  "http://localhost:5173",
];

const CORS_HEADERS = {
  "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
  "Access-Control-Allow-Headers":
    "Authorization, Content-Type, X-Requested-With, X-Tenant-Id",
  "Access-Control-Allow-Credentials": "true",
  "Access-Control-Max-Age": "86400",
};

export default {
  async fetch(request) {
    const origin = request.headers.get("Origin") || "";
    const isAllowedOrigin = ALLOWED_ORIGINS.includes(origin);

    // Handle CORS preflight at the Cloudflare edge.
    // This bypasses WAF/DDoS challenge mechanisms that return 520 on OPTIONS.
    if (request.method === "OPTIONS") {
      const headers = { ...CORS_HEADERS };
      if (isAllowedOrigin) {
        headers["Access-Control-Allow-Origin"] = origin;
        headers["Vary"] = "Origin";
      }
      return new Response(null, { status: 204, headers });
    }

    // Forward all other requests to the origin.
    const response = await fetch(request);
    const newHeaders = new Headers(response.headers);

    if (isAllowedOrigin) {
      newHeaders.set("Access-Control-Allow-Origin", origin);
      newHeaders.set("Access-Control-Allow-Credentials", "true");
      newHeaders.set("Vary", "Origin");
    }

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: newHeaders,
    });
  },
};
