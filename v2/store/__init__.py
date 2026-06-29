"""db2doc v2 metastore (MySQL via SQLAlchemy).

Persists run results — catalog, descriptions (AI original + reviewed),
relations, concepts, and a review audit trail — to a MySQL metastore so
they survive across machines and support multi-user review.

The pipeline still writes per-run JSON files; `sync.py` loads a finished
run's catalog into the metastore, and the web app reads from the DB when
configured (file fallback otherwise).
"""
