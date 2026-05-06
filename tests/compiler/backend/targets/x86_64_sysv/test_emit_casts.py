from __future__ import annotations

from compiler.backend.targets import BackendTargetOptions
from tests.compiler.backend.targets.x86_64_sysv.helpers import emit_source_asm


def _body_for_label(asm: str, label: str) -> str:
    epilogue = f".L{label}_epilogue:"
    return asm[asm.index(f"{label}:") : asm.index(epilogue)]


def test_emit_source_asm_emits_class_cast_and_type_test_helpers(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        class Person {
            age: i64;
        }

        fn keep(value: Obj) -> Person {
            return (Person)value;
        }

        fn matches(value: Obj) -> bool {
            return value is Person;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
    )

    assert "    call rt_checked_cast" in asm
    assert "    call rt_is_instance_of_type" in asm
    assert "    lea rsi, [rip + __nif_type_main__Person]" in asm


def test_emit_source_asm_inlines_interface_cast_and_type_test(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        interface Hashable {
            fn hash_code() -> u64;
        }

        class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }

        fn cast_it(value: Obj) -> Hashable {
            return (Hashable)value;
        }

        fn test_it(value: Obj) -> bool {
            return value is Hashable;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
    )

    assert "rt_checked_cast_interface" not in asm
    assert "rt_is_instance_of_interface" not in asm
    assert "    mov rcx, qword ptr [rax]" in asm
    assert "    mov rcx, qword ptr [rcx + 64]" in asm
    assert "    mov rcx, qword ptr [rcx]" in asm
    assert "    mov rdi, qword ptr [rcx + 24]" in asm
    assert "    setne al" in asm


def test_emit_source_asm_inlines_array_kind_cast_checks(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn erase(value: Obj[]) -> Obj {
            return value;
        }

        fn main() -> i64 {
            var value: Obj = erase(Obj[](1u));
            var numbers: u64[] = (u64[])value;
            return (i64)numbers[0];
        }
        """,
        skip_optimize=True,
    )

    main_body = _body_for_label(asm, "main")

    assert "    call rt_panic_bad_cast" in main_body
    assert "rt_checked_cast" not in main_body
    assert "rt_checked_cast_interface" not in main_body
    assert "    cmp qword ptr [rax + 32], 2" in main_body
    assert "    call rt_panic_array_get_out_of_bounds" in main_body


def test_emit_source_asm_handles_primitive_cast_families(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn main() -> i64 {
            var a: double = (double)7u;
            var b: i64 = (i64)a;
            var c: u8 = (u8)260;
            var d: bool = (bool)0.0;
            if d {
                return 1;
            }
            return b + (i64)c;
        }
        """,
        skip_optimize=True,
    )

    main_body = _body_for_label(asm, "main")

    assert "    call rt_cast_u64_to_double" in main_body
    assert "    call rt_cast_double_to_i64" in main_body
    assert "    and rax, 255" in main_body
    assert "    ucomisd xmm0, xmm1" in main_body
    assert "    or al, dl" in main_body


def test_emit_source_asm_emits_runtime_trace_hooks_by_default(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn bump(value: i64) -> i64 {
            return value + 1;
        }

        fn main() -> i64 {
            return bump(41);
        }
        """,
        skip_optimize=True,
    )

    main_body = _body_for_label(asm, "main")

    assert "    call rt_trace_push" in asm
    assert "    call rt_trace_pop" in asm
    assert "__nif_debug_fn_main:" in asm
    assert "__nif_debug_file_main:" in asm
    assert "    call rt_trace_set_location" in main_body


def test_emit_source_asm_emits_caller_call_site_trace_location(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn crash() -> i64 {
            var values: i64[] = null;
            return values[0];
        }

        fn main() -> i64 {
            return crash();
        }
        """,
        skip_optimize=True,
    )

    main_body = _body_for_label(asm, "main")

    assert "    call rt_trace_set_location" in main_body
    assert "    call __nif_fn_main__crash" in main_body
    assert "    mov edi," in main_body
    assert "    mov esi," in main_body


def test_emit_source_asm_emits_member_call_site_trace_location(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
fn make_box() -> Box {
    return Box();
}

class Box {
    fn crash() -> i64 {
        var values: i64[] = null;
        return values[0];
    }
}

fn main() -> i64 {
    return make_box().crash();
}
""",
        skip_optimize=True,
    )

    main_body = _body_for_label(asm, "main")

    assert main_body.count("    call rt_trace_set_location") == 2
    assert "    call __nif_fn_main__make_box" in main_body
    assert "    call rt_panic_null_deref" in main_body
    assert "    mov r10, qword ptr [rdi]" in main_body
    assert "    mov r10, qword ptr [r10 + 80]" in main_body
    assert "    mov r11, qword ptr [r10]" in main_body
    assert "    call r11" in main_body


def test_emit_source_asm_can_omit_runtime_trace_hooks(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        class Box {
            value: i64;
        }

        fn main() -> i64 {
            var box: Box = Box(0);
            return box.value;
        }
        """,
        skip_optimize=True,
        options=BackendTargetOptions(runtime_trace_enabled=False),
    )

    assert "rt_trace_push" not in asm
    assert "rt_trace_pop" not in asm
    assert "rt_trace_set_location" not in asm