---
name: write-golden-tests
description: 'Write, extend, debug, or explain golden tests in the niflheim repository. Use when asked to add golden coverage, create or update tests/golden specs, author mode=run or mode=compile-fail cases, choose stable compile_error_match substrings, or explain the golden test layout.'
argument-hint: 'Optional golden writing task, for example: add compile-fail tests for imported interfaces or explain the test_constructor layout'
user-invocable: true
---

# Write Golden Tests

Use this skill when the task is to add, modify, or explain golden tests in this repository.

## Repository Rules

- Golden tests live under `tests/golden`.
- Discovery is spec-driven, not source-driven. The runner discovers only files matching `tests/golden/**/test_*_spec.yaml`.
- Every spec has a top-level `tests:` list.
- Each `tests[*].src_file` is resolved relative to the spec file and must stay under `tests/golden`.
- Supported modes are exactly `run` and `compile-fail`.
- `run` tests must define `runs`.
- `compile-fail` tests must not define `runs` and should usually define `compile_error_match`.
- When you need only compile diagnostics, prefer compile-fail golden tests over ad hoc manual compiler invocations so the behavior stays regression-tested.

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
- For selector-driven runtime files, prefer passing the selector as the first program argument via `input.args`, not via stdin.
- `expect.stdout` and `expect.stdout_file` are mutually exclusive.
- `expect.stderr` and `expect.stderr_file` are mutually exclusive.
- For runtime validation, prefer asserting inside the test program over encoding success or failure in a raw process exit code.
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
- If `compile_error_match` is omitted, the runner only checks whether compilation fails, but most repo tests should include it.

## Writing Good Golden Tests

- Prefer one focused behavior per source file for compile-fail cases.
- Group related cases under one spec file when they belong to the same feature area.
- Keep error-case source names explicit, for example `error_unknown_superclass.nif`.
- Match stable diagnostic substrings, not entire multiline compiler output.
- Reuse helper modules in the same directory when the feature is multi-module.
- For runtime tests, prefer type-specific asserts from `std.test`, such as `assert_eq_i64`, `assert_eq_u64`, `assert_eq_bool`, `assert_eq_u8`, and `assert_eq_double`, when the value type is known.
- Do not indicate test failure by returning ad hoc raw exit codes from `main`; use asserts as the primary validation mechanism.
- Use stdout comparison only when the behavior is naturally output-oriented or when comparing emitted text is materially more convenient than expressing the check with asserts.
- For runtime tests, use one source file with multiple selector-driven cases only when it keeps setup shared and readable.
- For selector-driven runtime tests, prefer `var select: u64 = read_program_args()[1].to_u64();` or the equivalent `Str[]` local form, and pair that with `input.args: ["<selector>"]` in the spec.
- Do not use stdin just to choose which test case to run; reserve stdin for tests that actually validate stdin-driven program behavior.
- For compile-fail tests, do not over-pack many independent failures into one source; separate files make diagnostics stable and filtering easier.

## Procedure

1. Pick the existing feature area under `tests/golden` or create a new feature directory when helpers or many related cases are needed.
2. Add or update a `test_*_spec.yaml` file with one or more entries under `tests:`.
3. Use `mode: "run"` for compile-and-execute coverage and `mode: "compile-fail"` for compile-time rejection coverage.
4. Keep `src_file` relative to the spec file.
5. For compile-fail tests, choose a stable `compile_error_match` substring from the actual compiler diagnostic.
6. For selector-driven `mode: "run"` coverage, pass the selector in `input.args` and parse it from `read_program_args()[1]` in the NIF file.
7. For `mode: "run"` coverage, choose typed asserts first, and only switch to stdout-based expectations when the test is really about produced text or that route is clearly simpler.
8. Validate the narrowest useful scope after edits. Use the companion `run-golden-tests` skill for execution details and filter selection.
9. Report what behavior was added, what diagnostics were matched, and any gaps or real bugs found during authoring.

## Examples In This Repo

- Mixed runtime and compile-fail coverage in one feature directory:
  - `tests/golden/lang/test_constructor/test_constructor_spec.yaml`
- Multi-module runtime and compile-fail imported-interface coverage:
  - `tests/golden/lang/test_interface_imports/test_interface_imports_spec.yaml`
- Runtime-only single-file spec layout:
  - `tests/golden/lang/test_interfaces_end_to_end_spec.yaml`

## Notes

- Golden specs are YAML, and the repo already uses quoted string values consistently.
- A single spec file may define multiple source test files; the runner emits and counts results per source test file, not per spec file.