from __future__ import annotations

from pathlib import Path

from compiler.resolver import resolve_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.helpers.interface_dispatch import (
    build_interface_dispatch_index,
    resolve_implementing_method,
)
from compiler.semantic.symbols import ClassId, InterfaceMethodId, MethodId


def _write(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _lower(tmp_path: Path):
    return lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))


def test_build_interface_dispatch_index_maps_same_module_interface_methods(tmp_path: Path) -> None:
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

    semantic = _lower(tmp_path)
    dispatch_index = build_interface_dispatch_index(semantic)

    method_id = resolve_implementing_method(
        dispatch_index,
        ClassId(module_path=("main",), name="Key"),
        InterfaceMethodId(module_path=("main",), interface_name="Hashable", name="hash_code"),
    )

    assert method_id == MethodId(module_path=("main",), class_name="Key", name="hash_code")


def test_build_interface_dispatch_index_maps_imported_interface_methods(tmp_path: Path) -> None:
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

    semantic = _lower(tmp_path)
    dispatch_index = build_interface_dispatch_index(semantic)

    method_id = resolve_implementing_method(
        dispatch_index,
        ClassId(module_path=("main",), name="Key"),
        InterfaceMethodId(module_path=("contracts",), interface_name="Hashable", name="hash_code"),
    )

    assert method_id == MethodId(module_path=("main",), class_name="Key", name="hash_code")


def test_build_interface_dispatch_index_maps_multiple_interface_methods_to_same_class_method(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Hashable {
            fn hash_code() -> u64;
        }

        interface Identified {
            fn hash_code() -> u64;
        }

        class Key implements Hashable, Identified {
            fn hash_code() -> u64 {
                return 1u;
            }
        }

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    semantic = _lower(tmp_path)
    dispatch_index = build_interface_dispatch_index(semantic)

    hashable_method_id = resolve_implementing_method(
        dispatch_index,
        ClassId(module_path=("main",), name="Key"),
        InterfaceMethodId(module_path=("main",), interface_name="Hashable", name="hash_code"),
    )
    identified_method_id = resolve_implementing_method(
        dispatch_index,
        ClassId(module_path=("main",), name="Key"),
        InterfaceMethodId(module_path=("main",), interface_name="Identified", name="hash_code"),
    )

    expected = MethodId(module_path=("main",), class_name="Key", name="hash_code")
    assert hashable_method_id == expected
    assert identified_method_id == expected


def test_build_interface_dispatch_index_maps_inherited_interface_method_to_base_method(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Hashable {
            fn hash_code() -> u64;
        }

        class Base implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }

        class Derived extends Base {
        }

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    semantic = _lower(tmp_path)
    dispatch_index = build_interface_dispatch_index(semantic)

    method_id = resolve_implementing_method(
        dispatch_index,
        ClassId(module_path=("main",), name="Derived"),
        InterfaceMethodId(module_path=("main",), interface_name="Hashable", name="hash_code"),
    )

    assert method_id == MethodId(module_path=("main",), class_name="Base", name="hash_code")