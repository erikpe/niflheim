from __future__ import annotations

from compiler.backend.program.symbols import mangle_function_symbol
from compiler.backend.targets.x86_64_sysv.array_runtime import direct_primitive_array_store_operand
from compiler.backend.program.runtime import (
    ARRAY_CONSTRUCTOR_RUNTIME_CALLS,
    ARRAY_FROM_BYTES_U8_RUNTIME_CALL,
    ARRAY_INDEX_SET_RUNTIME_CALLS,
    ARRAY_SLICE_GET_RUNTIME_CALLS,
)
from compiler.common.collection_protocols import ArrayRuntimeKind
from compiler.common.type_names import TYPE_NAME_U8
from tests.compiler.backend.targets.x86_64_sysv.helpers import emit_source_asm


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

    assert f"    call {mangle_function_symbol(('main',), 'add')}" in asm
    assert "    call __nif_method_main__Math_inc" in asm
    assert "    call rt_alloc_obj" in main_body
    assert "    call __nif_ctor_init_main__Box" in main_body
    assert "    mov rcx, qword ptr [rcx + 80]" not in main_body


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

    assert "    mov qword ptr [rcx + 24], rax" in asm
    assert "    mov rax, qword ptr [rax + 24]" in asm
    assert ".Lmain_b" in asm
    assert "    je .Lmain_b" in asm
    assert "    jmp .Lmain_b" in asm


def test_emit_source_asm_emits_integer_binary_expr_shape(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn f(a: i64, b: i64) -> i64 { return a + b; }

        fn main() -> i64 { return f(20, 22); }
        """,
        skip_optimize=True,
        source_path="main.nif",
    )

    assert "    mov rdi, 20" in asm
    assert "    mov rsi, 22" in asm
    assert "    add rax, rcx" in asm


def test_emit_source_asm_emits_numeric_cast_conversion_shape(tmp_path) -> None:
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
        skip_optimize=True,
    )

    assert "    cvtsi2sd xmm0, rax" in asm
    assert "    movq qword ptr [rbp - " in asm
    assert "    movq xmm0, qword ptr [rbp - " in asm
    assert "    ucomisd xmm0, xmm1" in asm
    assert "    setne al" in asm
    assert "    setp dl" in asm


def test_emit_source_asm_emits_checked_double_to_integer_and_unsigned_u64_to_double_cast_shape(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn to_double(x: u64) -> double { return (double)x; }

        fn to_i64(x: double) -> i64 { return (i64)x; }

        fn main() -> i64 {
            return to_i64(to_double(42u));
        }
        """,
        skip_optimize=True,
    )

    assert "    call rt_cast_u64_to_double" in asm
    assert "    call rt_cast_double_to_i64" in asm


def test_emit_source_asm_emits_while_control_flow_shape(tmp_path) -> None:
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
        skip_optimize=True,
    )

    loop_label = mangle_function_symbol(("main",), "loop_to")
    assert f"{loop_label}:" in asm
    assert f".L{loop_label}_b" in asm
    assert f"    je .L{loop_label}_b" in asm


def test_emit_source_asm_emits_if_else_control_flow_shape(tmp_path) -> None:
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
        skip_optimize=True,
    )

    choose_label = mangle_function_symbol(("main",), "choose")
    assert f"{choose_label}:" in asm
    assert f".L{choose_label}_b" in asm
    assert f"    je .L{choose_label}_b" in asm
    assert f"    jmp .L{choose_label}_b" in asm