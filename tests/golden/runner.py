from __future__ import annotations

import argparse
import difflib
import fnmatch
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_ROOT = REPO_ROOT / "tests" / "golden"
BUILD_ROOT = REPO_ROOT / "build" / "golden"
BUILD_CASES_DIRNAME = "__cases__"
BUILD_RUNTIME_DIRNAME = "__runtime__"
PREBUILT_RUNTIME_ENV_VAR = "NIF_PREBUILT_RUNTIME"


@dataclass(frozen=True)
class RunInput:
    args: list[str]
    stdin: str | None


@dataclass(frozen=True)
class RunExpect:
    exit_code: int | None
    stdout: str | None
    stderr: str | None
    panic: str | None


@dataclass(frozen=True)
class RunCase:
    name: str
    run_input: RunInput
    expect: RunExpect


@dataclass(frozen=True)
class GoldenTest:
    name: str
    mode: str
    source_path: Path
    spec_path: Path
    runs: list[RunCase]
    compile_error_match: str | None
    build_args: list[str]


@dataclass(frozen=True)
class RunResult:
    name: str
    ok: bool
    details: list[str]


@dataclass(frozen=True)
class TestResult:
    name: str
    mode: str
    spec_path: Path
    source_path: Path
    compile_ok: bool
    compile_error: str | None
    run_results: list[RunResult]

    @property
    def ok(self) -> bool:
        if not self.compile_ok:
            return False
        return all(run.ok for run in self.run_results)


@dataclass(frozen=True)
class SpecResult:
    spec_path: Path
    test_results: list[TestResult]

    @property
    def ok(self) -> bool:
        return all(test.ok for test in self.test_results)


def _group_tests_by_spec(tests: list[GoldenTest]) -> list[tuple[Path, list[GoldenTest]]]:
    spec_order: list[Path] = []
    tests_by_spec: dict[Path, list[GoldenTest]] = {}
    for test in tests:
        if test.spec_path not in tests_by_spec:
            spec_order.append(test.spec_path)
            tests_by_spec[test.spec_path] = []
        tests_by_spec[test.spec_path].append(test)
    return [(spec_path, tests_by_spec[spec_path]) for spec_path in spec_order]


def _require_type(value: object, expected_type: type, label: str) -> None:
    if not isinstance(value, expected_type):
        raise ValueError(f"{label} must be {expected_type.__name__}")


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_input(raw: object, *, spec_path: Path, run_name: str) -> RunInput:
    if raw is None:
        return RunInput(args=[], stdin=None)

    _require_type(raw, dict, f"{spec_path}: run '{run_name}' input")
    input_obj: dict[str, object] = raw  # type: ignore[assignment]

    args_raw = input_obj.get("args", [])
    _require_type(args_raw, list, f"{spec_path}: run '{run_name}' input.args")
    args: list[str] = []
    for index, item in enumerate(args_raw):
        _require_type(item, str, f"{spec_path}: run '{run_name}' input.args[{index}]")
        args.append(item)

    stdin_raw = input_obj.get("stdin")
    stdin_file_raw = input_obj.get("stdin_file")
    if stdin_raw is not None and stdin_file_raw is not None:
        raise ValueError(f"{spec_path}: run '{run_name}' input.stdin and input.stdin_file are mutually exclusive")

    if stdin_raw is not None:
        _require_type(stdin_raw, str, f"{spec_path}: run '{run_name}' input.stdin")
        return RunInput(args=args, stdin=stdin_raw)

    if stdin_file_raw is not None:
        _require_type(stdin_file_raw, str, f"{spec_path}: run '{run_name}' input.stdin_file")
        stdin_path = (spec_path.parent / stdin_file_raw).resolve()
        return RunInput(args=args, stdin=_read_text_file(stdin_path))

    return RunInput(args=args, stdin=None)


