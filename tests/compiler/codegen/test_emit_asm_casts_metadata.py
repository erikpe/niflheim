from tests.compiler.codegen.helpers import emit_source_asm


def test_emit_asm_emits_array_type_metadata_symbols_for_reference_casts() -> None:
    source = """
class Person {
    age: i64;
}

fn f(value: Obj) -> Person[] {
    return (Person[])value;
}
"""
    asm = emit_source_asm(source)

    assert "__nif_type_name_Person__:" in asm
    assert '.asciz "Person[]"' in asm
    assert "__nif_type_Person__:" in asm


def test_emit_asm_reference_cast_calls_rt_checked_cast() -> None:
    source = """
class Person {
    age: i64;
}

fn f(o: Obj) -> Person {
    return (Person)o;
}
"""
    asm = emit_source_asm(source)

    assert "    call rt_checked_cast" in asm
    assert "    lea rsi, [rip + __nif_type_Person]" in asm


def test_emit_asm_reference_upcast_to_obj_does_not_call_rt_checked_cast() -> None:
    source = """
class Person {
    age: i64;
}

fn f(p: Person, nums: u64[]) -> Obj {
    var a: Obj = (Obj)p;
    var b: Obj = (Obj)nums;
    return b;
}
"""
    asm = emit_source_asm(source)

    assert "rt_checked_cast" not in asm


def test_emit_asm_obj_to_array_cast_calls_rt_checked_cast_array_kind() -> None:
    source = """
fn f(o: Obj) -> u64[] {
    return (u64[])o;
}
"""
    asm = emit_source_asm(source)

    assert "    call rt_checked_cast_array_kind" in asm
    assert "    mov rsi, 2" in asm


def test_emit_asm_primitive_cast_does_not_call_rt_checked_cast() -> None:
    source = """
fn f(x: i64) -> i64 {
    return (i64)x;
}
"""
    asm = emit_source_asm(source)

    assert "rt_checked_cast" not in asm


def test_emit_asm_emits_type_metadata_symbols_for_reference_casts() -> None:
    source = """
fn f(o: Obj) -> Obj {
    return (Obj)o;
}
"""
    asm = emit_source_asm(source)

    assert ".section .rodata" in asm
    assert "__nif_type_name_Obj:" in asm
    assert '.asciz "Obj"' in asm
    assert ".data" in asm
    assert "__nif_type_Obj:" in asm


def test_emit_asm_class_type_metadata_includes_pointer_offsets_for_reference_fields() -> None:
    source = """
class Holder {
    value: Obj;
    count: i64;
}

fn f(o: Obj) -> Holder {
    return (Holder)o;
}
"""
    asm = emit_source_asm(source)

    assert "__nif_type_name_Holder__ptr_offsets:" in asm
    assert "__nif_type_name_Holder__ptr_offsets:\n    .long 24" in asm
    assert (
        "__nif_type_Holder:\n"
        "    .long 0\n"
        "    .long 1\n"
        "    .long 1\n"
        "    .long 8\n"
        "    .quad 0\n"
        "    .quad __nif_type_name_Holder\n"
        "    .quad 0\n"
        "    .quad __nif_type_name_Holder__ptr_offsets\n"
        "    .long 1\n"
        "    .long 0"
    ) in asm


def test_emit_asm_class_type_metadata_omits_pointer_offsets_for_primitive_fields() -> None:
    source = """
class Counter {
    value: i64;
}

fn f(o: Obj) -> Counter {
    return (Counter)o;
}
"""
    asm = emit_source_asm(source)

    assert "__nif_type_name_Counter__ptr_offsets:" not in asm
    assert (
        "__nif_type_Counter:\n"
        "    .long 0\n"
        "    .long 0\n"
        "    .long 1\n"
        "    .long 8\n"
        "    .quad 0\n"
        "    .quad __nif_type_name_Counter\n"
        "    .quad 0\n"
        "    .quad 0\n"
        "    .long 0\n"
        "    .long 0"
    ) in asm


def test_emit_asm_emits_class_type_metadata_even_without_casts() -> None:
    source = """
class Holder {
    value: Obj;
}

fn main() -> i64 {
    var h: Holder = Holder(null);
    if h == null {
        return 1;
    }
    return 0;
}
"""
    asm = emit_source_asm(source)

    assert "__nif_type_name_Holder:" in asm
    assert "__nif_type_Holder:" in asm
    assert "__nif_type_name_Holder__ptr_offsets:" in asm