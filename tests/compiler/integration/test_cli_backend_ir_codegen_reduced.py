from __future__ import annotations

from pathlib import Path

import compiler.cli as cli

from tests.compiler.integration.helpers import compile_and_run, compile_to_asm, run_cli, write


_EXPERIMENTAL_BACKEND_ARGS = ["--experimental-backend", "backend-ir-x86_64_sysv"]


def test_cli_experimental_backend_selector_emits_assembly_without_default_codegen(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    def _unexpected_emit_asm(*args, **kwargs):
        raise AssertionError("default checked codegen should not run when the reduced backend selector is enabled")

    monkeypatch.setattr(cli, "emit_asm", _unexpected_emit_asm)

    asm_path = compile_to_asm(
        monkeypatch,
        entry,
        project_root=tmp_path,
        out_path=out_file,
        extra_args=list(_EXPERIMENTAL_BACKEND_ARGS),
    )
    asm = asm_path.read_text(encoding="utf-8")

    assert ".intel_syntax noprefix" in asm
    assert "main:" in asm
    assert "    mov rax, 0" in asm
    assert "    jmp .Lmain_epilogue" in asm


def test_cli_default_codegen_path_does_not_use_experimental_backend_without_selector(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    def _unexpected_backend_target(*args, **kwargs):
        raise AssertionError("experimental backend target should not run on the default checked codegen path")

    monkeypatch.setattr(cli, "emit_x86_64_sysv_asm", _unexpected_backend_target)

    asm_path = compile_to_asm(monkeypatch, entry, project_root=tmp_path, out_path=out_file)

    assert asm_path.exists()


def test_cli_experimental_backend_selector_reports_reduced_slice_limitations(tmp_path: Path, monkeypatch, capsys) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        class Box {
            value: i64;

            constructor(value: i64) {
                __self.value = value;
            }
        }

        fn bounce(value: Obj) -> Obj {
            return value;
        }

        fn main() -> i64 {
            var value: Box = Box(7);
            var raw: Obj = bounce(value);
            var box: Box = (Box)raw;
            return box.value;
        }
        """,
    )

    rc = run_cli(monkeypatch, ["nifc", str(entry), *list(_EXPERIMENTAL_BACKEND_ARGS)])
    captured = capsys.readouterr()

    assert rc == 1
    assert "Backend target 'x86_64_sysv'" in captured.err
    assert "BackendCastInst" in captured.err


def test_cli_experimental_backend_selector_can_compile_and_run_reduced_scope_program(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn inc(value: i64) -> i64 {
            return value + 1;
        }

        fn step(limit: i64) -> i64 {
            var total: i64 = 0;
            while total < limit {
                total = inc(total);
            }
            return total;
        }

        fn main() -> i64 {
            return step(4);
        }
        """,
    )

    run = compile_and_run(
        monkeypatch,
        entry,
        project_root=tmp_path,
        extra_args=list(_EXPERIMENTAL_BACKEND_ARGS),
    )

    assert run.returncode == 4
