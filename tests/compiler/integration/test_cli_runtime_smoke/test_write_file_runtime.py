from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, install_std_modules, write


def test_cli_runtime_smoke_supports_std_io_write_file(tmp_path: Path, monkeypatch) -> None:
    install_std_modules(tmp_path, ["io", "str", "error", "vec", "lang", "object"])
    output_path = tmp_path / "written.txt"
    entry = tmp_path / "main.nif"
    write(
        entry,
        f"""
        import std.io as io;
        import std.str;

        fn main() -> i64 {{
            io.write_file("{output_path}", "alpha\\nbeta\\n");

            var read_back: Str = io.read_file("{output_path}");
            if !read_back.equals("alpha\\nbeta\\n") {{
                return 1;
            }}

            return 0;
        }}
        """,
    )

    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0
    assert output_path.read_bytes() == b"alpha\nbeta\n"