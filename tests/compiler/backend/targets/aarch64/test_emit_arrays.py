from __future__ import annotations

from compiler.backend.targets import BackendTargetOptions
from tests.compiler.backend.targets.aarch64.helpers import emit_source_asm


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

    assert "    bl rt_array_new_i64" in asm
    assert "    bl rt_array_get_i64" not in asm
    assert "    bl rt_array_set_i64" not in asm
    assert "    bl rt_array_slice_i64" in asm
    assert "    bl rt_array_set_slice_i64" in asm
    assert "    bl rt_array_len" not in asm
    assert "    ldr x0, [x0, #24]" in asm


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

    assert "    bl rt_array_get_i64" in asm
    assert "    bl rt_array_set_i64" in asm
    assert "    bl rt_array_len" in asm


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

    assert "    bl rt_panic_array_api_null_object" in main_body
    assert ".Lmain_i1_array_len_nonnull:" in asm
    assert "    ldr x0, [x0, #24]" in main_body


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

    assert "    bl rt_panic_array_get_out_of_bounds" in main_body
    assert ".Lmain_i3_array_in_bounds_panic:" in asm
    assert "    ldr x0, [x9, x1, lsl #3]" in main_body


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

    assert "    bl rt_array_new_double" in main_body
    assert "    str d0, [x9, x1, lsl #3]" in main_body
    assert "    ldr d0, [x9, x1, lsl #3]" in main_body
    assert "    bl rt_array_get_double" not in main_body
    assert "    bl rt_array_set_double" not in main_body