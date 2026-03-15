from tests.compiler.codegen.helpers import build_generator, parse_module


def test_codegen_uses_builder_for_aligned_call_and_comments() -> None:
    source = """
fn callee() -> i64 {
    return 7;
}

fn caller() -> i64 {
    return callee();
}
"""
    generator = build_generator(parse_module(source, source_path="examples/codegen.nif"), build_symbols=False)

    asm = generator.generate()

    assert generator.asm.build() == asm
    assert any(line.startswith("    # ") for line in generator.asm.lines)
    assert "    test rsp, 8" in asm
    assert ".L__nif_aligned_call_0:" in asm