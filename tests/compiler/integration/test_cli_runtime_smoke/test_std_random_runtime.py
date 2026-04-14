from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, install_std_modules, write


def test_cli_runtime_smoke_supports_std_random(tmp_path: Path, monkeypatch) -> None:
    install_std_modules(tmp_path, ["random", "error", "str", "lang", "object", "vec"])
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        import std.random;

        fn main() -> i64 {
            var left: Random = Random(42u);
            var right: Random = Random(42u);

            if left.next_u64() != right.next_u64() {
                return 1;
            }
            if left.next_bounded(10u) >= 10u {
                return 2;
            }
            var value: i64 = left.randint(-3, 5);
            if value < -3 || value > 5 {
                return 3;
            }

            return 0;
        }
        """,
    )

    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0