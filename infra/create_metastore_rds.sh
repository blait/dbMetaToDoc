#!/usr/bin/env bash
# Create the metastore RDS MySQL instance for db2doc.
# Reuses the security group from the OMOP PG instance (same VPC, my IP on 3306).
#
# Cost: db.t4g.micro + 20GB. Delete when done:
#   aws rds delete-db-instance --db-instance-identifier db2doc-meta \
#       --skip-final-snapshot --region us-east-1
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
DB_ID="${DB_ID:-db2doc-meta}"
DB_CLASS="${DB_CLASS:-db.t4g.micro}"
ENGINE_VERSION="${ENGINE_VERSION:-8.0.44}"
STORAGE_GB="${STORAGE_GB:-20}"
MASTER_USER="${MASTER_USER:-db2doc}"
DB_NAME="${DB_NAME:-db2doc}"
SG_NAME="${SG_NAME:-db2doc-meta-sg}"

run() { echo "+ $*"; [ "${DRY_RUN:-0}" = "1" ] || "$@"; }

if [ -n "${METASTORE_PASSWORD:-}" ]; then
  MASTER_PW="$METASTORE_PASSWORD"
else
  MASTER_PW="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24)"
  echo ">> generated master password (save as METASTORE_PASSWORD):"
  echo "   $MASTER_PW"
fi

VPC_ID="$(aws ec2 describe-vpcs --region "$REGION" \
  --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)"
MY_IP="$(curl -s https://checkip.amazonaws.com)"
echo ">> VPC=$VPC_ID my_ip=$MY_IP"

SG_ID="$(aws ec2 describe-security-groups --region "$REGION" \
  --filters Name=group-name,Values="$SG_NAME" Name=vpc-id,Values="$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo None)"
if [ "$SG_ID" = "None" ] || [ -z "$SG_ID" ]; then
  SG_ID="$(aws ec2 create-security-group --region "$REGION" \
    --group-name "$SG_NAME" --description "db2doc metastore MySQL" \
    --vpc-id "$VPC_ID" --query GroupId --output text)"
  echo ">> created SG $SG_ID"
fi
run aws ec2 authorize-security-group-ingress --region "$REGION" \
  --group-id "$SG_ID" --protocol tcp --port 3306 --cidr "${MY_IP}/32" 2>/dev/null \
  || echo ">> ingress rule already present (ok)"

if aws rds describe-db-instances --region "$REGION" \
     --db-instance-identifier "$DB_ID" >/dev/null 2>&1; then
  echo ">> instance $DB_ID already exists, skipping create"
else
  run aws rds create-db-instance --region "$REGION" \
    --db-instance-identifier "$DB_ID" --db-instance-class "$DB_CLASS" \
    --engine mysql --engine-version "$ENGINE_VERSION" \
    --allocated-storage "$STORAGE_GB" --storage-type gp3 \
    --master-username "$MASTER_USER" --master-user-password "$MASTER_PW" \
    --db-name "$DB_NAME" --vpc-security-group-ids "$SG_ID" \
    --publicly-accessible --backup-retention-period 0 \
    --no-multi-az --no-deletion-protection
fi

echo ">> waiting for available ..."
run aws rds wait db-instance-available --region "$REGION" --db-instance-identifier "$DB_ID"
ENDPOINT="$(aws rds describe-db-instances --region "$REGION" \
  --db-instance-identifier "$DB_ID" --query 'DBInstances[0].Endpoint.Address' --output text)"
echo ""
echo "=== metastore ready. Put in .env: ==="
echo "METASTORE_HOST=$ENDPOINT"
echo "METASTORE_PORT=3306"
echo "METASTORE_DB=$DB_NAME"
echo "METASTORE_USER=$MASTER_USER"
echo "METASTORE_PASSWORD=<master password above>"
