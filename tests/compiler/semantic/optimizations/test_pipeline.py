from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from compiler.common.collection_protocols import CollectionOpKind
from compiler.resolver import resolve_program
from compiler.semantic.ir import (
    CallExprS,
    FunctionCallTarget,
    InterfaceMethodCallTarget,
    IndexReadExpr,
    InstanceMethodCallTarget,
    IntConstant,
    LiteralExprS,
    MethodDispatch,
    RuntimeDispatch,
    SemanticForIn,
    SemanticIf,
    SemanticReturn,
    SemanticVarDecl,
    SemanticWhile,
    VirtualMethodCallTarget,
)
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowering.executable import LoweredSemanticForInStrategy, lower_linked_semantic_program
from compiler.semantic.lowered_ir import LoweredSemanticForIn
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.copy_propagation import copy_propagation
from compiler.semantic.optimizations.constant_fold import constant_fold
from compiler.semantic.optimizations.dead_store_elimination import dead_store_elimination
from compiler.semantic.optimizations.dead_stmt_prune import dead_stmt_prune
from compiler.semantic.optimizations.flow_sensitive_type_narrowing import flow_sensitive_type_narrowing
from compiler.semantic.optimizations.interface_call_devirtualization import interface_call_devirtualization
from compiler.semantic.optimizations.pipeline import (
    DEFAULT_SEMANTIC_OPTIMIZATION_PASSES,
    SemanticOptimizationPass,
    optimize_semantic_program,
)
from compiler.semantic.optimizations.unreachable_prune import unreachable_prune
from compiler.semantic.optimizations.redundant_cast_elimination import redundant_cast_elimination
from compiler.semantic.optimizations.simplify_control_flow import simplify_control_flow
from compiler.semantic.symbols import MethodId


