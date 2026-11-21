#!/usr/bin/env bash
# Build Gawah's server in AWS (us-west-2) from nothing, or finish what is missing.
# Safe to run again: it finds what exists by the app=gawah tag and only adds what is not
# there. It never changes anything without that tag (the account has other things in it).
#
#   tools/deploy/provision.sh
#
# Makes: a security group (80 and 443 only, no SSH), an Elastic IP, the instance role and
# profile (read gawah/prod, read and write the S3 bucket in .env, SSM), the secret (from
# .env, through push-secrets.sh), GitHub's OIDC provider and a deploy role that trusts only
# buzo1234/gawah on main, and one t3.medium Ubuntu 24.04 instance with Docker.
# Prints the address and the GitHub variables to set.
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

[ -f "$ROOT/.env" ] || die "no .env in $ROOT"
aws_from_dotenv
ACCOUNT="$(account_id)"
BUCKET="$(dotenv_value S3_BUCKET)"
[ -n "$BUCKET" ] || die "S3_BUCKET is not set in .env"
TAGS_EC2="{Key=$TAG_KEY,Value=$TAG_VALUE},{Key=Name,Value=gawah}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# ---------- IAM: refuse to adopt a role of the same name that is not ours ----------

role_tag() {
  aws iam list-role-tags --role-name "$1" --query "Tags[?Key=='$TAG_KEY'].Value | [0]" --output text 2>/dev/null \
    || echo MISSING
}

ensure_role() {  # name, trust policy file
  case "$(role_tag "$1")" in
    MISSING) aws iam create-role --role-name "$1" --assume-role-policy-document "file://$2" \
               --tags "Key=$TAG_KEY,Value=$TAG_VALUE" --query Role.Arn --output text >/dev/null
             echo "created role $1" ;;
    "$TAG_VALUE") aws iam update-assume-role-policy --role-name "$1" --policy-document "file://$2"
                  echo "role $1 exists" ;;
    *) die "a role named $1 exists but is not tagged $TAG_KEY=$TAG_VALUE; not touching it" ;;
  esac
}

say "instance role $INSTANCE_ROLE"
cat >"$tmp/ec2-trust.json" <<EOF
{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
EOF
cat >"$tmp/instance-policy.json" <<EOF
{"Version": "2012-10-17", "Statement": [
  {"Sid": "ReadSettings", "Effect": "Allow", "Action": "secretsmanager:GetSecretValue",
   "Resource": "arn:aws:secretsmanager:$REGION:$ACCOUNT:secret:$SECRET_ID-*"},
  {"Sid": "AppObjects", "Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"],
   "Resource": "arn:aws:s3:::$BUCKET/*"},
  {"Sid": "ListBucket", "Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
   "Resource": "arn:aws:s3:::$BUCKET"}
]}
EOF
ensure_role "$INSTANCE_ROLE" "$tmp/ec2-trust.json"
aws iam put-role-policy --role-name "$INSTANCE_ROLE" --policy-name gawah-instance \
  --policy-document "file://$tmp/instance-policy.json"
aws iam attach-role-policy --role-name "$INSTANCE_ROLE" \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
if ! aws iam get-instance-profile --instance-profile-name "$INSTANCE_ROLE" >/dev/null 2>&1; then
  aws iam create-instance-profile --instance-profile-name "$INSTANCE_ROLE" \
    --tags "Key=$TAG_KEY,Value=$TAG_VALUE" >/dev/null
  echo "created instance profile $INSTANCE_ROLE"
fi
profile_tag="$(aws iam list-instance-profile-tags --instance-profile-name "$INSTANCE_ROLE" \
  --query "Tags[?Key=='$TAG_KEY'].Value | [0]" --output text)"
[ "$profile_tag" = "$TAG_VALUE" ] || die "instance profile $INSTANCE_ROLE is not tagged $TAG_KEY=$TAG_VALUE; not touching it"
in_profile="$(aws iam get-instance-profile --instance-profile-name "$INSTANCE_ROLE" \
  --query 'InstanceProfile.Roles[].RoleName' --output text)"
if [ "$in_profile" != "$INSTANCE_ROLE" ]; then
  [ -z "$in_profile" ] || die "instance profile $INSTANCE_ROLE holds another role ($in_profile)"
  aws iam add-role-to-instance-profile --instance-profile-name "$INSTANCE_ROLE" --role-name "$INSTANCE_ROLE"
fi

# ---------- GitHub: OIDC provider and the deploy role ----------

