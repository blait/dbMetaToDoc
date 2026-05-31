"""db2doc — metastore product core.

Turns the file-based PoC (single PG, out/*.json, baked HTML) into a real
metastore: register many target DBs, infer descriptions, review/edit, persist
everything in MySQL, serve a REST API + dynamic UI.
"""
__version__ = "0.1.0"
