from __future__ import annotations

from compiler.backend.targets import BackendTargetOptions
from tests.compiler.backend.targets.x86_64_sysv.helpers import emit_source_asm


def _body_for_label(asm: str, label: str) -> str:
    epilogue = f".L{label}_epilogue:"
    return asm[asm.index(f"{label}:") : asm.index(epilogue)]


def test_emit_source_asm_emits_runtime_backed_array_instruction_families(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn read(values: i64[]) -> i64 {
            return values[1];
        }

        fn write(values: i64[]) -> unit {
            values[1] = 7;
            return;
        }

        fn part(values: i64[]) -> i64[] {
            return values[0:2];
        }

        fn overwrite(values: i64[], replacement: i64[]) -> unit {
            values[0:2] = replacement;
            return;
        }

        fn size(values: i64[]) -> u64 {
            return values.len();
        }

        fn make() -> i64[] {
            return i64[](3u);
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
    )

    assert "    call rt_array_new_i64" in asm
    assert "    call rt_array_get_i64" not in asm
    assert "    call rt_array_set_i64" not in asm
    assert "    call rt_array_slice_i64" in asm
    assert "    call rt_array_set_slice_i64" in asm
    assert "    call rt_array_len" not in asm
    assert "    mov rax, qword ptr [rax + 24]" in asm


def test_emit_source_asm_emits_array_method_forms_via_runtime_helpers(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn write(values: u64[]) -> unit {
            values.index_set(1, 42u);
            return;
        }

        fn read(values: u64[]) -> u64 {
            var item: u64 = values.index_get(1);
            return item;
        }

        fn read_part(values: u64[]) -> u64[] {
            var part: u64[] = values.slice_get(0, 2);
            return part;
        }

        fn replace(values: u64[], part: u64[]) -> unit {
            values.slice_set(1, 3, part);
            return;
        }

        fn size(values: u64[]) -> u64 {
            return values.len();
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
    )

    read_body = _body_for_label(asm, "__nif_fn_main__read")
    write_body = _body_for_label(asm, "__nif_fn_main__write")
    part_body = _body_for_label(asm, "__nif_fn_main__read_part")
    replace_body = _body_for_label(asm, "__nif_fn_main__replace")
    size_body = _body_for_label(asm, "__nif_fn_main__size")

    assert "    call rt_array_set_u64" not in write_body
    assert "    call rt_array_get_u64" not in read_body
    assert "    call rt_array_slice_u64" in part_body
    assert "    call rt_array_set_slice_u64" in replace_body
    assert "    call rt_array_len" not in size_body
    assert "    mov qword ptr [rax + rcx * 8 + 48], rdx" in write_body
    assert "    mov rax, qword ptr [rax + rcx * 8 + 48]" in read_body
    assert "    mov rax, qword ptr [rax + 24]" in size_body


def test_emit_source_asm_can_disable_array_fast_paths(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn read(values: i64[]) -> i64 {
            return values[1];
        }

        fn write(values: i64[]) -> unit {
            values[1] = 7;
            return;
        }

        fn size(values: i64[]) -> u64 {
            return values.len();
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
        options=BackendTargetOptions(collection_fast_paths_enabled=False),
    )

    assert "    call rt_array_get_i64" in asm
    assert "    call rt_array_set_i64" in asm
    assert "    call rt_array_len" in asm


def test_emit_source_asm_emits_fast_path_iteration_for_direct_for_in_loop(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn main() -> i64 {
            var values: i64[] = i64[](4u);
            values[0] = 4;
            values[1] = 6;
            values[2] = 8;
            values[3] = 10;

            var total: i64 = 0;
            for value in values {
                total = total + value;
            }

            return total;
        }
        """,
        skip_optimize=True,
    )

    main_body = _body_for_label(asm, "main")

    assert "    mov rax, qword ptr [rax + 24]" in main_body
    assert "    mov rax, qword ptr [rax + rcx * 8 + 48]" in main_body
    assert ".Lmain_b1:" in asm
    assert "    jmp .Lmain_b1" in asm


def test_emit_source_asm_emits_fast_path_array_access_in_each_callable(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn first(values: i64[]) -> i64 {
            return (i64)values.len() + values[0];
        }

        fn second(values: i64[]) -> i64 {
            return (i64)values.len() + values[0];
        }

        fn main() -> i64 {
            var values: i64[] = i64[](3u);
            values[0] = 5;
            values[1] = 7;
            values[2] = 9;
            return first(values) + second(values);
        }
        """,
        skip_optimize=True,
    )

    first_body = _body_for_label(asm, "__nif_fn_main__first")
    second_body = _body_for_label(asm, "__nif_fn_main__second")

    assert "    mov rax, qword ptr [rax + 24]" in first_body
    assert "    mov rax, qword ptr [rax + rcx * 8 + 48]" in first_body
    assert "    mov rax, qword ptr [rax + 24]" in second_body
    assert "    mov rax, qword ptr [rax + rcx * 8 + 48]" in second_body


def test_emit_source_asm_emits_array_len_null_guard(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn main() -> i64 {
            var values: i64[] = null;
            values.len();
            return 0;
        }
        """,
    )

    main_body = _body_for_label(asm, "main")

    assert "    call rt_panic_array_api_null_object" in main_body
    assert ".Lmain_i1_array_len_nonnull:" in asm
    assert "    mov rax, qword ptr [rax + 24]" in main_body


def test_emit_source_asm_emits_array_index_null_guard(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn main() -> i64 {
            var values: i64[] = null;
            return values[0];
        }
        """,
    )

    main_body = _body_for_label(asm, "main")

    assert "    call rt_panic_array_api_null_object" in main_body
    assert "    mov rax, qword ptr [rax + rcx * 8 + 48]" in main_body
    assert "    call rt_array_get_i64" not in main_body


def test_emit_source_asm_emits_array_get_out_of_bounds_guard(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn main() -> i64 {
            var values: i64[] = i64[](1u);
            return values[2];
        }
        """,
    )

    main_body = _body_for_label(asm, "main")

    assert "    call rt_panic_array_get_out_of_bounds" in main_body
    assert ".Lmain_i3_array_in_bounds_panic:" in asm
    assert "    mov rax, qword ptr [rax + rcx * 8 + 48]" in main_body


def test_emit_source_asm_emits_array_set_out_of_bounds_guard(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn main() -> i64 {
            var values: i64[] = i64[](1u);
            values[2] = 7;
            return 0;
        }
        """,
    )

    main_body = _body_for_label(asm, "main")

    assert "    call rt_panic_array_set_out_of_bounds" in main_body
    assert "    mov qword ptr [rax + rcx * 8 + 48], rdx" in main_body
    assert "    call rt_array_set_i64" not in main_body


def test_emit_source_asm_emits_fast_path_double_array_access(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn main() -> i64 {
            var values: double[] = double[](2u);
            if values[0] != 0.0 { return 1; }
            if values[1] != 0.0 { return 2; }
            values[0] = 1.25;
            values[1] = 2.5;
            if values[0] != 1.25 { return 3; }
            if values[1] != 2.5 { return 4; }
            return 0;
        }
        """,
        skip_optimize=True,
    )

    main_body = _body_for_label(asm, "main")

    assert "    call rt_array_new_double" in main_body
    assert "    movq qword ptr [rax + rcx * 8 + 48], xmm0" in main_body
    assert "    movq xmm0, qword ptr [rax + rcx * 8 + 48]" in main_body
    assert "    call rt_array_get_double" not in main_body
    assert "    call rt_array_set_double" not in main_body