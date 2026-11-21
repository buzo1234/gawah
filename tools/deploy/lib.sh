# shellcheck shell=bash
# shellcheck disable=SC2034  # the names below are used by the scripts that source this
# Shared by the deploy scripts; sourced, never run. Everything Gawah owns in AWS is tagged
# app=gawah, and the scripts only ever change what carries that tag.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REGION=us-west-2
export AWS_REGION=$REGION AWS_DEFAULT_REGION=$REGION AWS_PAGER=""
TAG_KEY=app
TAG_VALUE=gawah
SECRET_ID=gawah/prod
SG_NAME=gawah-web
INSTANCE_ROLE=gawah-instance
DEPLOY_ROLE=gawah-github-deploy
GITHUB_REPO=buzo1234/gawah
COMPOSE="docker compose -p gawah -f deploy/compose.yaml --env-file /opt/gawah/host.env"

say() { printf '\n== %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

# A value from a dotenv file (default .env), surrounding quotes removed; empty if missing.
dotenv_value() {
  local file="${2:-$ROOT/.env}"
  [ -f "$file" ] || return 0
  sed -n "s/^$1=//p" "$file" | tail -n 1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}

# On the laptop, use the keys in .env unless the shell already has AWS credentials.
aws_from_dotenv() {
  if [ -z "${AWS_ACCESS_KEY_ID:-}" ] && [ -z "${AWS_PROFILE:-}" ] && [ -f "$ROOT/.env" ]; then
    AWS_ACCESS_KEY_ID="$(dotenv_value AWS_ACCESS_KEY_ID)"
    AWS_SECRET_ACCESS_KEY="$(dotenv_value AWS_SECRET_ACCESS_KEY)"
    AWS_SESSION_TOKEN="$(dotenv_value AWS_SESSION_TOKEN)"
    export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
    [ -n "$AWS_SESSION_TOKEN" ] || unset AWS_SESSION_TOKEN
  fi
  aws sts get-caller-identity --query Account --output text >/dev/null \
    || die "no working AWS credentials (shell, AWS_PROFILE, or the keys in .env)"
}

account_id() { aws sts get-caller-identity --query Account --output text; }

none_to_empty() { local v; v="$(cat)"; [ "$v" = "None" ] && v=""; printf '%s' "$v"; }

# The one Gawah instance that is not terminated; empty if there is none.
instance_id() {
  local ids
  ids="$(aws ec2 describe-instances \
    --filters "Name=tag:$TAG_KEY,Values=$TAG_VALUE" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId' --output text | none_to_empty)"
  [ "$(wc -w <<<"$ids")" -le 1 ] || die "more than one instance is tagged $TAG_KEY=$TAG_VALUE: $ids"
  printf '%s' "$ids"
}

instance_tag() {
  aws ec2 describe-tags --filters "Name=resource-id,Values=$1" "Name=key,Values=$2" \
    --query 'Tags[0].Value' --output text | none_to_empty
}

elastic_ip() {
  aws ec2 describe-addresses --filters "Name=tag:$TAG_KEY,Values=$TAG_VALUE" \
    --query 'Addresses[0].PublicIp' --output text | none_to_empty
}

address_for() { printf '%s.sslip.io' "$1"; }

# Run a shell script on the instance through SSM and wait for it. Prints its output and
# fails when the script fails. Usage: ssm_run <instance> <comment> <timeout seconds> <script>
ssm_run() {
  local instance="$1" comment="$2" timeout="$3" script="$4" params command_id status=""
  params="$(mktemp)"
  python3 -c 'import json, sys; print(json.dumps({"commands": sys.argv[1].splitlines(), "executionTimeout": [sys.argv[2]]}))' \
    "$script" "$timeout" >"$params"
  command_id="$(aws ssm send-command --instance-ids "$instance" --document-name AWS-RunShellScript \
    --comment "$comment" --parameters "file://$params" --query Command.CommandId --output text)"
  rm -f "$params"
  local waited=0
  while [ "$waited" -le "$timeout" ]; do
    sleep 5; waited=$((waited + 5))
    status="$(aws ssm get-command-invocation --command-id "$command_id" --instance-id "$instance" \
      --query Status --output text 2>/dev/null || echo Pending)"
    case "$status" in Pending|InProgress|Delayed) continue ;; *) break ;; esac
  done
  aws ssm get-command-invocation --command-id "$command_id" --instance-id "$instance" \
    --query '[StandardOutputContent, StandardErrorContent]' --output text || true
  [ "$status" = "Success" ] || die "'$comment' on $instance ended as: $status"
}
