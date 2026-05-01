---
name: run-golden-tests
description: Run, filter, and debug golden tests in the niflheim repository. Use when asked to run the full golden suite, run a tests/golden subset, use scripts/golden.sh or tests/golden/runner.py, choose a --filter glob, inspect per-run output, or troubleshoot golden discovery failures.
---

# Run Golden Tests

Use this skill when the task is to execute, filter, or troubleshoot golden tests in this repository.

## Repository Rules

- Use the repo root when running the golden runner.
- Prefer `./scripts/golden.sh` for normal execution. It is the thin wrapper around `python3 tests/golden/runner.py`.
- Do not pass a bare file path as a positional argument to `scripts/golden.sh` or `runner.py`; use `--filter` instead.
- Golden test discovery is spec-driven from `tests/golden/**/test_*_spec.yaml`.
- The filter is a glob under `tests/golden`, not a freeform substring search.

## Runner Behavior

The runner is `tests/golden/runner.py`.

It discovers `test_*_spec.yaml` files under `tests/golden`, parses the top-level `tests:` entries, builds run-mode cases with `scripts/build.sh`, invokes `python3 -m compiler.main` for compile-fail cases, and writes build artifacts under `build/golden/__cases__`.

The filter matches both the spec path and source path relative to `tests/golden`. Useful filters include:

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

Print per-run results:

```bash
cd /home/eka/git/niflheim && ./scripts/golden.sh --filter 'lang/test_constructor/**' --print-per-run
```

## Procedure

1. Choose the narrowest useful `--filter` glob before running.
2. Prefer `./scripts/golden.sh` unless the Python entrypoint is specifically needed.
3. If discovery fails with `golden: no tests discovered`, fix the glob instead of passing a raw path argument.
4. For authoring tasks, run the smallest affected scope first, then expand only if needed.
5. Report pass/fail concisely and include the failing source path, failing run name, or diagnostic substring when something breaks.

## Troubleshooting

- If a feature directory appears to be skipped, verify it contains a `test_*_spec.yaml` file.
- If a source file is not being picked up, check that it is referenced by `tests[*].src_file` in a discovered spec.
- If a compile-fail case fails unexpectedly, compare the actual compiler message with the spec's `compile_error_match` substring.
- If a run case fails, use `--print-per-run` to get the exact failing run name before widening the investigation.

## Notes

- The runner summary prints test-file pass counts plus total runtime run count; compile-fail entries contribute test files but not runtime runs.
- Use the companion `write-golden-tests` skill when the task is primarily to author or restructure test cases rather than run them.
