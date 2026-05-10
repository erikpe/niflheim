from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_to_asm, write


def test_cli_explicit_aarch64_target_compiles_smoke_program(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }

        fn main() -> i64 {
            return add(20, 22);
        }
        """,
    )

    asm_path = compile_to_asm(
        monkeypatch,
        entry,
        project_root=tmp_path,
        out_path=tmp_path / "out.s",
        extra_args=["--target", "aarch64"],
    )
    asm = asm_path.read_text(encoding="utf-8")

    assert "    stp x29, x30, [sp, #-16]!" in asm
    assert "    mov x29, sp" in asm
    assert "    bl __nif_fn_main__add" in asm
    assert "    ret" in asm


def test_cli_explicit_aarch64_target_can_omit_runtime_trace(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn add(a: i64, b: i64) -> i64 {
            return a + b;
        }

        fn main() -> i64 {
            return add(20, 22);
        }
        """,
    )

    asm_path = compile_to_asm(
        monkeypatch,
        entry,
        project_root=tmp_path,
        out_path=tmp_path / "out.s",
        extra_args=["--target", "aarch64", "--omit-runtime-trace"],
    )
    asm = asm_path.read_text(encoding="utf-8")

    assert "rt_trace_push" not in asm
    assert "rt_trace_pop" not in asm
    assert "rt_trace_set_location" not in asm