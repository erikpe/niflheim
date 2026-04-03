---
name: write-and-run-golden-tests
description: 'Write, extend, debug, and run golden tests in the niflheim repository. Use when asked to add golden coverage, explain the golden test layout, author mode=run or mode=compile-fail specs, or run tests with tests/golden/runner.py or scripts/golden.sh.'
argument-hint: 'Optional golden target or task, for example: lang/test_constructor/** or add compile-fail tests for imported interfaces'
user-invocable: true
---

# Write And Run Golden Tests

Use this skill when the task is to add, modify, explain, or run golden tests in this repository.

## Repository Rules

- Golden tests live under `tests/golden`.
- Discovery is spec-driven, not source-driven. The runner discovers only files matching `tests/golden/**/test_*_spec.yaml`.
- Every spec has a top-level `tests:` list.
- Each `tests[*].src_file` is resolved relative to the spec file and must stay under `tests/golden`.
- Supported modes are exactly `run` and `compile-fail`.
- `run` tests must define `runs`.
- `compile-fail` tests must not define `runs` and should usually define `compile_error_match`.
- Use the repo root when running the golden runner.
- Prefer `./scripts/golden.sh` for normal execution. It is the thin wrapper around `python3 tests/golden/runner.py`.
- Do not pass a bare file path as a positional argument to `scripts/golden.sh` or `runner.py`; use `--filter` instead.

## Directory Layout

Two common layouts are used under `tests/golden`:

1. Single-file layout for a small feature:

```text
tests/golden/lang/
  test_shadowing.nif
  test_shadowing_spec.yaml
```

2. Directory layout for a feature with helper modules or many related cases:

```text
tests/golden/lang/test_constructor/
  test_constructor.nif
  test_constructor_spec.yaml
  error_constructor_returns_value.nif
  error_missing_required_field_initialization.nif
  helper_module.nif
```

Use a directory when the feature needs:

- helper modules
- both positive and compile-fail coverage
- many related source files under one spec

## Spec Structure

Each spec file contains a top-level `tests:` list. A single spec may contain multiple source-backed test entries.

### `mode: "run"`

Use `run` when the source should compile successfully and then execute one or more runtime cases.

Template:

```yaml
tests:
  - mode: "run"
    name: "test_feature"
    src_file: "test_feature.nif"
    runs:
      - name: "case_name"
        input:
          args: ["arg1", "arg2"]
          stdin: "optional stdin\n"
          # stdin_file: "./input.txt"
        expect:
          exit_code: 0
          stdout: "expected stdout"
          # stdout_file: "./expected_stdout.txt"
          stderr: ""
          # stderr_file: "./expected_stderr.txt"
          panic: "optional panic substring"
```

Rules:

- `runs` is required and must be non-empty.
- Each run name must be unique within that test entry.
- `input.stdin` and `input.stdin_file` are mutually exclusive.
- `expect.stdout` and `expect.stdout_file` are mutually exclusive.
- `expect.stderr` and `expect.stderr_file` are mutually exclusive.
- Omitted expectation fields are not checked.
- `expect.panic` is a stderr substring check and also requires the process to fail.

### `mode: "compile-fail"`

Use `compile-fail` when the source is supposed to be rejected during compilation.

Template:

```yaml
tests:
  - mode: "compile-fail"
    name: "bad_case"
    src_file: "error_bad_case.nif"
    compile_error_match: "Expected compiler error substring"
```

Rules:

- `compile-fail` entries must not define `runs`.
- `compile_error_match` is a substring match against combined compiler stderr/stdout.
- The runner invokes `python3 -m compiler.main ... --project-root <repo_root>` for compile-fail cases.
- If `compile_error_match` is omitted, the runner only checks whether compilation fails, but most repo tests should include it.

## Writing Good Golden Tests

- Prefer one focused behavior per source file for compile-fail cases.
- Group related cases under one spec file when they belong to the same feature area.
- Keep error-case source names explicit, for example `error_unknown_superclass.nif`.
- Match stable diagnostic substrings, not entire multiline compiler output.
- Reuse helper modules in the same directory when the feature is multi-module.
- For runtime tests, use one source file with multiple selector-driven cases only when it keeps setup shared and readable.
- For compile-fail tests, do not over-pack many independent failures into one source; separate files make diagnostics stable and filtering easier.

## Runner Behavior

The runner is `tests/golden/runner.py`.

What it does:

- discovers `test_*_spec.yaml` files under `tests/golden`
- parses the top-level `tests:` entries
- for `run` entries: builds with `scripts/build.sh`, then executes each run case
- for `compile-fail` entries: invokes `python3 -m compiler.main` directly and checks the compile error substring
- writes build artifacts under `build/golden/__cases__`

Important detail:

- `--filter` is a glob under `tests/golden`, not a freeform substring search and not a positional path argument

The filter matches both:

- the spec path relative to `tests/golden`
- the source path relative to `tests/golden`

That means these all work when applicable:

- `lang/test_constructor/**`
- `lang/test_constructor/test_constructor_spec.yaml`
- `lang/test_constructor/error_*.nif`

## Default Commands

Run the full golden suite:

```bash
cd /home/eka/git/niflheim && ./scripts/golden.sh
```

Run one feature directory:

```bash
cd /home/eka/git/niflheim && ./scripts/golden.sh --filter 'lang/test_constructor/**'
```

Run a single spec file by glob:

```bash
cd /home/eka/git/niflheim && ./scripts/golden.sh --filter 'lang/test_constructor/test_constructor_spec.yaml'
```

Run only compile-fail source files in a directory:

```bash
cd /home/eka/git/niflheim && ./scripts/golden.sh --filter 'lang/test_constructor/error_*.nif'
```

Run with explicit worker count:

```bash
cd /home/eka/git/niflheim && ./scripts/golden.sh --jobs 8
```

Print per-run results instead of one line per source file:

```bash
cd /home/eka/git/niflheim && ./scripts/golden.sh --filter 'lang/test_constructor/**' --print-per-run
```

Run the Python runner directly:

```bash
cd /home/eka/git/niflheim && python3 tests/golden/runner.py --filter 'lang/test_constructor/**'
```

## Procedure

1. Pick the existing feature area under `tests/golden` or create a new feature directory when helpers or many related cases are needed.
2. Add or update a `test_*_spec.yaml` file with one or more entries under `tests:`.
3. Use `mode: "run"` for compile-and-execute coverage and `mode: "compile-fail"` for compile-time rejection coverage.
4. Keep `src_file` relative to the spec file.
5. For compile-fail tests, choose a stable `compile_error_match` substring from the actual compiler diagnostic.
6. Validate the narrowest useful scope first with `./scripts/golden.sh --filter '<glob>'`.
7. If a filter returns `golden: no tests discovered`, fix the glob instead of passing a raw path argument.
8. Report pass/fail concisely and include the relevant failing source path or diagnostic substring when something breaks.

## Examples In This Repo

- Mixed runtime and compile-fail coverage in one feature directory:
  - `tests/golden/lang/test_constructor/test_constructor_spec.yaml`
- Multi-module runtime and compile-fail imported-interface coverage:
  - `tests/golden/lang/test_interface_imports/test_interface_imports_spec.yaml`
- Runtime-only single-file spec layout:
  - `tests/golden/lang/test_interfaces_end_to_end_spec.yaml`

## Notes

- Golden specs are YAML, and the repo already uses quoted string values consistently.
- The runner summary prints test-file pass counts plus total runtime run count; compile-fail entries contribute test files but not runtime runs.
- When you need only compile diagnostics, prefer compile-fail golden tests over ad hoc manual compiler invocations so the behavior stays regression-tested.