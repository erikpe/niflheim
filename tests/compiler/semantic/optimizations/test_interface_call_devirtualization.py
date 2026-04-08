from __future__ import annotations

from pathlib import Path

from compiler.resolver import resolve_program
from compiler.semantic.ir import (
    IndexLValue,
    IndexReadExpr,
    InstanceMethodCallTarget,
    InterfaceMethodCallTarget,
    MethodDispatch,
    SemanticAssign,
    SemanticForIn,
    SemanticIf,
    SemanticReturn,
    SemanticVarDecl,
    SliceLValue,
    SliceReadExpr,
    VirtualMethodCallTarget,
)
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


def test_interface_call_devirtualization_rewrites_structural_interface_dispatch_after_constructor_seeded_exact_fact(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Buffer {
            fn index_get(index: i64) -> i64;
            fn index_set(index: i64, value: i64) -> unit;
            fn slice_get(begin: i64, end: i64) -> Buffer;
            fn slice_set(begin: i64, end: i64, value: Buffer) -> unit;
            fn iter_len() -> u64;
            fn iter_get(index: i64) -> i64;
        }

        class Store implements Buffer {
            fn index_get(index: i64) -> i64 {
                return index;
            }

            fn index_set(index: i64, value: i64) -> unit {
                return;
            }

            fn slice_get(begin: i64, end: i64) -> Buffer {
                return __self;
            }

            fn slice_set(begin: i64, end: i64, value: Buffer) -> unit {
                return;
            }

            fn iter_len() -> u64 {
                return 1u;
            }

            fn iter_get(index: i64) -> i64 {
                return 7;
            }
        }

        fn main() -> i64 {
            var buffer: Buffer = Store();
            var first: i64 = buffer[0];
            buffer[0] = first;
            var part: Buffer = buffer[0:1];
            buffer[0:1] = part;
            for value in buffer {
                return value;
            }
            return 0;
        }
        """,
    )

    optimized = _run_interface_call_devirtualization(tmp_path)
    statements = optimized.modules[("main",)].functions[0].body.statements

    first_decl = statements[1]
    assert isinstance(first_decl, SemanticVarDecl)
    assert isinstance(first_decl.initializer, IndexReadExpr)
    assert isinstance(first_decl.initializer.dispatch, MethodDispatch)
    assert first_decl.initializer.dispatch.method_id.class_name == "Store"
    assert first_decl.initializer.dispatch.method_id.name == "index_get"

    index_assign = statements[2]
    assert isinstance(index_assign, SemanticAssign)
    assert isinstance(index_assign.target, IndexLValue)
    assert isinstance(index_assign.target.dispatch, MethodDispatch)
    assert index_assign.target.dispatch.method_id.class_name == "Store"
    assert index_assign.target.dispatch.method_id.name == "index_set"

    slice_decl = statements[3]
    assert isinstance(slice_decl, SemanticVarDecl)
    assert isinstance(slice_decl.initializer, SliceReadExpr)
    assert isinstance(slice_decl.initializer.dispatch, MethodDispatch)
    assert slice_decl.initializer.dispatch.method_id.class_name == "Store"
    assert slice_decl.initializer.dispatch.method_id.name == "slice_get"

    slice_assign = statements[4]
    assert isinstance(slice_assign, SemanticAssign)
    assert isinstance(slice_assign.target, SliceLValue)
    assert isinstance(slice_assign.target.dispatch, MethodDispatch)
    assert slice_assign.target.dispatch.method_id.class_name == "Store"
    assert slice_assign.target.dispatch.method_id.name == "slice_set"

    loop_stmt = statements[5]
    assert isinstance(loop_stmt, SemanticForIn)
    assert isinstance(loop_stmt.iter_len_dispatch, MethodDispatch)
    assert loop_stmt.iter_len_dispatch.method_id.class_name == "Store"
    assert loop_stmt.iter_len_dispatch.method_id.name == "iter_len"
    assert isinstance(loop_stmt.iter_get_dispatch, MethodDispatch)
    assert loop_stmt.iter_get_dispatch.method_id.class_name == "Store"
    assert loop_stmt.iter_get_dispatch.method_id.name == "iter_get"


def test_interface_call_devirtualization_rewrites_virtual_method_calls_after_constructor_seeded_exact_fact(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Base {
            fn head() -> i64 {
                return 1;
            }
        }

        class Derived extends Base {
            override fn head() -> i64 {
                return 2;
            }
        }

        fn main() -> i64 {
            var value: Derived = Derived();
            return value.head();
        }
        """,
    )

    optimized = _run_interface_call_devirtualization(tmp_path)
    statements = optimized.modules[("main",)].functions[0].body.statements

    value_decl = statements[0]
    assert isinstance(value_decl, SemanticVarDecl)
    assert isinstance(value_decl.initializer.target, VirtualMethodCallTarget) is False

    return_stmt = statements[1]
    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value.target, InstanceMethodCallTarget)
    assert return_stmt.value.target.method_id.class_name == "Derived"
    assert return_stmt.value.target.method_id.name == "head"
    assert return_stmt.value.target.access.receiver_type_ref.class_id is not None
    assert return_stmt.value.target.access.receiver_type_ref.class_id.name == "Derived"


