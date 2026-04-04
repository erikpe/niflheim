from tests.compiler.codegen.helpers import emit_source_asm


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

    assert "    call __nif_ctor_BoxI64" in asm
    assert "    call __nif_method_BoxI64_value" not in main_body
    assert "    mov rcx, qword ptr [rcx]" in main_body
    assert "    mov rcx, qword ptr [rcx + 80]" in main_body
    assert "    call r11" in main_body


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

    assert "    call __nif_method_Vec_new" in asm
    assert "    call __nif_method_Vec_push" not in main_body
    assert "    call __nif_method_Vec_len" not in main_body
    assert main_body.count("    call r11") >= 2
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

    assert "    call __nif_method_Bag_index_set" not in main_body
    assert "    call __nif_method_Bag_index_get" not in main_body
    assert main_body.count("    mov rcx, qword ptr [rcx + 80]") >= 2
    assert main_body.count("    call r11") >= 2


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

    assert "    call __nif_method_Window_slice_get" not in main_body
    assert "    mov rcx, qword ptr [rcx + 80]" in main_body
    assert "    call r11" in main_body


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

    assert "__nif_method_Counter_add:" in asm
    assert "    call __nif_method_Counter_add" not in main_body
    assert "    mov rdi, qword ptr [rsp]" in main_body
    assert "    mov rsi, qword ptr [rsp + 8]" in main_body
    assert "    mov rcx, qword ptr [rcx + 80]" in main_body
    assert "    call r11" in main_body


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

    assert "__nif_method_Counter_add:" in asm
    assert "    call __nif_method_Counter_add" in asm


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

    assert "__nif_ctor_Counter:" in asm
    assert "    call __nif_ctor_Counter" in asm
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

    assert "__nif_ctor_Pair:" in asm
    assert "__nif_ctor_Pair__1:" in asm
    assert "    call __nif_ctor_Pair__1" in asm
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

    assert "__nif_ctor_init_Base:" in asm
    assert "__nif_ctor_init_Derived:" in asm
    assert "    call __nif_ctor_Derived" in asm
    assert "    call __nif_ctor_init_Derived" in asm
    assert "    call __nif_ctor_init_Base" in asm


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
