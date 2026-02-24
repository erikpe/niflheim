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

Recent backend/runtime updates:
- Full `double` lowering is implemented in codegen, including literals, arithmetic/comparisons, casts, and mixed integer/floating call signatures.
- SysV floating-point ABI paths are implemented for parameters/returns (`xmm0`-`xmm7`) in function calls, method calls, and constructors.
- Runtime box parity includes `BoxDouble` construction/getters with end-to-end tests for value reads and ABI correctness.

## Policy Decisions (MVP)

- Null-dereference checks are runtime-only in v0.1; compile-time static null-dereference analysis is intentionally out of scope.
- Imported class name resolution is symmetric for constructor calls and type annotations: unqualified names are local-first, qualified names are explicit, and ambiguous unqualified imported names are compile-time errors.
- See [docs/LANGUAGE_MVP_SPEC_V0.1.md](docs/LANGUAGE_MVP_SPEC_V0.1.md) for the canonical language/runtime policy details.

## Runtime / GC Tests

Runtime test harnesses live under `runtime/tests/` and are built/run via `runtime/Makefile`.

Runtime sources are split by responsibility:
- `runtime/src/runtime.c` - low-level runtime infrastructure (thread state, roots, allocation, panic support)
- `runtime/src/gc.c` - GC implementation
- `runtime/src/io.c` - runtime IO/println implementation
- `runtime/src/str.c` - `Str` implementation
- `runtime/src/box.c` - primitive box implementations
- `runtime/src/vec.c` - `Vec` implementation
- `runtime/src/strbuf.c` - `StrBuf` implementation

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
	- Runs golden tests (`./scripts/golden.sh`)
	- Runs runtime C harnesses (`make -C runtime test-all`)
	- Example: `./scripts/test.sh`

## Golden Tests

Golden tests live under `tests/golden/`.

- Every `tests/golden/**/test_*.nif` file is treated as a golden test source.
- Each source must have a sibling spec file named `<stem>_spec.yaml`.
	- Example source: `tests/golden/arithmetic/test_addition.nif`
	- Example spec: `tests/golden/arithmetic/test_addition_spec.yaml`
- Each source is compiled once via `scripts/build.sh` and output goes to `build/golden/...`.
- The spec can define multiple runs against the compiled binary.

Run the runner:

- `./scripts/golden.sh`
- `./scripts/golden.sh --jobs 8`
- `./scripts/golden.sh --filter 'arithmetic/**'`

Spec format:

```yaml
runs:
	- name: case_name
		input:
			args: ["arg1", "arg2"]
			stdin: "optional stdin text"
			# stdin_file: "./input.txt"
		expect:
			exit_code: 0
			stdout: "expected stdout"
			# stdout_file: "./expected_stdout.txt"
			stderr: ""
			# stderr_file: "./expected_stderr.txt"
			panic: "optional panic substring"
```

Notes:

- `input.stdin` and `input.stdin_file` are mutually exclusive.
- `expect.stderr` and `expect.stderr_file` are mutually exclusive.
- Unspecified input fields are not provided.
- Unspecified expectation fields are not validated.