def test_interface_call_devirtualization_rewrites_structural_virtual_dispatch_after_constructor_seeded_exact_fact(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class BufferBase {
            fn index_get(index: i64) -> i64 {
                return index;
            }

            fn index_set(index: i64, value: i64) -> unit {
                return;
            }

            fn slice_get(begin: i64, end: i64) -> BufferBase {
                return __self;
            }

            fn slice_set(begin: i64, end: i64, value: BufferBase) -> unit {
                return;
            }

            fn iter_len() -> u64 {
                return 1u;
            }

            fn iter_get(index: i64) -> i64 {
                return index;
            }
        }

        class Buffer extends BufferBase {
            override fn index_get(index: i64) -> i64 {
                return index + 1;
            }

            override fn index_set(index: i64, value: i64) -> unit {
                return;
            }

            override fn slice_get(begin: i64, end: i64) -> BufferBase {
                return __self;
            }

            override fn slice_set(begin: i64, end: i64, value: BufferBase) -> unit {
                return;
            }

            override fn iter_len() -> u64 {
                return 1u;
            }

            override fn iter_get(index: i64) -> i64 {
                return 7;
            }
        }

        fn main() -> i64 {
            var buffer: Buffer = Buffer();
            var first: i64 = buffer[0];
            buffer[0] = first;
            var part: BufferBase = buffer[0:1];
            buffer[0:1] = part;
            for value in buffer {
                return value;
            }
            return 0;
        }
        """,
    )

    optimized = _run_interface_call_devirtualization(tmp_path)
    statements = optimized.modules[("main",)].functions[0].body.statements

    first_decl = statements[1]
    assert isinstance(first_decl, SemanticVarDecl)
    assert isinstance(first_decl.initializer, IndexReadExpr)
    assert isinstance(first_decl.initializer.dispatch, MethodDispatch)
    assert first_decl.initializer.dispatch.method_id.class_name == "Buffer"
    assert first_decl.initializer.dispatch.method_id.name == "index_get"

    index_assign = statements[2]
    assert isinstance(index_assign, SemanticAssign)
    assert isinstance(index_assign.target, IndexLValue)
    assert isinstance(index_assign.target.dispatch, MethodDispatch)
    assert index_assign.target.dispatch.method_id.class_name == "Buffer"
    assert index_assign.target.dispatch.method_id.name == "index_set"

    slice_decl = statements[3]
    assert isinstance(slice_decl, SemanticVarDecl)
    assert isinstance(slice_decl.initializer, SliceReadExpr)
    assert isinstance(slice_decl.initializer.dispatch, MethodDispatch)
    assert slice_decl.initializer.dispatch.method_id.class_name == "Buffer"
    assert slice_decl.initializer.dispatch.method_id.name == "slice_get"

    slice_assign = statements[4]
    assert isinstance(slice_assign, SemanticAssign)
    assert isinstance(slice_assign.target, SliceLValue)
    assert isinstance(slice_assign.target.dispatch, MethodDispatch)
    assert slice_assign.target.dispatch.method_id.class_name == "Buffer"
    assert slice_assign.target.dispatch.method_id.name == "slice_set"

    loop_stmt = statements[5]
    assert isinstance(loop_stmt, SemanticForIn)
    assert isinstance(loop_stmt.iter_len_dispatch, MethodDispatch)
    assert loop_stmt.iter_len_dispatch.method_id.class_name == "Buffer"
    assert loop_stmt.iter_len_dispatch.method_id.name == "iter_len"
    assert isinstance(loop_stmt.iter_get_dispatch, MethodDispatch)
    assert loop_stmt.iter_get_dispatch.method_id.class_name == "Buffer"
    assert loop_stmt.iter_get_dispatch.method_id.name == "iter_get"


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