#!/usr/bin/env bash
# Deploy the CORS preflight Worker to Cloudflare.
#
# Usage:
#   CLOUDFLARE_API_TOKEN=<token> ./deploy-worker.sh
#
# The token needs Workers Scripts:Edit + Workers Routes:Edit permissions.
# Alternatively, run via wrangler:
#   cd workers/cors-preflight && npx wrangler deploy

set -euo pipefail

ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:?Error: CLOUDFLARE_ACCOUNT_ID is not set.}"
ZONE_ID="${CLOUDFLARE_ZONE_ID:?Error: CLOUDFLARE_ZONE_ID is not set.}"
WORKER_NAME="amprealize-api-cors"
SCRIPT_PATH="$(dirname "$0")/workers/cors-preflight/worker.js"

: "${CLOUDFLARE_API_TOKEN:?Error: CLOUDFLARE_API_TOKEN is not set.}"

METADATA=$(cat <<EOF
{"main_module":"worker.js","compatibility_date":"2024-09-23"}
EOF
)

METADATA_FILE=$(mktemp)
echo "$METADATA" > "$METADATA_FILE"
trap "rm -f $METADATA_FILE" EXIT

echo "Deploying Worker '$WORKER_NAME'..."
curl -s -X PUT \
  "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/workers/scripts/$WORKER_NAME" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -F "metadata=@$METADATA_FILE;type=application/json" \
  -F "worker.js=@$SCRIPT_PATH;type=application/javascript+module" \
  | python3 -m json.tool | grep -E '"success"|"id"|"message"'

echo ""
echo "Ensuring route exists..."
curl -s \
  "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/workers/routes" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  | python3 -m json.tool | grep -E '"pattern"|"script"'

echo ""
echo "Done. Worker is live at api.amprealize.ai/*"
