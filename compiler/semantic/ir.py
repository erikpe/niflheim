from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from compiler.frontend.lexer import SourceSpan
from compiler.resolver import ModulePath
from compiler.semantic.symbols import ClassId, ConstructorId, FunctionId, InterfaceId, InterfaceMethodId, MethodId, SyntheticId


def _decode_char_literal(lexeme: str) -> int:
    if len(lexeme) < 3 or not lexeme.startswith("'") or not lexeme.endswith("'"):
        raise ValueError(f"invalid char literal lexeme: {lexeme!r}")

    payload = lexeme[1:-1]
    if len(payload) == 1:
        return ord(payload)

    if not payload.startswith("\\"):
        raise ValueError(f"invalid char literal payload: {lexeme!r}")

    if len(payload) == 2:
        esc = payload[1]
        if esc == "n":
            return 0x0A
        if esc == "r":
            return 0x0D
        if esc == "t":
            return 0x09
        if esc == "0":
            return 0x00
        if esc == "\\":
            return 0x5C
        if esc == "'":
            return 0x27
        if esc == '"':
            return 0x22
        raise ValueError(f"unsupported char escape: {lexeme!r}")

    if len(payload) == 4 and payload[1] == "x":
        return int(payload[2:], 16)

    raise ValueError(f"invalid char literal payload: {lexeme!r}")


@dataclass(frozen=True)
class SemanticProgram:
    entry_module: ModulePath
    modules: dict[ModulePath, "SemanticModule"]


@dataclass(frozen=True)
class SemanticModule:
    module_path: ModulePath
    file_path: Path
    classes: list["SemanticClass"]
    functions: list["SemanticFunction"]
    span: SourceSpan
    interfaces: list["SemanticInterface"] = field(default_factory=list)


@dataclass(frozen=True)
class SemanticInterfaceMethod:
    method_id: InterfaceMethodId
    params: list["SemanticParam"]
    return_type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class SemanticInterface:
    interface_id: InterfaceId
    is_export: bool
    methods: list[SemanticInterfaceMethod]
    span: SourceSpan


@dataclass(frozen=True)
class SemanticField:
    name: str
    type_name: str
    initializer: "SemanticExpr | None"
    is_private: bool
    is_final: bool
    span: SourceSpan


@dataclass(frozen=True)
class SemanticClass:
    class_id: ClassId
    is_export: bool
    fields: list[SemanticField]
    methods: list["SemanticMethod"]
    span: SourceSpan
    implemented_interfaces: list[InterfaceId] = field(default_factory=list)


@dataclass(frozen=True)
class SemanticParam:
    name: str
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class SemanticFunction:
    function_id: FunctionId
    params: list[SemanticParam]
    return_type_name: str
    body: "SemanticBlock | None"
    is_export: bool
    is_extern: bool
    span: SourceSpan


@dataclass(frozen=True)
class SemanticMethod:
    method_id: MethodId
    params: list[SemanticParam]
    return_type_name: str
    body: "SemanticBlock"
    is_static: bool
    is_private: bool
    span: SourceSpan


@dataclass(frozen=True)
class SemanticBlock:
    statements: list["SemanticStmt"]
    span: SourceSpan


@dataclass(frozen=True)
class SemanticVarDecl:
    name: str
    type_name: str
    initializer: "SemanticExpr | None"
    span: SourceSpan


@dataclass(frozen=True)
class SemanticAssign:
    target: "SemanticLValue"
    value: "SemanticExpr"
    span: SourceSpan


@dataclass(frozen=True)
class SemanticExprStmt:
    expr: "SemanticExpr"
    span: SourceSpan


@dataclass(frozen=True)
class SemanticReturn:
    value: "SemanticExpr | None"
    span: SourceSpan


@dataclass(frozen=True)
class SemanticIf:
    condition: "SemanticExpr"
    then_block: SemanticBlock
    else_block: SemanticBlock | None
    span: SourceSpan


@dataclass(frozen=True)
class SemanticWhile:
    condition: "SemanticExpr"
    body: SemanticBlock
    span: SourceSpan


@dataclass(frozen=True)
class SemanticBreak:
    span: SourceSpan


@dataclass(frozen=True)
class SemanticContinue:
    span: SourceSpan


@dataclass(frozen=True)
class SemanticForIn:
    element_name: str
    collection: "SemanticExpr"
    iter_len_method: MethodId | None
    iter_get_method: MethodId | None
    element_type_name: str
    body: SemanticBlock
    span: SourceSpan


@dataclass(frozen=True)
class LocalLValue:
    name: str
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class FieldLValue:
    receiver: "SemanticExpr"
    receiver_type_name: str
    field_name: str
    field_type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class IndexLValue:
    target: "SemanticExpr"
    index: "SemanticExpr"
    value_type_name: str
    set_method: MethodId | None
    span: SourceSpan


@dataclass(frozen=True)
class SliceLValue:
    target: "SemanticExpr"
    begin: "SemanticExpr"
    end: "SemanticExpr"
    value_type_name: str
    set_method: MethodId | None
    span: SourceSpan


@dataclass(frozen=True)
class LocalRefExpr:
    name: str
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class FunctionRefExpr:
    function_id: FunctionId
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class ClassRefExpr:
    class_id: ClassId
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class MethodRefExpr:
    method_id: MethodId
    receiver: "SemanticExpr | None"
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class IntConstant:
    value: int
    type_name: str


@dataclass(frozen=True)
class FloatConstant:
    value: float
    type_name: str


@dataclass(frozen=True)
class BoolConstant:
    value: bool
    type_name: str


@dataclass(frozen=True)
class CharConstant:
    value: int
    type_name: str


SemanticConstant = IntConstant | FloatConstant | BoolConstant | CharConstant


