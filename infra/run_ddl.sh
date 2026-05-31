#!/usr/bin/env bash
# Load the OMOP CDM 5.3 schema into the target RDS PostgreSQL.
#
# Loads ddl -> primary_keys -> indices.  Foreign-key constraints are
# intentionally NOT applied here (that is the "no documentation" input state);
# the constraints file is saved under truth/ so eval can score FK recovery.
#
# Requires PG* env vars (see .env).  Uses psql.
set -euo pipefail

VER="${OMOP_VERSION:-5.3}"
SCHEMA="${PGSCHEMA:-cdm}"
BASE="https://raw.githubusercontent.com/OHDSI/CommonDataModel/v5.4.2/inst/ddl/${VER}/postgresql"
DDL_DIR="data/ddl_${VER}"
TRUTH_DIR="truth"
mkdir -p "$DDL_DIR" "$TRUTH_DIR"

fetch() {  # fetch <filename>
  local f="$1"
  [ -f "$DDL_DIR/$f" ] || curl -sL "$BASE/$f" -o "$DDL_DIR/$f"
}

DDL="OMOPCDM_postgresql_${VER}_ddl.sql"
PK="OMOPCDM_postgresql_${VER}_primary_keys.sql"
IDX="OMOPCDM_postgresql_${VER}_indices.sql"
FK="OMOPCDM_postgresql_${VER}_constraints.sql"

for f in "$DDL" "$PK" "$IDX" "$FK"; do fetch "$f"; done

# keep the FK file as ground-truth reference (not applied to the DB)
cp "$DDL_DIR/$FK" "$TRUTH_DIR/$FK"

# substitute the @cdmDatabaseSchema placeholder with our schema name
render() { sed "s/@cdmDatabaseSchema/${SCHEMA}/g" "$DDL_DIR/$1"; }

echo ">> creating schema ${SCHEMA}"
psql -v ON_ERROR_STOP=1 -c "CREATE SCHEMA IF NOT EXISTS ${SCHEMA};"

echo ">> applying ddl (tables)"
render "$DDL" | psql -v ON_ERROR_STOP=1 -f -

echo ">> applying primary keys"
render "$PK" | psql -v ON_ERROR_STOP=1 -f -

echo ">> applying indices"
render "$IDX" | psql -v ON_ERROR_STOP=1 -f -

echo ">> DONE.  FK constraints intentionally skipped (saved to truth/${FK})."
psql -c "SELECT count(*) AS tables FROM information_schema.tables WHERE table_schema='${SCHEMA}';"
