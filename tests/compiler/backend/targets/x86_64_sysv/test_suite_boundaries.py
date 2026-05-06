from __future__ import annotations

from pathlib import Path


SUITE_ROOT = Path(__file__).resolve().parent
FORBIDDEN_SNIPPETS = (
    "tests.compiler.support.runtime_execution",
    "compile_native_and_run(",
    "compile_and_run(",
    "build_executable(",
    "run_executable(",
)


def test_x86_target_suite_does_not_import_native_runtime_helpers() -> None:
    python_files = sorted(path for path in SUITE_ROOT.glob("*.py") if path.name != Path(__file__).name)

    offenders: list[str] = []
    for path in python_files:
        text = path.read_text(encoding="utf-8")
        if any(snippet in text for snippet in FORBIDDEN_SNIPPETS):
            offenders.append(path.name)

    assert offenders == []