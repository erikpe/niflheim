from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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
    assert tests[0].build_args == []


def test_discover_tests_parses_build_args(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    golden_root = tmp_path / "golden"
    _write(golden_root / "suite" / "test_alpha.nif", "fn main() -> i64 { return 0; }\n")
    _write(
        golden_root / "suite" / "test_alpha_spec.yaml",
        "tests:\n"
        "  - mode: run\n"
        "    name: alpha\n"
        "    src_file: test_alpha.nif\n"
        "    build_args: [\"--skip-optimize\", \"--omit-runtime-trace\"]\n"
        "    runs:\n"
        "      - name: ok\n",
    )

    monkeypatch.setattr(runner, "GOLDEN_ROOT", golden_root)

    tests = runner._discover_tests(None)

    assert len(tests) == 1
    assert tests[0].build_args == ["--skip-optimize", "--omit-runtime-trace"]


def test_build_output_path_flattens_spec_path_and_test_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    golden_root = tmp_path / "golden"
    build_root = tmp_path / "build"
    top_level = runner.GoldenTest(
        name="inheritance",
        mode="run",
        source_path=golden_root / "lang" / "test_inheritance.nif",
        spec_path=golden_root / "lang" / "test_inheritance_spec.yaml",
        runs=[],
        compile_error_match=None,
        build_args=[],
    )
    nested = runner.GoldenTest(
        name="case_nested",
        mode="run",
        source_path=golden_root / "lang" / "test_inheritance" / "test_inheritance.nif",
        spec_path=golden_root / "lang" / "test_inheritance" / "test_inheritance_spec.yaml",
        runs=[],
        compile_error_match=None,
        build_args=[],
    )

    monkeypatch.setattr(runner, "GOLDEN_ROOT", golden_root)
    monkeypatch.setattr(runner, "BUILD_ROOT", build_root)

    assert runner._build_output_path(top_level) == (
        build_root / runner.BUILD_CASES_DIRNAME / "lang__test_inheritance_spec__inheritance"
    )
    assert runner._build_output_path(nested) == (
        build_root / runner.BUILD_CASES_DIRNAME / "lang__test_inheritance__test_inheritance_spec__case_nested"
    )


def test_build_output_path_distinguishes_multiple_tests_for_same_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    golden_root = tmp_path / "golden"
    build_root = tmp_path / "build"
    source_path = golden_root / "vm_benchmark" / "test_vm_benchmark.nif"
    spec_path = golden_root / "vm_benchmark" / "test_vm_benchmark_spec.yaml"

    monkeypatch.setattr(runner, "GOLDEN_ROOT", golden_root)
    monkeypatch.setattr(runner, "BUILD_ROOT", build_root)

    traced = runner.GoldenTest(
        name="test_vm_benchmark",
        mode="run",
        source_path=source_path,
        spec_path=spec_path,
        runs=[],
        compile_error_match=None,
        build_args=[],
    )
    no_trace = runner.GoldenTest(
        name="test_vm_benchmark_no_trace",
        mode="run",
        source_path=source_path,
        spec_path=spec_path,
        runs=[],
        compile_error_match=None,
        build_args=["--omit-runtime-trace"],
    )

    assert runner._build_output_path(traced) != runner._build_output_path(no_trace)


def test_compile_run_test_passes_prebuilt_runtime_archive_to_build_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    golden_root = repo_root / "tests" / "golden"
    build_root = repo_root / "build" / "golden"
    source_path = golden_root / "suite" / "test_alpha.nif"
    spec_path = golden_root / "suite" / "test_alpha_spec.yaml"
    runtime_archive = build_root / runner.BUILD_RUNTIME_DIRNAME / "run_123" / "libruntime.a"

    _write(source_path, "fn main() -> i64 { return 0; }\n")
    _write(spec_path, "tests:\n  - mode: run\n    name: alpha\n    src_file: test_alpha.nif\n    runs:\n      - name: ok\n")

    monkeypatch.setattr(runner, "REPO_ROOT", repo_root)
    monkeypatch.setattr(runner, "GOLDEN_ROOT", golden_root)
    monkeypatch.setattr(runner, "BUILD_ROOT", build_root)

    captured: dict[str, object] = {}

    def _fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(runner.subprocess, "run", _fake_run)

    test = runner.GoldenTest(
        name="alpha",
        mode="run",
        source_path=source_path,
        spec_path=spec_path,
        runs=[],
        compile_error_match=None,
        build_args=[],
    )

    ok, error, output_path = runner._compile_run_test(test, runtime_archive)

    assert ok is True
    assert error is None
    assert output_path == build_root / runner.BUILD_CASES_DIRNAME / "suite__test_alpha_spec__alpha"
    env = captured["env"]
    assert isinstance(env, dict)
    assert env[runner.PREBUILT_RUNTIME_ENV_VAR] == str(runtime_archive)


def test_compile_run_test_forwards_build_args_to_build_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    golden_root = repo_root / "tests" / "golden"
    build_root = repo_root / "build" / "golden"
    source_path = golden_root / "suite" / "test_alpha.nif"
    spec_path = golden_root / "suite" / "test_alpha_spec.yaml"

    _write(source_path, "fn main() -> i64 { return 0; }\n")
    _write(spec_path, "tests:\n  - mode: run\n    name: alpha\n    src_file: test_alpha.nif\n    runs:\n      - name: ok\n")

    monkeypatch.setattr(runner, "REPO_ROOT", repo_root)
    monkeypatch.setattr(runner, "GOLDEN_ROOT", golden_root)
    monkeypatch.setattr(runner, "BUILD_ROOT", build_root)

    captured: dict[str, object] = {}

    def _fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(runner.subprocess, "run", _fake_run)

    test = runner.GoldenTest(
        name="alpha",
        mode="run",
        source_path=source_path,
        spec_path=spec_path,
        runs=[],
        compile_error_match=None,
        build_args=["--skip-optimize", "--omit-runtime-trace"],
    )

    ok, error, _output_path = runner._compile_run_test(test)

    assert ok is True
    assert error is None
    assert captured["cmd"] == [
        str(repo_root / "scripts" / "build.sh"),
        "tests/golden/suite/test_alpha.nif",
        "build/golden/__cases__/suite__test_alpha_spec__alpha",
        "--",
        "--skip-optimize",
        "--omit-runtime-trace",
    ]


def test_compile_fail_test_forwards_build_args_to_compiler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    golden_root = repo_root / "tests" / "golden"
    build_root = repo_root / "build" / "golden"
    source_path = golden_root / "suite" / "test_bad.nif"
    spec_path = golden_root / "suite" / "test_bad_spec.yaml"

    _write(source_path, "fn main() -> i64 { return 0; }\n")
    _write(spec_path, "tests:\n  - mode: compile-fail\n    name: bad\n    src_file: test_bad.nif\n    compile_error_match: boom\n")

    monkeypatch.setattr(runner, "REPO_ROOT", repo_root)
    monkeypatch.setattr(runner, "GOLDEN_ROOT", golden_root)
    monkeypatch.setattr(runner, "BUILD_ROOT", build_root)

    captured: dict[str, object] = {}

    def _fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=1, stderr="boom", stdout="")

    monkeypatch.setattr(runner.subprocess, "run", _fake_run)

    test = runner.GoldenTest(
        name="bad",
        mode="compile-fail",
        source_path=source_path,
        spec_path=spec_path,
        runs=[],
        compile_error_match="boom",
        build_args=["--skip-optimize"],
    )

    ok, error = runner._compile_fail_test(test)

    assert ok is True
    assert error is None
    assert captured["cmd"] == [
        "python3",
        "-m",
        "compiler.main",
        str(source_path),
        "-o",
        str(build_root / runner.BUILD_CASES_DIRNAME / "suite__test_bad_spec__bad.s"),
        "--project-root",
        str(repo_root),
        "--skip-optimize",
    ]


