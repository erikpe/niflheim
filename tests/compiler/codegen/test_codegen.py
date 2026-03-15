from compiler.codegen import emit_asm
from compiler.lexer import lex
from compiler.parser import parse


def test_emit_asm_masks_u8_arithmetic_results() -> None:
    source = """
fn f(a: u8, b: u8) -> u8 {
    var x: u8 = a + b;
    var y: u8 = a - b;
    var z: u8 = a * b;
    return z;
}
"""
    module = parse(lex(source, source_path="examples/codegen_u8_arith.nif"))

    asm = emit_asm(module)

    assert "    add rax, rcx" in asm
    assert "    sub rax, rcx" in asm
    assert "    imul rax, rcx" in asm
    assert asm.count("    and rax, 255") >= 3


def test_emit_asm_emits_bitwise_integer_ops_and_u8_masks() -> None:
    source = """
fn f(a: u8, b: u8, c: i64, d: i64) -> i64 {
    var x: u8 = (a & b) | (a ^ b);
    var y: u8 = ~a;
    var z: i64 = (c & d) | (c ^ d);
    return z;
}
"""
    module = parse(lex(source, source_path="examples/codegen_bitwise.nif"))

    asm = emit_asm(module)

    assert "    and rax, rcx" in asm
    assert "    or rax, rcx" in asm
    assert "    xor rax, rcx" in asm
    assert "    not rax" in asm
    assert asm.count("    and rax, 255") >= 2


def test_emit_asm_emits_checked_shift_ops() -> None:
    source = """
fn f(a: u64, b: i64, c: u8) -> i64 {
    var x: u64 = a << 3u;
    var y: i64 = b >> 1u;
    var z: u8 = c >> 2u;
    return y;
}
"""
    module = parse(lex(source, source_path="examples/codegen_shift.nif"))

    asm = emit_asm(module)

    assert "    shl rax, cl" in asm
    assert "    sar rax, cl" in asm
    assert "    shr rax, cl" in asm
    assert "    cmp rcx, 64" in asm
    assert "    cmp rcx, 8" in asm
    assert "    call rt_panic" in asm


def test_emit_asm_emits_integer_power_op() -> None:
    source = """
fn f(a: u64, b: u8) -> u64 {
    var x: u64 = a ** 5u;
    var y: u8 = b ** 3u;
    return x;
}
"""
    module = parse(lex(source, source_path="examples/codegen_pow.nif"))

    asm = emit_asm(module)

    assert "    test rcx, rcx" in asm
    assert "    test rcx, 1" in asm
    assert "    imul r8, r9" in asm
    assert "    imul r9, r9" in asm
    assert "    shr rcx, 1" in asm
    assert "    mov rax, r8" in asm
    assert "    and rax, 255" in asm


def test_emit_asm_normalizes_signed_modulo_to_true_modulo() -> None:
    source = """
fn f(a: i64, b: i64) -> i64 {
    return a % b;
}
"""
    module = parse(lex(source, source_path="examples/codegen_signed_mod.nif"))

    asm = emit_asm(module)

    assert "    cqo" in asm
    assert "    idiv rcx" in asm
    assert "    mov r8, rax" in asm
    assert "    xor r8, rcx" in asm
    assert "    add rax, rcx" in asm


def test_emit_asm_normalizes_signed_division_to_floor_division() -> None:
    source = """
fn f(a: i64, b: i64) -> i64 {
    return a / b;
}
"""
    module = parse(lex(source, source_path="examples/codegen_signed_div.nif"))

    asm = emit_asm(module)

    assert "    cqo" in asm
    assert "    idiv rcx" in asm
    assert "    test rdx, rdx" in asm
    assert "    mov r8, rdx" in asm
    assert "    xor r8, rcx" in asm
    assert "    sub rax, 1" in asm


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
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

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
    module = parse(lex(source, source_path="examples/codegen_for_in_string_literal.nif"))

    asm = emit_asm(module)

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
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call __nif_method_Str_index_get" in asm


