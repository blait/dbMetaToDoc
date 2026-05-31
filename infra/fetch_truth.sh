#!/usr/bin/env bash
# Download the OMOP CDM official data dictionary (the ground truth for scoring):
#   - Field_Level.csv : per-column userGuidance + isPrimaryKey/isForeignKey/fkTableName/fkFieldName
#   - Table_Level.csv : per-table description
set -euo pipefail
VER="${OMOP_VERSION:-5.3}"
BASE="https://raw.githubusercontent.com/OHDSI/CommonDataModel/v5.4.2/inst/csv"
mkdir -p truth
for f in "OMOP_CDMv${VER}_Field_Level.csv" "OMOP_CDMv${VER}_Table_Level.csv"; do
  echo ">> $f"
  curl -sL "$BASE/$f" -o "truth/$f"
done
wc -l truth/OMOP_CDMv${VER}_*.csv
