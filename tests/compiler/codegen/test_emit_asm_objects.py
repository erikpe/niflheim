import re

from compiler.codegen.symbols import mangle_function_symbol
from tests.compiler.codegen.helpers import emit_source_asm


def _main_function_body(asm: str, name: str) -> str:
    label = mangle_function_symbol(("main",), name)
    return asm[asm.index(f"{label}:") : asm.index(f".L{label}_epilogue:")]


def test_emit_asm_box_i64_constructor_and_value_method_lower_to_class_symbols(tmp_path) -> None:
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
    asm = emit_source_asm(tmp_path, source)
    main_body = asm[asm.index("main:") : asm.index(".Lmain_epilogue:")]

    assert "    call __nif_ctor_main__BoxI64" in asm
    assert "    call __nif_method_main__BoxI64_value" in main_body
    assert "    mov rcx, qword ptr [rcx + 80]" not in main_body
    assert "    call r11" not in main_body


def test_emit_asm_user_defined_vec_class_uses_method_symbols_not_rt_vec_builtins(tmp_path) -> None:
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
    asm = emit_source_asm(tmp_path, source)
    main_body = asm[asm.index("main:") : asm.index(".Lmain_epilogue:")]

    assert "    call __nif_method_main__Vec_new" in asm
    assert "    call __nif_method_main__Vec_push" in main_body
    assert "    call __nif_method_main__Vec_len" in main_body
    assert "    mov rcx, qword ptr [rcx + 80]" not in main_body
    assert "    call r11" not in main_body
    assert "rt_vec_" not in asm


def test_emit_asm_structural_index_sugar_for_user_class_lowers_to_get_set_methods(tmp_path) -> None:
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
    asm = emit_source_asm(tmp_path, source)
    main_body = asm[asm.index("main:") : asm.index(".Lmain_epilogue:")]

    assert "    call __nif_method_main__Bag_index_set" in main_body
    assert "    call __nif_method_main__Bag_index_get" in main_body
    assert "    mov rcx, qword ptr [rcx + 80]" not in main_body
    assert "    call r11" not in main_body


def test_emit_asm_structural_slice_sugar_for_user_class_lowers_to_slice_method(tmp_path) -> None:
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
    asm = emit_source_asm(tmp_path, source)
    main_body = asm[asm.index("main:") : asm.index(".Lmain_epilogue:")]

    assert "    call __nif_method_main__Window_slice_get" in main_body
    assert "    mov rcx, qword ptr [rcx + 80]" not in main_body
    assert "    call r11" not in main_body


def test_emit_asm_preserves_static_method_calls_used_only_from_constructor_bodies(tmp_path) -> None:
    source = """
class Factory {
    value: i64;

    static fn new() -> Factory {
        return Factory(7);
    }

    constructor(value: i64) {
        __self.value = value;
        return;
    }

    fn read() -> i64 {
        return __self.value;
    }
}

class Holder {
    value: Factory;

    constructor() {
        __self.value = Factory.new();
        return;
    }

    fn read() -> i64 {
        return __self.value.read();
    }
}

fn main() -> i64 {
    var holder: Holder = Holder();
    return holder.read();
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "__nif_method_main__Factory_new:" in asm
    assert "    call __nif_method_main__Factory_new" in asm


def test_emit_asm_structural_interface_dispatch_specializes_to_direct_calls_after_exact_constructor_fact(tmp_path) -> None:
    source = """
interface Buffer {
    fn index_get(index: i64) -> i64;
    fn index_set(index: i64, value: i64) -> unit;
    fn slice_get(begin: i64, end: i64) -> Buffer;
    fn slice_set(begin: i64, end: i64, value: Buffer) -> unit;
    fn iter_len() -> u64;
    fn iter_get(index: i64) -> i64;
}

class Store implements Buffer {
    fn index_get(index: i64) -> i64 {
        return index;
    }

    fn index_set(index: i64, value: i64) -> unit {
        return;
    }

    fn slice_get(begin: i64, end: i64) -> Buffer {
        return __self;
    }

    fn slice_set(begin: i64, end: i64, value: Buffer) -> unit {
        return;
    }

