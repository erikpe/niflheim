---
name: run-python
description: 'Run Python in the niflheim repository. Use when asked to run Python scripts, execute Python snippets, inspect Python behavior, or invoke repo Python tooling. Use the system-installed Python. Never create, activate, or rely on a Python virtual environment.'
argument-hint: 'Optional Python target or code snippet, for example: scripts/measure_root_liveness.py or -c "print(123)"'
user-invocable: true
---

# Run Python

Use this skill when the task is to run Python generally in this repository.

## Repository Rules

- Use the system-installed Python.
- Never create, activate, or rely on a Python virtual environment.
- Prefer `/bin/python3`, not `python`, when giving explicit commands.
- If running a repo Python script directly, keep repo-root import ordering correct before importing `compiler.*` modules.

## Default Commands

Run a Python script:

```bash
cd /home/eka/git/niflheim && /bin/python3 scripts/measure_root_liveness.py
```

Run an inline snippet:

```bash
cd /home/eka/git/niflheim && /bin/python3 -c 'print(123)'
```

Run a module:

```bash
cd /home/eka/git/niflheim && /bin/python3 -m pytest -n auto --dist loadfile
```

## Procedure

1. Use `/bin/python3` for explicit commands.
2. Do not create or activate a venv.
3. If the task is a quick Python expression or short snippet, prefer an in-memory snippet runner when available.
4. If the task is to run an existing repo script, execute it from the repository root.
5. If the script imports repo modules directly, preserve correct import ordering and repo-root path setup before importing `compiler.*`.
6. Report the result concisely, including any errors or relevant output.

## Notes

- This skill is for general Python execution, not just pytest.
- For pytest-specific workflows in this repo, prefer the `run-pytest-tests` skill.