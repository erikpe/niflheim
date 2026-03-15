from compiler.codegen.emitter_module import generate_module
from tests.compiler.codegen.helpers import build_generator, parse_module


def test_emitter_module_helper_orchestrates_sections_and_methods() -> None:
    source = """
class Box {
    value: i64;

    fn get(self: Box) -> i64 {
        return self.value;
    }
}

fn main() -> i64 {
    return 0;
}
"""
    generator = build_generator(parse_module(source, source_path="examples/codegen_module.nif"), build_symbols=False)

    asm = generate_module(generator)

    assert asm == generator.asm.build()
    assert ".text" in asm
    assert "__nif_method_Box_get" in asm
    assert "__nif_ctor_Box" in asm
    assert '.section .note.GNU-stack,"",@progbits' in asm