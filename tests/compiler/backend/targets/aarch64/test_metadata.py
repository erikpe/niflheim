from __future__ import annotations

from pathlib import Path

from compiler.backend.program.symbols import FunctionId
from compiler.backend.targets import BackendTargetOptions
from compiler.backend.targets.aarch64 import emit_aarch64_asm
from compiler.semantic.symbols import ClassId
from tests.compiler.backend.lowering.helpers import lower_project_to_backend_program
from tests.compiler.backend.targets.support import make_target_input


def _make_target_input(tmp_path: Path, files: dict[str, str], *, entry_relative_path: str = "main.nif"):
    program = lower_project_to_backend_program(
        tmp_path,
        files,
        entry_relative_path=entry_relative_path,
        skip_optimize=True,
    )
    return make_target_input(program)


def test_backend_program_context_prepares_class_interface_and_string_metadata(tmp_path: Path) -> None:
    target_input = _make_target_input(
        tmp_path,
        {
            "main.nif": """
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

            class Str {
                static fn from_u8_array(value: u8[]) -> Str {
                    return Str();
                }
            }

            fn cast_nums(value: Obj) -> i64[] {
                return (i64[])value;
            }

            fn bytes1() -> Str {
                return "hi";
            }

            fn bytes2() -> Str {
                return "hi";
            }

            fn main() -> i64 {
                return 0;
            }
            """,
        },
    )
    metadata = target_input.program_context.metadata
    derived_id = ClassId(module_path=("main",), name="Derived")
    derived_metadata = next(record for record in metadata.classes if record.class_id == derived_id)
    hashable_metadata = metadata.interfaces[0]

    assert hashable_metadata.descriptor_symbol == "__nif_interface_main__Hashable"
    assert hashable_metadata.name_symbol == "__nif_interface_name_main__Hashable"
    assert hashable_metadata.slot_index == 0
    assert hashable_metadata.method_count == 1

    assert derived_metadata.aliases == ("Derived", "main::Derived")
    assert derived_metadata.superclass_symbol == "__nif_type_main__Base"
    assert derived_metadata.pointer_offsets == (24, 40)
    assert derived_metadata.pointer_offsets_symbol == "__nif_type_name_main__Derived__ptr_offsets"
    assert derived_metadata.interface_tables_symbol == "__nif_interface_tables_main__Derived"
    assert derived_metadata.interface_table_entries == ("__nif_interface_methods_main__Derived__main__Hashable",)
    assert derived_metadata.interface_method_tables[0].method_labels == ("__nif_method_main__Derived_hash_code",)
    assert derived_metadata.class_vtable_symbol == "__nif_vtable_main__Derived"
    assert derived_metadata.class_vtable_labels == ("__nif_method_main__Derived_hash_code",)

    assert metadata.extra_runtime_type_names == ("i64[]",)
    assert metadata.extra_runtime_types[0].type_symbol == "__nif_type_i64__"
    assert len(metadata.data_blobs) == 1
    assert metadata.data_blobs[0].symbol == "__nif_str_lit_0"
    assert metadata.data_blobs[0].bytes_hex == "6869"
    assert metadata.data_blobs[0].byte_length == 2
    assert metadata.data_blobs[0].content_kind == "string"


def test_emit_aarch64_asm_uses_backend_program_context_symbols(tmp_path: Path) -> None:
    target_input = _make_target_input(
        tmp_path,
        {
            "main.nif": """
            fn helper() -> i64 {
                return 7;
            }

            fn main() -> i64 {
                return helper();
            }
            """,
        },
    )

    asm = emit_aarch64_asm(target_input, options=BackendTargetOptions()).assembly_text
    helper_id = FunctionId(module_path=("main",), name="helper")
    helper_symbol = target_input.program_context.symbols.callable(helper_id).direct_call_symbol
    main_symbols = target_input.program_context.symbols.callable(FunctionId(module_path=("main",), name="main"))

    assert f"{helper_symbol}:" in asm
    assert f"    bl {helper_symbol}" in asm
    assert "main:" in asm
    assert f"{main_symbols.alias_labels[0]}:" in asm


def test_emit_aarch64_asm_emits_type_interface_and_blob_sections(tmp_path: Path) -> None:
    asm = emit_aarch64_asm(
        _make_target_input(
            tmp_path,
            {
                "main.nif": """
                interface Hashable {
                    fn hash_code() -> u64;
                }

                class Box implements Hashable {
                    value: Obj;

                    fn hash_code() -> u64 {
                        return 1u;
                    }
                }

                class Str {
                    static fn from_u8_array(value: u8[]) -> Str {
                        return null;
                    }
                }

                fn main() -> i64 {
                    var value: Str = "hi";
                    return 0;
                }
                """,
            },
        ),
        options=BackendTargetOptions(),
    ).assembly_text

    for expected in [
        "__nif_interface_main__Hashable:",
        "__nif_interface_name_main__Hashable:",
        "__nif_interface_methods_main__Box__main__Hashable:",
        "__nif_interface_tables_main__Box:",
        "__nif_vtable_main__Box:",
        "__nif_type_main__Box:",
        "__nif_type_name_main__Box:",
        "__nif_str_lit_0:",
        '.asciz "hi"',
    ]:
        assert expected in asm