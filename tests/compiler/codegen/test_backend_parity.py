from __future__ import annotations

from compiler.codegen.abi.runtime import (
    ARRAY_CONSTRUCTOR_RUNTIME_CALLS,
    ARRAY_FROM_BYTES_U8_RUNTIME_CALL,
    ARRAY_INDEX_SET_RUNTIME_CALLS,
    ARRAY_SLICE_GET_RUNTIME_CALLS,
)
from compiler.codegen.abi.array import direct_primitive_array_store_operand
from compiler.codegen.symbols import mangle_function_symbol
from compiler.common.collection_protocols import ArrayRuntimeKind
from compiler.common.type_names import TYPE_NAME_U8
from tests.compiler.codegen.helpers import emit_source_asm


def test_backend_emits_expected_call_shapes(tmp_path) -> None:
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

    asm = emit_source_asm(tmp_path, source)
    main_body = asm[asm.index("main:") : asm.index(".Lmain_epilogue:")]

    for expected in [
        f'    call {mangle_function_symbol(("main",), "add")}',
        "    call __nif_method_main__Math_inc",
        "    call __nif_ctor_main__Box",
    ]:
        assert expected in asm
    assert "    call __nif_method_main__Box_get" in main_body
    assert "    mov rcx, qword ptr [rcx + 80]" not in main_body
    assert "    call r11" not in main_body


def test_backend_emits_expected_arrays_strings_and_casts(tmp_path) -> None:
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
        f"    call {ARRAY_CONSTRUCTOR_RUNTIME_CALLS[TYPE_NAME_U8]}",
        f"    call {ARRAY_SLICE_GET_RUNTIME_CALLS[ArrayRuntimeKind.U8]}",
        f"    call {ARRAY_FROM_BYTES_U8_RUNTIME_CALL}",
        "    call __nif_method_main__Str_from_u8_array",
        "    call __nif_method_main__Str_concat",
        "    call rt_checked_cast",
        "__nif_type_name_Person:",
        "__nif_type_Person:",
        f"    mov {direct_primitive_array_store_operand('rax', 'rcx', runtime_kind=ArrayRuntimeKind.U8)}, dl",
    ]:
        assert expected in asm
    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.U8]}" not in asm
    assert "    call rt_array_get_u8" not in asm


def test_backend_emits_expected_object_fields_and_control_flow(tmp_path) -> None:
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

    asm = emit_source_asm(tmp_path, source)

    for expected in [
        "    mov qword ptr [rcx + 24], rax",
        "    mov rax, qword ptr [rax + 24]",
        ".Lmain_while_start_",
        ".Lmain_while_end_",
        ".Lmain_if_else_",
    ]:
        assert expected in asm


def test_backend_emits_integer_binary_expr_shape(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn f(a: i64, b: i64) -> i64 { return a + b; }

        fn main() -> i64 { return f(20, 22); }
        """,
        source_path="main.nif",
    )

    assert "    push rax" in asm
    assert "    add rax, rcx" in asm


def test_backend_emits_numeric_cast_conversion_shape(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn to_double(x: i64) -> double { return (double)x; }

        fn to_bool(x: double) -> bool { return (bool)x; }

        fn main() -> i64 {
            var d: double = to_double(7);
            if to_bool(d) {
                return 0;
            }
            return 1;
        }
        """,
    )

    assert "    cvtsi2sd xmm0, rax" in asm
    assert "    movq rax, xmm0" in asm
    assert "    movq xmm0, rax" in asm
    assert "    ucomisd xmm0, xmm1" in asm
    assert "    setne al" in asm
    assert "    setp dl" in asm


def test_backend_emits_checked_double_to_integer_and_unsigned_u64_to_double_cast_shape(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn to_double(x: u64) -> double { return (double)x; }

        fn to_i64(x: double) -> i64 { return (i64)x; }

        fn main() -> i64 {
            return to_i64(to_double(42u));
        }
        """,
    )

    assert "    call rt_cast_u64_to_double" in asm
    assert "    call rt_cast_double_to_i64" in asm


def test_backend_emits_while_control_flow_shape(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn loop_to(limit: i64) -> i64 {
            var i: i64 = 0;
            while i < limit {
                i = i + 1;
            }
            return i;
        }

        fn main() -> i64 {
            return loop_to(4);
        }
        """,
    )

    loop_label = mangle_function_symbol(("main",), "loop_to")
    assert f".L{loop_label}_while_start_" in asm
    assert f".L{loop_label}_while_end_" in asm
    assert f"    je .L{loop_label}_while_end_" in asm


def test_backend_emits_if_else_control_flow_shape(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn choose(flag: bool) -> i64 {
            if flag {
                return 1;
            } else {
                return 2;
            }
        }

        fn main() -> i64 {
            return choose(true);
        }
        """,
    )

    choose_label = mangle_function_symbol(("main",), "choose")
    assert f".L{choose_label}_if_else_" in asm
    assert f".L{choose_label}_if_end_" in asm
    assert f"    je .L{choose_label}_if_else_" in asm
    assert f"    jmp .L{choose_label}_if_end_" in asm