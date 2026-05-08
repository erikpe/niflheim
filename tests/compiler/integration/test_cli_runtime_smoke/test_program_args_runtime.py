from __future__ import annotations

from pathlib import Path
import subprocess

from tests.compiler.integration.helpers import assemble_host_executable, compile_to_asm, install_std_modules, write


def test_cli_runtime_smoke_short_circuits_boolean_and_with_guarded_array_index(
    tmp_path: Path, monkeypatch
) -> None:
    install_std_modules(tmp_path, ["io", "str", "lang", "object", "vec", "error"])
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        import std.io;
        import std.str;

        fn main() -> i64 {
            var args: Str[] = read_program_args();
            if args.len() > 2u && args[2].compare_to("len") == 0 {
                return 1;
            }
            if args[1].compare_to("alpha") != 0 {
                return 2;
            }
            return 0;
        }
        """,
    )

    asm_path = compile_to_asm(
        monkeypatch,
        entry,
        project_root=tmp_path,
        out_path=tmp_path / "out.s",
    )
    exe_path = assemble_host_executable(asm_path, exe_path=tmp_path / "out")
    run = subprocess.run([str(exe_path), "alpha"], check=False, capture_output=True, text=True)

    assert run.returncode == 0, run.stderr