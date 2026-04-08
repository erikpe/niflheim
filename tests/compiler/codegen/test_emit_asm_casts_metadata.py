from tests.compiler.codegen.helpers import emit_source_asm


def test_emit_asm_emits_array_type_metadata_symbols_for_reference_casts(tmp_path) -> None:
    source = """
class Person {
    age: i64;
}

fn f(value: Obj) -> Person[] {
    return (Person[])value;
}

fn main() -> i64 {
    if f(null) == null {
        return 0;
    }
    return 1;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "__nif_type_name_Person__:" in asm
    assert '.asciz "Person[]"' in asm
    assert "__nif_type_Person__:" in asm


def test_emit_asm_reference_cast_calls_rt_checked_cast(tmp_path) -> None:
    source = """
class Person {
    age: i64;
}

fn f(o: Obj) -> Person {
    return (Person)o;
}

fn main() -> i64 {
    if f(null) == null {
        return 0;
    }
    return 1;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "    call rt_checked_cast" in asm
    assert "    lea rsi, [rip + __nif_type_Person]" in asm


def test_emit_asm_reference_upcast_to_obj_does_not_call_rt_checked_cast(tmp_path) -> None:
    source = """
class Person {
    age: i64;
}

fn f(p: Person, nums: u64[]) -> Obj {
    var a: Obj = (Obj)p;
    var b: Obj = (Obj)nums;
    return b;
}

fn main() -> i64 {
    if f(Person(7), u64[](1u)) == null {
        return 1;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "rt_checked_cast" not in asm


def test_emit_asm_obj_to_array_cast_calls_rt_checked_cast_array_kind(tmp_path) -> None:
    source = """
fn f(o: Obj) -> u64[] {
    return (u64[])o;
}

fn main() -> i64 {
    if f(null) == null {
        return 0;
    }
    return 1;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "    call rt_checked_cast_array_kind" in asm
    assert "    mov rsi, 2" in asm


def test_emit_asm_primitive_cast_does_not_call_rt_checked_cast(tmp_path) -> None:
    source = """
fn f(x: i64) -> i64 {
    return (i64)x;
}

fn main() -> i64 {
    return f(7);
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "rt_checked_cast" not in asm


def test_emit_asm_emits_type_metadata_symbols_for_reference_casts(tmp_path) -> None:
    source = """
fn f(o: Obj) -> Obj {
    return (Obj)o;
}

fn main() -> i64 {
    if f(null) == null {
        return 0;
    }
    return 1;
}
"""
    asm = emit_source_asm(tmp_path, source, disabled_passes={"redundant_cast_elimination"})

    assert ".section .rodata" in asm
    assert "__nif_type_name_Obj:" in asm
    assert '.asciz "Obj"' in asm
    assert ".data" in asm
    assert "__nif_type_Obj:" in asm


def test_emit_asm_class_type_metadata_includes_pointer_offsets_for_reference_fields(tmp_path) -> None:
    source = """
class Holder {
    value: Obj;
    count: i64;
}

fn f(o: Obj) -> Holder {
    return (Holder)o;
}

fn main() -> i64 {
    if f(null) == null {
        return 0;
    }
    return 1;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "__nif_type_name_main__Holder__ptr_offsets:" in asm
    assert "__nif_type_name_main__Holder__ptr_offsets:\n    .long 24" in asm
    assert "__nif_type_Holder:" in asm
    assert "__nif_type_main__Holder:" in asm
    assert "    .quad __nif_type_name_main__Holder" in asm
    assert "    .quad __nif_type_name_main__Holder__ptr_offsets" in asm
    assert "    .long 1" in asm
    assert "    .long 0" in asm


def test_emit_asm_class_type_metadata_omits_pointer_offsets_for_primitive_fields(tmp_path) -> None:
    source = """
class Counter {
    value: i64;
}

fn f(o: Obj) -> Counter {
    return (Counter)o;
}

fn main() -> i64 {
    if f(null) == null {
        return 0;
    }
    return 1;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "__nif_type_name_main__Counter__ptr_offsets:" not in asm
    assert "__nif_type_Counter:" in asm
    assert "__nif_type_main__Counter:" in asm
    assert "    .quad __nif_type_name_main__Counter" in asm
    assert "    .quad 0" in asm


def test_emit_asm_emits_class_type_metadata_even_without_casts(tmp_path) -> None:
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
    asm = emit_source_asm(tmp_path, source)

    assert "__nif_type_name_Holder:" in asm
    assert "__nif_type_Holder:" in asm
    assert "__nif_type_name_main__Holder__ptr_offsets:" in asm


def test_emit_asm_reserves_interface_metadata_slots_in_rt_type_records(tmp_path) -> None:
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
    asm = emit_source_asm(tmp_path, source)

    assert "__nif_type_Holder:" in asm
    assert "    .quad __nif_type_name_main__Holder" in asm
    assert "    .quad __nif_type_name_main__Holder__ptr_offsets" in asm
    assert "    .quad 0\n    .quad 0\n    .long 0\n    .long 0\n    .quad 0\n    .long 0\n    .long 0" in asm

def test_emit_asm_emits_inheritance_metadata_with_base_prefix_offsets(tmp_path) -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

class Base implements Hashable {
    head: Obj;

    fn hash_code() -> u64 {
        return 1u;
    }
}

class Derived extends Base {
    count: i64;
    tail: Obj;
}

fn main() -> i64 {
    var value: Derived = Derived(null, 1, null);
    if value == null {
        return 1;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "__nif_type_name_main__Derived__ptr_offsets:" in asm
    assert "__nif_type_name_main__Derived__ptr_offsets:\n    .long 24\n    .long 40" in asm
    assert "__nif_interface_methods_main__Derived__main__Hashable:\n    .quad __nif_method_Base_hash_code" in asm
    assert "    .quad __nif_type_main__Base" in asm


def test_emit_asm_emits_class_vtable_tables_and_rt_type_links(tmp_path) -> None:
    source = """
class Base {
    fn head() -> i64 {
        return 1;
    }
}

class Derived extends Base {
    override fn head() -> i64 {
        return 2;
    }

    fn tail() -> i64 {
        return 3;
    }
}

fn main() -> i64 {
    var value: Derived = Derived();
    if value == null {
        return 1;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "__nif_vtable_main__Base:\n    .quad __nif_method_Base_head" in asm
    assert (
        "__nif_vtable_main__Derived:\n    .quad __nif_method_Derived_head\n    .quad __nif_method_Derived_tail"
        in asm
    )
    assert "__nif_type_main__Derived:" in asm
    assert "    .quad __nif_vtable_main__Derived" in asm
    assert "    .long 2" in asm


def test_emit_asm_obj_to_interface_cast_inlines_slot_table_check(tmp_path) -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

class Key implements Hashable {
    fn hash_code() -> u64 {
        return 1u;
    }
}

fn f(o: Obj) -> Hashable {
    return (Hashable)o;
}

fn main() -> i64 {
    if f(null) == null {
        return 0;
    }
    return 1;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "    call rt_checked_cast_interface" not in asm
    assert "    mov rcx, qword ptr [rax]" in asm
    assert "    mov rcx, qword ptr [rcx + 64]" in asm
    assert "    mov rcx, qword ptr [rcx]" in asm
    assert "    lea rsi, [rip + __nif_interface_main__Hashable]" in asm
    assert "    call rt_panic_bad_cast" in asm
    assert "__nif_interface_name_main__Hashable:" in asm
    assert '.asciz "main::Hashable"' in asm
    assert "__nif_interface_main__Hashable:" in asm


def test_emit_asm_obj_type_test_calls_rt_is_instance_of_type(tmp_path) -> None:
    source = """
class Person {
    age: i64;
}

fn f(o: Obj) -> bool {
    return o is Person;
}

fn main() -> i64 {
    if f(null) {
        return 1;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "    call rt_is_instance_of_type" in asm
    assert "    lea rsi, [rip + __nif_type_Person]" in asm


def test_emit_asm_obj_type_test_inlines_slot_table_check(tmp_path) -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

class Key implements Hashable {
    fn hash_code() -> u64 {
        return 1u;
    }
}

fn f(o: Obj) -> bool {
    return o is Hashable;
}

fn main() -> i64 {
    if f(null) {
        return 1;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "    call rt_is_instance_of_interface" not in asm
    assert "    mov rcx, qword ptr [rax]" in asm
    assert "    mov rcx, qword ptr [rcx + 64]" in asm
    assert "    mov rcx, qword ptr [rcx]" in asm
    assert "    setne al" in asm
    assert "    movzx rax, al" in asm


def test_emit_asm_emits_interface_method_tables_and_impl_records(tmp_path) -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
    fn equals(other: Obj) -> bool;
}

class Key implements Hashable {
    fn hash_code() -> u64 {
        return 1u;
    }

    fn equals(other: Obj) -> bool {
        return true;
    }
}

fn main() -> i64 {
    var key: Key = Key();
    if key == null {
        return 1;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "__nif_interface_methods_main__Key__main__Hashable:" in asm
    assert (
        "__nif_interface_methods_main__Key__main__Hashable:\n    .quad __nif_method_Key_hash_code\n    .quad __nif_method_Key_equals"
        in asm
    )
    assert "__nif_interface_tables_main__Key:\n    .quad __nif_interface_methods_main__Key__main__Hashable" in asm
    assert "__nif_type_Key:" in asm
    assert (
        "__nif_interface_main__Hashable:\n    .quad __nif_interface_name_main__Hashable\n    .long 0\n    .long 2\n    .long 0"
        in asm
    )
    assert "    .quad __nif_interface_tables_main__Key" in asm
    assert "    .long 1" in asm
    assert "__nif_interface_impls_main__Key:" not in asm


def test_emit_asm_records_stable_interface_descriptor_slot_indices(tmp_path) -> None:
    source = """
interface Alpha {
    fn a() -> i64;
}

interface Beta {
    fn b() -> i64;
}

fn keep_alpha(value: Obj) -> Alpha {
    return (Alpha)value;
}

fn keep_beta(value: Obj) -> Beta {
    return (Beta)value;
}

fn main() -> i64 {
    if keep_alpha(null) != null {
        return 1;
    }
    if keep_beta(null) != null {
        return 1;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert (
        "__nif_interface_main__Alpha:\n    .quad __nif_interface_name_main__Alpha\n    .long 0\n    .long 1\n    .long 0"
        in asm
    )
    assert (
        "__nif_interface_main__Beta:\n    .quad __nif_interface_name_main__Beta\n    .long 1\n    .long 1\n    .long 0"
        in asm
    )


def test_emit_asm_emits_slotted_interface_tables_with_null_holes(tmp_path) -> None:
    source = """
interface Alpha {
    fn alpha() -> i64;
}

interface Beta {
    fn beta() -> i64;
}

interface Gamma {
    fn gamma() -> i64;
}

fn keep_beta(value: Obj) -> Beta {
    return (Beta)value;
}

class Mixed implements Alpha, Gamma {
    fn alpha() -> i64 {
        return 1;
    }

    fn gamma() -> i64 {
        return 2;
    }
}

fn main() -> i64 {
    var value: Mixed = Mixed();
    if value == null {
        return 1;
    }
    if keep_beta(null) != null {
        return 1;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert (
        "__nif_interface_tables_main__Mixed:\n"
        "    .quad __nif_interface_methods_main__Mixed__main__Alpha\n"
        "    .quad 0\n"
        "    .quad __nif_interface_methods_main__Mixed__main__Gamma"
    ) in asm
    assert "__nif_type_main__Mixed:" in asm
    assert "    .quad __nif_interface_tables_main__Mixed" in asm
    assert "    .long 3" in asm


def test_emit_asm_emits_imported_interface_descriptor_for_cast_targets(tmp_path) -> None:
    util_source = """
export interface Hashable {
    fn hash_code() -> u64;
}

export class Key implements Hashable {
    fn hash_code() -> u64 {
        return 1u;
    }
}
"""
    main_source = """
import util;

fn f(o: Obj) -> util.Hashable {
    return (util.Hashable)o;
}

fn main() -> i64 {
    if f(null) == null {
        return 0;
    }
    return 1;
}
"""

    (tmp_path / "util.nif").write_text(util_source.strip() + "\n", encoding="utf-8")
    asm = emit_source_asm(tmp_path, main_source, project_root=tmp_path)

    assert "    call rt_checked_cast_interface" not in asm
    assert "    mov rcx, qword ptr [rax]" in asm
    assert "    mov rcx, qword ptr [rcx + 64]" in asm
    assert "    lea rsi, [rip + __nif_interface_util__Hashable]" in asm
    assert "__nif_interface_name_util__Hashable:" in asm
    assert '.asciz "util::Hashable"' in asm


def test_emit_asm_collects_reference_cast_metadata_nested_under_interface_dispatch(tmp_path) -> None:
    source = """
interface Equalable {
    fn equals(other: Obj) -> bool;
}

class Person {
    age: i64;
}

class Key implements Equalable {
    fn equals(other: Obj) -> bool {
        return other != null;
    }
}

fn call_equals(value: Equalable, other: Obj) -> bool {
    return value.equals((Obj)(Person)other);
}

fn main() -> i64 {
    if call_equals(Key(), null) {
        return 1;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "__nif_type_Person:" in asm
    assert "__nif_type_name_main__Person:" in asm
    assert "    call rt_checked_cast" in asm