say "GitHub OIDC and deploy role $DEPLOY_ROLE"
OIDC_ARN="arn:aws:iam::$ACCOUNT:oidc-provider/token.actions.githubusercontent.com"
if ! aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN" >/dev/null 2>&1; then
  aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 1c58a3a8518e8759bf075b76b750d4f2df264fcd \
    --tags "Key=$TAG_KEY,Value=$TAG_VALUE" >/dev/null
  echo "created the OIDC provider"
else
  echo "the OIDC provider exists (used as it is)"
fi
# The token's sub starts with the repo's prefix. With GitHub's immutable subject claims it
# carries owner and repo ids (repo:owner@123/repo@456), so the plain form never matches.
github_sub_prefix() {
  local check="gh api repos/$GITHUB_REPO/actions/oidc/customization/sub" out use_default prefix
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1 \
      && out="$(gh api "repos/$GITHUB_REPO/actions/oidc/customization/sub" \
           --jq '"\(.use_default) \(.sub_claim_prefix // "")"' 2>/dev/null)"; then
    read -r use_default prefix <<<"$out"
    if [ "$use_default" = false ]; then
      echo "warning: $GITHUB_REPO has custom OIDC claim keys; the deploy role may not match ($check)" >&2
    fi
    printf '%s' "${prefix:-repo:$GITHUB_REPO}"
    return
  fi
  echo "warning: could not read $GITHUB_REPO's OIDC subject format (gh missing or not logged in);" >&2
  echo "  trusting repo:$GITHUB_REPO. If the repo uses immutable subject claims, deploys will fail" >&2
  echo "  with 'Not authorized to perform sts:AssumeRoleWithWebIdentity'. Check: $check" >&2
  echo "  then run gh auth login and run this script again." >&2
  printf 'repo:%s' "$GITHUB_REPO"
}
GITHUB_SUB="$(github_sub_prefix):ref:refs/heads/main"
echo "deploy role trusts sub $GITHUB_SUB"
cat >"$tmp/github-trust.json" <<EOF
{"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
  "Principal": {"Federated": "$OIDC_ARN"}, "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": {"StringEquals": {
    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
    "token.actions.githubusercontent.com:sub": "$GITHUB_SUB"}}}]}
EOF
cat >"$tmp/deploy-policy.json" <<EOF
{"Version": "2012-10-17", "Statement": [
  {"Sid": "UploadBundle", "Effect": "Allow", "Action": "s3:PutObject", "Resource": "arn:aws:s3:::$BUCKET/deploy/*"},
  {"Sid": "RunOnGawahOnly", "Effect": "Allow", "Action": "ssm:SendCommand",
   "Resource": "arn:aws:ec2:$REGION:$ACCOUNT:instance/*",
   "Condition": {"StringEquals": {"ssm:resourceTag/$TAG_KEY": "$TAG_VALUE"}}},
  {"Sid": "TheShellDocument", "Effect": "Allow", "Action": "ssm:SendCommand",
   "Resource": "arn:aws:ssm:$REGION::document/AWS-RunShellScript"},
  {"Sid": "Read", "Effect": "Allow",
   "Action": ["ssm:GetCommandInvocation", "ec2:DescribeInstances", "ec2:DescribeTags", "ec2:DescribeAddresses"],
   "Resource": "*"}
]}
EOF
ensure_role "$DEPLOY_ROLE" "$tmp/github-trust.json"
aws iam put-role-policy --role-name "$DEPLOY_ROLE" --policy-name gawah-deploy \
  --policy-document "file://$tmp/deploy-policy.json"
DEPLOY_ROLE_ARN="arn:aws:iam::$ACCOUNT:role/$DEPLOY_ROLE"

# ---------- the secret ----------

say "secret $SECRET_ID"
if aws secretsmanager describe-secret --secret-id "$SECRET_ID" >/dev/null 2>&1; then
  echo "exists (tools/deploy/push-secrets.sh updates it)"
else
  "$ROOT/tools/deploy/push-secrets.sh" --no-restart
fi

# ---------- network ----------

say "security group $SG_NAME"
VPC="$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text | none_to_empty)"
[ -n "$VPC" ] || die "this region has no default VPC"
SG="$(aws ec2 describe-security-groups --filters "Name=tag:$TAG_KEY,Values=$TAG_VALUE" "Name=group-name,Values=$SG_NAME" \
  --query 'SecurityGroups[0].GroupId' --output text | none_to_empty)"
