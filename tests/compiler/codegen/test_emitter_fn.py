from tests.compiler.codegen.helpers import emit_semantic_source_asm


def test_semantic_emitter_fn_emits_function_prologue_and_epilogue(tmp_path) -> None:
    asm = emit_semantic_source_asm(tmp_path, "fn main() -> i64 { return 0; }")

    assert ".globl main" in asm
    assert "main:" in asm
    assert ".Lmain_epilogue:" in asm
    assert "    ret" in asm
