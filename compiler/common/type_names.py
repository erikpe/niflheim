from __future__ import annotations

from typing import Final


TYPE_NAME_I64: Final = "i64"
TYPE_NAME_U64: Final = "u64"
TYPE_NAME_U8: Final = "u8"
TYPE_NAME_BOOL: Final = "bool"
TYPE_NAME_DOUBLE: Final = "double"
TYPE_NAME_UNIT: Final = "unit"

TYPE_NAME_OBJ: Final = "Obj"
TYPE_NAME_STR: Final = "Str"
TYPE_NAME_NULL: Final = "null"

PRIMITIVE_TYPE_NAMES: Final[frozenset[str]] = frozenset(
    {
        TYPE_NAME_I64,
        TYPE_NAME_U64,
        TYPE_NAME_U8,
        TYPE_NAME_BOOL,
        TYPE_NAME_DOUBLE,
        TYPE_NAME_UNIT,
    }
)

INTEGER_TYPE_NAMES: Final[frozenset[str]] = frozenset(
    {
        TYPE_NAME_I64,
        TYPE_NAME_U64,
        TYPE_NAME_U8,
    }
)

SIGNED_INTEGER_TYPE_NAMES: Final[frozenset[str]] = frozenset({TYPE_NAME_I64})

UNSIGNED_INTEGER_TYPE_NAMES: Final[frozenset[str]] = frozenset(
    {
        TYPE_NAME_U64,
        TYPE_NAME_U8,
    }
)

NUMERIC_TYPE_NAMES: Final[frozenset[str]] = frozenset(
    {
        TYPE_NAME_I64,
        TYPE_NAME_U64,
        TYPE_NAME_U8,
        TYPE_NAME_DOUBLE,
    }
)

BITWISE_TYPE_NAMES: Final[frozenset[str]] = frozenset(
    {
        TYPE_NAME_I64,
        TYPE_NAME_U64,
        TYPE_NAME_U8,
    }
)

REFERENCE_BUILTIN_TYPE_NAMES: Final[frozenset[str]] = frozenset({TYPE_NAME_OBJ})

SPECIAL_TYPE_NAMES: Final[frozenset[str]] = frozenset(
    {
        TYPE_NAME_OBJ,
        TYPE_NAME_STR,
        TYPE_NAME_NULL,
    }
)

BUILTIN_OR_SPECIAL_TYPE_NAMES: Final[frozenset[str]] = frozenset(
    PRIMITIVE_TYPE_NAMES | REFERENCE_BUILTIN_TYPE_NAMES | {TYPE_NAME_STR, TYPE_NAME_NULL}
)

NON_CLASS_TYPE_NAMES: Final[frozenset[str]] = frozenset(BUILTIN_OR_SPECIAL_TYPE_NAMES)
