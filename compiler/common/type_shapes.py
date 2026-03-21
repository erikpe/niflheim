from __future__ import annotations

from compiler.common.type_names import PRIMITIVE_TYPE_NAMES, TYPE_NAME_STR


def is_function_type_name(type_name: str) -> bool:
    return type_name.startswith("fn(")


def function_type_return_type_name(type_name: str) -> str:
    if not is_function_type_name(type_name):
        raise ValueError(f"not a function type name: {type_name}")

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
        raise ValueError(f"malformed function type name: {type_name}")

    tail = type_name[close_index + 1 :].lstrip()
    if not tail.startswith("->"):
        raise ValueError(f"malformed function type name: {type_name}")
    return tail[2:].strip()


def is_array_type_name(type_name: str) -> bool:
    return type_name.endswith("[]")


def array_element_type_name(array_type_name: str) -> str:
    if not is_array_type_name(array_type_name):
        raise ValueError(f"not an array type name: {array_type_name}")
    return array_type_name[:-2]


def is_reference_type_name(type_name: str) -> bool:
    if is_function_type_name(type_name):
        return False
    return type_name not in PRIMITIVE_TYPE_NAMES


def is_str_type_name(type_name: str) -> bool:
    return type_name == TYPE_NAME_STR or type_name.endswith("::" + TYPE_NAME_STR)
