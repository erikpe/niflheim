from __future__ import annotations

from compiler.backend.targets import BackendTargetOptions
from tests.compiler.backend.targets.aarch64.helpers import emit_source_asm


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

    assert "    bl rt_checked_cast" in asm
    assert "    bl rt_is_instance_of_type" in asm
    assert "    adrp x1, __nif_type_main__Person" in asm
    assert "    add x1, x1, :lo12:__nif_type_main__Person" in asm


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
    assert "    ldr x1, [x0]" in asm
    assert "    ldr x1, [x1, #64]" in asm
    assert "    ldr x1, [x1]" in asm
    assert "    cset w0, ne" in asm


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

    assert "    bl rt_panic_bad_cast" in main_body
    assert "rt_checked_cast" not in main_body
    assert "rt_checked_cast_interface" not in main_body
    assert "    ldr x1, [x0, #32]" in main_body
    assert "    cmp x1, #2" in main_body
    assert "    bl rt_panic_array_get_out_of_bounds" in main_body


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

    assert "    bl rt_cast_u64_to_double" in main_body
    assert "    bl rt_cast_double_to_i64" in main_body
    assert "    and x0, x0, #255" in main_body
    assert "    fcmp d0, #0.0" in main_body
    assert "    orr w0, w0, w1" in main_body


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