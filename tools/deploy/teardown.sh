#!/usr/bin/env bash
# Remove Gawah's server from AWS: only what is tagged app=gawah, and only after you say so.
# The database and recordings on the instance go with it (S3 keeps its own copies of the
# recordings and agreements). The S3 bucket is not ours to remove; the deploy bundles under
# its deploy/ prefix are listed at the end.
#
#   tools/deploy/teardown.sh
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

aws_from_dotenv
ACCOUNT="$(account_id)"
OIDC_ARN="arn:aws:iam::$ACCOUNT:oidc-provider/token.actions.githubusercontent.com"

tagged_role() {
  [ "$(aws iam list-role-tags --role-name "$1" --query "Tags[?Key=='$TAG_KEY'].Value | [0]" --output text 2>/dev/null)" = "$TAG_VALUE" ]
}
tagged_profile() {
  [ "$(aws iam list-instance-profile-tags --instance-profile-name "$1" --query "Tags[?Key=='$TAG_KEY'].Value | [0]" --output text 2>/dev/null)" = "$TAG_VALUE" ]
}
tagged_oidc() {
  [ "$(aws iam list-open-id-connect-provider-tags --open-id-connect-provider-arn "$OIDC_ARN" --query "Tags[?Key=='$TAG_KEY'].Value | [0]" --output text 2>/dev/null)" = "$TAG_VALUE" ]
}
tagged_secret() {
  [ "$(aws secretsmanager describe-secret --secret-id "$SECRET_ID" --query "Tags[?Key=='$TAG_KEY'].Value | [0]" --output text 2>/dev/null)" = "$TAG_VALUE" ]
}

INSTANCES="$(aws ec2 describe-instances \
  --filters "Name=tag:$TAG_KEY,Values=$TAG_VALUE" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'Reservations[].Instances[].InstanceId' --output text | none_to_empty)"
ALLOCS="$(aws ec2 describe-addresses --filters "Name=tag:$TAG_KEY,Values=$TAG_VALUE" \
  --query 'Addresses[].AllocationId' --output text | none_to_empty)"
SGS="$(aws ec2 describe-security-groups --filters "Name=tag:$TAG_KEY,Values=$TAG_VALUE" \
  --query 'SecurityGroups[].GroupId' --output text | none_to_empty)"

say "tagged $TAG_KEY=$TAG_VALUE in $REGION, to be removed"
echo "instances:       ${INSTANCES:-none}"
echo "elastic IPs:     ${ALLOCS:-none}"
echo "security groups: ${SGS:-none}"
for r in "$INSTANCE_ROLE" "$DEPLOY_ROLE"; do tagged_role "$r" && echo "role:            $r"; done
tagged_profile "$INSTANCE_ROLE" && echo "instance profile: $INSTANCE_ROLE"
tagged_oidc && echo "OIDC provider:   token.actions.githubusercontent.com"
tagged_secret && echo "secret:          $SECRET_ID (deleted at once, no recovery window)"
echo
read -r -p "Type 'gawah' to delete all of the above: " answer
[ "$answer" = gawah ] || die "nothing deleted"

if [ -n "$INSTANCES" ]; then
  say "terminating $INSTANCES"
  # shellcheck disable=SC2086  # a list of ids
  aws ec2 terminate-instances --instance-ids $INSTANCES >/dev/null
  # shellcheck disable=SC2086
  aws ec2 wait instance-terminated --instance-ids $INSTANCES
fi
for alloc in $ALLOCS; do
  say "releasing $alloc"
  assoc="$(aws ec2 describe-addresses --allocation-ids "$alloc" --query 'Addresses[0].AssociationId' --output text | none_to_empty)"
  [ -z "$assoc" ] || aws ec2 disassociate-address --association-id "$assoc"
  aws ec2 release-address --allocation-id "$alloc"
done
for sg in $SGS; do
  say "deleting $sg"
  for i in $(seq 1 12); do  # the instance's network card lets go a little after it ends
    aws ec2 delete-security-group --group-id "$sg" 2>/dev/null && break
    [ "$i" = 12 ] && die "could not delete $sg"
    sleep 10
  done
done
if tagged_profile "$INSTANCE_ROLE"; then
  say "deleting instance profile $INSTANCE_ROLE"
  for r in $(aws iam get-instance-profile --instance-profile-name "$INSTANCE_ROLE" --query 'InstanceProfile.Roles[].RoleName' --output text); do
    aws iam remove-role-from-instance-profile --instance-profile-name "$INSTANCE_ROLE" --role-name "$r"
  done
  aws iam delete-instance-profile --instance-profile-name "$INSTANCE_ROLE"
fi
for role in "$INSTANCE_ROLE" "$DEPLOY_ROLE"; do
  tagged_role "$role" || continue
  say "deleting role $role"
  for p in $(aws iam list-role-policies --role-name "$role" --query 'PolicyNames' --output text); do
    aws iam delete-role-policy --role-name "$role" --policy-name "$p"
  done
  for arn in $(aws iam list-attached-role-policies --role-name "$role" --query 'AttachedPolicies[].PolicyArn' --output text); do
    aws iam detach-role-policy --role-name "$role" --policy-arn "$arn"
  done
  aws iam delete-role --role-name "$role"
done
if tagged_oidc; then
  say "deleting the OIDC provider"
  aws iam delete-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN"
fi
if tagged_secret; then
  say "deleting the secret $SECRET_ID"
  aws secretsmanager delete-secret --secret-id "$SECRET_ID" --force-delete-without-recovery >/dev/null
fi

bucket="$(dotenv_value S3_BUCKET)"
say "done"
[ -z "$bucket" ] || echo "Deploy bundles left in s3://$bucket/deploy/ (remove by hand if wanted: aws s3 rm --recursive s3://$bucket/deploy/)"
