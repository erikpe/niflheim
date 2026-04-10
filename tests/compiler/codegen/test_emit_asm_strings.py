from compiler.codegen.abi.runtime import ARRAY_FROM_BYTES_U8_RUNTIME_CALL
from tests.compiler.codegen.helpers import emit_source_asm


def test_emit_asm_string_literal_lowers_via_u8_array_and_str_factory(tmp_path) -> None:
    source = """
class Str {
    _bytes: u8[];

    static fn from_u8_array(value: u8[]) -> Str {
        return Str(value);
    }
}

fn main() -> i64 {
    var s: Str = "A\\x42\\n";
    if s == null {
        return 1;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "__nif_str_lit_0:" in asm
    assert f"    call {ARRAY_FROM_BYTES_U8_RUNTIME_CALL}" in asm
    assert "    call __nif_method_main__Str_from_u8_array" in asm


def test_emit_asm_string_literal_inside_for_in_is_collected(tmp_path) -> None:
    source = """
class Str {
    _bytes: u8[];

    static fn from_u8_array(value: u8[]) -> Str {
        return Str(value);
    }
}

class Vec {
    fn iter_len() -> u64 {
        return 0u;
    }

    fn iter_get(index: i64) -> Str {
        return Str(u8[](0u));
    }
}

fn print(value: Str) -> unit {
    return;
}

fn main() -> i64 {
    var lines: Vec = null;
    for line in lines {
        print("Key: ");
        print(line);
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "__nif_str_lit_0:" in asm
    assert f"    call {ARRAY_FROM_BYTES_U8_RUNTIME_CALL}" in asm


def test_emit_asm_str_index_lowers_via_structural_get_call(tmp_path) -> None:
    source = """
class Str {
    _bytes: u8[];

    fn index_get(index: i64) -> u8 {
        return __self._bytes[index];
    }
}

fn main() -> i64 {
    var s: Str = Str(u8[](3u));
    var b: u8 = s[1];
    return (i64)b;
}
"""
    asm = emit_source_asm(tmp_path, source)
    main_body = asm[asm.index("main:") : asm.index(".Lmain_epilogue:")]

    assert "    call __nif_method_main__Str_index_get" in main_body
    assert "    mov rcx, qword ptr [rcx + 80]" not in main_body
    assert "    call r11" not in main_body


def test_emit_asm_dead_string_literal_helper_is_not_emitted_after_pruning(tmp_path) -> None:
    source = """
class Str {
    _bytes: u8[];

    static fn from_u8_array(value: u8[]) -> Str {
        return Str(value);
    }
}

fn dead() -> Str {
    return "unreachable";
}

fn main() -> i64 {
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "__nif_str_lit_0:" not in asm
    assert f"    call {ARRAY_FROM_BYTES_U8_RUNTIME_CALL}" not in asm
