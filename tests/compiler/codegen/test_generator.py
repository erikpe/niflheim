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


def test_codegen_build_symbol_tables_tracks_functions_methods_and_fields() -> None:
    source = """
class Box {
    value: i64;
    next: Obj;

    static fn make(value: i64) -> Box {
        return Box(value, null);
    }

    fn get() -> i64 {
        return __self.value;
    }
}

fn helper() -> bool {
    return true;
}
"""
    generator = build_generator(parse_module(source, source_path="examples/codegen.nif"), build_symbols=False)

    generator.build_symbol_tables()

    assert generator.method_labels[("Box", "make")] == "__nif_method_Box_make"
    assert generator.method_labels[("Box", "get")] == "__nif_method_Box_get"
    assert generator.method_return_types[("Box", "get")] == "i64"
    assert generator.method_is_static[("Box", "make")] is True
    assert generator.method_is_static[("Box", "get")] is False
    assert generator.function_return_types["helper"] == "bool"
    assert generator.constructor_labels["Box"] == "__nif_ctor_Box"
    assert generator.class_field_offsets[("Box", "value")] == 24
    assert generator.class_field_offsets[("Box", "next")] == 32
    assert generator.class_field_type_names[("Box", "next")] == "Obj"
    assert generator.constructor_layouts["Box"].param_field_names == ["value", "next"]
