from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_NULL, TYPE_NAME_OBJ, TYPE_NAME_U8, TYPE_NAME_U64
from compiler.semantic.types import SemanticTypeRef, semantic_type_canonical_name, semantic_type_is_interface, semantic_type_is_reference


class UnaryOpKind(Enum):
    NEGATE = "negate"
    BITWISE_NOT = "bitwise_not"
    LOGICAL_NOT = "logical_not"


class UnaryOpFlavor(Enum):
    INTEGER = "integer"
    FLOAT = "float"
    BOOL = "bool"


@dataclass(frozen=True)
class SemanticUnaryOp:
    kind: UnaryOpKind
    flavor: UnaryOpFlavor


class BinaryOpKind(Enum):
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    REMAINDER = "remainder"
    POWER = "power"
    BITWISE_AND = "bitwise_and"
    BITWISE_OR = "bitwise_or"
    BITWISE_XOR = "bitwise_xor"
    SHIFT_LEFT = "shift_left"
    SHIFT_RIGHT = "shift_right"
    LOGICAL_AND = "logical_and"
    LOGICAL_OR = "logical_or"
    EQUAL = "equal"
    NOT_EQUAL = "not_equal"
    LESS_THAN = "less_than"
    LESS_EQUAL = "less_equal"
    GREATER_THAN = "greater_than"
    GREATER_EQUAL = "greater_equal"


class BinaryOpFlavor(Enum):
    INTEGER = "integer"
    FLOAT = "float"
    BOOL_LOGICAL = "bool_logical"
    BOOL_COMPARISON = "bool_comparison"
    INTEGER_COMPARISON = "integer_comparison"
    FLOAT_COMPARISON = "float_comparison"
    IDENTITY_COMPARISON = "identity_comparison"


@dataclass(frozen=True)
class SemanticBinaryOp:
    kind: BinaryOpKind
    flavor: BinaryOpFlavor


class CastSemanticsKind(Enum):
    IDENTITY = "identity"
    TO_BOOL = "to_bool"
    TO_DOUBLE = "to_double"
    TO_INTEGER = "to_integer"
    REFERENCE_COMPATIBILITY = "reference_compatibility"


class TypeTestSemanticsKind(Enum):
    CLASS_COMPATIBILITY = "class_compatibility"
    INTERFACE_COMPATIBILITY = "interface_compatibility"


_UNARY_OP_TEXT = {
    UnaryOpKind.NEGATE: "-",
    UnaryOpKind.BITWISE_NOT: "~",
    UnaryOpKind.LOGICAL_NOT: "!",
}


_BINARY_OP_TEXT = {
    BinaryOpKind.ADD: "+",
    BinaryOpKind.SUBTRACT: "-",
    BinaryOpKind.MULTIPLY: "*",
    BinaryOpKind.DIVIDE: "/",
    BinaryOpKind.REMAINDER: "%",
    BinaryOpKind.POWER: "**",
    BinaryOpKind.BITWISE_AND: "&",
    BinaryOpKind.BITWISE_OR: "|",
    BinaryOpKind.BITWISE_XOR: "^",
    BinaryOpKind.SHIFT_LEFT: "<<",
    BinaryOpKind.SHIFT_RIGHT: ">>",
    BinaryOpKind.LOGICAL_AND: "&&",
    BinaryOpKind.LOGICAL_OR: "||",
    BinaryOpKind.EQUAL: "==",
    BinaryOpKind.NOT_EQUAL: "!=",
    BinaryOpKind.LESS_THAN: "<",
    BinaryOpKind.LESS_EQUAL: "<=",
    BinaryOpKind.GREATER_THAN: ">",
    BinaryOpKind.GREATER_EQUAL: ">=",
}


_UNARY_KIND_BY_TEXT = {text: kind for kind, text in _UNARY_OP_TEXT.items()}
_BINARY_KIND_BY_TEXT = {text: kind for kind, text in _BINARY_OP_TEXT.items()}

_INTEGER_TYPE_NAMES = {TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8}


def unary_op_text(op: SemanticUnaryOp | UnaryOpKind) -> str:
    kind = op.kind if isinstance(op, SemanticUnaryOp) else op
    return _UNARY_OP_TEXT[kind]


def binary_op_text(op: SemanticBinaryOp | BinaryOpKind) -> str:
    kind = op.kind if isinstance(op, SemanticBinaryOp) else op
    return _BINARY_OP_TEXT[kind]


def semantic_unary_op_from_token(operator_text: str, operand_type_ref: SemanticTypeRef) -> SemanticUnaryOp:
    kind = _UNARY_KIND_BY_TEXT.get(operator_text)
    if kind is None:
        raise ValueError(f"Unsupported semantic unary operator '{operator_text}'")
    if kind == UnaryOpKind.LOGICAL_NOT:
        return SemanticUnaryOp(kind=kind, flavor=UnaryOpFlavor.BOOL)
    if kind == UnaryOpKind.BITWISE_NOT:
        return SemanticUnaryOp(kind=kind, flavor=UnaryOpFlavor.INTEGER)
    if _semantic_type_name(operand_type_ref) == TYPE_NAME_DOUBLE:
        return SemanticUnaryOp(kind=kind, flavor=UnaryOpFlavor.FLOAT)
    return SemanticUnaryOp(kind=kind, flavor=UnaryOpFlavor.INTEGER)


