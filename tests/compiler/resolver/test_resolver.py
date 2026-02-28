from __future__ import annotations

from pathlib import Path

import pytest

from compiler.resolver import ResolveError, resolve_program


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_resolve_program_builds_module_graph_and_symbol_tables(tmp_path: Path) -> None:
    _write(
        tmp_path / "math_utils.nif",
        """
        export fn gcd(a: i64, b: i64) -> i64 {
            return a;
        }

        fn hidden() -> unit {
            return;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import math_utils;

        fn main() -> unit {
            math_utils.gcd(10, 5);
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)

    assert program.entry_module == ("main",)
    assert set(program.modules.keys()) == {("main",), ("math_utils",)}
    math_module = program.modules[("math_utils",)]
    assert "gcd" in math_module.exported_symbols
    assert "hidden" not in math_module.exported_symbols


def test_resolve_program_rejects_access_to_non_exported_member(tmp_path: Path) -> None:
    _write(
        tmp_path / "math_utils.nif",
        """
        export fn gcd(a: i64, b: i64) -> i64 {
            return a;
        }

        fn hidden() -> unit {
            return;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import math_utils;

        fn main() -> unit {
            math_utils.hidden();
            return;
        }
        """,
    )

    with pytest.raises(ResolveError) as error:
        resolve_program(tmp_path / "main.nif", project_root=tmp_path)

    assert "has no exported member 'hidden'" in str(error.value)


def test_resolve_program_supports_export_import_reexport_chain(tmp_path: Path) -> None:
    _write(
        tmp_path / "util" / "math.nif",
        """
        export fn gcd(a: i64, b: i64) -> i64 {
            return a;
        }
        """,
    )
    _write(
        tmp_path / "lib.nif",
        """
        export import util.math;

        fn local_only() -> unit {
            return;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import lib;

        fn main() -> unit {
            lib.math.gcd(10, 5);
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    assert ("util", "math") in program.modules


def test_resolve_program_detects_duplicate_declarations(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn foo() -> unit {
            return;
        }

        class foo {
            value: i64;
        }
        """,
    )

    with pytest.raises(ResolveError) as error:
        resolve_program(tmp_path / "main.nif", project_root=tmp_path)

    assert "Duplicate declaration 'foo'" in str(error.value)


def test_resolve_program_reports_missing_module(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        import does.not_exist;

        fn main() -> unit {
            return;
        }
        """,
    )

    with pytest.raises(ResolveError) as error:
        resolve_program(tmp_path / "main.nif", project_root=tmp_path)

    assert "Module 'does.not_exist' not found" in str(error.value)
