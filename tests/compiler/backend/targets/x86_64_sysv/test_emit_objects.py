from __future__ import annotations

from tests.compiler.backend.lowering.helpers import lower_project_to_backend_program
from tests.compiler.backend.targets.x86_64_sysv.helpers import compile_and_run_source, emit_program, emit_source_asm


def _body_for_label(asm: str, label: str) -> str:
    epilogue = f".L{label}_epilogue:"
    return asm[asm.index(f"{label}:") : asm.index(epilogue)]


def test_emit_source_asm_emits_object_alloc_constructor_init_and_field_offsets(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        class Counter {
            value: i64;

            constructor(value: i64) {
                __self.value = value;
            }
        }

        fn main() -> i64 {
            var counter: Counter = Counter(7);
            counter.value = 9;
            return counter.value;
        }
        """,
        skip_optimize=True,
    )

    main_body = _body_for_label(asm, "main")

    assert "__nif_ctor_main__Counter:" in asm
    assert "__nif_ctor_init_main__Counter:" in asm
    assert "    call rt_alloc_obj" in main_body
    assert "    lea rsi, [rip + __nif_type_main__Counter]" in main_body
    assert "    call __nif_ctor_init_main__Counter" in main_body
    assert "    mov qword ptr [rcx + 24], rax" in asm
    assert "    mov rax, qword ptr [rax + 24]" in asm


def test_emit_source_asm_emits_reference_field_metadata_records(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        class Record {
            head: Obj;
            count: i64;
            tail: Obj;

            constructor(head: Obj, count: i64, tail: Obj) {
                __self.head = head;
                __self.count = count;
                __self.tail = tail;
            }
        }

        fn main() -> i64 {
            var value: Record = Record(null, 7, null);
            return value.count;
        }
        """,
        skip_optimize=True,
    )

    assert "__nif_ctor_main__Record:" in asm
    assert "__nif_ctor_init_main__Record:" in asm
    assert "__nif_type_name_main__Record__ptr_offsets:" in asm
    assert ".long 24" in asm
    assert ".long 40" in asm
    assert "__nif_type_main__Record:" in asm
    assert ".quad __nif_type_name_main__Record" in asm
    assert ".quad __nif_type_name_main__Record__ptr_offsets" in asm
    assert ".quad 0" in asm


def test_emit_source_asm_emits_explicit_null_checks_for_object_field_flows(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        class Counter {
            value: i64;

            constructor(value: i64) {
                __self.value = value;
            }
        }

        fn bump(counter: Counter, delta: i64) -> i64 {
            counter.value = counter.value + delta;
            return counter.value;
        }

        fn main() -> i64 {
            return bump(Counter(41), 1);
        }
        """,
        skip_optimize=True,
    )

    bump_body = _body_for_label(asm, "__nif_fn_main__bump")

    assert bump_body.count("    call rt_panic_null_deref") == 3
    assert "    mov rax, qword ptr [rax + 24]" in bump_body
    assert "    mov qword ptr [rcx + 24], rax" in bump_body


def test_emit_source_asm_is_byte_stable_for_multimodule_object_metadata(tmp_path) -> None:
    files = {
        "left.nif": """
        export class Key {
            value: i64;
        }
        """,
        "right.nif": """
        export class Key {
            value: Obj;
        }
        """,
        "main.nif": """
        import left;
        import right;

        fn read(left_key: left.Key, right_key: right.Key) -> i64 {
            return left_key.value;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
    }

    first = emit_program(lower_project_to_backend_program(tmp_path / "run_a", files, skip_optimize=True))
    second = emit_program(lower_project_to_backend_program(tmp_path / "run_b", files, skip_optimize=True))

    assert first == second
    assert first.index("__nif_type_left__Key:") < first.index("__nif_type_right__Key:")


def test_emit_source_asm_can_execute_object_construction_and_field_access(tmp_path) -> None:
    run = compile_and_run_source(
        tmp_path,
        """
        class Pair {
            left: i64;
            right: i64;

            constructor(left: i64, right: i64) {
                __self.left = left;
                __self.right = right;
            }
        }

        fn main() -> i64 {
            var value: Pair = Pair(7, 9);
            return value.left + value.right;
        }
        """,
        skip_optimize=True,
    )

    assert run.returncode == 16