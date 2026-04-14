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


def test_resolve_program_exports_interface_symbols(tmp_path: Path) -> None:
    _write(
        tmp_path / "contracts.nif",
        """
        export interface Hashable {
            fn hash_code() -> u64;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import contracts;

        fn main() -> unit {
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    contracts_module = program.modules[("contracts",)]

    assert "Hashable" in contracts_module.exported_symbols
    assert contracts_module.exported_symbols["Hashable"].kind == "interface"


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
        export import util.math as math;

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


def test_resolve_program_supports_explicit_reexport_path_alias(tmp_path: Path) -> None:
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
        export import util.math as tools.calc;
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import lib;

        fn main() -> unit {
            lib.tools.calc.gcd(10, 5);
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    lib_module = program.modules[("lib",)]

    assert lib_module.exported_imports[0].bind_path == ("tools", "calc")
    assert lib_module.exported_imports[0].module_path == ("util", "math")


def test_resolve_program_supports_local_bind_path_for_plain_import(tmp_path: Path) -> None:
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
        import util.math as tools.calc;

        export fn local_score() -> i64 {
            return tools.calc.gcd(10, 5);
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import lib;

        fn main() -> unit {
            lib.local_score();
            return;
        }
        """,
    )

    resolve_program(tmp_path / "main.nif", project_root=tmp_path)


def test_resolve_program_supports_local_root_flatten_for_plain_import(tmp_path: Path) -> None:
    _write(
        tmp_path / "util" / "math.nif",
        """
        export fn gcd(a: i64, b: i64) -> i64 {
            return a + b;
        }
        """,
    )
    _write(
        tmp_path / "api.nif",
        """
        export import util.math as math;

        export fn twice(value: i64) -> i64 {
            return value * 2;
        }
        """,
    )
    _write(
        tmp_path / "lib.nif",
        """
        import api as .;

        export fn local_score() -> i64 {
            return math.gcd(19, 23) + twice(0);
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import lib;

        fn main() -> unit {
            lib.local_score();
            return;
        }
        """,
    )

    resolve_program(tmp_path / "main.nif", project_root=tmp_path)


def test_resolve_program_supports_root_flatten_reexport_surface(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export interface Hashable {
            fn hash_code() -> u64;
        }

        export class Key implements Hashable {
            seed: u64;

            fn hash_code() -> u64 {
                return __self.seed + 100u;
            }
        }

        export fn score(a: i64, b: i64) -> i64 {
            return a + b;
        }
        """,
    )
    _write(
        tmp_path / "lib.nif",
        """
        export import util as .;
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import lib;

        fn main() -> unit {
            lib.score(19, 23);
            var key: Obj = lib.Key(7u);
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    lib_module = program.modules[("lib",)]

    assert lib_module.exported_symbols["score"].owner_module_path == ("util",)
    assert lib_module.exported_symbols["Key"].owner_module_path == ("util",)
    assert lib_module.exported_symbols["Hashable"].owner_module_path == ("util",)


def test_resolve_program_rejects_conflicting_root_flatten_reexports(tmp_path: Path) -> None:
    _write(
        tmp_path / "left.nif",
        """
        export fn clash() -> i64 {
            return 1;
        }
        """,
    )
    _write(
        tmp_path / "right.nif",
        """
        export fn clash() -> i64 {
            return 2;
        }
        """,
    )
    _write(
        tmp_path / "lib.nif",
        """
        export import left as .;
        export import right as .;
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import lib;

        fn main() -> unit {
            return;
        }
        """,
    )

    with pytest.raises(ResolveError) as error:
        resolve_program(tmp_path / "main.nif", project_root=tmp_path)

    assert "Duplicate exported symbol 'clash'" in str(error.value)


def test_resolve_program_rejects_plain_root_flatten_import_conflicting_with_local_definition(tmp_path: Path) -> None:
    _write(
        tmp_path / "dep.nif",
        """
        export fn clash() -> i64 {
            return 1;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import dep as .;

        fn clash() -> i64 {
            return 2;
        }

        fn main() -> unit {
            return;
        }
        """,
    )

    with pytest.raises(ResolveError) as error:
        resolve_program(tmp_path / "main.nif", project_root=tmp_path)

    assert "Duplicate imported symbol 'clash'" in str(error.value)


def test_resolve_program_rejects_root_flatten_reexport_conflicting_with_local_definition(tmp_path: Path) -> None:
    _write(
        tmp_path / "dep.nif",
        """
        export fn clash() -> i64 {
            return 1;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        export import dep as .;

        fn clash() -> i64 {
            return 2;
        }

        fn main() -> unit {
            return;
        }
        """,
    )

    with pytest.raises(ResolveError) as error:
        resolve_program(tmp_path / "main.nif", project_root=tmp_path)

    assert "Duplicate exported symbol 'clash'" in str(error.value)


def test_resolve_program_rejects_import_bind_path_conflicting_with_local_definition(tmp_path: Path) -> None:
    _write(
        tmp_path / "dep.nif",
        """
        export fn clash() -> i64 {
            return 1;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import dep as tools.calc;

        fn tools() -> i64 {
            return 2;
        }

        fn main() -> unit {
            return;
        }
        """,
    )

    with pytest.raises(ResolveError) as error:
        resolve_program(tmp_path / "main.nif", project_root=tmp_path)

    assert "Duplicate import path 'tools.calc'" in str(error.value)


def test_resolve_program_rejects_export_import_bind_path_conflicting_with_local_definition(tmp_path: Path) -> None:
    _write(
        tmp_path / "dep.nif",
        """
        export fn clash() -> i64 {
            return 1;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        export import dep as tools.calc;

        fn tools() -> i64 {
            return 2;
        }

        fn main() -> unit {
            return;
        }
        """,
    )

    with pytest.raises(ResolveError) as error:
        resolve_program(tmp_path / "main.nif", project_root=tmp_path)

    assert "Duplicate exported module 'tools.calc'" in str(error.value)


def test_resolve_program_supports_import_bind_path_qualification(tmp_path: Path) -> None:
    _write(
        tmp_path / "util" / "math.nif",
        """
        export fn gcd(a: i64, b: i64) -> i64 {
            return a;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util.math as math;

        fn main() -> unit {
            math.gcd(10, 5);
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)

    main_module = program.modules[("main",)]
    imported_math = next(import_info for import_info in main_module.imports.values() if import_info.module_path == ("util", "math"))
    assert imported_math.bind_path == ("math",)
    assert main_module.bound_imports[0].bind_path == ("math",)


def test_resolve_program_allows_dotted_imports_with_same_leaf_name_under_strict_qualification(tmp_path: Path) -> None:
    _write(
        tmp_path / "left" / "math.nif",
        """
        export fn lhs() -> i64 {
            return 1;
        }
        """,
    )
    _write(
        tmp_path / "right" / "math.nif",
        """
        export fn rhs() -> i64 {
            return 2;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import left.math;
        import right.math;

        fn main() -> unit {
            left.math.lhs();
            right.math.rhs();
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)

    assert sorted(program.modules) == [("left", "math"), ("main",), ("right", "math")]


def test_resolve_program_supports_full_path_reexport_chain_without_leaf_alias_fallback(tmp_path: Path) -> None:
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
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import lib;

        fn main() -> unit {
            lib.util.math.gcd(10, 5);
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
