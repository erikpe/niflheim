from __future__ import annotations

from pathlib import Path

import compiler.cli as cli

from tests.compiler.integration.helpers import compile_to_asm, write


def test_cli_default_checked_path_uses_backend_ir_target_without_selector(tmp_path: Path, monkeypatch) -> None:
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

    seen = {"requested_target_name": None, "target_calls": 0}
    real_target = cli.resolve_backend_target("x86_64_sysv")

    class _CountingTarget:
        name = real_target.name

        def emit_assembly(self, *args, **kwargs):
            seen["target_calls"] += 1
            return real_target.emit_assembly(*args, **kwargs)

    def _counting_resolve_backend_target(requested_target_name: str | None = None):
        seen["requested_target_name"] = requested_target_name
        return _CountingTarget()

    monkeypatch.setattr(cli, "resolve_backend_target", _counting_resolve_backend_target)

    asm_path = compile_to_asm(monkeypatch, entry, project_root=tmp_path, out_path=out_file)

    assert asm_path.exists()
    assert seen["requested_target_name"] is None
    assert seen["target_calls"] == 1


def test_cli_default_checked_path_can_omit_runtime_trace_calls(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        class Box {
            value: i64;
        }

        fn make() -> Box {
            return Box(0);
        }

        fn main() -> i64 {
            var box: Box = make();
            return box.value;
        }
        """,
    )

    asm_path = compile_to_asm(
        monkeypatch,
        entry,
        project_root=tmp_path,
        out_path=tmp_path / "out.s",
        extra_args=["--omit-runtime-trace"],
    )
    asm = asm_path.read_text(encoding="utf-8")

    assert "rt_trace_push" not in asm
    assert "rt_trace_pop" not in asm
    assert "rt_trace_set_location" not in asm
