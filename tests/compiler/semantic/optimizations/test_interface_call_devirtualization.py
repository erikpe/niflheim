from __future__ import annotations

from pathlib import Path

from compiler.resolver import resolve_program
from compiler.semantic.ir import InterfaceMethodCallTarget, InstanceMethodCallTarget, SemanticIf, SemanticReturn
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.interface_call_devirtualization import interface_call_devirtualization


def _write(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _run_interface_call_devirtualization(tmp_path: Path):
    return interface_call_devirtualization(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))


def test_interface_call_devirtualization_rewrites_inside_positive_exact_type_branch(tmp_path: Path) -> None:
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

        fn main(value: Obj) -> u64 {
            if value is Key {
                var key: Key = (Key)value;
                var hashable: Hashable = key;
                return hashable.hash_code();
            }
            return 0u;
        }
        """,
    )

    optimized = _run_interface_call_devirtualization(tmp_path)
    if_stmt = optimized.modules[("main",)].functions[0].body.statements[0]

    assert isinstance(if_stmt, SemanticIf)
    assert isinstance(if_stmt.then_block.statements[2], SemanticReturn)
    assert isinstance(if_stmt.then_block.statements[2].value.target, InstanceMethodCallTarget)
    assert if_stmt.then_block.statements[2].value.target.method_id.name == "hash_code"
    assert if_stmt.then_block.statements[2].value.target.access.receiver_type_ref.class_id == if_stmt.then_block.statements[0].initializer.target_type_ref.class_id


def test_interface_call_devirtualization_rewrites_after_successful_checked_cast(tmp_path: Path) -> None:
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

        fn main(value: Obj) -> u64 {
            var key: Key = (Key)value;
            var hashable: Hashable = key;
            return hashable.hash_code();
        }
        """,
    )

    optimized = _run_interface_call_devirtualization(tmp_path)
    return_stmt = optimized.modules[("main",)].functions[0].body.statements[2]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value.target, InstanceMethodCallTarget)
    assert return_stmt.value.target.method_id.name == "hash_code"
    assert return_stmt.value.target.access.receiver_type_ref.class_id is not None
    assert return_stmt.value.target.access.receiver_type_ref.class_id.name == "Key"


def test_interface_call_devirtualization_rewrites_after_constructor_seeded_exact_fact(tmp_path: Path) -> None:
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

        fn main() -> u64 {
            var hashable: Hashable = Key();
            return hashable.hash_code();
        }
        """,
    )

    optimized = _run_interface_call_devirtualization(tmp_path)
    return_stmt = optimized.modules[("main",)].functions[0].body.statements[1]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value.target, InstanceMethodCallTarget)
    assert return_stmt.value.target.method_id.name == "hash_code"
    assert return_stmt.value.target.access.receiver_type_ref.class_id is not None
    assert return_stmt.value.target.access.receiver_type_ref.class_id.name == "Key"


def test_interface_call_devirtualization_keeps_interface_dispatch_after_merge_that_loses_exactness(tmp_path: Path) -> None:
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

        fn main(flag: bool, source: Obj, fallback: Hashable) -> u64 {
            var hashable: Hashable = fallback;
            if flag {
                var key: Key = (Key)source;
                hashable = key;
            }
            return hashable.hash_code();
        }
        """,
    )

    optimized = _run_interface_call_devirtualization(tmp_path)
    return_stmt = optimized.modules[("main",)].functions[0].body.statements[2]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value.target, InterfaceMethodCallTarget)


def test_interface_call_devirtualization_invalidates_exact_receiver_after_reassignment(tmp_path: Path) -> None:
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

        fn main(first: Obj, second: Hashable) -> u64 {
            var key: Key = (Key)first;
            var hashable: Hashable = key;
            hashable = second;
            return hashable.hash_code();
        }
        """,
    )

    optimized = _run_interface_call_devirtualization(tmp_path)
    return_stmt = optimized.modules[("main",)].functions[0].body.statements[3]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value.target, InterfaceMethodCallTarget)


def test_interface_call_devirtualization_requires_exact_receiver_type_not_interface_compatibility(tmp_path: Path) -> None:
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

        fn main(value: Obj) -> u64 {
            if value is Hashable {
                var hashable: Hashable = (Hashable)value;
                return hashable.hash_code();
            }
            return 0u;
        }
        """,
    )

    optimized = _run_interface_call_devirtualization(tmp_path)
    if_stmt = optimized.modules[("main",)].functions[0].body.statements[0]

    assert isinstance(if_stmt, SemanticIf)
    assert isinstance(if_stmt.then_block.statements[1], SemanticReturn)
    assert isinstance(if_stmt.then_block.statements[1].value.target, InterfaceMethodCallTarget)