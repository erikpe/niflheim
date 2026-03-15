from compiler.codegen.types import function_type_return_type_name, type_ref_name
from compiler.lexer import lex
from compiler.parser import parse


def test_codegen_type_helpers() -> None:
    module = parse(lex("fn f(callback: fn(i64,u64)->bool) -> unit { return; }", source_path="examples/codegen.nif"))
    fn = module.functions[0]

    assert type_ref_name(fn.params[0].type_ref) == "fn(i64,u64)->bool"
    assert function_type_return_type_name("fn(i64,u64)->bool") == "bool"
