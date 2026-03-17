from __future__ import annotations

from tests.compiler.codegen.helpers import emit_semantic_source_asm


def test_semantic_backend_emits_expected_call_shapes(tmp_path) -> None:
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

    semantic_asm = emit_semantic_source_asm(tmp_path, source)

    for expected in [
        "    call add",
        "    call __nif_method_Math_inc",
        "    call __nif_ctor_Box",
        "    call __nif_method_Box_get",
    ]:
        assert expected in semantic_asm


def test_semantic_backend_emits_expected_arrays_strings_and_casts(tmp_path) -> None:
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

    semantic_asm = emit_semantic_source_asm(tmp_path, source)

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
        assert expected in semantic_asm


def test_semantic_backend_emits_expected_object_fields_and_control_flow(tmp_path) -> None:
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

    semantic_asm = emit_semantic_source_asm(tmp_path, source)

    for expected in [
        "    mov qword ptr [rcx + 24], rax",
        "    mov rax, qword ptr [rax + 24]",
        ".Lmain_while_start_",
        ".Lmain_while_end_",
        ".Lmain_if_else_",
    ]:
        assert expected in semantic_asm