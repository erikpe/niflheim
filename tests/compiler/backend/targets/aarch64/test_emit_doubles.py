from __future__ import annotations

from compiler.backend.program.symbols import epilogue_label, mangle_function_symbol
from tests.compiler.backend.targets.aarch64.helpers import emit_source_asm


def _body_for_label(asm: str, label: str) -> str:
    return asm[asm.index(f"{label}:") : asm.index(f"{epilogue_label(label)}:")]


def test_emit_source_asm_emits_double_constants_and_arithmetic_sequences(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn add(a: double, b: double) -> double {
            var base: double = 1.5;
            return (a + b) * base;
        }

        fn main() -> i64 {
            if add(1.0, 2.0) == 4.5 {
                return 0;
            }
            return 1;
        }
        """,
        skip_optimize=True,
    )
    add_label = mangle_function_symbol(("main",), "add")
    add_body = _body_for_label(asm, add_label)

    assert "    fmov d0, x9" in asm
    assert "    str d0, [x29, #-8]" in add_body
    assert "    str d1, [x29, #-16]" in add_body
    assert "    ldr d0, [x29, #-8]" in add_body
    assert "    ldr d1, [x29, #-16]" in add_body
    assert "    fadd d0, d0, d1" in add_body
    assert "    fmul d0, d0, d1" in add_body


def test_emit_source_asm_emits_double_comparison_and_negation_sequences(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn is_ordered(a: double, b: double) -> i64 {
            var neg: double = -a;
            if neg < b {
                return 1;
            }
            return 0;
        }

        fn main() -> i64 {
            return is_ordered(1.5, 0.0);
        }
        """,
        skip_optimize=True,
    )
    ordered_label = mangle_function_symbol(("main",), "is_ordered")
    ordered_body = _body_for_label(asm, ordered_label)

    assert "    fneg d0, d0" in ordered_body
    assert "    fcmp d0, d1" in ordered_body
    assert "    cset w0, lt" in ordered_body
    assert "    cset w1, vc" in ordered_body
    assert "    and w0, w0, w1" in ordered_body


def test_emit_source_asm_emits_mixed_signature_calls_with_float_and_integer_registers(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn mix(a: i64, b: double, c: u64, d: double, e: bool, f: double, g: i64, h: double, i: u64, j: double, k: i64, l: i64) -> double {
            return j;
        }

        fn main() -> i64 {
            if mix(1, 0.5, 2u, 0.25, true, 0.125, 3, 0.75, 4u, 1.5, 5, 6) == 1.5 {
                return 0;
            }
            return 1;
        }
        """,
        skip_optimize=True,
    )
    main_body = _body_for_label(asm, "main")

    assert "    movz x0, #1" in main_body
    assert "    movz x1, #2" in main_body
    assert "    movz x2, #1" in main_body
    assert "    movz x3, #3" in main_body
    assert "    movz x4, #4" in main_body
    assert "    movz x5, #5" in main_body
    assert "    movz x6, #6" in main_body
    assert "    bl __nif_fn_main__mix" in main_body


def test_emit_source_asm_is_byte_stable_for_double_programs(tmp_path) -> None:
    source = """
    fn blend(a: double, b: double) -> double {
        return (a + b) / 2.0;
    }

    fn main() -> i64 {
        if blend(1.0, 3.0) == 2.0 {
            return 0;
        }
        return 1;
    }
    """

    first = emit_source_asm(tmp_path / "run_a", source, skip_optimize=True)
    second = emit_source_asm(tmp_path / "run_b", source, skip_optimize=True)

    assert first == second