    fn iter_len() -> u64 {
        return 1u;
    }

    fn iter_get(index: i64) -> i64 {
        return 7;
    }
}

fn main() -> i64 {
    var buffer: Buffer = Store();
    var first: i64 = buffer[0];
    buffer[0] = first;
    var part: Buffer = buffer[0:1];
    buffer[0:1] = part;
    for value in buffer {
        return value;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)
    main_body = asm[asm.index("main:") : asm.index(".Lmain_epilogue:")]

    assert "    call __nif_method_main__Store_index_get" in main_body
    assert "    call __nif_method_main__Store_index_set" in main_body
    assert "    call __nif_method_main__Store_slice_get" in main_body
    assert "    call __nif_method_main__Store_slice_set" in main_body
    assert "    call __nif_method_main__Store_iter_len" in main_body
    assert "    call __nif_method_main__Store_iter_get" in main_body
    assert "    mov rax, qword ptr [rcx + 64]" not in main_body
    assert "    call r11" not in main_body


def test_emit_asm_structural_virtual_dispatch_specializes_to_direct_calls_after_exact_constructor_fact(tmp_path) -> None:
    source = """
class BufferBase {
    fn index_get(index: i64) -> i64 {
        return index;
    }

    fn index_set(index: i64, value: i64) -> unit {
        return;
    }

    fn slice_get(begin: i64, end: i64) -> BufferBase {
        return __self;
    }

    fn slice_set(begin: i64, end: i64, value: BufferBase) -> unit {
        return;
    }

    fn iter_len() -> u64 {
        return 1u;
    }

    fn iter_get(index: i64) -> i64 {
        return index;
    }
}

class Buffer extends BufferBase {
    override fn index_get(index: i64) -> i64 {
        return index + 1;
    }

    override fn index_set(index: i64, value: i64) -> unit {
        return;
    }

    override fn slice_get(begin: i64, end: i64) -> BufferBase {
        return __self;
    }

    override fn slice_set(begin: i64, end: i64, value: BufferBase) -> unit {
        return;
    }

    override fn iter_len() -> u64 {
        return 1u;
    }

    override fn iter_get(index: i64) -> i64 {
        return 7;
    }
}

fn main() -> i64 {
    var buffer: Buffer = Buffer();
    var first: i64 = buffer[0];
    buffer[0] = first;
    var part: BufferBase = buffer[0:1];
    buffer[0:1] = part;
    for value in buffer {
        return value;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)
    main_body = asm[asm.index("main:") : asm.index(".Lmain_epilogue:")]

    assert "    call __nif_method_main__Buffer_index_get" in main_body
    assert "    call __nif_method_main__Buffer_index_set" in main_body
    assert "    call __nif_method_main__Buffer_slice_get" in main_body
    assert "    call __nif_method_main__Buffer_slice_set" in main_body
    assert "    call __nif_method_main__Buffer_iter_len" in main_body
    assert "    call __nif_method_main__Buffer_iter_get" in main_body
    assert "    mov rcx, qword ptr [rcx + 80]" not in main_body
    assert "    call r11" not in main_body


def test_emit_asm_structural_interface_dispatch_specializes_to_direct_calls_via_closed_world_monomorphism(tmp_path) -> None:
    source = """
interface Buffer {
    fn index_get(index: i64) -> i64;
    fn index_set(index: i64, value: i64) -> unit;
    fn slice_get(begin: i64, end: i64) -> Buffer;
    fn slice_set(begin: i64, end: i64, value: Buffer) -> unit;
    fn iter_len() -> u64;
    fn iter_get(index: i64) -> i64;
}

class BaseBuffer implements Buffer {
    fn index_get(index: i64) -> i64 {
        return index;
    }

    fn index_set(index: i64, value: i64) -> unit {
        return;
    }

    fn slice_get(begin: i64, end: i64) -> Buffer {
        return __self;
    }

    fn slice_set(begin: i64, end: i64, value: Buffer) -> unit {
        return;
    }

    fn iter_len() -> u64 {
        return 1u;
    }

    fn iter_get(index: i64) -> i64 {
        return index;
    }
}

class Store extends BaseBuffer {
}

class Queue extends BaseBuffer {
}

fn read(buffer: Buffer) -> i64 {
    var first: i64 = buffer[0];
    buffer[0] = first;
    var part: Buffer = buffer[0:1];
    buffer[0:1] = part;
    for value in buffer {
        return value;
    }
    return 0;
}

fn main() -> i64 {
    return read(Store());
}
"""
    asm = emit_source_asm(tmp_path, source)
    read_body = _main_function_body(asm, "read")

    assert "    call __nif_method_main__BaseBuffer_index_get" in read_body
    assert "    call __nif_method_main__BaseBuffer_index_set" in read_body
    assert "    call __nif_method_main__BaseBuffer_slice_get" in read_body
    assert "    call __nif_method_main__BaseBuffer_slice_set" in read_body
    assert "    call __nif_method_main__BaseBuffer_iter_len" in read_body
    assert "    call __nif_method_main__BaseBuffer_iter_get" in read_body
    assert "    mov rax, qword ptr [rcx + 64]" not in read_body
    assert "    call r11" not in read_body


def test_emit_asm_structural_virtual_dispatch_specializes_to_direct_calls_via_closed_world_monomorphism(tmp_path) -> None:
    source = """
class BufferBase {
    fn index_get(index: i64) -> i64 {
        return index;
    }

    fn index_set(index: i64, value: i64) -> unit {
        return;
    }

    fn slice_get(begin: i64, end: i64) -> BufferBase {
        return __self;
    }

    fn slice_set(begin: i64, end: i64, value: BufferBase) -> unit {
        return;
    }

    fn iter_len() -> u64 {
        return 1u;
    }

    fn iter_get(index: i64) -> i64 {
        return index;
    }
}

class Store extends BufferBase {
}

class Queue extends BufferBase {
}

fn read(buffer: BufferBase) -> i64 {
    var first: i64 = buffer[0];
    buffer[0] = first;
    var part: BufferBase = buffer[0:1];
    buffer[0:1] = part;
    for value in buffer {
        return value;
    }
    return 0;
}

fn main() -> i64 {
    return read(Store());
}
"""
    asm = emit_source_asm(tmp_path, source)
    read_body = _main_function_body(asm, "read")

    assert "    call __nif_method_main__BufferBase_index_get" in read_body
    assert "    call __nif_method_main__BufferBase_index_set" in read_body
    assert "    call __nif_method_main__BufferBase_slice_get" in read_body
    assert "    call __nif_method_main__BufferBase_slice_set" in read_body
    assert "    call __nif_method_main__BufferBase_iter_len" in read_body
    assert "    call __nif_method_main__BufferBase_iter_get" in read_body
    assert "    mov rcx, qword ptr [rcx + 80]" not in read_body
    assert "    call r11" not in read_body


def test_emit_asm_non_local_exact_structural_interface_receiver_expression_specializes_to_direct_call(tmp_path) -> None:
    source = """
interface Buffer {
    fn index_get(index: i64) -> i64;
}

class Store implements Buffer {
    fn index_get(index: i64) -> i64 {
        return index;
    }
}

fn main() -> i64 {
    return ((Buffer)Store())[0];
}
"""
    asm = emit_source_asm(tmp_path, source)
    main_body = asm[asm.index("main:") : asm.index(".Lmain_epilogue:")]

    assert "    call __nif_method_main__Store_index_get" in main_body
    assert "    mov rax, qword ptr [rcx + 64]" not in main_body
    assert "    call r11" not in main_body


def test_emit_asm_method_call_lowers_to_method_symbol_with_receiver_arg0(tmp_path) -> None:
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
    asm = emit_source_asm(tmp_path, source)
    main_body = asm[asm.index("main:") : asm.index(".Lmain_epilogue:")]

    assert "__nif_method_main__Counter_add:" in asm
    assert "    call __nif_method_main__Counter_add" in main_body
    assert re.search(r"mov rdi, qword ptr \[rbp - \d+\]", main_body)
    assert re.search(r"mov rsi, qword ptr \[rbp - \d+\]", main_body)
    assert "    call rt_panic_null_deref" in main_body
    assert "    mov rcx, qword ptr [rcx + 80]" not in main_body
    assert "    call r11" not in main_body


def test_emit_asm_static_method_call_lowers_to_method_symbol_without_receiver_arg0(tmp_path) -> None:
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
    asm = emit_source_asm(tmp_path, source)

    assert "__nif_method_main__Counter_add:" in asm
    assert "    call __nif_method_main__Counter_add" in asm


def test_emit_asm_constructor_call_lowers_to_constructor_symbol(tmp_path) -> None:
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
    asm = emit_source_asm(tmp_path, source)

    assert "__nif_ctor_main__Counter:" in asm
    assert "    call __nif_ctor_main__Counter" in asm
    assert "    call rt_alloc_obj" in asm


def test_emit_asm_overloaded_constructor_call_uses_selected_constructor_label(tmp_path) -> None:
    source = """
class Pair {
    left: i64;
    right: i64 = 0;

    constructor(left: i64) {
        __self.left = left;
        return;
    }

    constructor(left: i64, right: i64) {
        __self.left = left;
        __self.right = right;
        return;
    }
}

fn main() -> i64 {
    var pair: Pair = Pair(1, 2);
    return pair.right;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "__nif_ctor_main__Pair:" in asm
    assert "__nif_ctor_main__Pair__1:" in asm
    assert "    call __nif_ctor_main__Pair__1" in asm
    assert "    call rt_alloc_obj" in asm


def test_emit_asm_subclass_constructor_chains_through_super_init_label(tmp_path) -> None:
    source = """
class Base {
    value: i64;

    constructor(value: i64) {
        __self.value = value;
        return;
    }
}

class Derived extends Base {
    extra: i64;

    constructor(value: i64, extra: i64) {
        super(value);
        __self.extra = extra;
        return;
    }
}

fn main() -> i64 {
    var derived: Derived = Derived(1, 2);
    return derived.extra;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "__nif_ctor_init_main__Base:" in asm
    assert "__nif_ctor_init_main__Derived:" in asm
    assert "    call __nif_ctor_main__Derived" in asm
    assert "    call __nif_ctor_init_main__Derived" in asm
    assert "    call __nif_ctor_init_main__Base" in asm


def test_emit_asm_constructor_prologues_omit_zeroing_immediately_spilled_param_slots(tmp_path) -> None:
    source = """
class Box {
    value: Obj;
}

fn main() -> i64 {
    var b: Box = Box(null);
    if b == null {
        return 1;
    }
    return 0;
}
"""
    asm = emit_source_asm(tmp_path, source)
    ctor_body = asm[asm.index("__nif_ctor_main__Box:") : asm.index(".L__nif_ctor_main__Box_epilogue:")]
    init_body = asm[asm.index("__nif_ctor_init_main__Box:") : asm.index(".L__nif_ctor_init_main__Box_epilogue:")]

    assert "    mov qword ptr [rbp - 8], 0" in ctor_body
    assert "    mov qword ptr [rbp - 16], 0" not in ctor_body
    assert "    mov qword ptr [rbp - 16], rdi" in ctor_body

    assert "    mov qword ptr [rbp - 8], 0" not in init_body
    assert "    mov qword ptr [rbp - 16], 0" not in init_body
    assert "    mov qword ptr [rbp - 8], rdi" in init_body
    assert "    mov qword ptr [rbp - 16], rsi" in init_body


def test_emit_asm_class_field_read_lowers_to_object_payload_load(tmp_path) -> None:
    source = """
class Counter {
    value: i64;
}

fn main() -> i64 {
    var c: Counter = Counter(7);
    return c.value;
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "    mov rax, qword ptr [rax + 24]" in asm


def test_emit_asm_class_field_assignment_lowers_to_object_payload_store(tmp_path) -> None:
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
    asm = emit_source_asm(tmp_path, source)

    assert "    mov qword ptr [rcx + 24], rax" in asm
    assert "    mov rax, qword ptr [rax + 24]" in asm