def test_emit_asm_box_i64_constructor_and_value_method_lower_to_class_symbols() -> None:
    source = """
class BoxI64 {
    _value: i64;

    fn value() -> i64 {
        return __self._value;
    }
}

fn main() -> i64 {
    var b: BoxI64 = BoxI64(7);
    return b.value();
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call __nif_ctor_BoxI64" in asm
    assert "    call __nif_method_BoxI64_value" in asm


def test_emit_asm_user_defined_vec_class_uses_method_symbols_not_rt_vec_builtins() -> None:
    source = """
class Vec {
    _len: i64;

    static fn new() -> Vec {
        return Vec(0);
    }

    fn len() -> i64 {
        return __self._len;
    }

    fn push(value: Obj) -> unit {
        __self._len = __self._len + 1;
        return;
    }
}

fn main() -> i64 {
    var v: Vec = Vec.new();
    v.push(null);
    return v.len();
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call __nif_method_Vec_new" in asm
    assert "    call __nif_method_Vec_push" in asm
    assert "    call __nif_method_Vec_len" in asm
    assert "rt_vec_" not in asm


def test_emit_asm_structural_index_sugar_for_user_class_lowers_to_get_set_methods() -> None:
    source = """
class Bag {
    values: i64[];

    static fn new() -> Bag {
        return Bag(i64[](2u));
    }

    fn index_get(index: i64) -> i64 {
        return __self.values[index];
    }

    fn index_set(index: i64, value: i64) -> unit {
        __self.values[index] = value;
        return;
    }
}

fn main() -> i64 {
    var b: Bag = Bag.new();
    b[0] = 7;
    return b[0];
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call __nif_method_Bag_index_set" in asm
    assert "    call __nif_method_Bag_index_get" in asm


def test_emit_asm_structural_slice_sugar_for_user_class_lowers_to_slice_method() -> None:
    source = """
class Window {
    values: i64[];

    static fn new() -> Window {
        return Window(i64[](3u));
    }

    fn slice_get(begin: i64, end: i64) -> Window {
        return __self;
    }
}

fn main() -> i64 {
    var w: Window = Window.new();
    var part: Window = w[0:2];
    if part == null {
        return 1;
    }
    return 0;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call __nif_method_Window_slice_get" in asm


def test_emit_asm_array_constructor_lowers_to_runtime_symbol_by_element_kind() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> unit {
    var a: u8[] = u8[](4u);
    var b: i64[] = i64[](2u);
    var c: Person[] = Person[](3u);
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_array_new_u8" in asm
    assert "    call rt_array_new_i64" in asm
    assert "    call rt_array_new_ref" in asm


def test_emit_asm_array_index_get_set_lowers_to_runtime_calls() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> unit {
    var nums: u8[] = u8[](2u);
    nums[0] = (u8)1;
    var x: u8 = nums[0];

    var people: Person[] = Person[](1u);
    people[0] = Person(7);
    var p: Person = people[0];
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_array_set_u8" in asm
    assert "    call rt_array_get_u8" in asm
    assert "    call rt_array_set_ref" in asm
    assert "    call rt_array_get_ref" in asm


def test_emit_asm_array_len_and_slice_lower_to_runtime_calls() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> unit {
    var nums: u8[] = u8[](4u);
    var n: u64 = nums.len();
    var s: u8[] = nums[1:3];

    var people: Person[] = Person[](2u);
    var t: Person[] = people.slice_get(0, 1);
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_array_len" in asm
    assert "    call rt_array_slice_u8" in asm
    assert "    call rt_array_slice_ref" in asm


def test_emit_asm_array_constructor_dispatch_covers_remaining_primitive_kinds() -> None:
    source = """
fn main() -> unit {
    var a: u64[] = u64[](1u);
    var b: bool[] = bool[](1u);
    var c: double[] = double[](1u);
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_array_new_u64" in asm
    assert "    call rt_array_new_bool" in asm
    assert "    call rt_array_new_double" in asm


def test_emit_asm_nested_array_uses_reference_array_runtime_paths() -> None:
    source = """
fn main() -> unit {
    var mat: i64[][] = i64[][](2u);
    var row: i64[] = i64[](3u);
    mat[0] = row;
    var x: i64 = mat[0][1];
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_array_new_ref" in asm
    assert "    call rt_array_new_i64" in asm
    assert "    call rt_array_set_ref" in asm
    assert "    call rt_array_get_ref" in asm
    assert "    call rt_array_get_i64" in asm


def test_emit_asm_nested_array_chained_field_access_lowers() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> i64 {
    var teams: Person[][] = Person[][](1u);
    teams[0] = Person[](1u);
    teams[0][0] = Person(42);
    return teams[0][0].age;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    # One get for Person[] from Person[][], then one get for Person from Person[].
    assert asm.count("    call rt_array_get_ref") >= 2
    assert "    mov rax, qword ptr [rax + 24]" in asm


def test_emit_asm_nested_index_assignment_target_lowers_to_array_set() -> None:
    source = """
fn main() -> unit {
    var cube: u8[][][][] = u8[][][][](1u);
    cube[0] = u8[][][](1u);
    cube[0][0] = u8[][](1u);
    cube[0][0][0] = u8[](2u);
    cube[0][0][0][1] = (u8)9;
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_array_set_u8" in asm
    assert asm.count("    call rt_array_get_ref") >= 3


def test_emit_asm_array_method_form_get_set_slice_lowers_to_runtime_calls() -> None:
    source = """
fn main() -> unit {
    var nums: u64[] = u64[](4u);
    nums.index_set(1, 42u);
    var x: u64 = nums.index_get(1);
    var s: u64[] = nums.slice_get(0, 2);
    nums.slice_set(1, 3, s);
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_array_set_u64" in asm
    assert "    call rt_array_get_u64" in asm
    assert "    call rt_array_slice_u64" in asm
    assert "    call rt_array_set_slice_u64" in asm


def test_emit_asm_for_in_over_array_lowers_to_array_iter_runtime_calls() -> None:
    source = """
fn main() -> i64 {
    var values: i64[] = i64[](2u);
    values[0] = 4;
    values[1] = 6;

    var sum: i64 = 0;
    for value in values {
        sum = sum + value;
    }

    return sum;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_array_len" in asm
    assert "    call rt_array_get_i64" in asm


def test_emit_asm_array_reference_set_roots_reference_value_argument_for_runtime_call() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> unit {
    var people: Person[] = Person[](1u);
    var p: Person = Person(7);
    people.index_set(0, p);
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_array_set_ref" in asm
    assert "    mov esi, 2" in asm
    assert asm.count("    call rt_root_slot_store") >= 3


def test_emit_asm_array_index_assignment_roots_runtime_value_argument() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> unit {
    var people: Person[] = Person[](1u);
    var p: Person = Person(7);
    people[0] = p;
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_array_set_ref" in asm
    assert "    mov esi, 2" in asm


def test_emit_asm_emits_array_type_metadata_symbols_for_reference_casts() -> None:
    source = """
class Person {
    age: i64;
}

fn f(value: Obj) -> Person[] {
    return (Person[])value;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "__nif_type_name_Person__:" in asm
    assert '.asciz "Person[]"' in asm
    assert "__nif_type_Person__:" in asm


def test_emit_asm_method_call_lowers_to_method_symbol_with_receiver_arg0() -> None:
    source = """
class Counter {
    fn add(delta: i64) -> i64 {
        return delta;
    }
}

fn main() -> i64 {
    var c: Counter = null;
    return c.add(7);
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "__nif_method_Counter_add:" in asm
    assert "    call __nif_method_Counter_add" in asm
    assert "    mov rdi, qword ptr [r10]" in asm
    assert "    mov rsi, qword ptr [r10 + 8]" in asm


def test_emit_asm_static_method_call_lowers_to_method_symbol_without_receiver_arg0() -> None:
    source = """
class Counter {
    static fn add(delta: i64) -> i64 {
        return delta;
    }
}

fn main() -> i64 {
    return Counter.add(7);
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "__nif_method_Counter_add:" in asm
    assert "    call __nif_method_Counter_add" in asm


def test_emit_asm_constructor_call_lowers_to_constructor_symbol() -> None:
    source = """
class Counter {
    value: i64;
}

fn main() -> i64 {
    var c: Counter = Counter(7);
    if c == null {
        return 1;
    }
    return 0;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "__nif_ctor_Counter:" in asm
    assert "    call __nif_ctor_Counter" in asm
    assert "    call rt_alloc_obj" in asm


def test_emit_asm_class_field_read_lowers_to_object_payload_load() -> None:
    source = """
class Counter {
    value: i64;
}

fn main() -> i64 {
    var c: Counter = Counter(7);
    return c.value;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    mov rax, qword ptr [rax + 24]" in asm


def test_emit_asm_class_field_assignment_lowers_to_object_payload_store() -> None:
    source = """
class Counter {
    value: i64;
}

fn main() -> i64 {
    var c: Counter = Counter(7);
    c.value = 9;
    return c.value;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    mov qword ptr [rcx + 24], rax" in asm
    assert "    mov rax, qword ptr [rax + 24]" in asm


def test_emit_asm_runtime_call_has_safepoint_hooks() -> None:
    source = """
fn f(ts: Obj) -> unit {
    rt_gc_collect(ts);
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert ".Lf_rt_safepoint_before_" in asm
    assert ".Lf_rt_safepoint_after_" in asm
    assert "    call rt_gc_collect" in asm


def test_emit_asm_skips_extern_declaration_body_emission() -> None:
    source = """
extern fn rt_gc_collect(ts: Obj) -> unit;

fn main() -> i64 {
    var root: Obj = null;
    rt_gc_collect(root);
    return 0;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "rt_gc_collect:" not in asm
    assert "    call rt_gc_collect" in asm


def test_emit_asm_runtime_call_spills_named_slots_to_root_slots() -> None:
    source = """
fn f(ts: Obj) -> unit {
    var local: Obj = ts;
    rt_gc_collect(local);
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    mov qword ptr [rbp - 8], rdi" in asm
    assert "    mov qword ptr [rbp - 16], rax" in asm
    assert "    call rt_root_slot_store" in asm
    assert "    mov esi, 0" in asm
    assert "    mov esi, 1" in asm
    assert "    call rt_gc_collect" in asm


def test_emit_asm_initializes_value_and_root_slots_to_zero() -> None:
    source = """
fn f(a: i64) -> i64 {
    var x: i64;
    return a;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    mov qword ptr [rbp - 8], 0" in asm
    assert "    mov qword ptr [rbp - 16], 0" in asm
    assert "    mov qword ptr [rbp - 24], 0" not in asm
    assert "    mov qword ptr [rbp - 32], 0" not in asm


def test_emit_asm_wires_shadow_stack_abi_calls_in_prologue_and_epilogue() -> None:
    source = """
fn f(x: Obj) -> Obj {
    return x;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_thread_state" in asm
    assert "    call rt_root_frame_init" in asm
    assert "    call rt_push_roots" in asm
    assert "    call rt_pop_roots" in asm


def test_emit_asm_pushes_roots_before_trace_push_for_reference_functions() -> None:
    source = """
fn f(x: Obj) -> Obj {
    return x;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    push_roots_i = asm.index("    call rt_push_roots")
    trace_push_i = asm.index("    call rt_trace_push")
    assert push_roots_i < trace_push_i


def test_emit_asm_keeps_trace_push_for_functions_without_roots() -> None:
    source = """
fn f(a: i64) -> i64 {
    return a;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_trace_push" in asm
    assert "    call rt_trace_pop" in asm


def test_emit_asm_pushes_roots_before_trace_push_for_constructors() -> None:
    source = """
class Boxed {
    final value: Obj;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    ctor_label = "__nif_ctor_Boxed:"
    assert ctor_label in asm
    ctor_start = asm.index(ctor_label)
    ctor_body = asm[ctor_start:]
    push_roots_i = ctor_body.index("    call rt_push_roots")
    trace_push_i = ctor_body.index("    call rt_trace_push")
    assert push_roots_i < trace_push_i


def test_emit_asm_omits_shadow_stack_abi_when_no_named_slots() -> None:
    source = """
fn f() -> unit {
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "rt_root_frame_init" not in asm
    assert "rt_push_roots" not in asm
    assert "rt_pop_roots" not in asm


def test_emit_asm_roots_only_reference_typed_bindings() -> None:
    source = """
fn f(ts: Obj, n: i64) -> unit {
    var local_ref: Obj = ts;
    var local_i: i64 = n;
    rt_gc_collect(local_ref);
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    mov esi, 0" in asm
    assert "    mov esi, 1" in asm
    assert "    mov edx, 2" in asm
    assert asm.count("    call rt_root_slot_store") >= 2


def test_emit_asm_no_runtime_root_frame_for_primitive_only_function() -> None:
    source = """
fn sum(a: i64, b: i64) -> i64 {
    var c: i64 = a + b;
    return c;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "rt_root_frame_init" not in asm
    assert "rt_push_roots" not in asm
    assert "rt_pop_roots" not in asm


def test_emit_asm_preserves_rax_across_rt_pop_roots() -> None:
    source = """
fn f(x: Obj) -> Obj {
    return x;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    push_i = asm.index("    push rax")
    pop_call_i = asm.index("    call rt_pop_roots")
    pop_i = asm.index("    pop rax")
    assert push_i < pop_call_i < pop_i


def test_emit_asm_non_runtime_call_has_no_runtime_hooks() -> None:
    source = """
fn callee(x: i64) -> i64 {
    return x;
}

fn f() -> i64 {
    return callee(1);
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call callee" in asm
    assert "rt_safepoint_before" not in asm
    assert "rt_safepoint_after" not in asm


def test_emit_asm_ordinary_call_still_spills_root_slots() -> None:
    source = """
fn callee(x: Obj) -> Obj {
    return x;
}

fn caller(x: Obj) -> Obj {
    var y: Obj = x;
    return callee(y);
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call callee" in asm
    assert "    call rt_root_slot_store" in asm
    assert "rt_safepoint_before" not in asm


def test_emit_asm_roots_temporary_reference_args_for_non_runtime_call() -> None:
    source = """
fn takes_two(a: Obj[], b: Obj[]) -> u64 {
    return a.len();
}

fn caller() -> u64 {
    return takes_two(Obj[](1u), Obj[](2u));
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    caller_start = asm.index("caller:")
    caller_end = asm.index(".Lcaller_epilogue:")
    caller_body = asm[caller_start:caller_end]
    assert "    call takes_two" in caller_body
    assert caller_body.count("    call rt_root_slot_store") >= 2


def test_emit_asm_array_ctor_runtime_call_dynamic_aligns_with_prior_pushed_arg() -> None:
    source = """
fn consume(a: Obj[], b: i64) -> u64 {
    return a.len();
}

fn caller() -> u64 {
    return consume(Obj[](1u), 7);
}
"""
    module = parse(lex(source, source_path="examples/codegen_array_ctor_align.nif"))

    asm = emit_asm(module)

    assert "    call rt_array_new_ref" in asm
    assert "    test rsp, 8" in asm
    assert "    sub rsp, 8" in asm
    assert "    add rsp, 8" in asm


def test_emit_asm_reference_cast_calls_rt_checked_cast() -> None:
    source = """
class Person {
    age: i64;
}

fn f(o: Obj) -> Person {
    return (Person)o;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

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
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "rt_checked_cast" not in asm


def test_emit_asm_obj_to_array_cast_calls_rt_checked_cast_array_kind() -> None:
    source = """
fn f(o: Obj) -> u64[] {
    return (u64[])o;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_checked_cast_array_kind" in asm
    assert "    mov rsi, 2" in asm


def test_emit_asm_primitive_cast_does_not_call_rt_checked_cast() -> None:
    source = """
fn f(x: i64) -> i64 {
    return (i64)x;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "rt_checked_cast" not in asm


def test_emit_asm_emits_type_metadata_symbols_for_reference_casts() -> None:
    source = """
fn f(o: Obj) -> Obj {
    return (Obj)o;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

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
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

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
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

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
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "__nif_type_name_Holder:" in asm
    assert "__nif_type_Holder:" in asm
    assert "__nif_type_name_Holder__ptr_offsets:" in asm
