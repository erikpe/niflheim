from __future__ import annotations

from pathlib import Path

from compiler.codegen.class_hierarchy import ClassHierarchyIndex
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowering.executable import lower_linked_semantic_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.symbols import ClassId, MethodId


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_class_hierarchy_tracks_stable_virtual_slots_and_override_replacement(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Base {
            fn head() -> i64 {
                return 1;
            }

            fn tail() -> i64 {
                return 2;
            }

            private fn hidden() -> i64 {
                return 3;
            }

            static fn make() -> Base {
                return Base();
            }
        }

        class Mid extends Base {
            override fn head() -> i64 {
                return 4;
            }

            fn extra() -> i64 {
                return 5;
            }
        }

        class Derived extends Mid {
            override fn tail() -> i64 {
                return 6;
            }

            fn leaf() -> i64 {
                return 7;
            }
        }

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    program = lower_linked_semantic_program(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )
    hierarchy = ClassHierarchyIndex(program)

    base_id = ClassId(module_path=("main",), name="Base")
    mid_id = ClassId(module_path=("main",), name="Mid")
    derived_id = ClassId(module_path=("main",), name="Derived")

    base_slots = hierarchy.effective_virtual_slots(base_id)
    assert [(slot.slot_owner_class_id, slot.method_name, slot.selected_method_id, slot.slot_index) for slot in base_slots] == [
        (base_id, "head", MethodId(module_path=("main",), class_name="Base", name="head"), 0),
        (base_id, "tail", MethodId(module_path=("main",), class_name="Base", name="tail"), 1),
    ]

    mid_slots = hierarchy.effective_virtual_slots(mid_id)
    assert [(slot.slot_owner_class_id, slot.method_name, slot.selected_method_id, slot.slot_index) for slot in mid_slots] == [
        (base_id, "head", MethodId(module_path=("main",), class_name="Mid", name="head"), 0),
        (base_id, "tail", MethodId(module_path=("main",), class_name="Base", name="tail"), 1),
        (mid_id, "extra", MethodId(module_path=("main",), class_name="Mid", name="extra"), 2),
    ]

    derived_slots = hierarchy.effective_virtual_slots(derived_id)
    assert [(slot.slot_owner_class_id, slot.method_name, slot.selected_method_id, slot.slot_index) for slot in derived_slots] == [
        (base_id, "head", MethodId(module_path=("main",), class_name="Mid", name="head"), 0),
        (base_id, "tail", MethodId(module_path=("main",), class_name="Derived", name="tail"), 1),
        (mid_id, "extra", MethodId(module_path=("main",), class_name="Mid", name="extra"), 2),
        (derived_id, "leaf", MethodId(module_path=("main",), class_name="Derived", name="leaf"), 3),
    ]


def test_class_hierarchy_resolves_virtual_and_direct_methods_separately(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Base {
            fn read() -> i64 {
                return 1;
            }

            private fn hidden() -> i64 {
                return 2;
            }

            static fn make() -> Base {
                return Base();
            }
        }

        class Derived extends Base {
            override fn read() -> i64 {
                return 3;
            }
        }

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    program = lower_linked_semantic_program(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )
    hierarchy = ClassHierarchyIndex(program)

    base_id = ClassId(module_path=("main",), name="Base")
    derived_id = ClassId(module_path=("main",), name="Derived")

    assert hierarchy.resolve_virtual_slot_index(derived_id, base_id, "read") == 0
    assert hierarchy.resolve_virtual_method_id(derived_id, base_id, "read") == MethodId(
        module_path=("main",), class_name="Derived", name="read"
    )
    assert hierarchy.resolve_method_id(derived_id, "read") == MethodId(
        module_path=("main",), class_name="Derived", name="read"
    )
    assert hierarchy.resolve_method_id(derived_id, "hidden") == MethodId(
        module_path=("main",), class_name="Base", name="hidden"
    )
    assert hierarchy.resolve_method_id(derived_id, "make") == MethodId(
        module_path=("main",), class_name="Base", name="make"
    )