from compiler.codegen.symbols import mangle_constructor_symbol, mangle_method_symbol, next_label


def test_codegen_symbol_helpers() -> None:
    counter = [0]

    assert next_label("f", "loop", counter) == ".Lf_loop_0"
    assert next_label("f", "loop", counter) == ".Lf_loop_1"
    assert mangle_method_symbol("std::Str", "concat") == "__nif_method_std__Str_concat"
    assert mangle_constructor_symbol("std::BigInt") == "__nif_ctor_std__BigInt"
