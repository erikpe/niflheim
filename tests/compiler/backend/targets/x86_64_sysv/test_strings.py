from __future__ import annotations

from tests.compiler.backend.targets.x86_64_sysv.helpers import compile_and_run_source, emit_program, emit_source_asm
from tests.compiler.backend.lowering.helpers import lower_source_to_backend_program


def test_emit_source_asm_emits_pooled_string_literal_bytes_and_runtime_helper(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        class Str {
            static fn from_u8_array(value: u8[]) -> Str {
                return null;
            }
        }

        fn first() -> Str {
            return "hi";
        }

        fn second() -> Str {
            return "hi";
        }

        fn main() -> i64 {
            first();
            return 0;
        }
        """,
        skip_optimize=True,
    )

    assert asm.count("__nif_str_lit_0:") == 1
    assert "__nif_str_lit_1:" not in asm
    assert '.asciz "hi"' in asm
    assert asm.count("    lea rdi, [rip + __nif_str_lit_0]") == 2
    assert asm.count("    call rt_array_from_bytes_u8") == 2
    assert asm.count("    call __nif_method_main__Str_from_u8_array") == 2


def test_emit_source_asm_is_byte_stable_for_repeated_string_literal_lowering(tmp_path) -> None:
    source = """
    class Str {
        static fn from_u8_array(value: u8[]) -> Str {
            return null;
        }
    }

    fn greet() -> Str {
        return "hello";
    }

    fn main() -> i64 {
        greet();
        return 0;
    }
    """

    first = emit_program(lower_source_to_backend_program(tmp_path / "run_a", source, skip_optimize=True))
    second = emit_program(lower_source_to_backend_program(tmp_path / "run_b", source, skip_optimize=True))

    assert first == second


def test_emit_source_asm_can_execute_string_helper_flow(tmp_path) -> None:
    run = compile_and_run_source(
        tmp_path,
        """
        class Str {
            static fn from_u8_array(value: u8[]) -> Str {
                return null;
            }
        }

        fn main() -> i64 {
            var value: Str = "phase-5";
            return 0;
        }
        """,
        skip_optimize=True,
    )

    assert run.returncode == 0


def test_emit_source_asm_escapes_embedded_nul_and_control_bytes_in_string_blob(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        class Str {
            static fn from_u8_array(value: u8[]) -> Str {
                return null;
            }
        }

        fn main() -> i64 {
            var value: Str = "A\\x00B\\n\\xff";
            return 0;
        }
        """,
        skip_optimize=True,
    )

    assert '.asciz "A\\000B\\n\\377"' in asm