def _parse_expect(raw: object, *, spec_path: Path, run_name: str) -> RunExpect:
    if raw is None:
        return RunExpect(exit_code=None, stdout=None, stderr=None, panic=None)

    _require_type(raw, dict, f"{spec_path}: run '{run_name}' expect")
    expect_obj: dict[str, object] = raw  # type: ignore[assignment]

    exit_code_raw = expect_obj.get("exit_code")
    if exit_code_raw is not None:
        _require_type(exit_code_raw, int, f"{spec_path}: run '{run_name}' expect.exit_code")

    stdout_raw = expect_obj.get("stdout")
    stdout_file_raw = expect_obj.get("stdout_file")
    if stdout_raw is not None and stdout_file_raw is not None:
        raise ValueError(f"{spec_path}: run '{run_name}' expect.stdout and expect.stdout_file are mutually exclusive")
    stdout: str | None = None
    if stdout_raw is not None:
        _require_type(stdout_raw, str, f"{spec_path}: run '{run_name}' expect.stdout")
        stdout = stdout_raw
    elif stdout_file_raw is not None:
        _require_type(stdout_file_raw, str, f"{spec_path}: run '{run_name}' expect.stdout_file")
        stdout = _read_text_file((spec_path.parent / stdout_file_raw).resolve())

    stderr_raw = expect_obj.get("stderr")
    stderr_file_raw = expect_obj.get("stderr_file")
    if stderr_raw is not None and stderr_file_raw is not None:
        raise ValueError(f"{spec_path}: run '{run_name}' expect.stderr and expect.stderr_file are mutually exclusive")
    stderr: str | None = None
    if stderr_raw is not None:
        _require_type(stderr_raw, str, f"{spec_path}: run '{run_name}' expect.stderr")
        stderr = stderr_raw
    elif stderr_file_raw is not None:
        _require_type(stderr_file_raw, str, f"{spec_path}: run '{run_name}' expect.stderr_file")
        stderr = _read_text_file((spec_path.parent / stderr_file_raw).resolve())

    panic_raw = expect_obj.get("panic")
    if panic_raw is not None:
        _require_type(panic_raw, str, f"{spec_path}: run '{run_name}' expect.panic")

    return RunExpect(exit_code=exit_code_raw, stdout=stdout, stderr=stderr, panic=panic_raw)


def _resolve_path_relative_to_spec(spec_path: Path, raw_path: str, label: str) -> Path:
    path = (spec_path.parent / raw_path).resolve()
    try:
        path.relative_to(GOLDEN_ROOT)
    except ValueError as error:
        raise ValueError(f"{spec_path}: {label} must resolve under {GOLDEN_ROOT}") from error
    return path


def _parse_runs(raw: object, *, spec_path: Path, test_name: str) -> list[RunCase]:
    if raw is None:
        raise ValueError(f"{spec_path}: test '{test_name}' missing required 'runs'")

    _require_type(raw, list, f"{spec_path}: test '{test_name}' runs")
    runs_raw: list[object] = raw  # type: ignore[assignment]
    if len(runs_raw) == 0:
        raise ValueError(f"{spec_path}: test '{test_name}' runs must not be empty")

    runs: list[RunCase] = []
    names: set[str] = set()
    for index, run_raw in enumerate(runs_raw):
        _require_type(run_raw, dict, f"{spec_path}: test '{test_name}' runs[{index}]")
        run_obj: dict[str, object] = run_raw  # type: ignore[assignment]

        name_raw = run_obj.get("name")
        _require_type(name_raw, str, f"{spec_path}: test '{test_name}' runs[{index}].name")
        if name_raw in names:
            raise ValueError(f"{spec_path}: test '{test_name}' duplicate run name '{name_raw}'")
        names.add(name_raw)

        run_input = _parse_input(run_obj.get("input"), spec_path=spec_path, run_name=name_raw)
        expect = _parse_expect(run_obj.get("expect"), spec_path=spec_path, run_name=name_raw)

        runs.append(RunCase(name=name_raw, run_input=run_input, expect=expect))

    return runs


def _parse_compile_error_match(raw: object, *, spec_path: Path, test_name: str) -> str | None:
    if raw is None:
        return None
    _require_type(raw, str, f"{spec_path}: test '{test_name}' compile_error_match")
    return raw


def _parse_build_args(raw: object, *, spec_path: Path, test_name: str) -> list[str]:
    if raw is None:
        return []
    _require_type(raw, list, f"{spec_path}: test '{test_name}' build_args")
    build_args_raw: list[object] = raw  # type: ignore[assignment]
    build_args: list[str] = []
    for index, item in enumerate(build_args_raw):
        _require_type(item, str, f"{spec_path}: test '{test_name}' build_args[{index}]")
        build_args.append(item)
    return build_args


