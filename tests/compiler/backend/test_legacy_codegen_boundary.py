from __future__ import annotations

import ast
from pathlib import Path

from compiler.codegen import LEGACY_TREEWALK_BACKEND_MODULES


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPILER_ROOT = REPO_ROOT / "compiler"


def _production_python_files() -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in COMPILER_ROOT.rglob("*.py")
            if path.parts[len(COMPILER_ROOT.parts)] != "codegen"
        )
    )


def _imported_module_names(file_path: Path) -> set[str]:
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom) or node.module is None or node.level != 0:
            continue
        imported.add(node.module)
        if node.module == "compiler.codegen":
            imported.update(f"compiler.codegen.{alias.name}" for alias in node.names)
    return imported


def test_production_modules_do_not_import_legacy_treewalk_codegen_modules() -> None:
    offenders: dict[str, tuple[str, ...]] = {}

    for file_path in _production_python_files():
        imported_modules = _imported_module_names(file_path)
        legacy_imports = tuple(sorted(imported_modules.intersection(LEGACY_TREEWALK_BACKEND_MODULES)))
        if legacy_imports:
            offenders[str(file_path.relative_to(REPO_ROOT))] = legacy_imports

    assert offenders == {}