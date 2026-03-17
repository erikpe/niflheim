from tests.compiler.codegen.helpers import emit_semantic_source_asm


def test_semantic_emitter_expr_emits_integer_binary_expr(tmp_path) -> None:
    asm = emit_semantic_source_asm(
        tmp_path,
        """
        fn f(a: i64, b: i64) -> i64 { return a + b; }

        fn main() -> i64 { return f(20, 22); }
        """,
        source_path="main.nif",
    )

    assert "    push rax" in asm
    assert "    add rax, rcx" in asm


def test_semantic_emitter_expr_emits_numeric_cast_conversions(tmp_path) -> None:
    asm = emit_semantic_source_asm(
        tmp_path,
        """
        fn to_double(x: i64) -> double { return (double)x; }

        fn to_bool(x: double) -> bool { return (bool)x; }

        fn main() -> i64 {
            var d: double = to_double(7);
            if to_bool(d) {
                return 0;
            }
            return 1;
        }
        """,
    )

    assert "    cvtsi2sd xmm0, rax" in asm
    assert "    movq rax, xmm0" in asm
    assert "    movq xmm0, rax" in asm
    assert "    cvttsd2si rax, xmm0" in asm
    assert "    cmp rax, 0" in asm
    assert "    setne al" in asm