def _load_tests_for_spec(spec_path: Path) -> list[GoldenTest]:
    raw_data = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    if raw_data is None:
        raw_data = {}
    _require_type(raw_data, dict, f"{spec_path}")
    data: dict[str, object] = raw_data  # type: ignore[assignment]

    tests_raw = data.get("tests")
    if tests_raw is None:
        raise ValueError(f"{spec_path}: missing required top-level 'tests'")
    _require_type(tests_raw, list, f"{spec_path}: tests")
    if len(tests_raw) == 0:
        raise ValueError(f"{spec_path}: tests must not be empty")

    tests: list[GoldenTest] = []
    names: set[str] = set()
    for index, test_raw in enumerate(tests_raw):
        _require_type(test_raw, dict, f"{spec_path}: tests[{index}]")
        test_obj: dict[str, object] = test_raw  # type: ignore[assignment]

        mode_raw = test_obj.get("mode")
        _require_type(mode_raw, str, f"{spec_path}: tests[{index}].mode")
        if mode_raw not in {"run", "compile-fail"}:
            raise ValueError(f"{spec_path}: test mode '{mode_raw}' is not supported")

        name_raw = test_obj.get("name")
        _require_type(name_raw, str, f"{spec_path}: tests[{index}].name")
        if name_raw in names:
            raise ValueError(f"{spec_path}: duplicate test name '{name_raw}'")
        names.add(name_raw)

        src_file_raw = test_obj.get("src_file")
        _require_type(src_file_raw, str, f"{spec_path}: tests[{index}].src_file")
        source_path = _resolve_path_relative_to_spec(spec_path, src_file_raw, f"test '{name_raw}' src_file")
        if not source_path.exists():
            raise ValueError(f"missing source for {spec_path}: expected {src_file_raw}")

        compile_error_match = _parse_compile_error_match(
            test_obj.get("compile_error_match"), spec_path=spec_path, test_name=name_raw
        )
        build_args = _parse_build_args(test_obj.get("build_args"), spec_path=spec_path, test_name=name_raw)

        if mode_raw == "run":
            runs = _parse_runs(test_obj.get("runs"), spec_path=spec_path, test_name=name_raw)
        else:
            if test_obj.get("runs") is not None:
                raise ValueError(f"{spec_path}: compile-fail test '{name_raw}' must not define runs")
            runs = []

        tests.append(
            GoldenTest(
                name=name_raw,
                mode=mode_raw,
                source_path=source_path,
                spec_path=spec_path,
                runs=runs,
                compile_error_match=compile_error_match,
                build_args=build_args,
            )
        )

    return tests


def _matches_filter(spec_path: Path, source_path: Path, pattern: str) -> bool:
    spec_rel = spec_path.relative_to(GOLDEN_ROOT).as_posix()
    source_rel = source_path.relative_to(GOLDEN_ROOT).as_posix()
    return fnmatch.fnmatch(spec_rel, pattern) or fnmatch.fnmatch(source_rel, pattern)


def _discover_tests(filter_glob: str | None) -> list[GoldenTest]:
    if not GOLDEN_ROOT.exists():
        return []

    spec_files = sorted(path for path in GOLDEN_ROOT.glob("**/test_*_spec.yaml") if path.is_file())

    tests: list[GoldenTest] = []
    for spec_path in spec_files:
        spec_tests = _load_tests_for_spec(spec_path)
        if filter_glob is None:
            tests.extend(spec_tests)
            continue
        if fnmatch.fnmatch(spec_path.relative_to(GOLDEN_ROOT).as_posix(), filter_glob):
            tests.extend(spec_tests)
            continue
        tests.extend(test for test in spec_tests if _matches_filter(spec_path, test.source_path, filter_glob))

    return tests


def _flatten_relative_stem(path: Path, root: Path) -> str:
    return path.relative_to(root).with_suffix("").as_posix().replace("/", "__")


def _sanitize_output_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")


def _build_output_path(test: GoldenTest) -> Path:
    spec_stem = _flatten_relative_stem(test.spec_path, GOLDEN_ROOT)
    test_name = _sanitize_output_component(test.name)
    flat_name = f"{spec_stem}__{test_name}"
    return BUILD_ROOT / BUILD_CASES_DIRNAME / flat_name


def _runtime_archive_path() -> Path:
    return BUILD_ROOT / BUILD_RUNTIME_DIRNAME / f"run_{os.getpid()}" / "libruntime.a"


