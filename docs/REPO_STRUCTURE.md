# Repository Structure

This document summarizes the current repository layout for MVP v0.1 work.

## Top-Level Files

- [README.md](../README.md) - project overview and policy highlights.
- `pyproject.toml` - Python tooling/test configuration.

## `compiler/`

Stage-0 compiler implementation in Python.

- `frontend/` - syntax-layer package.
	- `tokens.py` - token kinds and lexer token tables.
	- `lexer.py` - lexical analysis with source spans, token objects, and diagnostics.
	- `ast_nodes.py` - canonical AST dataclasses.
	- `parser.py` - recursive-descent parser for modules/statements/expressions.
	- `ast_dump.py` - deterministic AST debug serialization used by golden tests.
- `resolver.py` - module graph loading and import/export visibility resolution.
- `typecheck/` - typecheck package modules.
	- `api.py` - typecheck entry points (`typecheck`, `typecheck_program`).
	- `model.py` - shared typechecker data model/constants/errors.
	- `context.py`, `constants.py` - explicit checker context/state helpers and extracted constants.
	- `relations.py` - extracted type relation helpers.
	- `module_lookup.py`, `type_resolution.py` - extracted lookup and type resolution helpers.
	- `declarations.py` - extracted declaration pre-pass and field-initializer validation helpers.
	- `calls.py` - extracted call typing and call-argument validation helpers.
	- `structural.py` - extracted indexing, slicing, and iteration protocol helpers.
	- `expressions.py` - extracted non-call expression inference and field-assignability helpers.
	- `statements.py` - extracted statement checking, return analysis, assignment-target validation, and visibility helpers.
	- `engine.py` - lean internal typecheck engine adapter composed from the extracted helper modules.
- `codegen/` - backend package entry point and internal code generation modules.
	- `__init__.py` - stable `emit_asm(module_ast)` public entry point.
	- `generator.py` - shared backend state and remaining coordination helpers.
	- `model.py`, `strings.py`, `symbols.py`, `types.py`, `layout.py`, `call_resolution.py`, `abi_sysv.py` - shared backend helpers by responsibility.
	- `asm.py`, `ops_int.py`, `ops_float.py` - assembly building and operator instruction selection.
	- `emitter_expr.py`, `emitter_stmt.py`, `emitter_fn.py`, `emitter_module.py` - layered expression, statement, function, and module emission.
- `cli.py` - minimal phase-oriented CLI scaffold.
- `main.py` - package entry point.
- `grammar/niflheim_v0_1.ebnf` - canonical grammar source.

## `runtime/`

Minimal C runtime skeleton for upcoming backend/GC work.

- `include/runtime.h` - runtime ABI declarations.
- `include/io.h` - runtime IO/println API declarations.
- `include/vec.h` - `Vec` runtime API declarations.
- `src/runtime.c` - low-level runtime infrastructure (thread state, root frames, allocation, panic support).
- `src/gc.c` - GC implementation unit.
- `src/io.c` - runtime IO/println implementation unit.
- `src/vec.c` - `Vec` object implementation.
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
- [TYPECHECK_REFACTOR_PLAN.md](TYPECHECK_REFACTOR_PLAN.md) - concrete module split and migration plan for the typechecker.
- [ABI_NOTES.md](ABI_NOTES.md) - compiler/runtime ABI notes.
- [TEST_PLAN_v0.1.md](TEST_PLAN_v0.1.md) - testing strategy and release gate criteria.
- [SUGARING_DESIGN.md](SUGARING_DESIGN.md) - canonical sugar protocols (indexing/slicing and for-in iteration).
