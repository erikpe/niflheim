from tests.compiler.codegen.helpers import emit_source_asm


def test_emit_asm_string_literal_lowers_via_u8_array_and_str_factory() -> None:
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
    asm = emit_source_asm(source)

    assert "__nif_str_lit_0:" in asm
    assert "    call rt_array_from_bytes_u8" in asm
    assert "    call __nif_method_Str_from_u8_array" in asm


def test_emit_asm_string_literal_inside_for_in_is_collected() -> None:
    source = """
class Str {
    _bytes: u8[];

    static fn from_u8_array(value: u8[]) -> Str {
        return Str(value);
    }
}

class Vec {
    fn iter_len() -> i64 {
        return 0;
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
    asm = emit_source_asm(source, source_path="examples/codegen_for_in_string_literal.nif")

    assert "__nif_str_lit_0:" in asm
    assert "    call rt_array_from_bytes_u8" in asm


def test_emit_asm_str_index_lowers_via_structural_get_call() -> None:
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
    asm = emit_source_asm(source)

    assert "    call __nif_method_Str_index_get" in asm