def _write(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _erased_array_method_dispatch(method_name: str) -> MethodDispatch:
    return MethodDispatch(method_id=MethodId(module_path=("main",), class_name="ErasedArray", name=method_name))


def _erase_array_structural_dispatches(program):
    module = program.modules[("main",)]
    fn = module.functions[0]
    statements = list(fn.body.statements)
    loop_stmt = next(stmt for stmt in statements if isinstance(stmt, SemanticForIn))
    loop_index = statements.index(loop_stmt)
    statements[loop_index] = replace(
        loop_stmt,
        iter_len_dispatch=_erased_array_method_dispatch("iter_len"),
        iter_get_dispatch=_erased_array_method_dispatch("iter_get"),
    )
    rewritten_fn = replace(fn, body=replace(fn.body, statements=statements))
    rewritten_module = replace(module, functions=[rewritten_fn])
    return replace(program, modules={**program.modules, ("main",): rewritten_module})


def test_optimize_semantic_program_uses_default_pass_pipeline(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn dead() -> i64 {
            return 7;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))

    optimized = optimize_semantic_program(semantic)
    expected = unreachable_prune(
        dead_stmt_prune(
            simplify_control_flow(
                constant_fold(
                    dead_store_elimination(
                        redundant_cast_elimination(
                            interface_call_devirtualization(
                                flow_sensitive_type_narrowing(copy_propagation(simplify_control_flow(constant_fold(semantic))))
                            )
                        )
                    )
                )
            )
        )
    )

    assert [optimization_pass.name for optimization_pass in DEFAULT_SEMANTIC_OPTIMIZATION_PASSES] == [
        "constant_fold",
        "simplify_control_flow",
        "copy_propagation",
        "flow_sensitive_type_narrowing",
        "interface_call_devirtualization",
        "redundant_cast_elimination",
        "dead_store_elimination",
        "constant_fold",
        "simplify_control_flow",
        "dead_stmt_prune",
        "unreachable_prune",
    ]
    assert optimized == expected


def test_optimize_semantic_program_applies_passes_in_order(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    applied: list[str] = []

    def record_first(program):
        applied.append("first")
        return program

    def record_second(program):
        applied.append("second")
        return program

    optimized = optimize_semantic_program(
        semantic,
        passes=(
            SemanticOptimizationPass(name="first", transform=record_first),
            SemanticOptimizationPass(name="second", transform=record_second),
        ),
    )

    assert optimized == semantic
    assert applied == ["first", "second"]


def test_optimize_semantic_program_folds_constants_before_pruning(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn helper(value: i64) -> i64 {
            return value;
        }

        fn main() -> i64 {
            return helper(1 + 2);
        }
        """,
    )

    optimized = optimize_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    return_stmt = optimized.modules[("main",)].functions[1].body.statements[0]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, CallExprS)
    assert isinstance(return_stmt.value.target, FunctionCallTarget)
    assert isinstance(return_stmt.value.args[0], LiteralExprS)
    assert isinstance(return_stmt.value.args[0].constant, IntConstant)
    assert return_stmt.value.args[0].constant.value == 3


def test_optimize_semantic_program_devirtualizes_interface_calls_after_narrowing(tmp_path: Path) -> None:
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
                var hashable: Hashable = (Hashable)value;
                return hashable.hash_code();
            }
            return 0u;
        }
        """,
    )

    optimized = optimize_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    if_stmt = optimized.modules[("main",)].functions[0].body.statements[0]

    assert isinstance(if_stmt, SemanticIf)
    assert isinstance(if_stmt.then_block.statements[1], SemanticReturn)
    assert isinstance(if_stmt.then_block.statements[1].value, CallExprS)
    assert isinstance(if_stmt.then_block.statements[1].value.target, InstanceMethodCallTarget)
    assert if_stmt.then_block.statements[1].value.target.method_id.name == "hash_code"
    assert if_stmt.then_block.statements[1].value.target.access.receiver_type_ref.class_id is not None
    assert if_stmt.then_block.statements[1].value.target.access.receiver_type_ref.class_id.name == "Key"


def test_optimize_semantic_program_devirtualizes_interface_calls_after_constructor_seeded_exact_fact(tmp_path: Path) -> None:
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

    optimized = optimize_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    return_stmt = optimized.modules[("main",)].functions[0].body.statements[1]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, CallExprS)
    assert isinstance(return_stmt.value.target, InstanceMethodCallTarget)
    assert return_stmt.value.target.method_id.name == "hash_code"
    assert return_stmt.value.target.access.receiver_type_ref.class_id is not None
    assert return_stmt.value.target.access.receiver_type_ref.class_id.name == "Key"


def test_optimize_semantic_program_specializes_structural_interface_dispatch_after_constructor_seeded_exact_fact(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Buffer {
            fn index_get(index: i64) -> i64;
            fn iter_len() -> u64;
            fn iter_get(index: i64) -> i64;
        }

        class Store implements Buffer {
            fn index_get(index: i64) -> i64 {
                return index;
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
            for value in buffer {
                return value + first;
            }
            return 0;
        }
        """,
    )

    optimized = optimize_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    statements = optimized.modules[("main",)].functions[0].body.statements

    first_decl = statements[1]
    assert isinstance(first_decl, SemanticVarDecl)
    assert isinstance(first_decl.initializer, IndexReadExpr)
    assert isinstance(first_decl.initializer.dispatch, MethodDispatch)
    assert first_decl.initializer.dispatch.method_id.class_name == "Store"
    assert first_decl.initializer.dispatch.method_id.name == "index_get"

    loop_stmt = statements[2]
    assert isinstance(loop_stmt, SemanticForIn)
    assert isinstance(loop_stmt.iter_len_dispatch, MethodDispatch)
    assert loop_stmt.iter_len_dispatch.method_id.class_name == "Store"
    assert loop_stmt.iter_len_dispatch.method_id.name == "iter_len"
    assert isinstance(loop_stmt.iter_get_dispatch, MethodDispatch)
    assert loop_stmt.iter_get_dispatch.method_id.class_name == "Store"
    assert loop_stmt.iter_get_dispatch.method_id.name == "iter_get"


def test_optimize_semantic_program_devirtualizes_virtual_calls_after_constructor_seeded_exact_fact(
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

    optimized = optimize_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    return_stmt = optimized.modules[("main",)].functions[0].body.statements[1]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, CallExprS)
    assert isinstance(return_stmt.value.target, InstanceMethodCallTarget)
    assert return_stmt.value.target.method_id.class_name == "Derived"
    assert return_stmt.value.target.method_id.name == "head"


def test_optimize_semantic_program_specializes_structural_virtual_dispatch_after_constructor_seeded_exact_fact(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class BufferBase {
            fn index_get(index: i64) -> i64 {
                return index;
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
            for value in buffer {
                return value + first;
            }
            return 0;
        }
        """,
    )

    optimized = optimize_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    statements = optimized.modules[("main",)].functions[0].body.statements

    first_decl = statements[1]
    assert isinstance(first_decl, SemanticVarDecl)
    assert isinstance(first_decl.initializer, IndexReadExpr)
    assert isinstance(first_decl.initializer.dispatch, MethodDispatch)
    assert first_decl.initializer.dispatch.method_id.class_name == "Buffer"
    assert first_decl.initializer.dispatch.method_id.name == "index_get"

    loop_stmt = statements[2]
    assert isinstance(loop_stmt, SemanticForIn)
    assert isinstance(loop_stmt.iter_len_dispatch, MethodDispatch)
    assert loop_stmt.iter_len_dispatch.method_id.class_name == "Buffer"
    assert loop_stmt.iter_len_dispatch.method_id.name == "iter_len"
    assert isinstance(loop_stmt.iter_get_dispatch, MethodDispatch)
    assert loop_stmt.iter_get_dispatch.method_id.class_name == "Buffer"
    assert loop_stmt.iter_get_dispatch.method_id.name == "iter_get"


def test_optimize_semantic_program_devirtualizes_non_local_exact_virtual_receiver_expression(
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
            return Derived().head();
        }
        """,
    )

    optimized = optimize_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    return_stmt = optimized.modules[("main",)].functions[0].body.statements[0]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, CallExprS)
    assert isinstance(return_stmt.value.target, InstanceMethodCallTarget)
    assert return_stmt.value.target.method_id.class_name == "Derived"
    assert return_stmt.value.target.method_id.name == "head"


def test_optimize_semantic_program_specializes_non_local_exact_structural_interface_receiver_expression(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Buffer {
            fn index_get(index: i64) -> i64;
        }

        class Store implements Buffer {
            fn index_get(index: i64) -> i64 {
                return index;
            }
        }

        fn main() -> i64 {
            return ((Buffer)Store())[0];
        }
        """,
    )

    optimized = optimize_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    return_stmt = optimized.modules[("main",)].functions[0].body.statements[0]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, IndexReadExpr)
    assert isinstance(return_stmt.value.dispatch, MethodDispatch)
    assert return_stmt.value.dispatch.method_id.class_name == "Store"
    assert return_stmt.value.dispatch.method_id.name == "index_get"


