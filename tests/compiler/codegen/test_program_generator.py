from __future__ import annotations

from pathlib import Path

import pytest

from compiler.codegen.program_generator import ProgramGenerator
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowering.executable import lower_linked_semantic_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.symbols import ClassId, ConstructorId, FunctionId, InterfaceId, InterfaceMethodId, MethodId


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_program_generator_builds_declaration_tables_from_program(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export class Box {
            value: i64;
            next: Obj;

            static fn make(value: i64) -> Box {
                return Box(value, null);
            }

            fn get() -> i64 {
                return __self.value;
            }
        }

        export fn helper() -> bool {
            return true;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    program = lower_linked_semantic_program(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )
    generator = ProgramGenerator(program)

    tables = generator.build_declaration_tables()

    box_id = ClassId(module_path=("util",), name="Box")
    make_id = MethodId(module_path=("util",), class_name="Box", name="make")
    get_id = MethodId(module_path=("util",), class_name="Box", name="get")
    ctor_id = ConstructorId(module_path=("util",), class_name="Box")
    helper_id = FunctionId(module_path=("util",), name="helper")

    assert tables.function_label(helper_id) == "__nif_fn_util__helper"
    assert tables.method_label(make_id) == "__nif_method_util__Box_make"
    assert tables.method_label(get_id) == "__nif_method_util__Box_get"
    assert tables.class_field_offset(box_id, "value") == 24
    assert tables.class_field_offset(box_id, "next") == 32
    assert tables.class_vtable_symbol(box_id) == "__nif_vtable_util__Box"
    assert tables.class_virtual_slot_index(box_id, box_id, "get") == 0
    assert tables.constructor_layout(ctor_id).label == "__nif_ctor_util__Box"
    assert tables.constructor_layout(ctor_id).init_label == "__nif_ctor_init_util__Box"
    assert tables.constructor_layout(ctor_id).type_symbol == "__nif_type_util__Box"
    assert tables.constructor_layout(ctor_id).param_field_names == ["value", "next"]


def test_program_generator_generate_builds_module_output(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Box {
            value: i64;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    program = lower_linked_semantic_program(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )
    generator = ProgramGenerator(program)

    asm = generator.generate()

    assert generator.declaration_tables is not None
    assert generator.type_metadata is not None
    assert generator.declaration_tables.function_label(FunctionId(module_path=("main",), name="main")) == "__nif_fn_main__main"
    assert generator.declaration_tables.constructor_layout(ConstructorId(module_path=("main",), class_name="Box")) is not None
    assert "__nif_ctor_main__Box" in asm
    assert "main:" in asm
    assert "__nif_fn_main__main:" in asm


def test_program_generator_builds_overloaded_constructor_labels(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Box {
            value: i64;
            other: i64 = 0;

            constructor(value: i64) {
                __self.value = value;
                return;
            }

            constructor(value: i64, other: i64) {
                __self.value = value;
                __self.other = other;
                return;
            }
        }

        fn main() -> i64 {
            var box: Box = Box(1, 2);
            return box.other;
        }
        """,
    )

    program = lower_linked_semantic_program(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )
    tables = ProgramGenerator(program).build_declaration_tables()

    first_ctor_id = ConstructorId(module_path=("main",), class_name="Box", ordinal=0)
    second_ctor_id = ConstructorId(module_path=("main",), class_name="Box", ordinal=1)

    assert tables.constructor_layout(first_ctor_id).label == "__nif_ctor_main__Box"
    assert tables.constructor_layout(first_ctor_id).init_label == "__nif_ctor_init_main__Box"
    assert tables.constructor_layout(first_ctor_id).param_names == ["value"]
    assert tables.constructor_layout(first_ctor_id).param_field_names == []
    assert tables.constructor_layout(second_ctor_id).label == "__nif_ctor_main__Box__1"
    assert tables.constructor_layout(second_ctor_id).init_label == "__nif_ctor_init_main__Box__1"
    assert tables.constructor_layout(second_ctor_id).param_names == ["value", "other"]
    assert tables.constructor_layout(second_ctor_id).param_field_names == []


def test_program_generator_builds_constructor_init_metadata_for_inherited_compatibility_chain(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Base {
            value: i64;
        }

        class Derived extends Base {
            extra: i64;
        }

        fn main() -> i64 {
            var derived: Derived = Derived(1, 2);
            return derived.extra;
        }
        """,
    )

    program = lower_linked_semantic_program(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )
    tables = ProgramGenerator(program).build_declaration_tables()

    derived_ctor_id = ConstructorId(module_path=("main",), class_name="Derived")
    derived_layout = tables.constructor_layout(derived_ctor_id)

    assert derived_layout.init_label == "__nif_ctor_init_main__Derived"
    assert derived_layout.param_names == ["value", "extra"]
    assert derived_layout.super_param_count == 1


def test_program_generator_builds_interface_descriptor_and_slot_tables(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export interface Hashable {
            fn hash_code() -> u64;
            fn equals(other: Obj) -> bool;
        }

        export class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }

            fn equals(other: Obj) -> bool {
                return true;
            }
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    program = lower_linked_semantic_program(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )
    tables = ProgramGenerator(program).build_declaration_tables()

    interface_id = InterfaceId(module_path=("util",), name="Hashable")
    hash_code_id = InterfaceMethodId(module_path=("util",), interface_name="Hashable", name="hash_code")
    equals_id = InterfaceMethodId(module_path=("util",), interface_name="Hashable", name="equals")

    assert tables.interface_descriptor_symbol(interface_id) == "__nif_interface_util__Hashable"
    assert tables.interface_slot(interface_id) == 0
    assert tables.interface_method_slot(hash_code_id) == 0
    assert tables.interface_method_slot(equals_id) == 1


def test_program_generator_assigns_stable_whole_program_interface_slots(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Alpha {
            fn a() -> i64;
        }

        interface Beta {
            fn b() -> i64;
        }

        interface Gamma {
            fn c() -> i64;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    program = lower_linked_semantic_program(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )
    tables = ProgramGenerator(program).build_declaration_tables()

    alpha_id = InterfaceId(module_path=("main",), name="Alpha")
    beta_id = InterfaceId(module_path=("main",), name="Beta")
    gamma_id = InterfaceId(module_path=("main",), name="Gamma")

    assert tables.interface_slot(alpha_id) == 0
    assert tables.interface_slot(beta_id) == 1
    assert tables.interface_slot(gamma_id) == 2


def test_program_generator_builds_type_metadata_before_emission(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Hashable {
            fn hash_code() -> u64;
        }

        class Person {
            next: Obj;
        }

        class Key implements Hashable {
            next: Obj;

            fn hash_code() -> u64 {
                return 1u;
            }
        }

        fn cast_person(value: Obj) -> Person {
            return (Person)value;
        }

        fn main() -> i64 {
            if cast_person(null) == null {
                return 0;
            }
            return 1;
        }
        """,
    )

    program = lower_linked_semantic_program(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )
    generator = ProgramGenerator(program)

    metadata = generator.build_type_metadata()

    key_metadata = next(record for record in metadata.classes if record.class_id.name == "Key")
    person_metadata = next(record for record in metadata.classes if record.class_id.name == "Person")
    hashable_metadata = next(record for record in metadata.interfaces if record.interface_id.name == "Hashable")

    assert key_metadata.aliases == ("Key", "main::Key")
    assert key_metadata.pointer_offsets == (24,)
    assert key_metadata.interface_tables_symbol == "__nif_interface_tables_main__Key"
    assert key_metadata.interface_table_slot_count == 1
    assert key_metadata.interface_table_entries == ("__nif_interface_methods_main__Key__main__Hashable",)
    assert key_metadata.interface_method_tables[0].method_table_symbol == "__nif_interface_methods_main__Key__main__Hashable"
    assert key_metadata.interface_method_tables[0].method_labels == ("__nif_method_main__Key_hash_code",)
    assert key_metadata.class_vtable_symbol == "__nif_vtable_main__Key"
    assert key_metadata.class_vtable_labels == ("__nif_method_main__Key_hash_code",)
    assert person_metadata.aliases == ("Person", "main::Person")
    assert person_metadata.interface_tables_symbol == "__nif_interface_tables_main__Person"
    assert person_metadata.interface_table_slot_count == 1
    assert person_metadata.interface_table_entries == (None,)
    assert person_metadata.class_vtable_symbol is None
    assert person_metadata.class_vtable_labels == ()
    assert metadata.extra_runtime_type_names == ()
    assert hashable_metadata.descriptor_symbol == "__nif_interface_main__Hashable"
    assert hashable_metadata.slot_index == 0
    assert hashable_metadata.method_count == 1


def test_program_generator_records_interface_slots_in_type_metadata(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Alpha {
            fn a() -> i64;
        }

        interface Beta {
            fn b() -> i64;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    program = lower_linked_semantic_program(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )
    metadata = ProgramGenerator(program).build_type_metadata()

    interface_slots = {record.interface_id.name: record.slot_index for record in metadata.interfaces}

    assert interface_slots == {"Alpha": 0, "Beta": 1}

def test_program_generator_uses_effective_layout_and_inherited_interface_methods(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Hashable {
            fn hash_code() -> u64;
        }

        class Base implements Hashable {
            head: Obj;

            fn hash_code() -> u64 {
                return 1u;
            }
        }

        class Derived extends Base {
            count: i64;
            tail: Obj;

            override fn hash_code() -> u64 {
                return 2u;
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
    generator = ProgramGenerator(program)

    tables = generator.build_declaration_tables()
    metadata = generator.build_type_metadata()

    base_id = ClassId(module_path=("main",), name="Base")
    derived_id = ClassId(module_path=("main",), name="Derived")
    derived_ctor_id = ConstructorId(module_path=("main",), class_name="Derived")
    derived_metadata = next(record for record in metadata.classes if record.class_id == derived_id)

    assert tables.class_field_offset(base_id, "head") == 24
    assert tables.class_field_offset(derived_id, "count") == 32
    assert tables.class_field_offset(derived_id, "tail") == 40
    assert tables.class_vtable_symbol(derived_id) == "__nif_vtable_main__Derived"
    assert tables.class_virtual_slot_index(derived_id, base_id, "hash_code") == 0
    assert tables.constructor_layout(derived_ctor_id).payload_bytes == 24
    assert derived_metadata.superclass_symbol == "__nif_type_main__Base"
    assert derived_metadata.pointer_offsets == (24, 40)
    assert derived_metadata.interface_tables_symbol == "__nif_interface_tables_main__Derived"
    assert derived_metadata.interface_table_slot_count == 1
    assert derived_metadata.interface_table_entries == ("__nif_interface_methods_main__Derived__main__Hashable",)
    assert derived_metadata.interface_method_tables[0].method_table_symbol == "__nif_interface_methods_main__Derived__main__Hashable"
    assert derived_metadata.interface_method_tables[0].method_labels == ("__nif_method_main__Derived_hash_code",)
    assert derived_metadata.class_vtable_symbol == "__nif_vtable_main__Derived"
    assert derived_metadata.class_vtable_labels == ("__nif_method_main__Derived_hash_code",)


def test_program_generator_builds_slotted_interface_table_entries_with_null_holes(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Alpha {
            fn alpha() -> i64;
        }

        interface Beta {
            fn beta() -> i64;
        }

        interface Gamma {
            fn gamma() -> i64;
        }

        class Mixed implements Alpha, Gamma {
            fn alpha() -> i64 {
                return 1;
            }

            fn gamma() -> i64 {
                return 2;
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
    metadata = ProgramGenerator(program).build_type_metadata()
    mixed_metadata = next(record for record in metadata.classes if record.class_id.name == "Mixed")

    assert mixed_metadata.interface_tables_symbol == "__nif_interface_tables_main__Mixed"
    assert mixed_metadata.interface_table_slot_count == 3
    assert mixed_metadata.interface_table_entries == (
        "__nif_interface_methods_main__Mixed__main__Alpha",
        None,
        "__nif_interface_methods_main__Mixed__main__Gamma",
    )


def test_program_generator_omits_short_aliases_for_duplicate_class_leaf_names(tmp_path: Path) -> None:
    _write(
        tmp_path / "left.nif",
        """
        export class Key {
            value: i64;
        }
        """,
    )
    _write(
        tmp_path / "right.nif",
        """
        export class Key {
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

    program = lower_linked_semantic_program(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )
    generator = ProgramGenerator(program)

    metadata = generator.build_type_metadata()
    tables = generator.build_declaration_tables()

    left_id = ClassId(module_path=("left",), name="Key")
    right_id = ClassId(module_path=("right",), name="Key")
    left_metadata = next(record for record in metadata.classes if record.class_id == left_id)
    right_metadata = next(record for record in metadata.classes if record.class_id == right_id)

    assert left_metadata.aliases == ("left::Key",)
    assert right_metadata.aliases == ("right::Key",)
    assert tables.constructor_layout(ConstructorId(module_path=("left",), class_name="Key")).type_symbol == "__nif_type_left__Key"
    assert tables.constructor_layout(ConstructorId(module_path=("right",), class_name="Key")).type_symbol == "__nif_type_right__Key"


def test_program_generator_canonicalizes_class_owned_labels_for_duplicate_leaf_names(tmp_path: Path) -> None:
    _write(
        tmp_path / "left.nif",
        """
        export class Key {
            value: i64;

            fn read() -> i64 {
                return __self.value;
            }
        }
        """,
    )
    _write(
        tmp_path / "right.nif",
        """
        export class Key {
            value: i64;

            fn read() -> i64 {
                return __self.value + 1;
            }
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

    program = lower_linked_semantic_program(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )
    tables = ProgramGenerator(program).build_declaration_tables()

    left_ctor_id = ConstructorId(module_path=("left",), class_name="Key")
    right_ctor_id = ConstructorId(module_path=("right",), class_name="Key")
    left_method_id = MethodId(module_path=("left",), class_name="Key", name="read")
    right_method_id = MethodId(module_path=("right",), class_name="Key", name="read")

    assert tables.constructor_layout(left_ctor_id).label == "__nif_ctor_left__Key"
    assert tables.constructor_layout(right_ctor_id).label == "__nif_ctor_right__Key"
    assert tables.constructor_layout(left_ctor_id).init_label == "__nif_ctor_init_left__Key"
    assert tables.constructor_layout(right_ctor_id).init_label == "__nif_ctor_init_right__Key"
    assert tables.method_label(left_method_id) == "__nif_method_left__Key_read"
    assert tables.method_label(right_method_id) == "__nif_method_right__Key_read"