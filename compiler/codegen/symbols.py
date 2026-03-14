from __future__ import annotations


def _epilogue_label(fn_name: str) -> str:
    return f".L{fn_name}_epilogue"


def _next_label(fn_name: str, prefix: str, label_counter: list[int]) -> str:
    value = label_counter[0]
    label_counter[0] += 1
    return f".L{fn_name}_{prefix}_{value}"


def _is_runtime_call_name(name: str) -> bool:
    return name.startswith("rt_")


def _mangle_type_symbol(type_name: str) -> str:
    safe = type_name.replace(".", "_").replace(":", "_").replace("[", "_").replace("]", "_")
    return f"__nif_type_{safe}"


def _mangle_type_name_symbol(type_name: str) -> str:
    safe = type_name.replace(".", "_").replace(":", "_").replace("[", "_").replace("]", "_")
    return f"__nif_type_name_{safe}"


def _mangle_method_symbol(type_name: str, method_name: str) -> str:
    safe_type = type_name.replace(".", "_").replace(":", "_")
    safe_method = method_name.replace(".", "_").replace(":", "_")
    return f"__nif_method_{safe_type}_{safe_method}"


def _mangle_constructor_symbol(type_name: str) -> str:
    safe_type = type_name.replace(".", "_").replace(":", "_")
    return f"__nif_ctor_{safe_type}"