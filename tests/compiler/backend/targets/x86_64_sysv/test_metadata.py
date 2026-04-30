from __future__ import annotations

from pathlib import Path

from compiler.backend.program.symbols import (
    epilogue_label,
    mangle_class_vtable_symbol,
    mangle_constructor_init_symbol,
    mangle_constructor_symbol,
    mangle_debug_file_symbol,
    mangle_debug_function_symbol,
    mangle_function_symbol,
    mangle_interface_name_symbol,
    mangle_interface_symbol,
    mangle_method_symbol,
    mangle_type_pointer_offsets_symbol,
    qualified_class_name,
    string_literal_symbol,
)
from compiler.backend.targets import BackendTargetOptions
from compiler.backend.targets.x86_64_sysv import emit_x86_64_sysv_asm
from compiler.semantic.symbols import ClassId, ConstructorId, FunctionId, InterfaceId, MethodId
from tests.compiler.backend.lowering.helpers import lower_project_to_backend_program
from tests.compiler.backend.targets.x86_64_sysv.helpers import make_target_input


def _make_target_input(tmp_path: Path, files: dict[str, str], *, entry_relative_path: str = "main.nif"):
    program = lower_project_to_backend_program(
        tmp_path,
        files,
        entry_relative_path=entry_relative_path,
        skip_optimize=True,
    )
    return make_target_input(program)


def _callable_snapshot(target_input) -> tuple[tuple[str, str, str | None, tuple[str, ...], str | None], ...]:
    snapshot: list[tuple[str, str, str | None, tuple[str, ...], str | None]] = []
    for callable_id, record in target_input.program_context.symbols.callable_symbols_by_id.items():
        if isinstance(callable_id, FunctionId):
            rendered = f"{'.'.join(callable_id.module_path)}::{callable_id.name}"
        elif isinstance(callable_id, MethodId):
            rendered = f"{'.'.join(callable_id.module_path)}::{callable_id.class_name}.{callable_id.name}"
        else:
            rendered = f"{'.'.join(callable_id.module_path)}::{callable_id.class_name}#{callable_id.ordinal}"
        snapshot.append((rendered, record.direct_call_symbol, record.emitted_label, record.alias_labels, record.global_label))
    return tuple(sorted(snapshot))


def test_backend_program_symbol_helpers_preserve_callable_and_metadata_contracts() -> None:
    box_id = ClassId(module_path=("std",), name="Box")
    hashable_id = InterfaceId(module_path=("std",), name="Hashable")
    helper_id = FunctionId(module_path=("std",), name="helper")
    get_id = MethodId(module_path=("std",), class_name="Box", name="get")
    ctor_id = ConstructorId(module_path=("std",), class_name="Box", ordinal=1)

    assert epilogue_label("main") == ".Lmain_epilogue"
    assert mangle_function_symbol(("std",), "helper") == "__nif_fn_std__helper"
    assert mangle_method_symbol(get_id) == "__nif_method_std__Box_get"
    assert mangle_constructor_symbol(ctor_id) == "__nif_ctor_std__Box__1"
    assert mangle_constructor_init_symbol(ctor_id) == "__nif_ctor_init_std__Box__1"
    assert mangle_debug_function_symbol("main") == "__nif_debug_fn_main"
    assert mangle_debug_file_symbol("__nif_fn_std__helper") == "__nif_debug_file___nif_fn_std__helper"
    assert mangle_class_vtable_symbol(box_id) == "__nif_vtable_std__Box"
    assert mangle_type_pointer_offsets_symbol(qualified_class_name(box_id)) == "__nif_type_name_std__Box__ptr_offsets"
    assert mangle_interface_symbol(hashable_id) == "__nif_interface_std__Hashable"
    assert mangle_interface_name_symbol(hashable_id) == "__nif_interface_name_std__Hashable"
    assert string_literal_symbol(3) == "__nif_str_lit_3"


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


def test_backend_program_context_keeps_multimodule_order_and_duplicate_leaf_symbols_stable(tmp_path: Path) -> None:
    files = {
        "left.nif": """
        export class Key {
            value: i64;

            fn read() -> i64 {
                return __self.value;
            }
        }
        """,
        "right.nif": """
        export class Key {
            value: i64;

            fn read() -> i64 {
                return __self.value + 1;
            }
        }
        """,
        "main.nif": """
        import left;
        import right;

        fn main() -> i64 {
            return left.Key(20).read() + right.Key(21).read();
        }
        """,
    }

    first = _make_target_input(tmp_path / "run_a", files)
    second = _make_target_input(tmp_path / "run_b", files)

    left_id = ClassId(module_path=("left",), name="Key")
    right_id = ClassId(module_path=("right",), name="Key")
    left_ctor = ConstructorId(module_path=("left",), class_name="Key")
    right_ctor = ConstructorId(module_path=("right",), class_name="Key")
    left_method = MethodId(module_path=("left",), class_name="Key", name="read")
    right_method = MethodId(module_path=("right",), class_name="Key", name="read")

    first_metadata = {record.class_id: record for record in first.program_context.metadata.classes}

    assert first_metadata[left_id].aliases == ("left::Key",)
    assert first_metadata[right_id].aliases == ("right::Key",)
    assert first.program_context.symbols.callable(left_ctor).direct_call_symbol == "__nif_ctor_left__Key"
    assert first.program_context.symbols.callable(right_ctor).direct_call_symbol == "__nif_ctor_right__Key"
    assert first.program_context.symbols.callable(left_method).direct_call_symbol == "__nif_method_left__Key_read"
    assert first.program_context.symbols.callable(right_method).direct_call_symbol == "__nif_method_right__Key_read"
    assert _callable_snapshot(first) == _callable_snapshot(second)
    assert tuple((record.qualified_type_name, record.aliases) for record in first.program_context.metadata.classes) == tuple(
        (record.qualified_type_name, record.aliases) for record in second.program_context.metadata.classes
    )


def test_emit_x86_64_sysv_asm_uses_backend_program_context_symbols(tmp_path: Path) -> None:
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

    asm = emit_x86_64_sysv_asm(target_input, options=BackendTargetOptions()).assembly_text
    helper_id = FunctionId(module_path=("main",), name="helper")
    helper_symbol = target_input.program_context.symbols.callable(helper_id).direct_call_symbol
    main_symbols = target_input.program_context.symbols.callable(FunctionId(module_path=("main",), name="main"))

    assert f"{helper_symbol}:" in asm
    assert f"    call {helper_symbol}" in asm
    assert "main:" in asm
    assert f"{main_symbols.alias_labels[0]}:" in asm