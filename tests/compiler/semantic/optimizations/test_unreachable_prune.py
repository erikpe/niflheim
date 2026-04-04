from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from compiler.common.collection_protocols import CollectionOpKind, collection_method_name
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.unreachable_prune import analyze_semantic_reachability, unreachable_prune
from compiler.semantic.symbols import ClassId, FunctionId, InterfaceId, MethodId


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

    assert (
        MethodId(module_path=("main",), class_name="Buffer", name=collection_method_name(CollectionOpKind.ITER_LEN))
        in reachability.reachable_methods
    )
    assert (
        MethodId(module_path=("main",), class_name="Buffer", name=collection_method_name(CollectionOpKind.ITER_GET))
        in reachability.reachable_methods
    )
    assert MethodId(module_path=("main",), class_name="Buffer", name="dead") in reachability.reachable_methods


def test_unreachable_prune_program_drops_dead_functions_and_methods(tmp_path: Path) -> None:
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

    pruned = unreachable_prune(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    module = pruned.modules[("main",)]

    assert [fn.function_id.name for fn in module.functions] == ["helper", "main"]
    assert [cls.class_id.name for cls in module.classes] == ["Box"]
    assert [method.method_id.name for method in module.classes[0].methods] == ["make", "read", "dead"]


def test_unreachable_prune_removes_dead_duplicate_class_symbols_before_link(tmp_path: Path) -> None:
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

    pruned = unreachable_prune(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    linked = link_semantic_program(pruned)

    assert [cls.class_id.name for cls in linked.classes] == []
    assert [fn.function_id.name for fn in linked.functions] == ["main"]


def test_semantic_reachability_follows_canonical_type_refs_on_declarations(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Hashable {
            fn hash_code() -> u64;
        }

        class Box implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }

        fn main(box: Box) -> Hashable {
            return box;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    reachability = analyze_semantic_reachability(semantic)

    assert ClassId(module_path=("main",), name="Box") in reachability.reachable_classes
    assert InterfaceId(module_path=("main",), name="Hashable") in reachability.reachable_interfaces


def test_semantic_reachability_follows_nested_canonical_type_refs_on_callable_declarations(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Hashable {
            fn hash_code() -> u64;
        }

        class Box implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }

        fn main(callback: fn(Box) -> Hashable[]) -> i64 {
            return 0;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    reachability = analyze_semantic_reachability(semantic)

    assert ClassId(module_path=("main",), name="Box") in reachability.reachable_classes
    assert InterfaceId(module_path=("main",), name="Hashable") in reachability.reachable_interfaces


def test_semantic_reachability_walks_interface_method_call_receivers(tmp_path: Path) -> None:
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
            return ((Hashable)Key()).hash_code();
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    reachability = analyze_semantic_reachability(semantic)

    assert FunctionId(module_path=("main",), name="main") in reachability.reachable_functions
    assert ClassId(module_path=("main",), name="Key") in reachability.reachable_classes


def test_semantic_reachability_uses_canonical_type_refs_when_compatibility_strings_are_stale(tmp_path: Path) -> None:
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
            return ((Hashable)Key()).hash_code();
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    function = semantic.modules[("main",)].functions[0]
    return_stmt = function.body.statements[0]
    call_expr = return_stmt.value
    assert not hasattr(call_expr.target.access, "receiver_type_name")

    reachability = analyze_semantic_reachability(semantic)

    assert InterfaceId(module_path=("main",), name="Hashable") in reachability.reachable_interfaces
    assert ClassId(module_path=("main",), name="Key") in reachability.reachable_classes


def test_unreachable_prune_keeps_interface_impl_methods_for_reachable_classes(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Hashable {
            fn hash_code() -> u64;
            fn equals(other: Obj) -> bool;
        }

        class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }

            fn equals(other: Obj) -> bool {
                return true;
            }
        }

        fn main() -> i64 {
            var key: Key = Key();
            if key == null {
                return 1;
            }
            return 0;
        }
        """,
    )

    pruned = unreachable_prune(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    module = pruned.modules[("main",)]

    assert [cls.class_id.name for cls in module.classes] == ["Key"]
    assert [method.method_id.name for method in module.classes[0].methods] == ["hash_code", "equals"]


def test_unreachable_prune_keeps_imported_interface_impl_methods_for_reachable_classes(tmp_path: Path) -> None:
    _write(
        tmp_path / "contracts.nif",
        """
        export interface Hashable {
            fn hash_code() -> u64;
        }
        """,
    )
    _write(
        tmp_path / "model.nif",
        """
        import contracts;

        export class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }

        export fn make() -> contracts.Hashable {
            return Key();
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import model;

        fn main() -> u64 {
            return model.make().hash_code();
        }
        """,
    )

    pruned = unreachable_prune(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))

    assert [fn.function_id.name for fn in pruned.modules[("model",)].functions] == ["make"]
    assert [cls.class_id.name for cls in pruned.modules[("model",)].classes] == ["Key"]
    assert [method.method_id.name for method in pruned.modules[("model",)].classes[0].methods] == ["hash_code"]


def test_unreachable_prune_drops_dead_interfaces_but_keeps_referenced_ones(tmp_path: Path) -> None:
    _write(
        tmp_path / "contracts.nif",
        """
        export interface Hashable {
            fn hash_code() -> u64;
        }

        export interface Unused {
            fn value() -> i64;
        }
        """,
    )
    _write(
        tmp_path / "model.nif",
        """
        import contracts;

        export class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }

        export fn make() -> contracts.Hashable {
            return Key();
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import model;

        fn main() -> u64 {
            return model.make().hash_code();
        }
        """,
    )

    pruned = unreachable_prune(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))

    assert [interface.interface_id.name for interface in pruned.modules[("contracts",)].interfaces] == ["Hashable"]
    assert pruned.modules[("model",)].classes[0].implemented_interfaces == [
        pruned.modules[("contracts",)].interfaces[0].interface_id
    ]


def test_unreachable_prune_keeps_superclasses_and_inherited_interface_methods(tmp_path: Path) -> None:
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
            extra: u64;
        }

        fn main() -> u64 {
            return ((Hashable)Derived(1u)).hash_code();
        }
        """,
    )

    pruned = unreachable_prune(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    module = pruned.modules[("main",)]

    assert [cls.class_id.name for cls in module.classes] == ["Base", "Derived"]
    assert [method.method_id.name for method in module.classes[0].methods] == ["hash_code"]
    assert module.classes[1].implemented_interfaces == [InterfaceId(module_path=("main",), name="Hashable")]


def test_unreachable_prune_keeps_virtual_methods_for_reachable_classes_without_direct_calls(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Base {
            fn head() -> i64 {
                return 1;
            }

            private fn hidden() -> i64 {
                return 2;
            }
        }

        class Derived extends Base {
            override fn head() -> i64 {
                return 3;
            }

            fn tail() -> i64 {
                return 4;
            }

            static fn make() -> Derived {
                return Derived();
            }
        }

        fn main() -> i64 {
            var value: Derived = Derived();
            if value == null {
                return 1;
            }
            return 0;
        }
        """,
    )

    pruned = unreachable_prune(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    module = pruned.modules[("main",)]

    assert [cls.class_id.name for cls in module.classes] == ["Base", "Derived"]
    assert [method.method_id.name for method in module.classes[0].methods] == ["head"]
    assert [method.method_id.name for method in module.classes[1].methods] == ["head", "tail"]


def test_unreachable_prune_drops_dead_extern_functions(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export extern fn helper() -> i64;
        export extern fn dead_helper() -> i64;
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> i64 {
            return util.helper();
        }
        """,
    )

    pruned = unreachable_prune(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))

    assert [fn.function_id.name for fn in pruned.modules[("util",)].functions] == ["helper"]
