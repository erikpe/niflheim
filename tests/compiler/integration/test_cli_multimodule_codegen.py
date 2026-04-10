from __future__ import annotations

from pathlib import Path

from compiler.codegen.symbols import mangle_function_symbol, mangle_method_symbol, mangle_constructor_symbol
from tests.compiler.integration.helpers import compile_to_asm, run_cli, write_project


def test_cli_codegen_uses_program_resolution_for_multimodule_build(tmp_path: Path, monkeypatch) -> None:
    write_project(
        tmp_path,
        {
            "util.nif": """
            export class Box {
                value: i64;
            }
            """,
            "main.nif": """
            import util;

            fn main() -> i64 {
                return 0;
            }
            """,
        },
    )

    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    rc = run_cli(monkeypatch, ["nifc", str(entry), "-o", str(out_file)])

    assert rc == 0
    assert out_file.exists()


def test_cli_codegen_imported_constructor_call_lowers(tmp_path: Path, monkeypatch) -> None:
    write_project(
        tmp_path,
        {
            "util.nif": """
            export class Box {
                value: i64;
            }
            """,
            "main.nif": """
            import util;

            fn main() -> i64 {
                var b: util.Box = util.Box(7);
                if b == null {
                    return 1;
                }
                return 0;
            }
            """,
        },
    )

    entry = tmp_path / "main.nif"
    out_file = compile_to_asm(monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s")
    asm = out_file.read_text(encoding="utf-8")
    assert f"    call {mangle_constructor_symbol('util::Box')}" in asm


def test_cli_codegen_imported_static_method_call_lowers(tmp_path: Path, monkeypatch) -> None:
    write_project(
        tmp_path,
        {
            "util.nif": """
            export class Math {
                static fn add(value: i64) -> i64 {
                    return value + 1;
                }
            }
            """,
            "main.nif": """
            import util;

            fn main() -> i64 {
                return util.Math.add(7);
            }
            """,
        },
    )

    entry = tmp_path / "main.nif"
    out_file = compile_to_asm(monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s")
    asm = out_file.read_text(encoding="utf-8")

    assert f"    call {mangle_method_symbol('util::Math', 'add')}" in asm


def test_cli_codegen_keeps_duplicate_leaf_class_constructors_and_methods_distinct(tmp_path: Path, monkeypatch) -> None:
    write_project(
        tmp_path,
        {
            "left.nif": """
            export class Key {
                value: i64;

                fn read() -> i64 {
                    return __self.value;
                }
            }
            """,
            "right.nif": """
            export class Key {
                value: i64;

                fn read() -> i64 {
                    return __self.value + 1;
                }
            }
            """,
            "main.nif": """
            import left as left_lib;
            import right as right_lib;

            fn main() -> i64 {
                return left_lib.Key(20).read() + right_lib.Key(21).read();
            }
            """,
        },
    )

    entry = tmp_path / "main.nif"
    out_file = compile_to_asm(monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s")
    asm = out_file.read_text(encoding="utf-8")

    assert f"    call {mangle_constructor_symbol('left::Key')}" in asm
    assert f"    call {mangle_constructor_symbol('right::Key')}" in asm
    assert f"    call {mangle_method_symbol('left::Key', 'read')}" in asm
    assert f"    call {mangle_method_symbol('right::Key', 'read')}" in asm


def test_cli_codegen_resolves_nested_project_root_imports(tmp_path: Path, monkeypatch) -> None:
    write_project(
        tmp_path,
        {
            "lib/math.nif": """
            export fn add(a: i64, b: i64) -> i64 {
                return a + b;
            }
            """,
            "app/main.nif": """
            import lib.math;

            fn main() -> i64 {
                return lib.math.add(20, 22);
            }
            """,
        },
    )

    entry = tmp_path / "app" / "main.nif"
    out_file = compile_to_asm(monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s")
    asm = out_file.read_text(encoding="utf-8")

    assert f'    call {mangle_function_symbol(("lib", "math"), "add")}' in asm


def test_cli_codegen_keeps_distinct_imported_helper_functions_by_canonical_label(tmp_path: Path, monkeypatch) -> None:
    write_project(
        tmp_path,
        {
            "left/math.nif": """
            export fn helper() -> i64 {
                return 20;
            }
            """,
            "right/math.nif": """
            export fn helper() -> i64 {
                return 22;
            }
            """,
            "app/main.nif": """
            import left.math as left_math;
            import right.math as right_math;

            fn main() -> i64 {
                return left_math.helper() + right_math.helper();
            }
            """,
        },
    )

    entry = tmp_path / "app" / "main.nif"
    out_file = compile_to_asm(monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s")
    asm = out_file.read_text(encoding="utf-8")

    assert f'    call {mangle_function_symbol(("left", "math"), "helper")}' in asm
    assert f'    call {mangle_function_symbol(("right", "math"), "helper")}' in asm


def test_cli_codegen_entry_module_main_keeps_abi_entrypoint_while_other_main_stays_canonical(
    tmp_path: Path, monkeypatch
) -> None:
    write_project(
        tmp_path,
        {
            "tools/worker.nif": """
            export fn main() -> i64 {
                return 41;
            }
            """,
            "app/main.nif": """
            import tools.worker as worker;

            fn main() -> i64 {
                return worker.main() + 1;
            }
            """,
        },
    )

    entry = tmp_path / "app" / "main.nif"
    out_file = compile_to_asm(monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s")
    asm = out_file.read_text(encoding="utf-8")

    assert ".globl main" in asm
    assert "main:" in asm
    assert f'{mangle_function_symbol(("app", "main"), "main")}:' in asm
    assert f'{mangle_function_symbol(("tools", "worker"), "main")}:' in asm
    assert f'    call {mangle_function_symbol(("tools", "worker"), "main")}' in asm
