from compiler.common.type_names import (
    BUILTIN_OR_SPECIAL_TYPE_NAMES,
    INTEGER_TYPE_NAMES,
    NUMERIC_TYPE_NAMES,
    PRIMITIVE_TYPE_NAMES,
    REFERENCE_BUILTIN_TYPE_NAMES,
    SPECIAL_TYPE_NAMES,
    TYPE_NAME_BOOL,
    TYPE_NAME_DOUBLE,
    TYPE_NAME_I64,
    TYPE_NAME_NULL,
    TYPE_NAME_OBJ,
    TYPE_NAME_STR,
    TYPE_NAME_U8,
    TYPE_NAME_U64,
    TYPE_NAME_UNIT,
    UNSIGNED_INTEGER_TYPE_NAMES,
)


def test_type_name_constants_use_canonical_spellings() -> None:
    assert TYPE_NAME_I64 == "i64"
    assert TYPE_NAME_U64 == "u64"
    assert TYPE_NAME_U8 == "u8"
    assert TYPE_NAME_BOOL == "bool"
    assert TYPE_NAME_DOUBLE == "double"
    assert TYPE_NAME_UNIT == "unit"
    assert TYPE_NAME_OBJ == "Obj"
    assert TYPE_NAME_STR == "Str"
    assert TYPE_NAME_NULL == "null"


def test_type_name_groups_are_built_from_canonical_constants() -> None:
    assert PRIMITIVE_TYPE_NAMES == frozenset({TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8, TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_UNIT})
    assert INTEGER_TYPE_NAMES == frozenset({TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8})
    assert UNSIGNED_INTEGER_TYPE_NAMES == frozenset({TYPE_NAME_U64, TYPE_NAME_U8})
    assert NUMERIC_TYPE_NAMES == frozenset({TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8, TYPE_NAME_DOUBLE})
    assert REFERENCE_BUILTIN_TYPE_NAMES == frozenset({TYPE_NAME_OBJ})
    assert SPECIAL_TYPE_NAMES == frozenset({TYPE_NAME_OBJ, TYPE_NAME_STR, TYPE_NAME_NULL})
    assert TYPE_NAME_STR in BUILTIN_OR_SPECIAL_TYPE_NAMES
    assert TYPE_NAME_NULL in BUILTIN_OR_SPECIAL_TYPE_NAMES