def _prepare_runtime_archive() -> tuple[bool, str | None, Path]:
    archive_path = _runtime_archive_path()
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(REPO_ROOT / "scripts" / "build_runtime.sh"),
        str(archive_path.relative_to(REPO_ROOT)),
    ]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout).strip()
        if not message:
            message = f"runtime build failed with exit code {proc.returncode}"
        return False, message, archive_path
    return True, None, archive_path


def _compile_run_test(test: GoldenTest, runtime_archive: Path | None = None) -> tuple[bool, str | None, Path]:
    output_path = _build_output_path(test)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(REPO_ROOT / "scripts" / "build.sh"),
        str(test.source_path.relative_to(REPO_ROOT)),
        str(output_path.relative_to(REPO_ROOT)),
    ]
    if test.build_args:
        cmd.extend(["--", *test.build_args])
    env = os.environ.copy()
    if runtime_archive is not None:
        env[PREBUILT_RUNTIME_ENV_VAR] = str(runtime_archive)
    proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout).strip()
        if not message:
            message = f"build failed with exit code {proc.returncode}"
        return False, message, output_path
    return True, None, output_path


def _compile_fail_test(test: GoldenTest) -> tuple[bool, str | None]:
    asm_path = _build_output_path(test).with_suffix(".s")
    asm_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "python3",
        "-m",
        "compiler.main",
        str(test.source_path),
        "-o",
        str(asm_path),
        "--project-root",
        str(REPO_ROOT),
        *test.build_args,
    ]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    output_text = "\n".join(part for part in [proc.stderr.strip(), proc.stdout.strip()] if part).strip()

    if test.compile_error_match is None:
        if proc.returncode == 0:
            return True, None
        message = output_text or f"compile failed with exit code {proc.returncode}"
        return False, message

    if proc.returncode == 0:
        return False, f"expected compile error containing '{test.compile_error_match}', but compilation succeeded"

    if test.compile_error_match not in output_text:
        if not output_text:
            output_text = "<empty>"
        return False, (
            f"compile error mismatch: expected substring '{test.compile_error_match}'\n"
            f"captured compiler output:\n{output_text}"
        )

    return True, None


def _append_stderr_details(errors: list[str], stderr_text: str) -> None:
    if stderr_text == "":
        errors.append("captured stderr: <empty>")
        return

    max_chars = 8000
    truncated = stderr_text
    if len(truncated) > max_chars:
        truncated = truncated[:max_chars] + "\n...<truncated>"

    errors.append("captured stderr:")
    for line in truncated.splitlines():
        errors.append(f"stderr | {line}")


def _append_text_diff(errors: list[str], *, label: str, expected: str, actual: str) -> None:
    errors.append(f"{label} expected {len(expected)} chars, got {len(actual)} chars")

    diff_lines = list(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile=f"expected {label}",
            tofile=f"actual {label}",
            lineterm="",
        )
    )

    if not diff_lines:
        errors.append(f"{label} diff: <no line-level changes>")
        return

    max_diff_lines = 200
    errors.append(f"{label} diff (expected vs actual):")
    for line in diff_lines[:max_diff_lines]:
        errors.append(f"diff | {line}")
    if len(diff_lines) > max_diff_lines:
        errors.append(f"diff | ...<truncated {len(diff_lines) - max_diff_lines} lines>")


def _execute_run(binary_path: Path, run: RunCase) -> RunResult:
    cmd = [str(binary_path), *run.run_input.args]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, input=run.run_input.stdin, capture_output=True, text=True, check=False)

    errors: list[str] = []
    expect = run.expect

    if expect.exit_code is not None and proc.returncode != expect.exit_code:
        errors.append(f"exit_code expected {expect.exit_code}, got {proc.returncode}")

    if expect.stdout is not None and proc.stdout != expect.stdout:
        errors.append("stdout mismatch")
        _append_text_diff(errors, label="stdout", expected=expect.stdout, actual=proc.stdout)

    if expect.stderr is not None and proc.stderr != expect.stderr:
        errors.append("stderr mismatch")
        _append_text_diff(errors, label="stderr", expected=expect.stderr, actual=proc.stderr)

    if expect.panic is not None:
        if proc.returncode == 0:
            errors.append("expected panic but process exited with code 0")
        if expect.panic not in proc.stderr:
            errors.append(f"panic mismatch: expected substring '{expect.panic}'")

    if errors:
        _append_stderr_details(errors, proc.stderr)

    return RunResult(name=run.name, ok=len(errors) == 0, details=errors)


