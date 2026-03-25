from __future__ import annotations

from pathlib import Path

import pytest

from compiler.resolver import resolve_program
from compiler.semantic.ir import local_display_name_for_owner, local_type_name_for_owner, require_local_info_for_owner
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.symbols import LocalId


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_lower_program_records_function_local_metadata_by_local_id(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn sum(values: i64[]) -> i64 {
            var total: i64 = 0;
            for item in values {
                total = total + item;
            }
            return total;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    function = semantic.modules[("main",)].functions[0]

    total_decl = function.body.statements[0]
    loop_stmt = function.body.statements[1]
    return_stmt = function.body.statements[2]

    values_info = next(local_info for local_info in function.local_info_by_id.values() if local_info.display_name == "values")
    total_info = require_local_info_for_owner(function, total_decl.local_id)
    item_ref = loop_stmt.body.statements[0].value.right
    item_info = require_local_info_for_owner(function, item_ref.local_id)

    assert total_decl.name is None
    assert total_decl.type_name is None
    assert total_decl.type_ref is None
    assert values_info.binding_kind == "param"
    assert values_info.type_name == "i64[]"
    assert total_info.display_name == "total"
    assert total_info.binding_kind == "local"
    assert local_type_name_for_owner(function, total_decl.local_id) == "i64"
    assert item_info.display_name == "item"
    assert item_info.binding_kind == "for_in_element"
    assert local_display_name_for_owner(function, return_stmt.value.local_id) == "total"


def test_lower_program_records_method_receiver_metadata(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Counter {
            value: i64;

            fn add(delta: i64) -> i64 {
                return __self.value + delta;
            }
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    method = semantic.modules[("main",)].classes[0].methods[0]

    receiver_info = next(local_info for local_info in method.local_info_by_id.values() if local_info.display_name == "__self")
    delta_info = next(local_info for local_info in method.local_info_by_id.values() if local_info.display_name == "delta")

    assert receiver_info.binding_kind == "receiver"
    assert receiver_info.type_name == "Counter"
    assert delta_info.binding_kind == "param"
    assert delta_info.owner_id == method.method_id


def test_require_local_info_for_owner_rejects_unknown_local_id(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main(x: i64) -> i64 {
            return x;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    function = semantic.modules[("main",)].functions[0]

    with pytest.raises(KeyError, match="Missing semantic local metadata"):
        require_local_info_for_owner(function, LocalId(owner_id=function.function_id, ordinal=99))