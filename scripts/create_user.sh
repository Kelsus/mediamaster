#!/usr/bin/env bash
# Create the (single) user account with a generated permanent password.
# Usage: scripts/create_user.sh <email>
set -euo pipefail
cd "$(dirname "$0")/.."

EMAIL="${1:?usage: create_user.sh <email>}"
[ -f .env ] && . ./.env
export AWS_PROFILE="${AWS_PROFILE:-default}"

POOL_ID=$(python3 -c "import json; print(json.load(open('infra/outputs.json'))['Mediamaster']['UserPoolId'])")

if aws cognito-idp admin-get-user --user-pool-id "$POOL_ID" --username "$EMAIL" >/dev/null 2>&1; then
  echo "User $EMAIL already exists in pool $POOL_ID"
  exit 0
fi

PASSWORD=$(python3 -c "import secrets,string; a=string.ascii_letters+string.digits; print('Mm1!'+''.join(secrets.choice(a) for _ in range(20)))")

aws cognito-idp admin-create-user \
  --user-pool-id "$POOL_ID" \
  --username "$EMAIL" \
  --user-attributes Name=email,Value="$EMAIL" Name=email_verified,Value=true \
  --message-action SUPPRESS >/dev/null

aws cognito-idp admin-set-user-password \
  --user-pool-id "$POOL_ID" \
  --username "$EMAIL" \
  --password "$PASSWORD" \
  --permanent

echo "Created $EMAIL"
echo "Password (save this in your password manager; it is the passkey-loss fallback):"
echo "  $PASSWORD"
