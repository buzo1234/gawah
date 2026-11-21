#!/usr/bin/env bash
# Write the server's settings to AWS Secrets Manager (gawah/prod), then restart the app.
#
#   tools/deploy/push-secrets.sh               write the secret, restart the app on the server
#   tools/deploy/push-secrets.sh --no-restart  only write the secret (provision.sh uses this)
#
# The secret is .env, then .env.deploy on top (git-ignored: values for the server only,
# such as ACCESS_KEY), without the AWS keys (the server uses its instance role) and without
# PUBLIC_BASE_URL and DATABASE_PATH (deploy/compose.yaml sets those). If neither file has an
# ACCESS_KEY, one is made and kept in .env.deploy. No value is ever printed.
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

restart=1
[ "${1:-}" = "--no-restart" ] && restart=0
[ -f "$ROOT/.env" ] || die "no .env in $ROOT"
aws_from_dotenv

DEPLOY_ENV="$ROOT/.env.deploy"
if [ -z "$(dotenv_value ACCESS_KEY)" ] && [ -z "$(dotenv_value ACCESS_KEY "$DEPLOY_ENV")" ]; then
  umask 077
  printf 'ACCESS_KEY=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')" >>"$DEPLOY_ENV"
  say "made an access key for the dashboard; it is in .env.deploy (git-ignored)"
fi

payload="$(mktemp)"
trap 'rm -f "$payload"' EXIT
chmod 600 "$payload"
(cd "$ROOT" && uv run --quiet python - "$payload" <<'PY'
import json, sys
from pathlib import Path
from dotenv import dotenv_values

DROPPED = {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "PUBLIC_BASE_URL", "DATABASE_PATH"}
values = {**dotenv_values(".env"), **(dotenv_values(".env.deploy") if Path(".env.deploy").exists() else {})}
values = {k: v for k, v in values.items() if k not in DROPPED and v not in (None, "")}
if values.get("WHATSAPP_PROVIDER") == "meta" and not values.get("META_APP_SECRET"):
    sys.exit("WHATSAPP_PROVIDER=meta needs META_APP_SECRET: the server refuses to start without it")
Path(sys.argv[1]).write_text(json.dumps(values))
print(f"{len(values)} settings: " + ", ".join(sorted(values)))
PY
)

existing="$(aws secretsmanager describe-secret --secret-id "$SECRET_ID" \
  --query "Tags[?Key=='$TAG_KEY'].Value | [0]" --output text 2>/dev/null || echo MISSING)"
case "$existing" in
  MISSING)
    say "creating the secret $SECRET_ID"
    aws secretsmanager create-secret --name "$SECRET_ID" --description "Gawah server settings" \
      --secret-string "file://$payload" --tags "Key=$TAG_KEY,Value=$TAG_VALUE" --query ARN --output text >/dev/null ;;
  "$TAG_VALUE")
    say "updating the secret $SECRET_ID"
    aws secretsmanager put-secret-value --secret-id "$SECRET_ID" --secret-string "file://$payload" \
      --query VersionId --output text >/dev/null ;;
  *) die "a secret named $SECRET_ID exists but is not tagged $TAG_KEY=$TAG_VALUE; not touching it" ;;
esac

if [ "$restart" = 1 ]; then
  instance="$(instance_id)"
  [ -n "$instance" ] || die "no Gawah instance to restart (run tools/deploy/provision.sh)"
  say "restarting the app on $instance so it reads the new settings"
  ssm_run "$instance" "gawah: restart after new settings" 300 "set -e
cd /opt/gawah/app || { echo 'not deployed yet: nothing to restart'; exit 0; }
$COMPOSE restart app
$COMPOSE ps"
fi
say "done"
