from __future__ import annotations

import struct

from compiler.ast_nodes import ArrayTypeRef, FunctionTypeRef, TypeRef, TypeRefNode
from compiler.codegen.model import PRIMITIVE_TYPE_NAMES


def _span_location(span: object | None) -> str | None:
    if span is None:
        return None
    start = getattr(span, "start", None)
    if start is None:
        return None
    path = getattr(start, "path", None)
    line = getattr(start, "line", None)
    column = getattr(start, "column", None)
    if isinstance(path, str) and isinstance(line, int) and isinstance(column, int):
        return f"{path}:{line}:{column}"
    return None


def _raise_codegen_error(message: str, *, span: object | None = None) -> None:
    location = _span_location(span)
    if location is not None:
        raise NotImplementedError(f"{message} at {location}")
    raise NotImplementedError(message)


def _is_reference_type_name(type_name: str) -> bool:
    if _is_function_type_name(type_name):
        return False
    return type_name not in PRIMITIVE_TYPE_NAMES


def _is_function_type_name(type_name: str) -> bool:
    return type_name.startswith("fn(")


def _function_type_return_type_name(type_name: str, *, span: object | None = None) -> str:
    if not _is_function_type_name(type_name):
        _raise_codegen_error(f"not a function type name: {type_name}", span=span)

    depth = 0
    close_index = -1
    for index, char in enumerate(type_name):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                close_index = index
                break

    if close_index < 0:
        _raise_codegen_error(f"malformed function type name: {type_name}", span=span)

    tail = type_name[close_index + 1 :].lstrip()
    if not tail.startswith("->"):
        _raise_codegen_error(f"malformed function type name: {type_name}", span=span)
    return tail[2:].strip()


def _is_array_type_name(type_name: str) -> bool:
    return type_name.endswith("[]")


def _array_element_type_name(array_type_name: str, *, span: object | None = None) -> str:
    if not _is_array_type_name(array_type_name):
        _raise_codegen_error(f"not an array type name: {array_type_name}", span=span)
    return array_type_name[:-2]


def _array_element_runtime_kind(element_type_name: str) -> str:
    if element_type_name in {"i64", "u64", "u8", "bool", "double"}:
        return element_type_name
    return "ref"


def _type_ref_name(type_ref: TypeRefNode) -> str:
    if isinstance(type_ref, TypeRef):
        return type_ref.name
    if isinstance(type_ref, ArrayTypeRef):
        return f"{_type_ref_name(type_ref.element_type)}[]"
    if isinstance(type_ref, FunctionTypeRef):
        params_text = ",".join(_type_ref_name(param_type) for param_type in type_ref.param_types)
        return f"fn({params_text})->{_type_ref_name(type_ref.return_type)}"
    _raise_codegen_error(
        f"unsupported type ref node: {type(type_ref).__name__}",
        span=getattr(type_ref, "span", None),
    )


def _is_double_literal_text(text: str) -> bool:
    if "." not in text:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


def _double_literal_bits(text: str) -> int:
    packed = struct.pack("<d", float(text))
    return struct.unpack("<Q", packed)[0]