from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_native_and_run, install_std_modules, write


def test_cli_runtime_smoke_runs_std_string_literal_len(tmp_path: Path, monkeypatch) -> None:
    install_std_modules(tmp_path, ["str", "lang", "object", "vec", "error"])
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        import std.str;

        fn main() -> i64 {
            return (i64)"abc".len();
        }
        """,
    )

    run = compile_native_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 3, run.stderr


def test_cli_runtime_smoke_runs_qualified_imported_constructor_with_shadowed_local_class(
    tmp_path: Path, monkeypatch
) -> None:
    write(
        tmp_path / "main.nif",
        """
        import util.shadow as shadow;

        class Token {
            value: i64;

            fn read() -> i64 {
                return __self.value;
            }
        }

        fn main() -> i64 {
            return shadow.Token(11).read() + Token(7).read();
        }
        """,
    )
    write(
        tmp_path / "util/shadow.nif",
        """
        export class Token {
            value: i64;

            fn read() -> i64 {
                return __self.value;
            }
        }
        """,
    )

    run = compile_native_and_run(
        monkeypatch,
        tmp_path / "main.nif",
        project_root=tmp_path,
        out_path=tmp_path / "out.s",
        exe_path=tmp_path / "program",
    )

    assert run.returncode == 18, run.stderr


def test_cli_runtime_smoke_supports_string_helper_flow(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        class Str {
            static fn from_u8_array(value: u8[]) -> Str {
                return null;
            }
        }

        fn main() -> i64 {
            var value: Str = "phase-5";
            return 0;
        }
        """,
    )

    run = compile_native_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0, run.stderr