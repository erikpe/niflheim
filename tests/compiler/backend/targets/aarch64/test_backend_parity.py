from __future__ import annotations

from compiler.backend.program.runtime import (
    ARRAY_CONSTRUCTOR_RUNTIME_CALLS,
    ARRAY_FROM_BYTES_U8_RUNTIME_CALL,
    ARRAY_SLICE_GET_RUNTIME_CALLS,
)
from compiler.backend.program.symbols import mangle_function_symbol
from compiler.common.collection_protocols import ArrayRuntimeKind
from compiler.common.type_names import TYPE_NAME_U8
from tests.compiler.backend.targets.aarch64.helpers import emit_source_asm


def test_emit_source_asm_emits_expected_call_shapes(tmp_path) -> None:
    source = """
    fn add(a: i64, b: i64) -> i64 {
        return a + b;
    }

    class Math {
        static fn inc(v: i64) -> i64 {
            return v + 1;
        }
    }

    class Box {
        value: i64;

        fn get() -> i64 {
            return __self.value;
        }
    }

    fn main() -> i64 {
        var box: Box = Box(Math.inc(20));
        return add(box.get(), 21);
    }
    """

    asm = emit_source_asm(tmp_path, source, skip_optimize=True)
    main_body = asm[asm.index("main:") : asm.index(".Lmain_epilogue:")]

    assert f"    bl {mangle_function_symbol(('main',), 'add')}" in asm
    assert "    bl __nif_method_main__Math_inc" in asm
    assert "    bl rt_alloc_obj" in main_body
    assert "    bl __nif_ctor_init_main__Box" in main_body
    assert "    ldr x10, [x10, #80]" in main_body
    assert "    blr x16" in main_body


def test_emit_source_asm_emits_expected_arrays_strings_and_casts(tmp_path) -> None:
    source = """
    class Str {
        _bytes: u8[];

        static fn from_u8_array(value: u8[]) -> Str {
            return Str(value);
        }

        static fn concat(left: Str, right: Str) -> Str {
            return Str(left._bytes);
        }
    }

    class Person {
        age: i64;
    }

    fn main() -> i64 {
        var nums: u8[] = u8[](4u);
        nums[0] = (u8)1;
        var x: u8 = nums[0];
        var s: u8[] = nums[1:3];
        var msg: Str = "hi" + " there";
        var obj: Obj = (Obj)Person(7);
        var p: Person = (Person)obj;
        if p == null {
            return 1;
        }
        return (i64)x;
    }
    """

    asm = emit_source_asm(tmp_path, source)

    for expected in [
        f"    bl {ARRAY_CONSTRUCTOR_RUNTIME_CALLS[TYPE_NAME_U8]}",
        f"    bl {ARRAY_SLICE_GET_RUNTIME_CALLS[ArrayRuntimeKind.U8]}",
        f"    bl {ARRAY_FROM_BYTES_U8_RUNTIME_CALL}",
        "    bl __nif_method_main__Str_from_u8_array",
        "    bl __nif_method_main__Str_concat",
        "    bl rt_checked_cast",
        "__nif_type_name_Person:",
        "__nif_type_Person:",
        "    strb w2, [x9, x1]",
    ]:
        assert expected in asm
    assert "    bl rt_array_set_u8" not in asm
    assert "    bl rt_array_get_u8" not in asm


def test_emit_source_asm_emits_expected_object_fields_and_control_flow(tmp_path) -> None:
    source = """
    class Counter {
        value: i64;
    }

    fn main() -> i64 {
        var c: Counter = Counter(0);
        var i: i64 = 0;
        while i < 3 {
            c.value = i;
            if i == 2 {
                break;
            }
            i = i + 1;
        }
        return c.value;
    }
    """

    asm = emit_source_asm(tmp_path, source, skip_optimize=True)

    assert "    str x0, [x1, #24]" in asm
    assert "    ldr x0, [x0, #24]" in asm
    assert ".Lmain_b" in asm
    assert "    b.eq .Lmain_b" in asm
    assert "    b .Lmain_b" in asm