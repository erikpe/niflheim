from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden import runner


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_discover_tests_uses_spec_files_as_the_source_of_truth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    golden_root = tmp_path / "golden"
    _write(golden_root / "suite" / "test_alpha.nif", "fn main() -> i64 { return 0; }\n")
    _write(
        golden_root / "suite" / "test_alpha_spec.yaml",
        "tests:\n  - mode: run\n    name: alpha\n    src_file: test_alpha.nif\n    runs:\n      - name: ok\n",
    )
    _write(golden_root / "suite" / "test_orphan.nif", "fn main() -> i64 { return 0; }\n")

    monkeypatch.setattr(runner, "GOLDEN_ROOT", golden_root)

    tests = runner._discover_tests(None)

    assert [test.source_path.relative_to(golden_root).as_posix() for test in tests] == ["suite/test_alpha.nif"]
    assert [test.spec_path.relative_to(golden_root).as_posix() for test in tests] == ["suite/test_alpha_spec.yaml"]
    assert [test.name for test in tests] == ["alpha"]


def test_discover_tests_requires_source_next_to_matching_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    golden_root = tmp_path / "golden"
    _write(
        golden_root / "suite" / "test_missing_spec.yaml",
        "tests:\n  - mode: run\n    name: missing\n    src_file: test_missing.nif\n    runs:\n      - name: ok\n",
    )

    monkeypatch.setattr(runner, "GOLDEN_ROOT", golden_root)

    with pytest.raises(ValueError, match="missing source"):
        runner._discover_tests(None)


def test_discover_tests_filter_matches_source_and_spec_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    golden_root = tmp_path / "golden"
    _write(golden_root / "suite" / "test_alpha.nif", "fn main() -> i64 { return 0; }\n")
    _write(
        golden_root / "suite" / "test_alpha_spec.yaml",
        "tests:\n  - mode: run\n    name: alpha\n    src_file: test_alpha.nif\n    runs:\n      - name: ok\n",
    )

    monkeypatch.setattr(runner, "GOLDEN_ROOT", golden_root)

    by_source = runner._discover_tests("suite/test_alpha.nif")
    by_spec = runner._discover_tests("suite/test_alpha_spec.yaml")

    assert [test.source_path.name for test in by_source] == ["test_alpha.nif"]
    assert [test.source_path.name for test in by_spec] == ["test_alpha.nif"]


def test_discover_tests_supports_multiple_sources_in_one_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    golden_root = tmp_path / "golden"
    _write(golden_root / "suite" / "test_alpha.nif", "fn main() -> i64 { return 0; }\n")
    _write(golden_root / "suite" / "test_beta.nif", "fn main() -> i64 { return 0; }\n")
    _write(
        golden_root / "suite" / "test_combo_spec.yaml",
        "tests:\n"
        "  - mode: run\n"
        "    name: alpha\n"
        "    src_file: test_alpha.nif\n"
        "    runs:\n"
        "      - name: ok_alpha\n"
        "  - mode: run\n"
        "    name: beta\n"
        "    src_file: test_beta.nif\n"
        "    runs:\n"
        "      - name: ok_beta\n",
    )

    monkeypatch.setattr(runner, "GOLDEN_ROOT", golden_root)

    tests = runner._discover_tests(None)

    assert [(test.name, test.source_path.name) for test in tests] == [
        ("alpha", "test_alpha.nif"),
        ("beta", "test_beta.nif"),
    ]


def test_discover_tests_supports_compile_fail_mode_without_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    golden_root = tmp_path / "golden"
    _write(golden_root / "suite" / "test_bad_cast.nif", "fn main() -> i64 { return 0; }\n")
    _write(
        golden_root / "suite" / "test_compile_spec.yaml",
        "tests:\n"
        "  - mode: compile-fail\n"
        "    name: bad_cast\n"
        "    src_file: test_bad_cast.nif\n"
        "    compile_error_match: boom\n",
    )

    monkeypatch.setattr(runner, "GOLDEN_ROOT", golden_root)

    tests = runner._discover_tests(None)

    assert len(tests) == 1
    assert tests[0].mode == "compile-fail"
    assert tests[0].runs == []
    assert tests[0].compile_error_match == "boom"