def test_main_prints_one_row_per_spec_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    repo_root = tmp_path / "repo"
    golden_root = repo_root / "tests" / "golden"
    spec_path = golden_root / "vm_benchmark" / "test_vm_benchmark_spec.yaml"
    source_path = golden_root / "vm_benchmark" / "test_vm_benchmark.nif"

    monkeypatch.setattr(runner, "REPO_ROOT", repo_root)
    monkeypatch.setattr(runner, "GOLDEN_ROOT", golden_root)

    tests = [
        runner.GoldenTest(
            name="test_vm_benchmark",
            mode="run",
            source_path=source_path,
            spec_path=spec_path,
            runs=[runner.RunCase("slice1_minimal_output", runner.RunInput([], None), runner.RunExpect(None, None, None, None))],
            compile_error_match=None,
            build_args=[],
        ),
        runner.GoldenTest(
            name="test_vm_benchmark_no_trace",
            mode="run",
            source_path=source_path,
            spec_path=spec_path,
            runs=[runner.RunCase("slice1_minimal_output", runner.RunInput([], None), runner.RunExpect(None, None, None, None))],
            compile_error_match=None,
            build_args=["--omit-runtime-trace"],
        ),
    ]

    def _fake_run_spec(
        spec_path_arg: Path,
        spec_tests: list[runner.GoldenTest],
        runtime_archive: Path | None = None,
        *,
        extra_build_args: list[str] | None = None,
    ) -> runner.SpecResult:
        assert spec_path_arg == spec_path
        assert spec_tests == tests
        assert extra_build_args == []
        return runner.SpecResult(
            spec_path=spec_path,
            test_results=[
                runner.TestResult(
                    name=test.name,
                    mode=test.mode,
                    spec_path=test.spec_path,
                    source_path=test.source_path,
                    compile_ok=True,
                    compile_error=None,
                    run_results=[runner.RunResult(name="slice1_minimal_output", ok=True, details=[])],
                )
                for test in spec_tests
            ],
        )

    monkeypatch.setattr(runner, "_discover_tests", lambda filter_glob: tests)
    monkeypatch.setattr(runner, "_prepare_runtime_archive", lambda: (True, None, repo_root / "build" / "runtime.a"))
    monkeypatch.setattr(runner, "_run_spec", _fake_run_spec)
    monkeypatch.setattr(
        runner.sys,
        "argv",
        ["golden-runner", "--jobs", "1", "--filter", "vm_benchmark/test_vm_benchmark_spec.yaml"],
    )

    exit_code = runner.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.splitlines() == [
        "PASS tests/golden/vm_benchmark/test_vm_benchmark_spec.yaml",
        "golden: 1/1 spec files passed; 2 runs total",
    ]