def _run_test(test: GoldenTest, runtime_archive: Path | None = None) -> TestResult:
    if test.mode == "compile-fail":
        compile_ok, compile_error = _compile_fail_test(test)
        return TestResult(
            name=test.name,
            mode=test.mode,
            spec_path=test.spec_path,
            source_path=test.source_path,
            compile_ok=compile_ok,
            compile_error=compile_error,
            run_results=[],
        )

    compile_ok, compile_error, output_path = _compile_run_test(test, runtime_archive)
    if not compile_ok:
        return TestResult(
            name=test.name,
            mode=test.mode,
            spec_path=test.spec_path,
            source_path=test.source_path,
            compile_ok=False,
            compile_error=compile_error,
            run_results=[],
        )

    run_results = [_execute_run(output_path, run) for run in test.runs]
    return TestResult(
        name=test.name,
        mode=test.mode,
        spec_path=test.spec_path,
        source_path=test.source_path,
        compile_ok=True,
        compile_error=None,
        run_results=run_results,
    )


def _run_spec(spec_path: Path, tests: list[GoldenTest], runtime_archive: Path | None = None) -> SpecResult:
    del spec_path
    return SpecResult(spec_path=tests[0].spec_path, test_results=[_run_test(test, runtime_archive) for test in tests])


def _print_result_per_spec(result: SpecResult) -> None:
    rel_path = result.spec_path.relative_to(REPO_ROOT)
    if result.ok:
        print(f"PASS {rel_path}")
        return

    print(f"FAIL {rel_path}")
    for test_result in result.test_results:
        if test_result.ok:
            continue
        if not test_result.compile_ok:
            print(f"  test '{test_result.name}' :: <compile>")
            print(f"    {test_result.compile_error}")
            continue
        for run in test_result.run_results:
            if run.ok:
                continue
            print(f"  test '{test_result.name}' :: {run.name}")
            for detail in run.details:
                print(f"    - {detail}")


def _print_result_per_run(result: SpecResult) -> None:
    rel_path = result.spec_path.relative_to(REPO_ROOT)
    for test_result in result.test_results:
        if test_result.mode == "compile-fail":
            status = "PASS" if test_result.ok else "FAIL"
            print(f"{status} {rel_path} :: {test_result.name}")
            if not test_result.ok:
                print(f"  compile: {test_result.compile_error}")
            continue

        if not test_result.compile_ok:
            print(f"FAIL {rel_path} :: {test_result.name} :: <compile>")
            print(f"  compile: {test_result.compile_error}")
            continue

        for run in test_result.run_results:
            status = "PASS" if run.ok else "FAIL"
            print(f"{status} {rel_path} :: {test_result.name} :: {run.name}")
            if not run.ok:
                for detail in run.details:
                    print(f"  - {detail}")


def _print_result(result: SpecResult, *, per_run: bool) -> None:
    if per_run:
        _print_result_per_run(result)
        return
    _print_result_per_spec(result)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Niflheim golden tests")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1, help="Number of concurrent workers")
    parser.add_argument("--filter", type=str, default=None, help="Glob under tests/golden (e.g. 'arithmetic/**')")
    parser.add_argument(
        "--print-per-run",
        action="store_true",
        help="Print one PASS/FAIL line per run case and compile-fail test instead of per spec file",
    )
    args = parser.parse_args()

    try:
        tests = _discover_tests(args.filter)
    except Exception as error:
        print(f"golden: spec error: {error}", file=sys.stderr)
        return 2

    if not tests:
        print("golden: no tests discovered")
        return 0

    runtime_archive: Path | None = None
    if any(test.mode == "run" for test in tests):
        runtime_ok, runtime_error, runtime_archive = _prepare_runtime_archive()
        if not runtime_ok:
            print(f"golden: runtime build failed: {runtime_error}")
            return 1

    from concurrent.futures import ThreadPoolExecutor, as_completed

    specs = _group_tests_by_spec(tests)
    spec_results: list[SpecResult] = []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [pool.submit(_run_spec, spec_path, spec_tests, runtime_archive) for spec_path, spec_tests in specs]
        for future in as_completed(futures):
            result = future.result()
            spec_results.append(result)
            _print_result(result, per_run=args.print_per_run)

    failed = [result for result in spec_results if not result.ok]
    total_runs = sum(len(test.runs) for test in tests)
    print(f"golden: {len(spec_results) - len(failed)}/{len(spec_results)} spec files passed; {total_runs} runs total")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
