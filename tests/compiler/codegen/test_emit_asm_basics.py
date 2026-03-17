from tests.compiler.codegen.helpers import emit_semantic_source_asm


def test_emit_asm_emits_intel_text_header(tmp_path) -> None:
    asm = emit_semantic_source_asm(tmp_path, "fn main() -> i64 { return 0; }")

    assert ".intel_syntax noprefix" in asm
    assert ".text" in asm
    assert '.section .note.GNU-stack,"",@progbits' in asm


def test_emit_asm_emits_sysv_prologue_and_epilogue(tmp_path) -> None:
    asm = emit_semantic_source_asm(tmp_path, "fn main() -> i64 { return 0; }")

    assert "main:" in asm
    assert "    push rbp" in asm
    assert "    mov rbp, rsp" in asm
    assert ".Lmain_epilogue:" in asm
    assert "    mov rsp, rbp" in asm
    assert "    pop rbp" in asm
    assert "    ret" in asm


def test_emit_asm_emits_return_jump_to_single_epilogue(tmp_path) -> None:
    source = """
fn f() -> unit {
    return;
    return;
}

fn main() -> i64 {
    f();
    return 0;
}
"""
    asm = emit_semantic_source_asm(tmp_path, source)

    assert asm.count("jmp .Lf_epilogue") == 2
    assert asm.count(".Lf_epilogue:") == 1


def test_emit_asm_marks_exported_functions_global(tmp_path) -> None:
    source = """
export fn pubf() -> unit {
    return;
}

fn privf() -> unit {
    return;
}

fn main() -> i64 {
    pubf();
    return 0;
}
"""
    asm = emit_semantic_source_asm(tmp_path, source)

    assert ".globl pubf" in asm
    assert ".globl privf" not in asm


def test_emit_asm_marks_main_global_without_export(tmp_path) -> None:
    asm = emit_semantic_source_asm(tmp_path, "fn main() -> i64 { return 0; }")

    assert ".globl main" in asm


def test_emit_asm_return_integer_literal(tmp_path) -> None:
    asm = emit_semantic_source_asm(
        tmp_path,
        """
        fn answer() -> i64 { return 42; }

        fn main() -> i64 { return answer(); }
        """,
    )

    assert "answer:" in asm
    assert "    mov rax, 42" in asm
    assert "    jmp .Lanswer_epilogue" in asm


def test_emit_asm_return_u64_suffixed_integer_literal(tmp_path) -> None:
    asm = emit_semantic_source_asm(
        tmp_path,
        """
        fn answer() -> u64 { return 42u; }

        fn main() -> i64 { return (i64)answer(); }
        """,
    )

    assert "answer:" in asm
    assert "    mov rax, 42" in asm
    assert "    mov rax, 42u" not in asm


def test_emit_asm_return_u8_suffixed_integer_literal(tmp_path) -> None:
    asm = emit_semantic_source_asm(
        tmp_path,
        """
        fn answer() -> u8 { return 113u8; }

        fn main() -> i64 { return (i64)answer(); }
        """,
    )

    assert "answer:" in asm
    assert "    mov rax, 113" in asm
    assert "    mov rax, 113u8" not in asm


def test_emit_asm_return_char_literal(tmp_path) -> None:
    asm = emit_semantic_source_asm(
        tmp_path,
        """
        fn answer() -> u8 { return 'q'; }

        fn main() -> i64 { return (i64)answer(); }
        """,
    )

    assert "answer:" in asm
    assert "    mov rax, 113" in asm


def test_emit_asm_return_double_literal_bits(tmp_path) -> None:
    asm = emit_semantic_source_asm(
        tmp_path,
        """
        fn answer() -> double { return 1.5; }

        fn main() -> i64 { return (i64)answer(); }
        """,
    )

    assert "answer:" in asm
    assert "0x3ff8000000000000" in asm


def test_emit_asm_double_call_uses_xmm_registers(tmp_path) -> None:
    source = """
fn add(a: double, b: double) -> double {
    return a + b;
}

fn main() -> i64 {
    return (i64)add(1.0, 2.0);
}
"""
    asm = emit_semantic_source_asm(tmp_path, source)

    assert "    movq xmm0, qword ptr [r10]" in asm
    assert "    movq xmm1, qword ptr [r10 + 8]" in asm
    assert "    addsd xmm0, xmm1" in asm


def test_emit_asm_expression_with_params_and_local_slot(tmp_path) -> None:
    source = """
fn add(x: i64, y: i64) -> i64 {
    var z: i64 = x + y;
    return z;
}

fn main() -> i64 {
    return add(20, 22);
}
"""
    asm = emit_semantic_source_asm(tmp_path, source)

    assert "    mov qword ptr [rbp - 8], rdi" in asm
    assert "    mov qword ptr [rbp - 16], rsi" in asm
    assert "    mov rax, qword ptr [rbp - 8]" in asm
    assert "    add rax, rcx" in asm
    assert "    mov qword ptr [rbp - 24], rax" in asm


def test_emit_asm_null_reference_expression(tmp_path) -> None:
    asm = emit_semantic_source_asm(
        tmp_path,
        """
        fn f() -> Obj { return null; }

        fn main() -> i64 {
            if f() == null {
                return 0;
            }
            return 1;
        }
        """,
    )

    assert "f:" in asm
    assert "    mov rax, 0" in asm


def test_emit_asm_logical_short_circuit(tmp_path) -> None:
    source = """
fn f(a: bool, b: bool) -> bool {
    return a && b;
}

fn main() -> i64 {
    if f(true, false) {
        return 1;
    }
    return 0;
}
"""
    asm = emit_semantic_source_asm(tmp_path, source)

    assert ".Lf_logic_rhs_0:" in asm
    assert ".Lf_logic_done_0:" in asm
    assert "    cmp rax, 0" in asm


def test_emit_asm_if_else_control_flow(tmp_path) -> None:
    source = """
fn choose(flag: bool) -> i64 {
    if flag {
        return 1;
    } else {
        return 2;
    }
}
"""
    source += "\nfn main() -> i64 { return choose(true); }\n"
    asm = emit_semantic_source_asm(tmp_path, source)

    assert ".Lchoose_if_else_" in asm
    assert ".Lchoose_if_end_" in asm
    assert "    je .Lchoose_if_else_" in asm


def test_emit_asm_while_loop_control_flow(tmp_path) -> None:
    source = """
fn loop_to(limit: i64) -> i64 {
    var i: i64 = 0;
    while i < limit {
        i = i + 1;
    }
    return i;
}
"""
    source += "\nfn main() -> i64 { return loop_to(4); }\n"
    asm = emit_semantic_source_asm(tmp_path, source)

    assert ".Lloop_to_while_start_" in asm
    assert ".Lloop_to_while_end_" in asm
    assert "    je .Lloop_to_while_end_" in asm
    assert "    jmp .Lloop_to_while_start_" in asm


def test_emit_asm_else_if_chain_and_nested_locals(tmp_path) -> None:
    source = """
fn classify(x: i64) -> i64 {
    if x < 0 {
        var y: i64 = 10;
        return y;
    } else if x == 0 {
        var z: i64 = 20;
        return z;
    } else {
        return 30;
    }
}
"""
    source += "\nfn main() -> i64 { return classify(0); }\n"
    asm = emit_semantic_source_asm(tmp_path, source)

    assert asm.count("_if_else_") >= 2
    assert "    mov qword ptr [rbp - 16], rax" in asm
    assert "    mov qword ptr [rbp - 24], rax" in asm
