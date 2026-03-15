from compiler.codegen.layout import build_layout
from compiler.lexer import lex
from compiler.parser import parse


def test_codegen_build_layout_tracks_reference_roots_and_temp_roots() -> None:
    module = parse(lex("fn f(a: Obj) -> unit { g(a); }", source_path="examples/codegen.nif"))
    fn = module.functions[0]

    layout = build_layout(fn)

    assert layout.root_slot_names == ["a"]
    assert layout.root_slot_count >= 7
    assert layout.stack_size % 16 == 0