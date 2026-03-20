from __future__ import annotations

from pathlib import Path

import pytest

from compiler.codegen.linker import build_codegen_program, require_main_function
from compiler.resolver import resolve_program
from compiler.semantic.lowering import lower_program


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_build_codegen_program_orders_non_entry_modules_before_entry(tmp_path: Path) -> None:
    _write(
        tmp_path / "zeta.nif",
        """
        export class Zed {
            value: i64;
        }

        export fn helper_z() -> i64 {
            return 1;
        }
        """,
    )
    _write(
        tmp_path / "alpha.nif",
        """
        export class Alpha {
            value: i64;
        }

        export fn helper_a() -> i64 {
            return 2;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import zeta;
        import alpha;

        class MainBox {
            value: i64;
        }

        fn main() -> i64 {
            return helper_a() + helper_z();
        }
        """,
    )

    program = build_codegen_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))

    assert [module.module_path for module in program.ordered_modules] == [("alpha",), ("zeta",), ("main",)]
    assert [cls.class_id.name for cls in program.classes] == ["Alpha", "Zed", "MainBox"]
    assert [fn.function_id.name for fn in program.functions] == ["helper_a", "helper_z", "main"]


def test_build_codegen_program_prefers_body_over_extern_duplicate(tmp_path: Path) -> None:
    _write(
        tmp_path / "decls.nif",
        """
        export extern fn helper() -> i64;
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import decls;

        fn helper() -> i64 {
            return 7;
        }

        fn main() -> i64 {
            return helper();
        }
        """,
    )

    program = build_codegen_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))

    helper = next(fn for fn in program.functions if fn.function_id.name == "helper")
    assert helper.function_id.module_path == ("main",)
    assert helper.body is not None
    assert helper.is_extern is False


def test_build_codegen_program_preserves_module_interfaces_for_codegen_metadata(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export interface Hashable {
            fn hash_code() -> u64;
        }

        export class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    program = build_codegen_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))

    util_module = next(module for module in program.ordered_modules if module.module_path == ("util",))
    assert [interface.interface_id.name for interface in util_module.interfaces] == ["Hashable"]
    assert util_module.interfaces[0].methods[0].method_id.name == "hash_code"
    util_key = next(cls for cls in program.classes if cls.class_id.module_path == ("util",) and cls.class_id.name == "Key")
    assert util_key.implemented_interfaces == [util_module.interfaces[0].interface_id]


def test_build_codegen_program_rejects_duplicate_class_symbols(tmp_path: Path) -> None:
    _write(
        tmp_path / "left.nif",
        """
        export class Box {
            value: i64;
        }
        """,
    )
    _write(
        tmp_path / "right.nif",
        """
        export class Box {
            value: i64;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import left;
        import right;

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))

    with pytest.raises(ValueError, match="Duplicate class symbol 'Box'"):
        build_codegen_program(semantic)


def test_require_main_function_validates_entrypoint(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> unit {
            return;
        }
        """,
    )

    program = build_codegen_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))

    with pytest.raises(ValueError, match="Invalid main signature: expected return type 'i64'"):
        require_main_function(program)
