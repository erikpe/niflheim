from compiler.codegen import emit_asm
from compiler.lexer import lex
from compiler.parser import parse


def test_emit_asm_emits_intel_text_header() -> None:
    module = parse(lex("fn main() -> unit { return; }", source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert ".intel_syntax noprefix" in asm
    assert ".text" in asm
    assert '.section .note.GNU-stack,"",@progbits' in asm


def test_emit_asm_emits_sysv_prologue_and_epilogue() -> None:
    module = parse(lex("fn main() -> unit { return; }", source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "main:" in asm
    assert "    push rbp" in asm
    assert "    mov rbp, rsp" in asm
    assert ".Lmain_epilogue:" in asm
    assert "    mov rsp, rbp" in asm
    assert "    pop rbp" in asm
    assert "    ret" in asm


def test_emit_asm_emits_return_jump_to_single_epilogue() -> None:
    source = """
fn f() -> unit {
    return;
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert asm.count("jmp .Lf_epilogue") == 2
    assert asm.count(".Lf_epilogue:") == 1


def test_emit_asm_marks_exported_functions_global() -> None:
    source = """
export fn pubf() -> unit {
    return;
}

fn privf() -> unit {
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert ".globl pubf" in asm
    assert ".globl privf" not in asm


def test_emit_asm_marks_main_global_without_export() -> None:
    module = parse(lex("fn main() -> i64 { return 0; }", source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert ".globl main" in asm


def test_emit_asm_return_integer_literal() -> None:
    module = parse(lex("fn answer() -> i64 { return 42; }", source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "answer:" in asm
    assert "    mov rax, 42" in asm
    assert "    jmp .Lanswer_epilogue" in asm


def test_emit_asm_return_u64_suffixed_integer_literal() -> None:
    module = parse(lex("fn answer() -> u64 { return 42u; }", source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "answer:" in asm
    assert "    mov rax, 42" in asm
    assert "42u" not in asm


def test_emit_asm_return_u8_suffixed_integer_literal() -> None:
    module = parse(lex("fn answer() -> u8 { return 113u8; }", source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "answer:" in asm
    assert "    mov rax, 113" in asm
    assert "113u8" not in asm


def test_emit_asm_return_char_literal() -> None:
    module = parse(lex("fn answer() -> u8 { return 'q'; }", source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "answer:" in asm
    assert "    mov rax, 113" in asm


def test_emit_asm_return_double_literal_bits() -> None:
    module = parse(lex("fn answer() -> double { return 1.5; }", source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "answer:" in asm
    assert "0x3ff8000000000000" in asm


def test_emit_asm_double_call_uses_xmm_registers() -> None:
    source = """
fn add(a: double, b: double) -> double {
    return a + b;
}

fn main() -> double {
    return add(1.0, 2.0);
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    movq xmm0, rax" in asm
    assert "    movq xmm1, rax" in asm
    assert "    addsd xmm0, xmm1" in asm


def test_emit_asm_expression_with_params_and_local_slot() -> None:
    source = """
fn add(x: i64, y: i64) -> i64 {
    var z: i64 = x + y;
    return z;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    mov qword ptr [rbp - 8], rdi" in asm
    assert "    mov qword ptr [rbp - 16], rsi" in asm
    assert "    mov rax, qword ptr [rbp - 8]" in asm
    assert "    add rax, rcx" in asm
    assert "    mov qword ptr [rbp - 24], rax" in asm


def test_emit_asm_null_reference_expression() -> None:
    module = parse(lex("fn f() -> Obj { return null; }", source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "f:" in asm
    assert "    mov rax, 0" in asm


def test_emit_asm_logical_short_circuit() -> None:
    source = """
fn f(a: bool, b: bool) -> bool {
    return a && b;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert ".Lf_logic_rhs_0:" in asm
    assert ".Lf_logic_done_0:" in asm
    assert "    cmp rax, 0" in asm


def test_emit_asm_if_else_control_flow() -> None:
    source = """
fn choose(flag: bool) -> i64 {
    if flag {
        return 1;
    } else {
        return 2;
    }
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert ".Lchoose_if_else_" in asm
    assert ".Lchoose_if_end_" in asm
    assert "    je .Lchoose_if_else_" in asm


def test_emit_asm_while_loop_control_flow() -> None:
    source = """
fn loop_to(limit: i64) -> i64 {
    var i: i64 = 0;
    while i < limit {
        i = i + 1;
    }
    return i;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert ".Lloop_to_while_start_" in asm
    assert ".Lloop_to_while_end_" in asm
    assert "    je .Lloop_to_while_end_" in asm
    assert "    jmp .Lloop_to_while_start_" in asm


def test_emit_asm_else_if_chain_and_nested_locals() -> None:
    source = """
fn classify(x: i64) -> i64 {
    if x < 0 {
        var y: i64 = 10;
        return y;
    } else if x == 0 {
        var z: i64 = 20;
        return z;
    } else {
        return 30;
    }
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert asm.count("_if_else_") >= 2
    assert "    mov qword ptr [rbp - 16], rax" in asm
    assert "    mov qword ptr [rbp - 24], rax" in asm


def test_emit_asm_direct_call_no_args() -> None:
    source = """
fn callee() -> i64 {
    return 7;
}

fn caller() -> i64 {
    return callee();
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call callee" in asm
    assert "    sub rsp, 8" not in asm
    assert "    add rsp, 8" not in asm


def test_emit_asm_direct_call_argument_register_order() -> None:
    source = """
fn sum3(a: i64, b: i64, c: i64) -> i64 {
    return a + b + c;
}

fn main() -> i64 {
    return sum3(1, 2, 3);
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    mov rax, 3" in asm
    assert "    mov rax, 2" in asm
    assert "    mov rax, 1" in asm
    assert "    mov rdi, rax" in asm
    assert "    mov rsi, rax" in asm
    assert "    mov rdx, rax" in asm
    assert "    call sum3" in asm


def test_emit_asm_module_qualified_call_uses_member_symbol_name() -> None:
    source = """
fn main() -> i64 {
    return std.io.println_i64(23);
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call println_i64" in asm


def test_emit_asm_string_literal_lowers_via_rt_str_from_bytes() -> None:
    source = """
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
    assert "    call rt_str_from_bytes" in asm


def test_emit_asm_str_index_lowers_via_rt_str_get_u8() -> None:
    source = """
extern fn rt_str_get_u8(value: Str, index: i64) -> u8;

class Str {
    fn get_u8(index: i64) -> u8 {
        return rt_str_get_u8(__self, index);
    }
}

fn main() -> i64 {
    var s: Str = "ABC";
    var b: u8 = s[1];
    return (i64)b;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_str_get_u8" in asm


def test_emit_asm_newbox_i64_constructor_and_value_method_lower_to_class_symbols() -> None:
    source = """
class NewBoxI64 {
    _value: i64;

    fn value() -> i64 {
        return __self._value;
    }
}

fn main() -> i64 {
    var b: NewBoxI64 = NewBoxI64(7);
    return b.value();
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call __nif_ctor_NewBoxI64" in asm
    assert "    call __nif_method_NewBoxI64_value" in asm


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

    fn get(index: i64) -> i64 {
        return __self.values[index];
    }

    fn set(index: i64, value: i64) -> unit {
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

    assert "    call __nif_method_Bag_set" in asm
    assert "    call __nif_method_Bag_get" in asm


def test_emit_asm_structural_slice_sugar_for_user_class_lowers_to_slice_method() -> None:
    source = """
class Window {
    values: i64[];

    static fn new() -> Window {
        return Window(i64[](3u));
    }

    fn slice(begin: i64, end: i64) -> Window {
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

    assert "    call __nif_method_Window_slice" in asm


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
    var t: Person[] = people.slice(0, 1);
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


def test_emit_asm_array_method_form_get_set_slice_lowers_to_runtime_calls() -> None:
    source = """
fn main() -> unit {
    var nums: u64[] = u64[](4u);
    nums.set(1, 42u);
    var x: u64 = nums.get(1);
    var s: u64[] = nums.slice(0, 2);
    return;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_array_set_u64" in asm
    assert "    call rt_array_get_u64" in asm
    assert "    call rt_array_slice_u64" in asm


def test_emit_asm_array_reference_set_roots_reference_value_argument_for_runtime_call() -> None:
    source = """
class Person {
    age: i64;
}

fn main() -> unit {
    var people: Person[] = Person[](1u);
    var p: Person = Person(7);
    people.set(0, p);
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
    assert "    mov rdi, rax" in asm
    assert "    mov rsi, rax" in asm


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
    assert "    mov esi, 2" not in asm
    assert "    mov edx, 2" in asm
    assert asm.count("    call rt_root_slot_store") == 2


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


def test_emit_asm_reference_cast_calls_rt_checked_cast() -> None:
    source = """
fn f(o: Obj) -> Obj {
    return (Obj)o;
}
"""
    module = parse(lex(source, source_path="examples/codegen.nif"))

    asm = emit_asm(module)

    assert "    call rt_checked_cast" in asm
    assert "    lea rsi, [rip + __nif_type_Obj]" in asm


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
