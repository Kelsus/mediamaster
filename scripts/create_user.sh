#!/usr/bin/env bash
# Create a user account with a generated permanent password and register it
# in the users table (transfer targets, scheduled sweeps).
# Usage: scripts/create_user.sh <email> [display name]
set -euo pipefail
cd "$(dirname "$0")/.."

EMAIL="${1:?usage: create_user.sh <email> [display name]}"
DISPLAY_NAME="${2:-$EMAIL}"
[ -f .env ] && . ./.env
export AWS_PROFILE="${AWS_PROFILE:-default}"

POOL_ID=$(python3 -c "import json; print(json.load(open('infra/outputs.json'))['Mediamaster']['UserPoolId'])")
TABLE_NAME="${TABLE_NAME:-mediamaster}"

register_user() {
  local sub
  sub=$(aws cognito-idp admin-get-user --user-pool-id "$POOL_ID" --username "$EMAIL" \
    --query "UserAttributes[?Name=='sub'].Value" --output text)
  aws dynamodb put-item --table-name "$TABLE_NAME" --item "{
    \"PK\": {\"S\": \"USERS\"}, \"SK\": {\"S\": \"USER#$sub\"},
    \"uid\": {\"S\": \"$sub\"}, \"email\": {\"S\": \"$EMAIL\"},
    \"display_name\": {\"S\": \"$DISPLAY_NAME\"}}"
  echo "Registered $EMAIL (uid $sub) in users table"
}

if aws cognito-idp admin-get-user --user-pool-id "$POOL_ID" --username "$EMAIL" >/dev/null 2>&1; then
  echo "User $EMAIL already exists in pool $POOL_ID; ensuring registry row"
  register_user
  exit 0
fi

PASSWORD=$(python3 -c "import secrets,string; a=string.ascii_letters+string.digits; print('Mm1!'+''.join(secrets.choice(a) for _ in range(20)))")

aws cognito-idp admin-create-user \
  --user-pool-id "$POOL_ID" \
  --username "$EMAIL" \
  --user-attributes Name=email,Value="$EMAIL" Name=email_verified,Value=true \
  --temporary-password "$PASSWORD" \
  --message-action SUPPRESS >/dev/null

aws cognito-idp admin-set-user-password \
  --user-pool-id "$POOL_ID" \
  --username "$EMAIL" \
  --password "$PASSWORD" \
  --permanent

register_user

echo "Created $EMAIL"
echo "Password (save this in your password manager; it is the passkey-loss fallback):"
echo "  $PASSWORD"
