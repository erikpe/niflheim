from __future__ import annotations

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

    for expected in [
        "    call add",
        "    call __nif_method_Math_inc",
        "    call __nif_ctor_Box",
        "    call __nif_method_Box_get",
    ]:
        assert expected in asm


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
        "    call rt_array_new_u8",
        "    call rt_array_set_u8",
        "    call rt_array_get_u8",
        "    call rt_array_slice_u8",
        "    call rt_array_from_bytes_u8",
        "    call __nif_method_Str_from_u8_array",
        "    call __nif_method_Str_concat",
        "    call rt_checked_cast",
        "__nif_type_name_Person:",
        "__nif_type_Person:",
    ]:
        assert expected in asm


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
    assert "    cvttsd2si rax, xmm0" in asm
    assert "    cmp rax, 0" in asm
    assert "    setne al" in asm


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

    assert ".Lloop_to_while_start_" in asm
    assert ".Lloop_to_while_end_" in asm
    assert "    je .Lloop_to_while_end_" in asm


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

    assert ".Lchoose_if_else_" in asm
    assert ".Lchoose_if_end_" in asm
    assert "    je .Lchoose_if_else_" in asm
    assert "    jmp .Lchoose_if_end_" in asm