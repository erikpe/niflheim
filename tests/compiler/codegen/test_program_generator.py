from __future__ import annotations

from pathlib import Path

import pytest

from compiler.codegen.program_generator import ProgramGenerator
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.symbols import ClassId, ConstructorId, InterfaceId, InterfaceMethodId, MethodId


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

    program = link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    generator = ProgramGenerator(program)

    tables = generator.build_declaration_tables()

    box_id = ClassId(module_path=("util",), name="Box")
    make_id = MethodId(module_path=("util",), class_name="Box", name="make")
    get_id = MethodId(module_path=("util",), class_name="Box", name="get")
    ctor_id = ConstructorId(module_path=("util",), class_name="Box")

    assert tables.method_label(make_id) == "__nif_method_Box_make"
    assert tables.method_label(get_id) == "__nif_method_Box_get"
    assert tables.class_field_offset(box_id, "value") == 24
    assert tables.class_field_offset(box_id, "next") == 32
    assert tables.constructor_layout(ctor_id).label == "__nif_ctor_Box"
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

    program = link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    generator = ProgramGenerator(program)

    asm = generator.generate()

    assert generator.declaration_tables is not None
    assert generator.type_metadata is not None
    assert generator.declaration_tables.constructor_layout(ConstructorId(module_path=("main",), class_name="Box")) is not None
    assert "__nif_ctor_Box" in asm
    assert "main:" in asm


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

    program = link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    tables = ProgramGenerator(program).build_declaration_tables()

    interface_id = InterfaceId(module_path=("util",), name="Hashable")
    hash_code_id = InterfaceMethodId(module_path=("util",), interface_name="Hashable", name="hash_code")
    equals_id = InterfaceMethodId(module_path=("util",), interface_name="Hashable", name="equals")

    assert tables.interface_descriptor_symbol(interface_id) == "__nif_interface_util__Hashable"
    assert tables.interface_method_slot(hash_code_id) == 0
    assert tables.interface_method_slot(equals_id) == 1


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

    program = link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    generator = ProgramGenerator(program)

    metadata = generator.build_type_metadata()

    key_metadata = next(record for record in metadata.classes if record.class_id.name == "Key")
    person_metadata = next(record for record in metadata.classes if record.class_id.name == "Person")
    hashable_metadata = next(record for record in metadata.interfaces if record.interface_id.name == "Hashable")

    assert key_metadata.aliases == ("Key", "main::Key")
    assert key_metadata.pointer_offsets == (24,)
    assert key_metadata.interface_impls_symbol == "__nif_interface_impls_main__Key"
    assert key_metadata.interface_impls[0].method_table_symbol == "__nif_interface_methods_main__Key__main__Hashable"
    assert key_metadata.interface_impls[0].method_labels == ("__nif_method_Key_hash_code",)
    assert person_metadata.aliases == ("Person", "main::Person")
    assert metadata.extra_runtime_type_names == ()
    assert hashable_metadata.descriptor_symbol == "__nif_interface_main__Hashable"
    assert hashable_metadata.method_count == 1