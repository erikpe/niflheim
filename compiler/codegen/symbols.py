from __future__ import annotations


def _mangle_type_fragment(name: str) -> str:
    return name.replace(".", "_").replace(":", "_").replace("[", "_").replace("]", "_")


def epilogue_label(fn_name: str) -> str:
    return f".L{fn_name}_epilogue"


def next_label(fn_name: str, prefix: str, label_counter: list[int]) -> str:
    value = label_counter[0]
    label_counter[0] += 1
    return f".L{fn_name}_{prefix}_{value}"


def is_runtime_call_name(name: str) -> bool:
    return name.startswith("rt_")


def mangle_type_symbol(type_name: str) -> str:
    safe = _mangle_type_fragment(type_name)
    return f"__nif_type_{safe}"


def mangle_type_name_symbol(type_name: str) -> str:
    safe = _mangle_type_fragment(type_name)
    return f"__nif_type_name_{safe}"


def mangle_interface_symbol(type_name: str) -> str:
    return f"__nif_interface_{_mangle_type_fragment(type_name)}"


def mangle_interface_name_symbol(type_name: str) -> str:
    return f"__nif_interface_name_{_mangle_type_fragment(type_name)}"


def mangle_interface_method_table_symbol(class_type_name: str, interface_type_name: str) -> str:
    safe_class = _mangle_type_fragment(class_type_name)
    safe_interface = _mangle_type_fragment(interface_type_name)
    return f"__nif_interface_methods_{safe_class}__{safe_interface}"


def mangle_class_interface_impls_symbol(class_type_name: str) -> str:
    return f"__nif_interface_impls_{_mangle_type_fragment(class_type_name)}"


def mangle_method_symbol(type_name: str, method_name: str) -> str:
    safe_type = type_name.replace(".", "_").replace(":", "_")
    safe_method = method_name.replace(".", "_").replace(":", "_")
    return f"__nif_method_{safe_type}_{safe_method}"


def mangle_constructor_symbol(type_name: str) -> str:
    safe_type = type_name.replace(".", "_").replace(":", "_")
    return f"__nif_ctor_{safe_type}"
