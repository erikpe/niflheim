from compiler.codegen.emitter_fn import emit_function
from tests.compiler.codegen.helpers import build_generator, parse_module


def test_emitter_fn_module_emits_function_prologue_and_epilogue() -> None:
    module_ast = parse_module("fn main() -> i64 { return 0; }", source_path="examples/codegen_fn.nif")
    generator = build_generator(module_ast)

    emit_function(generator, module_ast.functions[0])

    assert ".globl main" in generator.asm.lines
    assert "main:" in generator.asm.lines
    assert ".Lmain_epilogue:" in generator.asm.lines
    assert "    ret" in generator.asm.lines