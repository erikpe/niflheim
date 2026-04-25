from __future__ import annotations

from compiler.backend.ir import BackendConstOperand, BackendRegOperand, BackendReturnTerminator
from compiler.backend.ir._ordering import callable_id_sort_key, class_id_sort_key, interface_id_sort_key
from compiler.backend.ir.verify import verify_backend_program
from compiler.semantic.symbols import ClassId, ConstructorId, InterfaceId
from tests.compiler.backend.lowering.helpers import (
    block_by_ordinal,
    callable_by_name,
    callable_by_suffix,
    lower_project_to_backend_program,
    lower_source_to_backend_program,
)


def test_lower_to_backend_ir_returns_verified_backend_program_for_minimal_linked_program(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    verify_backend_program(program)
    main_callable = callable_by_name(program, "main")
    entry_block = block_by_ordinal(main_callable, 0)

    assert main_callable.kind == "function"
    assert main_callable.entry_block_id is not None
    assert entry_block.debug_name == "entry"
    assert isinstance(entry_block.terminator, BackendReturnTerminator)
    assert isinstance(entry_block.terminator.value, BackendConstOperand)


def test_lower_to_backend_ir_preserves_deterministic_top_level_declaration_ordering(tmp_path) -> None:
    program = lower_project_to_backend_program(
        tmp_path,
        {
            "decls.nif": """
            export interface Beta {
                fn b() -> i64;
            }

            export interface Alpha {
                fn a() -> i64;
            }

            export extern fn helper(value: i64) -> i64;

            export class Zed {
                fn read() -> i64 {
                    return 3;
                }
            }

            export class Box {
                constructor(seed: i64) {
                    return;
                }

                fn read() -> i64 {
                    return 2;
                }
            }

            export fn zebra() -> i64 {
                return 1;
            }
            """,
            "main.nif": """
            import decls;

            fn helper() -> i64 {
                return 4;
            }

            fn main() -> i64 {
                return 0;
            }
            """,
        },
        skip_optimize=True,
    )

    assert [interface.interface_id for interface in program.interfaces] == sorted(
        (interface.interface_id for interface in program.interfaces),
        key=interface_id_sort_key,
    )
    assert [class_decl.class_id for class_decl in program.classes] == sorted(
        (class_decl.class_id for class_decl in program.classes),
        key=class_id_sort_key,
    )
    assert [callable_decl.callable_id for callable_decl in program.callables] == sorted(
        (callable_decl.callable_id for callable_decl in program.callables),
        key=callable_id_sort_key,
    )

    assert [interface.interface_id.name for interface in program.interfaces] == ["Alpha", "Beta"]
    assert [class_decl.class_id.name for class_decl in program.classes] == ["Box", "Zed"]


def test_lower_to_backend_ir_maps_receiver_parameter_and_semantic_local_origins(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        class Box {
            constructor(seed: i64) {
                var tmp: i64 = seed;
                return;
            }

            fn read(extra: i64) -> i64 {
                var copy: i64 = extra;
                return copy;
            }
        }

        fn mirror(value: i64) -> i64 {
            var copy: i64 = value;
            return copy;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
    )

    constructor_callable = callable_by_suffix(program, "main.Box.#0")
    method_callable = callable_by_suffix(program, "main.Box.read")
    function_callable = callable_by_name(program, "mirror")

    assert [register.origin_kind for register in constructor_callable.registers] == ["receiver", "param", "local"]
    assert [register.origin_kind for register in method_callable.registers] == ["receiver", "param", "local"]
    assert [register.origin_kind for register in function_callable.registers] == ["param", "local"]

    assert constructor_callable.registers[0].debug_name == "__self"
    assert method_callable.registers[0].debug_name == "__self"
    assert function_callable.registers[0].debug_name == "value"


def test_lower_to_backend_ir_lowers_externs_without_blocks_and_concrete_callables_with_entry_b0(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        extern fn helper(value: i64) -> i64;

        class Box {
            value: i64;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
    )

    extern_helper = callable_by_name(program, "helper")
    compat_constructor = next(
        callable_decl for callable_decl in program.callables if isinstance(callable_decl.callable_id, ConstructorId)
    )
    main_callable = callable_by_name(program, "main")

    assert extern_helper.is_extern is True
    assert extern_helper.entry_block_id is None
    assert extern_helper.blocks == ()

    assert compat_constructor.is_extern is False
    assert compat_constructor.entry_block_id is not None
    assert compat_constructor.entry_block_id.ordinal == 0
    assert compat_constructor.blocks[0].block_id.ordinal == 0

    assert main_callable.entry_block_id is not None
    assert main_callable.entry_block_id.ordinal == 0


def test_lower_to_backend_ir_verifies_tiny_function_method_and_constructor_smoke_bodies(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        class Box {
            constructor() {
                return;
            }

            fn read() -> i64 {
                return 7;
            }
        }

        fn helper(value: i64) -> i64 {
            var copy: i64 = value;
            return copy;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
    )

    verify_backend_program(program)
    helper_callable = callable_by_name(program, "helper")
    method_callable = callable_by_suffix(program, "main.Box.read")
    constructor_callable = callable_by_suffix(program, "main.Box.#0")

    assert isinstance(helper_callable.blocks[0].terminator.value, BackendRegOperand)
    assert isinstance(method_callable.blocks[0].terminator.value, BackendConstOperand)
    assert isinstance(constructor_callable.blocks[0].terminator.value, BackendRegOperand)