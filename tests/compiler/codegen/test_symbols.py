from compiler.codegen.abi.runtime import ARRAY_LEN_RUNTIME_CALL
from compiler.codegen.symbols import (
    epilogue_label,
    is_runtime_call_name,
    mangle_constructor_symbol,
    mangle_debug_file_symbol,
    mangle_debug_function_symbol,
    mangle_method_symbol,
    mangle_type_pointer_offsets_symbol,
    next_label,
    string_literal_symbol,
)


def test_codegen_symbol_helpers() -> None:
    counter = [0]

    assert next_label("f", "loop", counter) == ".Lf_loop_0"
    assert next_label("f", "loop", counter) == ".Lf_loop_1"
    assert mangle_method_symbol("std::Str", "concat") == "__nif_method_std__Str_concat"
    assert mangle_constructor_symbol("std::BigInt") == "__nif_ctor_std__BigInt"
    assert mangle_type_pointer_offsets_symbol("main::Holder") == "__nif_type_name_main__Holder__ptr_offsets"
    assert mangle_debug_function_symbol(".Lmain:entry") == "__nif_dbg_fn__Lmain_entry"
    assert mangle_debug_file_symbol(".Lmain:entry") == "__nif_dbg_file__Lmain_entry"
    assert string_literal_symbol(3) == "__nif_str_lit_3"


def test_codegen_symbol_helpers_cover_epilogues_and_runtime_detection() -> None:
    assert epilogue_label("main") == ".Lmain_epilogue"
    assert is_runtime_call_name(ARRAY_LEN_RUNTIME_CALL) is True
    assert is_runtime_call_name("__nif_method_Box_get") is False
