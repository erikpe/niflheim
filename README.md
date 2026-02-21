# Niflheim

This repository contains the stage-0 compiler and minimal C runtime for Niflheim, a learning-oriented, statically typed compiled language.

Niflheim source files use the `.nif` extension.

Key design docs:
- [docs/LANGUAGE_MVP_SPEC_V0.1.md](docs/LANGUAGE_MVP_SPEC_V0.1.md)
- [docs/ROADMAP_v0.1.md](docs/ROADMAP_v0.1.md)
- [docs/ABI_NOTES.md](docs/ABI_NOTES.md)
- [docs/TEST_PLAN_v0.1.md](docs/TEST_PLAN_v0.1.md)
- [docs/GRAMMAR_EBNF.md](docs/GRAMMAR_EBNF.md)
- [docs/REPO_STRUCTURE.md](docs/REPO_STRUCTURE.md)

## Repository Areas

- `compiler/` - Python stage-0 compiler
- `runtime/` - C runtime and GC
- `tests/` - unit, golden, integration, and stress tests
- `examples/` - small language programs
- `docs/` - repository-level reference docs

## Current Status

Frontend for MVP v0.1 is largely implemented:

- Lexer, parser, resolver, and type checker are in place with test coverage.
- Program-level module import/export visibility checks are implemented.
- Type checking includes explicit casts, `Obj` up/downcast typing rules, return-path checks, and module-aware type resolution.

Backend/codegen, runtime GC implementation details, and full CLI workflow are still in progress.

## Policy Decisions (MVP)

- Null-dereference checks are runtime-only in v0.1; compile-time static null-dereference analysis is intentionally out of scope.
- Imported class name resolution is symmetric for constructor calls and type annotations: unqualified names are local-first, qualified names are explicit, and ambiguous unqualified imported names are compile-time errors.
- See [docs/LANGUAGE_MVP_SPEC_V0.1.md](docs/LANGUAGE_MVP_SPEC_V0.1.md) for the canonical language/runtime policy details.

## Runtime / GC Tests

Runtime test harnesses live under `runtime/tests/` and are built/run via `runtime/Makefile`.

- `make -C runtime test` runs GC stress scenarios (`test_gc_stress`):
	- no-root reclaim
	- rooted chain survival + reclaim after root clear
	- reachable and unreachable cycle behavior
	- global root registration/unregistration behavior
	- nested shadow-stack frame behavior
	- threshold-trigger behavior under allocation pressure
- `make -C runtime test-positive` runs root API happy-path checks (`test_roots_positive`).
- `make -C runtime test-negative` runs root/global-root misuse checks that must fail (`test_roots_negative`).
- `make -C runtime test-all` runs all runtime harnesses.

## Build and Run Helpers

For quick local workflows, use scripts under `scripts/`:

- `scripts/build.sh <input.nif> <output-executable>`
	- Compiles to assembly at `<output-executable>.s`
	- Links the runtime and emits `<output-executable>`
	- Example: `./scripts/build.sh samples/arithmetic_loop.nif build/loopy`
- `scripts/run.sh <input.nif> [output-executable] [-- <program-args...>]`
	- Builds via `build.sh`, then executes the produced binary
	- If output path is omitted, defaults to `build/<input-basename>`
	- Example: `./scripts/run.sh samples/arithmetic_loop.nif`

## Test Helper

- `scripts/test.sh`
	- Runs the full Python test suite (`pytest -q`)
	- Runs runtime C harnesses (`make -C runtime test-all`)
	- Example: `./scripts/test.sh`
