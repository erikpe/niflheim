from tests.compiler.codegen.helpers import emit_semantic_source_asm


def test_semantic_emitter_stmt_emits_while_control_flow(tmp_path) -> None:
    source = """
fn loop_to(limit: i64) -> i64 {
    var i: i64 = 0;
    while i < limit {
        i = i + 1;
    }
    return i;
}

fn main() -> i64 {
    return loop_to(4);
}
"""
    asm = emit_semantic_source_asm(tmp_path, source)

    assert ".Lloop_to_while_start_" in asm
    assert ".Lloop_to_while_end_" in asm
    assert "    je .Lloop_to_while_end_" in asm


def test_semantic_emitter_stmt_initializes_uninitialized_var_decls(tmp_path) -> None:
    asm = emit_semantic_source_asm(
        tmp_path,
        """
        fn f() -> i64 { var x: i64; return 0; }

        fn main() -> i64 { return f(); }
        """,
    )

    assert "    mov rax, 0" in asm
    assert "    mov qword ptr [rbp - 8], rax" in asm


def test_semantic_emitter_stmt_emits_if_else_control_flow_labels(tmp_path) -> None:
    source = """
fn choose(flag: bool) -> i64 {
    if flag {
        return 1;
    } else {
        return 2;
    }
}

fn main() -> i64 {
    return choose(true);
}
"""
    asm = emit_semantic_source_asm(tmp_path, source)

    assert ".Lchoose_if_else_" in asm
    assert ".Lchoose_if_end_" in asm
    assert "    je .Lchoose_if_else_" in asm
    assert "    jmp .Lchoose_if_end_" in asm