def test_main_prints_per_run_rows_for_run_and_compile_fail_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    repo_root = tmp_path / "repo"
    golden_root = repo_root / "tests" / "golden"
    spec_path = golden_root / "vm_benchmark" / "test_vm_benchmark_spec.yaml"
    source_path = golden_root / "vm_benchmark" / "test_vm_benchmark.nif"
    bad_source_path = golden_root / "vm_benchmark" / "wrong_gazonk.nif"

    monkeypatch.setattr(runner, "REPO_ROOT", repo_root)
    monkeypatch.setattr(runner, "GOLDEN_ROOT", golden_root)

    tests = [
        runner.GoldenTest(
            name="test_vm_benchmark",
            mode="run",
            source_path=source_path,
            spec_path=spec_path,
            runs=[
                runner.RunCase("slice1_minimal_output", runner.RunInput([], None), runner.RunExpect(None, None, None, None)),
                runner.RunCase("arithmetic_mixer_output", runner.RunInput([], None), runner.RunExpect(None, None, None, None)),
            ],
            compile_error_match=None,
            build_args=[],
        ),
        runner.GoldenTest(
            name="wrong_gazonk_compile_error",
            mode="compile-fail",
            source_path=bad_source_path,
            spec_path=spec_path,
            runs=[],
            compile_error_match="boom",
            build_args=[],
        ),
    ]

    def _fake_run_spec(
        spec_path_arg: Path,
        spec_tests: list[runner.GoldenTest],
        runtime_archive: Path | None = None,
        *,
        extra_build_args: list[str] | None = None,
    ) -> runner.SpecResult:
        assert spec_path_arg == spec_path
        assert spec_tests == tests
        assert extra_build_args == []
        return runner.SpecResult(
            spec_path=spec_path,
            test_results=[
                runner.TestResult(
                    name=test.name,
                    mode=test.mode,
                    spec_path=test.spec_path,
                    source_path=test.source_path,
                    compile_ok=True,
                    compile_error=None,
                    run_results=[]
                    if test.mode == "compile-fail"
                    else [
                        runner.RunResult(name="slice1_minimal_output", ok=True, details=[]),
                        runner.RunResult(name="arithmetic_mixer_output", ok=True, details=[]),
                    ],
                )
                for test in spec_tests
            ],
        )

    monkeypatch.setattr(runner, "_discover_tests", lambda filter_glob: tests)
    monkeypatch.setattr(runner, "_prepare_runtime_archive", lambda: (True, None, repo_root / "build" / "runtime.a"))
    monkeypatch.setattr(runner, "_run_spec", _fake_run_spec)
    monkeypatch.setattr(runner.sys, "argv", ["golden-runner", "--jobs", "1", "--print-per-run"])

    exit_code = runner.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.splitlines() == [
        "PASS tests/golden/vm_benchmark/test_vm_benchmark_spec.yaml :: test_vm_benchmark :: slice1_minimal_output",
        "PASS tests/golden/vm_benchmark/test_vm_benchmark_spec.yaml :: test_vm_benchmark :: arithmetic_mixer_output",
        "PASS tests/golden/vm_benchmark/test_vm_benchmark_spec.yaml :: wrong_gazonk_compile_error",
        "golden: 1/1 spec files passed; 2 runs total",
    ]
