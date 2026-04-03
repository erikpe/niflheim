---
name: run-pytest-tests
description: 'Run pytest tests in the niflheim repository. Use when asked to run Python tests, pytest, test files, test directories, or the full pytest suite. Use system Python and do not create or activate a Python venv. Prefer pytest -n auto --dist loadfile for this repo because integration tests are split per file for xdist loadfile scheduling.'
argument-hint: 'Optional pytest target or arguments, for example: tests/compiler/typecheck -q'
user-invocable: true
---

# Run Pytest Tests

Use this skill when the task is to run pytest in this repository.

## Repository Rules

- Do not create, activate, or rely on a Python virtual environment for this repo.
- Use the system Python and system-installed pytest tooling.
- The repo has `python3-pytest-xdist` installed at the system level.
- Prefer `/bin/python3 -m pytest -n auto --dist loadfile` unless the user explicitly asks for serial execution.
- The pytest config in `pyproject.toml` already scopes collection to `tests/compiler`.
- Integration compile-and-run tests were split into one test per file specifically to work well with `--dist loadfile`.

## Default Commands

Run the full pytest suite:

```bash
cd /home/eka/git/niflheim && /bin/python3 -m pytest -n auto --dist loadfile
```

Run a specific test directory:

```bash
cd /home/eka/git/niflheim && /bin/python3 -m pytest -n auto --dist loadfile tests/compiler/integration
```

Run a single test file:

```bash
cd /home/eka/git/niflheim && /bin/python3 -m pytest -n auto --dist loadfile tests/compiler/typecheck/test_expressions.py
```

Run serially only when requested or when diagnosing order-sensitive issues:

```bash
cd /home/eka/git/niflheim && /bin/python3 -m pytest
```

## Procedure

1. Use `/bin/python3 -m pytest`, not bare `pytest`, when giving an explicit command.
2. Default to `-n auto --dist loadfile`.
3. If the user gave a target, append it after the xdist flags.
4. If the user wants the complete repo test driver instead of only pytest, run `./scripts/test.sh`.
5. Report the pass/fail result and the most relevant timing or failing-test details.

## Notes

- `--dist loadfile` keeps each test file on one worker, which matches this repo's current integration-test layout.
- If the user asks for per-file timing, run pytest with JUnit output and aggregate testcase times by file afterward.