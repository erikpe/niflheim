from __future__ import annotations

from pathlib import Path

from compiler.resolver import resolve_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.helpers.type_compatibility import (
    build_type_compatibility_index,
    class_implements_interface,
    exact_type_implies_runtime_compatibility,
    is_exact_runtime_target,
    proven_compatible_type_names,
)
from compiler.semantic.symbols import ClassId, InterfaceId
from compiler.semantic.types import (
    semantic_array_type_ref,
    semantic_null_type_ref,
    semantic_primitive_type_ref,
    semantic_type_ref_for_class_id,
    semantic_type_ref_for_interface_id,
    semantic_type_ref_from_type_info,
)
from compiler.typecheck.model import TypeInfo


def _write(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _obj_type_ref():
    return semantic_type_ref_from_type_info(("main",), TypeInfo(name="Obj", kind="reference"))


def test_build_type_compatibility_index_tracks_implemented_interfaces_by_ids(tmp_path: Path) -> None:
    _write(
        tmp_path / "contracts.nif",
        """
        export interface Hashable {
            fn hash_code() -> u64;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import contracts;

        class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    compatibility_index = build_type_compatibility_index(semantic)
    key_id = ClassId(module_path=("main",), name="Key")
    hashable_id = InterfaceId(module_path=("contracts",), name="Hashable")

    assert class_implements_interface(compatibility_index, key_id, hashable_id) is True


def test_exact_type_implies_runtime_compatibility_for_class_obj_and_interface(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Hashable {
            fn hash_code() -> u64;
        }

        interface Equalable {
            fn equals(other: Obj) -> bool;
        }

        class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }

        class Box {
            value: i64;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    compatibility_index = build_type_compatibility_index(semantic)
    key_type_ref = semantic_type_ref_for_class_id(ClassId(module_path=("main",), name="Key"))
    box_type_ref = semantic_type_ref_for_class_id(ClassId(module_path=("main",), name="Box"))
    hashable_type_ref = semantic_type_ref_for_interface_id(InterfaceId(module_path=("main",), name="Hashable"))
    equalable_type_ref = semantic_type_ref_for_interface_id(InterfaceId(module_path=("main",), name="Equalable"))

    assert exact_type_implies_runtime_compatibility(compatibility_index, key_type_ref, key_type_ref) is True
    assert exact_type_implies_runtime_compatibility(compatibility_index, key_type_ref, _obj_type_ref()) is True
    assert exact_type_implies_runtime_compatibility(compatibility_index, key_type_ref, hashable_type_ref) is True
    assert exact_type_implies_runtime_compatibility(compatibility_index, key_type_ref, box_type_ref) is False
    assert exact_type_implies_runtime_compatibility(compatibility_index, key_type_ref, equalable_type_ref) is False


def test_exact_type_implies_runtime_compatibility_for_arrays(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Hashable {
            fn hash_code() -> u64;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    compatibility_index = build_type_compatibility_index(semantic)
    array_type_ref = semantic_array_type_ref(semantic_primitive_type_ref("i64"))
    hashable_type_ref = semantic_type_ref_for_interface_id(InterfaceId(module_path=("main",), name="Hashable"))

    assert exact_type_implies_runtime_compatibility(compatibility_index, array_type_ref, array_type_ref) is True
    assert exact_type_implies_runtime_compatibility(compatibility_index, array_type_ref, _obj_type_ref()) is True
    assert exact_type_implies_runtime_compatibility(compatibility_index, array_type_ref, hashable_type_ref) is False


def test_type_compatibility_helpers_handle_null_conservatively(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Hashable {
            fn hash_code() -> u64;
        }

        class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    compatibility_index = build_type_compatibility_index(semantic)
    null_type_ref = semantic_null_type_ref()
    key_type_ref = semantic_type_ref_for_class_id(ClassId(module_path=("main",), name="Key"))
    hashable_type_ref = semantic_type_ref_for_interface_id(InterfaceId(module_path=("main",), name="Hashable"))

    assert is_exact_runtime_target(null_type_ref) is False
    assert exact_type_implies_runtime_compatibility(compatibility_index, null_type_ref, _obj_type_ref()) is False
    assert exact_type_implies_runtime_compatibility(compatibility_index, null_type_ref, key_type_ref) is False
    assert exact_type_implies_runtime_compatibility(compatibility_index, null_type_ref, hashable_type_ref) is False


def test_proven_compatible_type_names_include_implied_interfaces_and_obj(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Hashable {
            fn hash_code() -> u64;
        }

        class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    compatibility_index = build_type_compatibility_index(semantic)
    key_type_ref = semantic_type_ref_for_class_id(ClassId(module_path=("main",), name="Key"))
    hashable_type_ref = semantic_type_ref_for_interface_id(InterfaceId(module_path=("main",), name="Hashable"))

    assert proven_compatible_type_names(compatibility_index, key_type_ref) == frozenset(
        {"main::Key", "main::Hashable", "Obj"}
    )
    assert proven_compatible_type_names(compatibility_index, hashable_type_ref) == frozenset(
        {"main::Hashable", "Obj"}
    )