if [ -z "$SG" ]; then
  SG="$(aws ec2 create-security-group --group-name "$SG_NAME" --description "Gawah: HTTP and HTTPS only" \
    --vpc-id "$VPC" --tag-specifications "ResourceType=security-group,Tags=[$TAGS_EC2]" --query GroupId --output text)"
  echo "created $SG"
fi
for port in 80 443; do
  aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port "$port" --cidr 0.0.0.0/0 \
    >/dev/null 2>&1 || true  # already there
done

say "Elastic IP"
IP="$(elastic_ip)"
if [ -z "$IP" ]; then
  IP="$(aws ec2 allocate-address --domain vpc \
    --tag-specifications "ResourceType=elastic-ip,Tags=[$TAGS_EC2]" --query PublicIp --output text)"
  echo "allocated $IP"
fi
ALLOC="$(aws ec2 describe-addresses --public-ips "$IP" --query 'Addresses[0].AllocationId' --output text)"
ADDRESS="$(address_for "$IP")"

# ---------- the instance ----------

say "instance"
INSTANCE="$(instance_id)"
if [ -z "$INSTANCE" ]; then
  AMI="$(aws ssm get-parameter --query Parameter.Value --output text \
    --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id)"
  cat >"$tmp/user-data.sh" <<'EOF'
#!/bin/bash
# First boot: Docker and the AWS CLI. The SSM agent is already on Ubuntu's image.
# The app arrives with the first tools/deploy/deploy.sh.
set -eux
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y docker.io docker-compose-v2 docker-buildx curl
systemctl enable --now docker
snap install aws-cli --classic
mkdir -p /opt/gawah
EOF
  # A new instance profile can take a few seconds before EC2 accepts it.
  for attempt in 1 2 3 4 5 6; do
    if INSTANCE="$(aws ec2 run-instances --image-id "$AMI" --instance-type t3.medium \
        --iam-instance-profile "Name=$INSTANCE_ROLE" --security-group-ids "$SG" \
        --user-data "file://$tmp/user-data.sh" \
        --metadata-options HttpTokens=required,HttpPutResponseHopLimit=2,HttpEndpoint=enabled \
        --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=20,VolumeType=gp3,DeleteOnTermination=true}' \
        --tag-specifications "ResourceType=instance,Tags=[$TAGS_EC2,{Key=gawah-bucket,Value=$BUCKET}]" \
          "ResourceType=volume,Tags=[$TAGS_EC2]" \
        --query 'Instances[0].InstanceId' --output text)"; then
      break
    fi
    [ "$attempt" = 6 ] && die "run-instances kept failing"
    echo "waiting for the instance profile..."; sleep 10
  done
  echo "launched $INSTANCE"
else
  aws ec2 create-tags --resources "$INSTANCE" --tags "Key=gawah-bucket,Value=$BUCKET"
  state="$(aws ec2 describe-instances --instance-ids "$INSTANCE" --query 'Reservations[0].Instances[0].State.Name' --output text)"
  if [ "$state" = stopped ]; then aws ec2 start-instances --instance-ids "$INSTANCE" >/dev/null; fi
  echo "$INSTANCE exists ($state)"
fi
aws ec2 wait instance-running --instance-ids "$INSTANCE"
current="$(aws ec2 describe-addresses --public-ips "$IP" --query 'Addresses[0].InstanceId' --output text | none_to_empty)"
if [ "$current" != "$INSTANCE" ]; then
  [ -z "$current" ] || die "the Elastic IP $IP is attached to $current, not $INSTANCE"
  aws ec2 associate-address --instance-id "$INSTANCE" --allocation-id "$ALLOC" >/dev/null
  echo "attached $IP to $INSTANCE"
fi

say "waiting for the instance to report to SSM (a minute or two on first boot)"
for i in $(seq 1 40); do
  ping="$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$INSTANCE" \
    --query 'InstanceInformationList[0].PingStatus' --output text | none_to_empty)"
  [ "$ping" = Online ] && { echo online; break; }
  [ "$i" = 40 ] && echo "not online yet; deploy.sh will fail until it is (check again in a few minutes)"
  sleep 10
done

cat <<EOF

Ready.
  Address:          https://$ADDRESS
  Meta webhook URL: https://$ADDRESS/whatsapp/webhook
  Instance:         $INSTANCE

Set these GitHub repository variables (Settings > Secrets and variables > Actions > Variables):
  AWS_DEPLOY_ROLE_ARN = $DEPLOY_ROLE_ARN
  DEPLOY_ENABLED      = true

Next: tools/deploy/deploy.sh  (the first deploy builds the image on the server)
EOF
