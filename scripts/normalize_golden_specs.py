#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString


REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_ROOT = REPO_ROOT / "tests" / "golden"
MAX_FLOW_SEQUENCE_LENGTH = 120
MAX_FLOW_RUN_ENTRY_LENGTH = 120


def _is_simple_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _inline_length(seq: list[Any]) -> int:
    parts: list[str] = []
    for item in seq:
        parts.append(json.dumps(item) if isinstance(item, str) else str(item))
    return len("[" + ", ".join(parts) + "]")


def _should_use_flow_style(seq: list[Any]) -> bool:
    if not seq:
        return True
    if not all(_is_simple_scalar(item) for item in seq):
        return False
    if any(isinstance(item, str) and "\n" in item for item in seq):
        return False
    return _inline_length(seq) <= MAX_FLOW_SEQUENCE_LENGTH


def _render_inline(node: Any) -> str | None:
    if isinstance(node, str):
        return json.dumps(node)
    if node is None:
        return "null"
    if isinstance(node, bool):
        return "true" if node else "false"
    if isinstance(node, (int, float)):
        return str(node)
    if isinstance(node, CommentedSeq):
        rendered_items: list[str] = []
        for item in node:
            rendered = _render_inline(item)
            if rendered is None:
                return None
            rendered_items.append(rendered)
        return "[" + ", ".join(rendered_items) + "]"
    if isinstance(node, CommentedMap):
        rendered_items: list[str] = []
        for key, value in node.items():
            if not isinstance(key, str):
                return None
            rendered_value = _render_inline(value)
            if rendered_value is None:
                return None
            rendered_items.append(f"{key}: {rendered_value}")
        return "{ " + ", ".join(rendered_items) + " }"
    return None


def _should_use_flow_run_entry(node: CommentedMap) -> bool:
    rendered = _render_inline(node)
    if rendered is None:
        return False
    return len(rendered) <= MAX_FLOW_RUN_ENTRY_LENGTH


def _set_flow_style_recursive(node: Any) -> None:
    if isinstance(node, CommentedMap):
        node.fa.set_flow_style()
        for value in node.values():
            _set_flow_style_recursive(value)
        return

    if isinstance(node, CommentedSeq):
        node.fa.set_flow_style()
        for item in node:
            _set_flow_style_recursive(item)


def _normalize(node: Any, *, parent_key: str | None = None) -> Any:
    if isinstance(node, CommentedMap):
        node.fa.set_block_style()
        for key in list(node.keys()):
            child_parent_key = key if isinstance(key, str) else None
            node[key] = _normalize(node[key], parent_key=child_parent_key)
        if parent_key == "run_entry" and _should_use_flow_run_entry(node):
            _set_flow_style_recursive(node)
        return node

    if isinstance(node, CommentedSeq):
        for index, item in enumerate(list(node)):
            child_parent_key = "run_entry" if parent_key == "runs" else None
            node[index] = _normalize(item, parent_key=child_parent_key)

        if _should_use_flow_style(list(node)):
            node.fa.set_flow_style()
        else:
            node.fa.set_block_style()
        return node

    if isinstance(node, str):
        return DoubleQuotedScalarString(node)

    return node


def normalize_spec_file(path: Path, yaml: YAML) -> bool:
    original = path.read_text(encoding="utf-8")
    data = yaml.load(original)
    normalized = _normalize(data)

    from io import StringIO

    buffer = StringIO()
    yaml.dump(normalized, buffer)
    updated = buffer.getvalue()

    if updated != original:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def discover_specs(root: Path) -> list[Path]:
    return sorted(path for path in root.glob("**/test_*_spec.yaml") if path.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize golden spec YAML formatting.")
    parser.add_argument(
        "--root",
        default=str(GOLDEN_ROOT),
        help="Root directory containing golden spec YAML files.",
    )
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        raise FileNotFoundError(f"Golden root does not exist: {root}")

    yaml = YAML()
    yaml.preserve_quotes = False
    yaml.default_flow_style = False
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)

    changed = 0
    for spec_path in discover_specs(root):
        if normalize_spec_file(spec_path, yaml):
            changed += 1
            print(f"normalized {spec_path.relative_to(REPO_ROOT)}")

    print(f"normalized {changed} spec files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())