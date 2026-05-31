"""Dialect-aware identifier quoting for generated DDL (e.g. COMMENT SQL)."""


def quoter(engine):
    """Return a fn(name)->quoted identifier for the engine's dialect."""
    prep = engine.dialect.identifier_preparer
    return prep.quote


def quote_literal(value):
    """Single-quote a string literal for SQL (basic escaping)."""
    return "'" + str(value).replace("'", "''") + "'"
