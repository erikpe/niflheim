from __future__ import annotations

from dataclasses import fields, is_dataclass
import json
from typing import Any



def ast_to_debug_data(node: Any, *, include_spans: bool = False) -> Any:
    if node is None:
        return None

    if isinstance(node, (str, int, float, bool)):
        return node

    if isinstance(node, list):
        return [ast_to_debug_data(item, include_spans=include_spans) for item in node]

    if isinstance(node, tuple):
        return [ast_to_debug_data(item, include_spans=include_spans) for item in node]

    if is_dataclass(node):
        result: dict[str, Any] = {"node": type(node).__name__}
        for field in fields(node):
            if not include_spans and field.name == "span":
                continue
            result[field.name] = ast_to_debug_data(getattr(node, field.name), include_spans=include_spans)
        return result

    if isinstance(node, dict):
        return {str(k): ast_to_debug_data(v, include_spans=include_spans) for k, v in node.items()}

    raise TypeError(f"Unsupported AST debug serialization value: {type(node).__name__}")



def ast_to_debug_json(node: Any, *, include_spans: bool = False) -> str:
    data = ast_to_debug_data(node, include_spans=include_spans)
    return json.dumps(data, indent=2, sort_keys=True)
