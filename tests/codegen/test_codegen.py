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
