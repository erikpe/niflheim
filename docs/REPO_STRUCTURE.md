# Repository Structure

This document describes the minimal repository layout for MVP v0.1.

## Top-Level Files

- `LANGUAGE_MVP_SPEC_V0.1.md` - Language requirements and implementation checklist.
- `ROADMAP_v0.1.md` - Milestone and week-by-week delivery plan.
- `ABI_NOTES.md` - Compiler/runtime ABI contract.
- `TEST_PLAN_v0.1.md` - Test strategy and release gates.
- `README.md` - Project entry point and references.
- `pyproject.toml` - Python project and test configuration for stage-0 compiler.

## Directories

## `compiler/`

Stage-0 compiler implementation in Python.

Current scaffold:
- `main.py` - executable entry point.
- `cli.py` - phase-oriented CLI (`lex`, `parse`, `check`, `codegen`).
- `lexer.py` - lexer placeholder.
- `parser.py` - parser placeholder.
- `ast.py` - AST placeholder.
- `resolver.py` - module/symbol resolution placeholder.
- `typecheck.py` - type checker placeholder.
- `codegen.py` - x86-64 emitter placeholder.

## `runtime/`

Minimal C runtime linked with generated programs.

Current scaffold:
- `include/runtime.h` - runtime ABI declarations.
- `src/runtime.c` - runtime state, roots push/pop, allocation, panic stubs.
- `src/gc.c` - GC placeholder implementation unit.
- `Makefile` - builds `libruntime.a`.

## `tests/`

Tests organized by compiler/runtime stage.

Current scaffold includes:
- `lexer/`
- `parser/`
- `typecheck/`
- `integration/`
- `README.md` with target layout

Additional planned directories (per test plan):
- `resolver/`, `codegen/`, `runtime/`, `gc/`, `stress/`

## `examples/`

Language example programs.

Current scaffold:
- `hello.nif` - placeholder source sample.

## `scripts/`

Small helper scripts.

Current scaffold:
- `build_runtime.sh` - convenience wrapper for runtime build on Linux.

## `docs/`

Repository-oriented supporting documentation.

Current scaffold:
- `REPO_STRUCTURE.md` - this document.

## Intended Evolution Path

1. Flesh out `compiler/` passes in roadmap order.
2. Implement mark-sweep GC in `runtime/src/gc.c`.
3. Expand `tests/` to match full layout in test plan.
4. Add specialized containers and new docs after v0.1 stabilizes.
