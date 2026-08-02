#!/usr/bin/env bash
# Full deploy: lambda bundle -> frontend build -> cdk deploy.
# First deploy runs a second CDK pass to set the passkey RP ID to the real
# CloudFront domain (unknowable before the distribution exists).
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] && . ./.env
PROFILE="${AWS_PROFILE:-default}"
export AWS_PROFILE="$PROFILE"
export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1
RP_FILE=".rp_id"

if ! aws sts get-caller-identity >/dev/null 2>&1; then
  echo "AWS credentials for profile '$PROFILE' are not valid. Running aws sso login..."
  aws sso login --profile "$PROFILE"
fi

./scripts/build_lambda.sh

if [ -d frontend/node_modules ]; then
  (cd frontend && npm run build)
elif [ -f frontend/package.json ]; then
  (cd frontend && npm install && npm run build)
fi

RP_ID="localhost"
[ -f "$RP_FILE" ] && RP_ID="$(cat "$RP_FILE")"

cd infra
npx cdk deploy --require-approval never -c "rp_id=$RP_ID" --outputs-file outputs.json
DOMAIN=$(python3 -c "import json; print(json.load(open('outputs.json'))['Mediamaster']['DistributionDomain'])")
cd ..

if [ "$RP_ID" != "$DOMAIN" ]; then
  echo "Setting passkey RP ID to $DOMAIN (second pass)..."
  echo "$DOMAIN" > "$RP_FILE"
  (cd infra && npx cdk deploy --require-approval never -c "rp_id=$DOMAIN" --outputs-file outputs.json)
fi

echo ""
echo "Deployed: https://$DOMAIN"
