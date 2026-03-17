from tests.compiler.codegen.helpers import emit_semantic_source_asm


def test_semantic_emitter_module_orchestrates_sections_and_methods(tmp_path) -> None:
    source = """
class Box {
    value: i64;

    fn get() -> i64 {
        return __self.value;
    }
}

fn main() -> i64 {
    return Box(0).get();
}
"""
    asm = emit_semantic_source_asm(tmp_path, source)

    assert ".text" in asm
    assert "__nif_method_Box_get" in asm
    assert "__nif_ctor_Box" in asm
    assert '.section .note.GNU-stack,"",@progbits' in asm
