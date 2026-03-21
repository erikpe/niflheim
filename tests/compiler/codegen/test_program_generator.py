from __future__ import annotations

from pathlib import Path

import pytest

from compiler.codegen.program_generator import ProgramGenerator
from compiler.codegen.linker import build_codegen_program
from compiler.resolver import resolve_program
from compiler.semantic.lowering import lower_program
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

    program = build_codegen_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    generator = ProgramGenerator(program)

    tables = generator.build_declaration_tables()

    box_id = ClassId(module_path=("util",), name="Box")
    make_id = MethodId(module_path=("util",), class_name="Box", name="make")
    get_id = MethodId(module_path=("util",), class_name="Box", name="get")
    helper_id = FunctionId(module_path=("util",), name="helper")
    ctor_id = ConstructorId(module_path=("util",), class_name="Box")

    assert tables.method_labels_by_id[make_id] == "__nif_method_Box_make"
    assert tables.method_labels_by_id[get_id] == "__nif_method_Box_get"
    assert tables.method_return_types_by_id[get_id] == "i64"
    assert tables.method_is_static_by_id[make_id] is True
    assert tables.method_is_static_by_id[get_id] is False
    assert tables.function_return_types_by_id[helper_id] == "bool"
    assert tables.constructor_labels_by_id[ctor_id] == "__nif_ctor_Box"
    assert tables.class_field_offsets_by_id[(box_id, "value")] == 24
    assert tables.class_field_offsets_by_id[(box_id, "next")] == 32
    assert tables.class_field_type_names_by_id[(box_id, "next")] == "Obj"
    assert tables.constructor_layouts_by_id[ctor_id].param_field_names == ["value", "next"]


def test_program_generator_tracks_extern_and_entry_function_return_types(tmp_path: Path) -> None:
    _write(
        tmp_path / "decls.nif",
        """
        export extern fn helper() -> i64;
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import decls;

        fn helper() -> i64 {
            return 7;
        }

        fn main() -> i64 {
            return helper();
        }
        """,
    )

    program = build_codegen_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    tables = ProgramGenerator(program).build_declaration_tables()

    assert tables.function_return_types_by_id[FunctionId(module_path=("main",), name="helper")] == "i64"
    assert tables.function_return_types_by_id[FunctionId(module_path=("main",), name="main")] == "i64"


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

    program = build_codegen_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    generator = ProgramGenerator(program)

    asm = generator.generate()

    assert generator.declaration_tables is not None
    assert generator.type_metadata is not None
    assert ConstructorId(module_path=("main",), class_name="Box") in generator.declaration_tables.constructor_labels_by_id
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

    program = build_codegen_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    tables = ProgramGenerator(program).build_declaration_tables()

    interface_id = InterfaceId(module_path=("util",), name="Hashable")
    hash_code_id = InterfaceMethodId(module_path=("util",), interface_name="Hashable", name="hash_code")
    equals_id = InterfaceMethodId(module_path=("util",), interface_name="Hashable", name="equals")

    assert tables.interface_descriptor_symbols_by_id[interface_id] == "__nif_interface_util__Hashable"
    assert tables.interface_method_slots_by_id[hash_code_id] == 0
    assert tables.interface_method_slots_by_id[equals_id] == 1
    assert tables.local_interface_ids_by_module[("util",)]["Hashable"] == interface_id


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

    program = build_codegen_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
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