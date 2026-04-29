from __future__ import annotations

from tests.compiler.backend.lowering.helpers import lower_project_to_backend_program
from tests.compiler.backend.targets.x86_64_sysv.helpers import compile_and_run_source, emit_program, emit_source_asm


def _body_for_label(asm: str, label: str) -> str:
    epilogue = f".L{label}_epilogue:"
    return asm[asm.index(f"{label}:") : asm.index(epilogue)]


def test_emit_source_asm_emits_direct_instance_method_calls_without_vtable_lookup(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        class Box {
            private fn hidden() -> i64 {
                return 4;
            }

            fn expose() -> i64 {
                return __self.hidden();
            }
        }

        fn use(value: Box) -> i64 {
            return value.expose();
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
    )

    expose_body = _body_for_label(asm, "__nif_method_main__Box_expose")

    assert "    call rt_panic_null_deref" in expose_body
    assert "    call __nif_method_main__Box_hidden" in expose_body
    assert "    call r11" not in expose_body
    assert "    mov rcx, qword ptr [rcx + 80]" not in expose_body


def test_emit_source_asm_emits_virtual_dispatch_through_class_vtable(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
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

        fn read(value: Base) -> i64 {
            return value.head();
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
    )

    read_body = _body_for_label(asm, "__nif_fn_main__read")

    assert "    call rt_panic_null_deref" in read_body
    assert "    mov rcx, qword ptr [rdi]" in read_body
    assert "    mov rcx, qword ptr [rcx + 80]" in read_body
    assert "    mov r11, qword ptr [rcx]" in read_body
    assert "    call r11" in read_body
    assert "    call __nif_method_main__Base_head" not in read_body
    assert "    call __nif_method_main__Derived_head" not in read_body


def test_emit_source_asm_emits_interface_dispatch_and_metadata_sections(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        interface Metric {
            fn score() -> i64;
        }

        class Box implements Metric {
            fn score() -> i64 {
                return 7;
            }
        }

        fn use(value: Metric) -> i64 {
            return value.score();
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
    )

    use_body = _body_for_label(asm, "__nif_fn_main__use")

    assert "    call rt_panic_null_deref" in use_body
    assert "    mov rcx, qword ptr [rdi]" in use_body
    assert "    mov rcx, qword ptr [rcx + 64]" in use_body
    assert "    mov rcx, qword ptr [rcx]" in use_body
    assert "    mov r11, qword ptr [rcx]" in use_body
    assert "    call r11" in use_body
    assert "__nif_interface_main__Metric:" in asm
    assert "__nif_interface_name_main__Metric:" in asm
    assert "__nif_interface_methods_main__Box__main__Metric:" in asm
    assert "__nif_interface_tables_main__Box:" in asm


def test_emit_source_asm_is_byte_stable_for_multimodule_dispatch_metadata(tmp_path) -> None:
    files = {
        "left.nif": """
        export interface Metric {
            fn score() -> i64;
        }

        export class Key implements Metric {
            fn score() -> i64 {
                return 1;
            }
        }
        """,
        "right.nif": """
        export interface Metric {
            fn score() -> i64;
        }

        export class Token implements Metric {
            fn score() -> i64 {
                return 2;
            }
        }
        """,
        "main.nif": """
        import left;
        import right;

        fn use_left(value: left.Metric) -> i64 {
            return value.score();
        }

        fn use_right(value: right.Metric) -> i64 {
            return value.score();
        }

        fn main() -> i64 {
            return 0;
        }
        """,
    }

    first = emit_program(lower_project_to_backend_program(tmp_path / "run_a", files, skip_optimize=True))
    second = emit_program(lower_project_to_backend_program(tmp_path / "run_b", files, skip_optimize=True))

    assert first == second
    assert first.index("__nif_interface_left__Metric:") < first.index("__nif_interface_right__Metric:")
    assert first.index("__nif_vtable_left__Key:") < first.index("__nif_vtable_right__Token:")


def test_emit_source_asm_can_execute_virtual_and_interface_dispatch(tmp_path) -> None:
    run = compile_and_run_source(
        tmp_path,
        """
        interface Metric {
            fn score() -> i64;
        }

        class Base {
            fn value() -> i64 {
                return 1;
            }
        }

        class Derived extends Base {
            override fn value() -> i64 {
                return 2;
            }
        }

        class Box implements Metric {
            fn score() -> i64 {
                return 5;
            }
        }

        fn read(value: Base) -> i64 {
            return value.value();
        }

        fn use(value: Metric) -> i64 {
            return value.score();
        }

        fn main() -> i64 {
            return read(Derived()) + use(Box());
        }
        """,
        skip_optimize=True,
    )

    assert run.returncode == 7