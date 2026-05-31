#!/usr/bin/env python3
"""Load the Eunomia GiBleed 5.3 demo dataset into the OMOP schema on RDS.

GiBleed ships one CSV per OMOP table (real synthetic rows).  We COPY each CSV
into cdm.<table>, mapping by header (lowercased) so it matches the DDL columns.

Run AFTER infra/run_ddl.sh has created the tables.
"""
import io
import os
import sys
import csv
import zipfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import connect, PGSCHEMA  # noqa: E402

ZIP_URL = ("https://raw.githubusercontent.com/OHDSI/EunomiaDatasets/main/"
           "datasets/GiBleed/GiBleed_5.3.zip")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
ZIP_PATH = os.path.join(DATA_DIR, "GiBleed_5.3.zip")
CSV_DIR = os.path.join(DATA_DIR, "GiBleed_5.3")

# OMOP "Z"-suffixed ISO datetimes -> strip Z so TIMESTAMP (no tz) parses cleanly.
DATETIME_FIX = "Z"


def download():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(ZIP_PATH):
        print(f">> downloading {ZIP_URL}")
        urllib.request.urlretrieve(ZIP_URL, ZIP_PATH)
    if not os.path.isdir(CSV_DIR):
        with zipfile.ZipFile(ZIP_PATH) as z:
            z.extractall(DATA_DIR)
    # the zip extracts to GiBleed_5.3/ (plus a __MACOSX/ we ignore)
    return CSV_DIR


def clean_row(row):
    """Strip trailing Z from ISO datetimes; pass everything else through."""
    out = []
    for v in row:
        if v and len(v) >= 20 and v.endswith(DATETIME_FIX) and "T" in v:
            v = v[:-1].replace("T", " ")
        out.append(v)
    return out


def load_table(cur, table, csv_path):
    with open(csv_path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        cols = [h.strip().lower() for h in header]
        # build an in-memory cleaned CSV for COPY
        buf = io.StringIO()
        w = csv.writer(buf)
        n = 0
        for row in reader:
            w.writerow(clean_row(row))
            n += 1
        buf.seek(0)
        collist = ", ".join(cols)
        sql = (f"COPY {PGSCHEMA}.{table} ({collist}) "
               f"FROM STDIN WITH (FORMAT csv, NULL '')")
        cur.copy_expert(sql, buf)
        return n


def main():
    csv_dir = download()
    files = sorted(x for x in os.listdir(csv_dir) if x.lower().endswith(".csv"))
    conn = connect()
    conn.autocommit = False
    total = 0
    with conn.cursor() as cur:
        # discover which tables actually exist in the schema
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema=%s",
            (PGSCHEMA,))
        existing = {r[0] for r in cur.fetchall()}
        for fn in files:
            table = fn[:-4].lower()
            if table not in existing:
                print(f"   skip {fn} (no table {PGSCHEMA}.{table})")
                continue
            try:
                n = load_table(cur, table, os.path.join(csv_dir, fn))
                conn.commit()
                total += n
                print(f"   loaded {table:<26} {n:>7} rows")
            except Exception as e:
                conn.rollback()
                print(f"   FAIL  {table:<26} {type(e).__name__}: {str(e)[:120]}")
    conn.close()
    print(f">> done, {total} rows total")


if __name__ == "__main__":
    main()
