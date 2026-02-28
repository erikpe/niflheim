from __future__ import annotations


STR_CLASS_NAME = "NewStr"


def is_str_type_name(type_name: str) -> bool:
    return type_name == STR_CLASS_NAME or type_name.endswith("::NewStr")
