from compiler.codegen import emit_asm
from compiler.lexer import lex
from compiler.parser import parse


def test_emit_asm_emits_intel_text_header() -> None:
    module = parse(lex("fn main() -> unit { return; }", source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert ".intel_syntax noprefix" in asm
    assert ".text" in asm


def test_emit_asm_emits_sysv_prologue_and_epilogue() -> None:
    module = parse(lex("fn main() -> unit { return; }", source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "main:" in asm
    assert "    push rbp" in asm
    assert "    mov rbp, rsp" in asm
    assert ".Lmain_epilogue:" in asm
    assert "    mov rsp, rbp" in asm
    assert "    pop rbp" in asm
    assert "    ret" in asm


def test_emit_asm_emits_return_jump_to_single_epilogue() -> None:
    source = """
fn f() -> unit {
    return;
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert asm.count("jmp .Lf_epilogue") == 2
    assert asm.count(".Lf_epilogue:") == 1


def test_emit_asm_marks_exported_functions_global() -> None:
    source = """
export fn pubf() -> unit {
    return;
}

fn privf() -> unit {
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert ".globl pubf" in asm
    assert ".globl privf" not in asm


def test_emit_asm_return_integer_literal() -> None:
    module = parse(lex("fn answer() -> i64 { return 42; }", source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "answer:" in asm
    assert "    mov rax, 42" in asm
    assert "    jmp .Lanswer_epilogue" in asm


def test_emit_asm_expression_with_params_and_local_slot() -> None:
    source = """
fn add(x: i64, y: i64) -> i64 {
    var z: i64 = x + y;
    return z;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    mov qword ptr [rbp - 8], rdi" in asm
    assert "    mov qword ptr [rbp - 16], rsi" in asm
    assert "    mov rax, qword ptr [rbp - 8]" in asm
    assert "    add rax, rcx" in asm
    assert "    mov qword ptr [rbp - 24], rax" in asm


def test_emit_asm_null_reference_expression() -> None:
    module = parse(lex("fn f() -> Obj { return null; }", source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "f:" in asm
    assert "    mov rax, 0" in asm


def test_emit_asm_logical_short_circuit() -> None:
    source = """
fn f(a: bool, b: bool) -> bool {
    return a && b;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert ".Lf_logic_rhs_0:" in asm
    assert ".Lf_logic_done_0:" in asm
    assert "    cmp rax, 0" in asm
