from __future__ import annotations

from pathlib import Path

from compiler.resolver import resolve_program
from compiler.codegen.linker import build_codegen_program
from compiler.semantic.lowering import lower_program
from compiler.semantic.reachability import analyze_semantic_reachability, prune_unreachable_semantic
from compiler.semantic.symbols import ClassId, FunctionId, MethodId


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_semantic_reachability_follows_functions_methods_and_structural_edges(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Buffer {
            fn iter_len() -> u64 {
                return 1u;
            }

            fn iter_get(index: i64) -> i64 {
                return index;
            }

            fn dead() -> i64 {
                return 99;
            }
        }

        fn helper(value: i64) -> i64 {
            return value + 1;
        }

        fn dead_helper() -> i64 {
            return 0;
        }

        fn main(buffer: Buffer) -> i64 {
            for value in buffer {
                return helper(value);
            }
            return 0;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    reachability = analyze_semantic_reachability(semantic)

    assert FunctionId(module_path=("main",), name="main") in reachability.reachable_functions
    assert FunctionId(module_path=("main",), name="helper") in reachability.reachable_functions
    assert FunctionId(module_path=("main",), name="dead_helper") not in reachability.reachable_functions

    assert ClassId(module_path=("main",), name="Buffer") in reachability.reachable_classes

    assert MethodId(module_path=("main",), class_name="Buffer", name="iter_len") in reachability.reachable_methods
    assert MethodId(module_path=("main",), class_name="Buffer", name="iter_get") in reachability.reachable_methods
    assert MethodId(module_path=("main",), class_name="Buffer", name="dead") not in reachability.reachable_methods


def test_prune_unreachable_semantic_program_drops_dead_functions_and_methods(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Box {
            value: i64;

            static fn make(value: i64) -> Box {
                return Box(value);
            }

            fn read() -> i64 {
                return __self.value;
            }

            fn dead() -> i64 {
                return 99;
            }
        }

        fn helper() -> i64 {
            return 1;
        }

        fn dead_helper() -> i64 {
            return 7;
        }

        fn main() -> i64 {
            var box: Box = Box.make(helper());
            return box.read();
        }
        """,
    )

    pruned = prune_unreachable_semantic(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    module = pruned.modules[("main",)]

    assert [fn.function_id.name for fn in module.functions] == ["helper", "main"]
    assert [cls.class_id.name for cls in module.classes] == ["Box"]
    assert [method.method_id.name for method in module.classes[0].methods] == ["make", "read"]


def test_prune_unreachable_semantic_program_removes_dead_duplicate_class_symbols_before_link(tmp_path: Path) -> None:
    _write(
        tmp_path / "left.nif",
        """
        export class Box {
            value: i64;
        }
        """,
    )
    _write(
        tmp_path / "right.nif",
        """
        export class Box {
            value: i64;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import left;
        import right;

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    pruned = prune_unreachable_semantic(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    linked = build_codegen_program(pruned)

    assert [cls.class_id.name for cls in linked.classes] == []
    assert [fn.function_id.name for fn in linked.functions] == ["main"]
