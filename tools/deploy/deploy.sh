#!/usr/bin/env bash
# Deploy the committed code to the server: the same by hand and from GitHub Actions.
#
#   tools/deploy/deploy.sh          deploy HEAD
#   tools/deploy/deploy.sh <ref>    deploy a commit, tag or branch
#
# The source (git archive, so only committed files) goes to the app's S3 bucket under
# deploy/, then SSM tells the instance to fetch it and run `docker compose up -d --build`.
# The image is built on the server; there is no registry. The data volume is kept.
# Ends by checking https://<address>/health. In GitHub Actions it also writes the address
# to $GITHUB_OUTPUT.
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

ref="${1:-HEAD}"
aws_from_dotenv

instance="$(instance_id)"
[ -n "$instance" ] || die "no Gawah instance (run tools/deploy/provision.sh)"
bucket="$(instance_tag "$instance" gawah-bucket)"
[ -n "$bucket" ] || die "the instance has no gawah-bucket tag (run tools/deploy/provision.sh)"
ip="$(elastic_ip)"
[ -n "$ip" ] || die "no Elastic IP tagged $TAG_KEY=$TAG_VALUE (run tools/deploy/provision.sh)"
address="$(address_for "$ip")"

sha="$(git -C "$ROOT" rev-parse --short=12 "$ref^{commit}")"
bundle="gawah-$sha.tgz"
key="deploy/$bundle"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

say "packing $sha"
git -C "$ROOT" archive --format=tar.gz -o "$tmp/$bundle" "$sha"
aws s3 cp --only-show-errors "$tmp/$bundle" "s3://$bucket/$key"

say "building and starting $sha on $instance (the first build takes a few minutes)"
ssm_run "$instance" "gawah: deploy $sha" 1500 "set -eu
cloud-init status --wait >/dev/null || true
export PATH=/snap/bin:\$PATH
mkdir -p /opt/gawah
cat > /opt/gawah/host.env <<EOT
GAWAH_ADDRESS=$address
GAWAH_SECRET_ID=$SECRET_ID
AWS_DEFAULT_REGION=$REGION
EOT
aws s3 cp --only-show-errors s3://$bucket/$key /opt/gawah/$bundle
rm -rf /opt/gawah/app.new && mkdir /opt/gawah/app.new
tar -xzf /opt/gawah/$bundle -C /opt/gawah/app.new && rm -f /opt/gawah/$bundle
echo $sha > /opt/gawah/app.new/REVISION
rm -rf /opt/gawah/app.old
if [ -d /opt/gawah/app ]; then mv /opt/gawah/app /opt/gawah/app.old; fi
mv /opt/gawah/app.new /opt/gawah/app
cd /opt/gawah/app
$COMPOSE up -d --build --remove-orphans
for i in \$(seq 1 40); do
  state=\$(docker inspect --format '{{.State.Health.Status}}' \$($COMPOSE ps -q app))
  [ \"\$state\" = healthy ] && break
  [ \$i = 40 ] && { $COMPOSE logs --tail 80 app; echo \"app is \$state\"; exit 1; }
  sleep 3
done
docker image prune -f >/dev/null
$COMPOSE ps
echo deployed $sha"

say "checking https://$address/health"
for i in $(seq 1 20); do
  if curl -fsS --max-time 10 "https://$address/health"; then
    echo
    [ -n "${GITHUB_OUTPUT:-}" ] && echo "address=$address" >>"$GITHUB_OUTPUT"
    say "deployed $sha at https://$address"
    exit 0
  fi
  [ "$i" = 20 ] && die "https://$address/health did not answer"
  sleep 6  # the first deploy waits for Let's Encrypt
done
