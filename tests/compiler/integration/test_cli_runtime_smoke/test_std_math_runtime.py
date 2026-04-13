from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, install_std_modules, write


def test_cli_runtime_smoke_supports_std_math(tmp_path: Path, monkeypatch) -> None:
    install_std_modules(tmp_path, ["math"])
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        import std.math as math;

        fn main() -> i64 {
            if math.abs(-7.5) != 7.5 {
                return 1;
            }
            if math.pow(2.0, 5.0) != 32.0 {
                return 2;
            }
            if !math.is_nan(math.sqrt(-1.0)) {
                return 3;
            }
            if !math.is_infinite(math.log(0.0)) {
                return 4;
            }
            return 0;
        }
        """,
    )

    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0