# Repository Structure

This document summarizes the current repository layout for MVP v0.1 work.

## Top-Level Files

- [README.md](../README.md) - project overview and policy highlights.
- `pyproject.toml` - Python tooling/test configuration.

## `compiler/`

Stage-0 compiler implementation in Python.

- `tokens.py` - token kinds and lexer token tables.
- `lexer.py` - lexical analysis with source spans and diagnostics.
- `ast_nodes.py` - canonical AST dataclasses.
- `ast.py` - compatibility re-export of `ast_nodes` symbols.
- `parser.py` - recursive-descent parser for modules/statements/expressions.
- `ast_dump.py` - deterministic AST debug serialization used by golden tests.
- `resolver.py` - module graph loading and import/export visibility resolution.
- `typecheck.py` - typecheck entry points (`typecheck`, `typecheck_program`) and public typecheck exports.
- `typecheck_model.py` - shared typechecker data model/constants/errors.
- `typecheck_checker.py` - typechecker engine implementation.
- `codegen.py` - codegen placeholder.
- `cli.py` - minimal phase-oriented CLI scaffold.
- `main.py` - package entry point.
- `grammar/niflheim_v0_1.ebnf` - canonical grammar source.

## `runtime/`

Minimal C runtime skeleton for upcoming backend/GC work.

- `include/runtime.h` - runtime ABI declarations.
- `src/runtime.c` - runtime bring-up stubs.
- `src/gc.c` - GC implementation unit (pending full implementation).
- `Makefile` - runtime static library build.

## `tests/`

Current active suites:

- `lexer/` - tokenization and lexer diagnostics.
- `parser/` - parser behavior, precedence, spans, golden AST shape tests.
- `resolver/` - module graph and visibility enforcement tests.
- `typecheck/` - type-checking behavior across single-module and multi-module flows.
- `integration/` - end-to-end placeholder suite.

## `examples/`

Small `.nif` source programs used for language bring-up and experimentation.

## `scripts/`

Utility scripts for repository workflows (for example golden refresh/build helpers).

## `docs/`

Supporting documentation:

- [REPO_STRUCTURE.md](REPO_STRUCTURE.md) - this file.
- [GRAMMAR_EBNF.md](GRAMMAR_EBNF.md) - grammar conventions and parser-facing notes.
- [LANGUAGE_MVP_SPEC_V0.1.md](LANGUAGE_MVP_SPEC_V0.1.md) - canonical language and implementation checklist.
- [ROADMAP_v0.1.md](ROADMAP_v0.1.md) - milestone/iteration plan.
- [ABI_NOTES.md](ABI_NOTES.md) - compiler/runtime ABI notes.
- [TEST_PLAN_v0.1.md](TEST_PLAN_v0.1.md) - testing strategy and release gate criteria.
