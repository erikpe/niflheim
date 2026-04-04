---
name: run-golden-tests
description: 'Run, filter, and debug golden tests in the niflheim repository. Use when asked to run the full golden suite, run a tests/golden subset, use scripts/golden.sh or tests/golden/runner.py, choose a --filter glob, inspect per-run output, or troubleshoot golden discovery failures.'
argument-hint: 'Optional golden target, for example: lang/test_constructor/** or lang/test_constructor/error_*.nif'
user-invocable: true
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

What it does:

- discovers `test_*_spec.yaml` files under `tests/golden`
- parses the top-level `tests:` entries
- for `run` entries: builds with `scripts/build.sh`, then executes each run case
- for `compile-fail` entries: invokes `python3 -m compiler.main` directly and checks the compile error substring
- writes build artifacts under `build/golden/__cases__`

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

1. Choose the narrowest useful `--filter` glob before running.
2. Prefer `./scripts/golden.sh` unless you specifically need the Python entrypoint.
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