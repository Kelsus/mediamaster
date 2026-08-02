#!/usr/bin/env bash
# Local dev: uvicorn against the deployed table (real AWS creds), Vite dev server
# proxying /api -> :8000. Passkeys don't work on localhost (RP ID is the
# CloudFront domain) — use password login locally.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] && . ./.env
export AWS_PROFILE="${AWS_PROFILE:-default}"
export TABLE_NAME="${TABLE_NAME:-mediamaster}"
export USER_POOL_ID=$(python3 -c "import json; print(json.load(open('infra/outputs.json'))['Mediamaster']['UserPoolId'])")
export USER_POOL_CLIENT_ID=$(python3 -c "import json; print(json.load(open('infra/outputs.json'))['Mediamaster']['UserPoolClientId'])")

(cd backend && uv run uvicorn mediamaster_api.main:app --reload --port 8000) &
API_PID=$!
trap "kill $API_PID" EXIT

cd frontend && npm run dev