def semantic_binary_op_from_token(
    operator_text: str, left_type_ref: SemanticTypeRef, right_type_ref: SemanticTypeRef
) -> SemanticBinaryOp:
    kind = _BINARY_KIND_BY_TEXT.get(operator_text)
    if kind is None:
        raise ValueError(f"Unsupported semantic binary operator '{operator_text}'")

    left_name = _semantic_type_name(left_type_ref)
    right_name = _semantic_type_name(right_type_ref)

    if kind in {BinaryOpKind.LOGICAL_AND, BinaryOpKind.LOGICAL_OR}:
        return SemanticBinaryOp(kind=kind, flavor=BinaryOpFlavor.BOOL_LOGICAL)

    if kind in {BinaryOpKind.EQUAL, BinaryOpKind.NOT_EQUAL}:
        if left_name == TYPE_NAME_BOOL and right_name == TYPE_NAME_BOOL:
            return SemanticBinaryOp(kind=kind, flavor=BinaryOpFlavor.BOOL_COMPARISON)
        if left_name == TYPE_NAME_DOUBLE and right_name == TYPE_NAME_DOUBLE:
            return SemanticBinaryOp(kind=kind, flavor=BinaryOpFlavor.FLOAT_COMPARISON)
        if left_name in _INTEGER_TYPE_NAMES and right_name in _INTEGER_TYPE_NAMES:
            return SemanticBinaryOp(kind=kind, flavor=BinaryOpFlavor.INTEGER_COMPARISON)
        return SemanticBinaryOp(kind=kind, flavor=BinaryOpFlavor.IDENTITY_COMPARISON)

    if kind in {BinaryOpKind.LESS_THAN, BinaryOpKind.LESS_EQUAL, BinaryOpKind.GREATER_THAN, BinaryOpKind.GREATER_EQUAL}:
        if left_name == TYPE_NAME_DOUBLE:
            return SemanticBinaryOp(kind=kind, flavor=BinaryOpFlavor.FLOAT_COMPARISON)
        return SemanticBinaryOp(kind=kind, flavor=BinaryOpFlavor.INTEGER_COMPARISON)

    if left_name == TYPE_NAME_DOUBLE:
        return SemanticBinaryOp(kind=kind, flavor=BinaryOpFlavor.FLOAT)
    return SemanticBinaryOp(kind=kind, flavor=BinaryOpFlavor.INTEGER)


def semantic_cast_kind(source_type_ref: SemanticTypeRef, target_type_ref: SemanticTypeRef) -> CastSemanticsKind:
    source_name = _semantic_type_name(source_type_ref)
    target_name = _semantic_type_name(target_type_ref)
    if source_name == target_name:
        return CastSemanticsKind.IDENTITY
    if target_name == TYPE_NAME_BOOL:
        return CastSemanticsKind.TO_BOOL
    if target_name == TYPE_NAME_DOUBLE:
        return CastSemanticsKind.TO_DOUBLE
    if target_name in _INTEGER_TYPE_NAMES:
        return CastSemanticsKind.TO_INTEGER
    return CastSemanticsKind.REFERENCE_COMPATIBILITY


def semantic_type_test_kind(target_type_ref: SemanticTypeRef) -> TypeTestSemanticsKind:
    if semantic_type_is_interface(target_type_ref):
        return TypeTestSemanticsKind.INTERFACE_COMPATIBILITY
    if semantic_type_is_reference(target_type_ref):
        return TypeTestSemanticsKind.CLASS_COMPATIBILITY
    raise ValueError(
        f"Semantic type-test target must be reference or interface, got '{semantic_type_canonical_name(target_type_ref)}'"
    )


def binary_op_uses_u8_mask(kind: BinaryOpKind) -> bool:
    return kind in {
        BinaryOpKind.ADD,
        BinaryOpKind.SUBTRACT,
        BinaryOpKind.MULTIPLY,
        BinaryOpKind.POWER,
        BinaryOpKind.DIVIDE,
        BinaryOpKind.REMAINDER,
        BinaryOpKind.BITWISE_AND,
        BinaryOpKind.BITWISE_OR,
        BinaryOpKind.BITWISE_XOR,
        BinaryOpKind.SHIFT_LEFT,
        BinaryOpKind.SHIFT_RIGHT,
    }


def _semantic_type_name(type_ref: SemanticTypeRef) -> str:
    canonical_name = semantic_type_canonical_name(type_ref)
    if canonical_name in _INTEGER_TYPE_NAMES | {TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_NULL, TYPE_NAME_OBJ}:
        return canonical_name
    return canonical_name