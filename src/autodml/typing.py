"""SQL type -> MDL type mapping."""

from __future__ import annotations

from typing import Any

# SQLAlchemy generic types map cleanly
_GENERIC = {
    "String": "string", "Text": "string", "Unicode": "string", "UnicodeText": "string",
    "Char": "string", "VARCHAR": "string", "TEXT": "string", "CLOB": "string",
    "NCHAR": "string", "NVARCHAR": "string",
    "Integer": "integer", "BigInteger": "integer", "SmallInteger": "integer",
    "INT": "integer", "INTEGER": "integer", "BIGINT": "integer", "SMALLINT": "integer",
    "SERIAL": "integer", "BIGSERIAL": "integer",
    "Numeric": "decimal", "DECIMAL": "decimal", "NUMERIC": "decimal",
    "Float": "float", "REAL": "float", "FLOAT": "float",
    "Double": "double", "DOUBLE_PRECISION": "double", "DOUBLE": "double",
    "Boolean": "boolean", "BOOLEAN": "boolean", "BOOL": "boolean",
    "Date": "date", "DATE": "date",
    "Time": "time", "TIME": "time",
    "DateTime": "timestamp", "TIMESTAMP": "timestamp", "DATETIME": "timestamp",
    "TIMESTAMP_WITH_TIME_ZONE": "timestamptz", "TIMESTAMPTZ": "timestamptz",
    "JSON": "json", "JSONB": "json",
    "UUID": "string",
}

_PATTERNS = (
    (r"(timestamp|datetime).*(with|tz|zone)", "timestamptz"),
    (r"timestamp|datetime", "timestamp"),
    (r"^char|text|string|varchar|clob", "string"),
    (r"bigint|smallint|int|serial", "integer"),
    (r"numeric|decimal|money", "decimal"),
    (r"double", "double"),
    (r"float|real", "float"),
    (r"bool", "boolean"),
    (r"^date$", "date"),
    (r"^time", "time"),
    (r"json|jsonb|struct|array", "json"),
)


def to_mdl_type(sqla_type: Any) -> str:
    """Map a SQLAlchemy type instance/string to an MDL type."""
    # 1. by class name (works for generic + many dialect types)
    cls = sqla_type.__class__
    names = {cls.__name__} | {c.__name__ for c in cls.__mro__}
    for n in names:
        if n in _GENERIC:
            return _GENERIC[n]

    # 2. by rendered compilation / string form
    text = str(sqla_type).lower()
    import re as _re
    for pat, mdl in _PATTERNS:
        if _re.search(pat, text):
            return mdl

    return "unknown"