def test_optimize_semantic_program_keeps_unknown_function_receiver_virtual_dispatch_dynamic(
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

        fn choose(flag: bool) -> Base {
            if flag {
                return Derived();
            }
            return Base();
        }

        fn main(flag: bool) -> i64 {
            return choose(flag).head();
        }
        """,
    )

    optimized = optimize_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    return_stmt = optimized.modules[("main",)].functions[1].body.statements[0]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, CallExprS)
    assert return_stmt.value.target.__class__.__name__ == "VirtualMethodCallTarget"


def test_optimize_semantic_program_devirtualizes_interface_calls_inside_while_loop_when_receiver_stays_exact(
    tmp_path: Path,
) -> None:
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

        fn main(value: Obj, keep_looping: bool) -> u64 {
            var key: Key = (Key)value;
            var hashable: Hashable = key;
            while keep_looping {
                return hashable.hash_code();
            }
            return 0u;
        }
        """,
    )

    optimized = optimize_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    loop_stmt = next(
        stmt for stmt in optimized.modules[("main",)].functions[0].body.statements if isinstance(stmt, SemanticWhile)
    )

    assert isinstance(loop_stmt, SemanticWhile)
    assert isinstance(loop_stmt.body.statements[0], SemanticReturn)
    assert isinstance(loop_stmt.body.statements[0].value, CallExprS)
    assert isinstance(loop_stmt.body.statements[0].value.target, InstanceMethodCallTarget)
    assert loop_stmt.body.statements[0].value.target.method_id.class_name == "Key"
    assert loop_stmt.body.statements[0].value.target.method_id.name == "hash_code"


