#!/usr/bin/env bash
# Create a small, publicly-accessible RDS PostgreSQL 16 instance for the db2doc PoC.
# Idempotent-ish: skips creation if the instance already exists. Prints the endpoint.
#
# Usage:
#   bash infra/create_rds.sh          # create + wait + print endpoint
#   DRY_RUN=1 bash infra/create_rds.sh  # print what it would do, no AWS changes
#
# Cost note: db.t4g.micro + 20GB gp3 is small but NOT free. Delete when done:
#   aws rds delete-db-instance --db-instance-identifier db2doc-omop \
#       --skip-final-snapshot --region "$REGION"
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
DB_ID="${DB_ID:-db2doc-omop}"
DB_CLASS="${DB_CLASS:-db.t4g.micro}"
ENGINE_VERSION="${ENGINE_VERSION:-16.14}"
STORAGE_GB="${STORAGE_GB:-20}"
MASTER_USER="${MASTER_USER:-omop_admin}"
DB_NAME="${DB_NAME:-omop}"
SG_NAME="${SG_NAME:-db2doc-pg-sg}"

run() { echo "+ $*"; [ "${DRY_RUN:-0}" = "1" ] || "$@"; }

# --- master password: reuse PGPASSWORD if set, else generate one ---
if [ -n "${PGPASSWORD:-}" ]; then
  MASTER_PW="$PGPASSWORD"
else
  MASTER_PW="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24)"
  echo ">> generated master password (save this to .env as PGPASSWORD):"
  echo "   $MASTER_PW"
fi

# --- default VPC + caller IP ---
VPC_ID="$(aws ec2 describe-vpcs --region "$REGION" \
  --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)"
MY_IP="$(curl -s https://checkip.amazonaws.com)"
echo ">> VPC=$VPC_ID  my_ip=$MY_IP"

# --- security group (create if missing) ---
SG_ID="$(aws ec2 describe-security-groups --region "$REGION" \
  --filters Name=group-name,Values="$SG_NAME" Name=vpc-id,Values="$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo None)"
if [ "$SG_ID" = "None" ] || [ -z "$SG_ID" ]; then
  SG_ID="$(aws ec2 create-security-group --region "$REGION" \
    --group-name "$SG_NAME" --description "db2doc PoC PG access" \
    --vpc-id "$VPC_ID" --query GroupId --output text)"
  echo ">> created SG $SG_ID"
fi
# allow my IP on 5432 (ignore if rule already exists)
run aws ec2 authorize-security-group-ingress --region "$REGION" \
  --group-id "$SG_ID" --protocol tcp --port 5432 --cidr "${MY_IP}/32" 2>/dev/null \
  || echo ">> ingress rule already present (ok)"

# --- create instance if it doesn't exist ---
if aws rds describe-db-instances --region "$REGION" \
     --db-instance-identifier "$DB_ID" >/dev/null 2>&1; then
  echo ">> instance $DB_ID already exists, skipping create"
else
  run aws rds create-db-instance --region "$REGION" \
    --db-instance-identifier "$DB_ID" \
    --db-instance-class "$DB_CLASS" \
    --engine postgres --engine-version "$ENGINE_VERSION" \
    --allocated-storage "$STORAGE_GB" --storage-type gp3 \
    --master-username "$MASTER_USER" --master-user-password "$MASTER_PW" \
    --db-name "$DB_NAME" \
    --vpc-security-group-ids "$SG_ID" \
    --publicly-accessible --backup-retention-period 0 \
    --no-multi-az --no-deletion-protection
fi

echo ">> waiting for instance to become available ..."
run aws rds wait db-instance-available --region "$REGION" --db-instance-identifier "$DB_ID"

ENDPOINT="$(aws rds describe-db-instances --region "$REGION" \
  --db-instance-identifier "$DB_ID" \
  --query 'DBInstances[0].Endpoint.Address' --output text)"
echo ""
echo "=========================================================="
echo " RDS ready. Put these in your .env:"
echo "   PGHOST=$ENDPOINT"
echo "   PGPORT=5432"
echo "   PGDATABASE=$DB_NAME"
echo "   PGUSER=$MASTER_USER"
echo "   PGPASSWORD=<the master password above>"
echo "   PGSCHEMA=cdm"
echo "=========================================================="
