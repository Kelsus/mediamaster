#!/usr/bin/env bash
# Full deploy: lambda bundle -> frontend build -> cdk deploy.
# First deploy runs a second CDK pass to set the passkey RP ID to the real
# CloudFront domain (unknowable before the distribution exists).
#
# Custom domain: set CUSTOM_DOMAIN and CERT_ARN in .env (ACM cert must be
# ISSUED, in us-east-1). The domain becomes the passkey RP ID — existing
# passkeys re-enroll after the switch. DNS (an alias/CNAME to the CloudFront
# domain) is managed outside this script.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] && . ./.env
PROFILE="${AWS_PROFILE:-default}"
export AWS_PROFILE="$PROFILE"
export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1
RP_FILE=".rp_id"
CUSTOM_DOMAIN="${CUSTOM_DOMAIN:-}"
CERT_ARN="${CERT_ARN:-}"

DOMAIN_CTX=()
if [ -n "$CUSTOM_DOMAIN" ]; then
  if [ -z "$CERT_ARN" ]; then
    echo "CUSTOM_DOMAIN is set but CERT_ARN is not; both are required." >&2
    exit 1
  fi
  DOMAIN_CTX=(-c "custom_domain=$CUSTOM_DOMAIN" -c "cert_arn=$CERT_ARN")
fi

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
# With a custom domain the RP target is known up front — no second pass needed.
[ -n "$CUSTOM_DOMAIN" ] && RP_ID="$CUSTOM_DOMAIN"

cd infra
npx cdk deploy --require-approval never -c "rp_id=$RP_ID" ${DOMAIN_CTX[@]+"${DOMAIN_CTX[@]}"} --outputs-file outputs.json
DOMAIN=$(python3 -c "import json; print(json.load(open('outputs.json'))['Mediamaster']['DistributionDomain'])")
cd ..

TARGET="${CUSTOM_DOMAIN:-$DOMAIN}"
if [ "$RP_ID" != "$TARGET" ]; then
  echo "Setting passkey RP ID to $TARGET (second pass)..."
  echo "$TARGET" > "$RP_FILE"
  (cd infra && npx cdk deploy --require-approval never -c "rp_id=$TARGET" ${DOMAIN_CTX[@]+"${DOMAIN_CTX[@]}"} --outputs-file outputs.json)
else
  echo "$TARGET" > "$RP_FILE"
fi

echo ""
echo "Deployed: https://$TARGET"
[ -n "$CUSTOM_DOMAIN" ] && echo "(CloudFront origin domain: $DOMAIN — point DNS here)"