def test_optimize_semantic_program_devirtualizes_virtual_calls_inside_for_in_loop_when_receiver_stays_exact(
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

        fn main(items: i64[]) -> i64 {
            var current: Derived = Derived();
            for item in items {
                return current.head();
            }
            return 0;
        }
        """,
    )

    optimized = optimize_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    loop_stmt = next(
        stmt for stmt in optimized.modules[("main",)].functions[0].body.statements if isinstance(stmt, SemanticForIn)
    )

    assert isinstance(loop_stmt, SemanticForIn)
    assert isinstance(loop_stmt.body.statements[0], SemanticReturn)
    assert isinstance(loop_stmt.body.statements[0].value, CallExprS)
    assert isinstance(loop_stmt.body.statements[0].value.target, InstanceMethodCallTarget)
    assert loop_stmt.body.statements[0].value.target.method_id.class_name == "Derived"
    assert loop_stmt.body.statements[0].value.target.method_id.name == "head"


def test_optimize_semantic_program_keeps_loop_reassignment_interface_dispatch_dynamic(tmp_path: Path) -> None:
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

        fn main(value: Obj, fallback: Hashable, keep_looping: bool) -> u64 {
            var key: Key = (Key)value;
            var hashable: Hashable = key;
            while keep_looping {
                hashable = fallback;
                return hashable.hash_code();
            }
            return 0u;
        }
        """,
    )

    optimized = optimize_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    loop_stmt = next(
        stmt for stmt in optimized.modules[("main",)].functions[0].body.statements if isinstance(stmt, SemanticWhile)
    )

    assert isinstance(loop_stmt, SemanticWhile)
    assert isinstance(loop_stmt.body.statements[-1], SemanticReturn)
    assert isinstance(loop_stmt.body.statements[-1].value, CallExprS)
    assert isinstance(loop_stmt.body.statements[-1].value.target, InterfaceMethodCallTarget)
    assert not isinstance(loop_stmt.body.statements[-1].value.target, InstanceMethodCallTarget)


def test_optimize_semantic_program_keeps_loop_reassignment_virtual_dispatch_dynamic(tmp_path: Path) -> None:
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

        fn main(replacement: Derived, keep_looping: bool) -> i64 {
            var current: Derived = Derived();
            while keep_looping {
                current = replacement;
                return current.head();
            }
            return 0;
        }
        """,
    )

    optimized = optimize_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    loop_stmt = next(
        stmt for stmt in optimized.modules[("main",)].functions[0].body.statements if isinstance(stmt, SemanticWhile)
    )

    assert isinstance(loop_stmt, SemanticWhile)
    assert isinstance(loop_stmt.body.statements[-1], SemanticReturn)
    assert isinstance(loop_stmt.body.statements[-1].value, CallExprS)
    assert isinstance(loop_stmt.body.statements[-1].value.target, VirtualMethodCallTarget)


def test_optimize_semantic_program_recovers_array_direct_for_in_after_dispatch_erasure(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var values: i64[] = i64[](2u);
            values[0] = 4;
            values[1] = 6;

            var sum: i64 = 0;
            for value in values {
                sum = sum + value;
            }

            return sum;
        }
        """,
    )

    optimized = optimize_semantic_program(
        lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)),
        passes=(
            SemanticOptimizationPass(name="erase_array_dispatches", transform=_erase_array_structural_dispatches),
            *DEFAULT_SEMANTIC_OPTIMIZATION_PASSES,
        ),
    )
    loop_stmt = next(stmt for stmt in optimized.modules[("main",)].functions[0].body.statements if isinstance(stmt, SemanticForIn))

    assert isinstance(loop_stmt.iter_len_dispatch, RuntimeDispatch)
    assert loop_stmt.iter_len_dispatch.operation is CollectionOpKind.ITER_LEN
    assert isinstance(loop_stmt.iter_get_dispatch, RuntimeDispatch)
    assert loop_stmt.iter_get_dispatch.operation is CollectionOpKind.ITER_GET

    lowered = lower_linked_semantic_program(link_semantic_program(optimized))
    lowered_loop = next(stmt for stmt in lowered.functions[0].body.statements if isinstance(stmt, LoweredSemanticForIn))

    assert lowered_loop.strategy is LoweredSemanticForInStrategy.ARRAY_DIRECT
    assert isinstance(lowered_loop.iter_len_dispatch, RuntimeDispatch)
    assert isinstance(lowered_loop.iter_get_dispatch, RuntimeDispatch)