def _constant_from_legacy_literal(*, value: str, type_name: str) -> SemanticConstant:
    if type_name == "bool":
        if value == "true":
            return BoolConstant(value=True, type_name=type_name)
        if value == "false":
            return BoolConstant(value=False, type_name=type_name)
        raise ValueError(f"invalid bool literal: {value}")

    if type_name == "double":
        return FloatConstant(value=float(value), type_name=type_name)

    if type_name == "u8" and value.startswith("'"):
        return CharConstant(value=_decode_char_literal(value), type_name=type_name)

    if type_name in {"i64", "u64", "u8"}:
        text = value
        if text.endswith("u8"):
            text = text[:-2]
        elif text.endswith("u"):
            text = text[:-1]
        return IntConstant(value=int(text), type_name=type_name)

    raise ValueError(f"unsupported semantic literal for type '{type_name}': {value}")


def _legacy_literal_text(constant: SemanticConstant) -> str:
    if isinstance(constant, BoolConstant):
        return "true" if constant.value else "false"
    if isinstance(constant, FloatConstant):
        return str(constant.value)
    if isinstance(constant, IntConstant):
        if constant.type_name == "u8":
            return str(constant.value)
        if constant.type_name == "u64":
            return f"{constant.value}u"
        return str(constant.value)
    return str(constant.value)


@dataclass(frozen=True, init=False)
class LiteralExprS:
    constant: SemanticConstant
    type_name: str
    span: SourceSpan
    raw_text: str | None

    def __init__(
        self,
        *,
        constant: SemanticConstant | None = None,
        type_name: str,
        span: SourceSpan,
        value: str | None = None,
        raw_text: str | None = None,
    ) -> None:
        if constant is None:
            if value is None:
                raise TypeError("LiteralExprS requires either 'constant' or legacy 'value'")
            constant = _constant_from_legacy_literal(value=value, type_name=type_name)
            if raw_text is None:
                raw_text = value
        elif value is not None:
            raise TypeError("LiteralExprS accepts either 'constant' or 'value', not both")

        object.__setattr__(self, "constant", constant)
        object.__setattr__(self, "type_name", type_name)
        object.__setattr__(self, "span", span)
        object.__setattr__(self, "raw_text", raw_text)

    @property
    def value(self) -> str:
        if self.raw_text is not None:
            return self.raw_text
        return _legacy_literal_text(self.constant)


@dataclass(frozen=True)
class NullExprS:
    span: SourceSpan


@dataclass(frozen=True)
class UnaryExprS:
    operator: str
    operand: "SemanticExpr"
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class BinaryExprS:
    operator: str
    left: "SemanticExpr"
    right: "SemanticExpr"
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class CastExprS:
    operand: "SemanticExpr"
    target_type_name: str
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class TypeTestExprS:
    operand: "SemanticExpr"
    target_type_name: str
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class FieldReadExpr:
    receiver: "SemanticExpr"
    receiver_type_name: str
    field_name: str
    field_type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class FunctionCallExpr:
    function_id: FunctionId
    args: list["SemanticExpr"]
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class StaticMethodCallExpr:
    method_id: MethodId
    args: list["SemanticExpr"]
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class InstanceMethodCallExpr:
    method_id: MethodId
    receiver: "SemanticExpr"
    receiver_type_name: str
    args: list["SemanticExpr"]
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class InterfaceMethodCallExpr:
    interface_id: InterfaceId
    method_id: InterfaceMethodId
    receiver: "SemanticExpr"
    receiver_type_name: str
    args: list["SemanticExpr"]
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class ConstructorCallExpr:
    constructor_id: ConstructorId
    args: list["SemanticExpr"]
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class CallableValueCallExpr:
    callee: "SemanticExpr"
    args: list["SemanticExpr"]
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class ArrayLenExpr:
    target: "SemanticExpr"
    span: SourceSpan


@dataclass(frozen=True)
class IndexReadExpr:
    target: "SemanticExpr"
    index: "SemanticExpr"
    result_type_name: str
    get_method: MethodId | None
    span: SourceSpan


@dataclass(frozen=True)
class SliceReadExpr:
    target: "SemanticExpr"
    begin: "SemanticExpr"
    end: "SemanticExpr"
    result_type_name: str
    get_method: MethodId | None
    span: SourceSpan


@dataclass(frozen=True)
class ArrayCtorExprS:
    element_type_name: str
    length_expr: "SemanticExpr"
    type_name: str
    span: SourceSpan


@dataclass(frozen=True)
class SyntheticExpr:
    synthetic_id: SyntheticId
    args: list["SemanticExpr"]
    type_name: str
    span: SourceSpan


SemanticStmt = (
    SemanticBlock
    | SemanticVarDecl
    | SemanticAssign
    | SemanticExprStmt
    | SemanticReturn
    | SemanticIf
    | SemanticWhile
    | SemanticForIn
    | SemanticBreak
    | SemanticContinue
)


SemanticLValue = LocalLValue | FieldLValue | IndexLValue | SliceLValue


SemanticExpr = (
    LocalRefExpr
    | FunctionRefExpr
    | ClassRefExpr
    | MethodRefExpr
    | LiteralExprS
    | NullExprS
    | UnaryExprS
    | BinaryExprS
    | CastExprS
    | TypeTestExprS
    | FieldReadExpr
    | FunctionCallExpr
    | StaticMethodCallExpr
    | InstanceMethodCallExpr
    | InterfaceMethodCallExpr
    | ConstructorCallExpr
    | CallableValueCallExpr
    | ArrayLenExpr
    | IndexReadExpr
    | SliceReadExpr
    | ArrayCtorExprS
    | SyntheticExpr
)
