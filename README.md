# Niflheim

This repository contains the stage-0 compiler and minimal C runtime for Niflheim, a learning-oriented, statically typed compiled language.

Niflheim source files use the `.nif` extension.

Key design docs:
- [docs/LANGUAGE_MVP_SPEC_V0.1.md](docs/LANGUAGE_MVP_SPEC_V0.1.md)
- [docs/ROADMAP_v0.1.md](docs/ROADMAP_v0.1.md)
- [docs/ABI_NOTES.md](docs/ABI_NOTES.md)
- [docs/archive/EXPLICIT_CONSTRUCTORS_PLAN.md](docs/archive/EXPLICIT_CONSTRUCTORS_PLAN.md)
- [docs/archive/INLINE_INTERFACE_DISPATCH_PLAN.md](docs/archive/INLINE_INTERFACE_DISPATCH_PLAN.md)
- [docs/archive/OVERRIDE_VIRTUAL_DISPATCH_PLAN.md](docs/archive/OVERRIDE_VIRTUAL_DISPATCH_PLAN.md)
- [docs/archive/RUNTIME_SURFACE_REDUCTION_PLAN.md](docs/archive/RUNTIME_SURFACE_REDUCTION_PLAN.md)
- [docs/archive/SINGLE_INHERITANCE_PLAN.md](docs/archive/SINGLE_INHERITANCE_PLAN.md)
- [docs/INTERFACES_V1.md](docs/INTERFACES_V1.md)
- [docs/TEST_PLAN_v0.1.md](docs/TEST_PLAN_v0.1.md)
- [docs/GRAMMAR_EBNF.md](docs/GRAMMAR_EBNF.md)
- [docs/REPO_STRUCTURE.md](docs/REPO_STRUCTURE.md)
- [docs/SUGARING_DESIGN.md](docs/SUGARING_DESIGN.md)

## Repository Areas

- `compiler/` - Python stage-0 compiler
	- `compiler/frontend/` contains the syntax-layer modules: lexer, tokens, parser, AST nodes, and AST debug dumping helpers.
- `runtime/` - C runtime and GC
- `std/` - standard library modules layered on the compiler/runtime surface
- `tests/` - unit, golden, integration, and stress tests
- `samples/` - runnable language samples and example programs
- `docs/` - repository-level reference docs

## Current Status

Frontend for MVP v0.1 is largely implemented:

- Lexer, parser, resolver, and type checker are in place with test coverage.
- Program-level module import/export visibility checks are implemented.
- Type checking includes explicit casts, `Obj` up/downcast typing rules, return-path checks, and module-aware type resolution.

The end-to-end compiler pipeline is implemented: resolve, typecheck, semantic lowering/optimization, linking, and assembly emission all run through the default CLI path. Current work is mostly on optimization/runtime hot paths, diagnostics polish, and broadening the standard-library/runtime surface.

Recent backend/runtime updates:
- Full `double` lowering is implemented in codegen, including literals, arithmetic/comparisons, casts, and mixed integer/floating call signatures.
- SysV floating-point ABI paths are implemented for parameters/returns (`xmm0`-`xmm7`) in function calls, method calls, and constructors.
- Callable types plus indirect calls for top-level functions and static methods are implemented end-to-end; instance and interface method references remain out of scope for MVP.
- Single inheritance without overriding is implemented end-to-end, including inherited field/method access, transitive interface implementation, subtype-aware class casts/type tests, and constructor chaining via `super(...)`.
- Explicit `override` declarations and virtual dispatch for ordinary instance methods are implemented end-to-end, including base-typed dispatch, virtual calls through `__self`, and override-aware interface dispatch updates.
- Interface dispatch now uses inline slot-table loads from `RtType` rather than a runtime lookup helper, and runtime interface casts/type tests use the same slot metadata.
- `std.box` primitive wrapper classes (`Box*`) are available for `Obj`-container use cases.
- Fixed-size arrays (`T[]`, `T[](len)`) are implemented end-to-end (typecheck/runtime/codegen/golden tests), including indexing, slicing, and bounds panics.
- `std.io` supports stdout printing, stdin batch reads (`read_stdin`), whole-file reads (`read_file(path)`), and program-argument decoding (`read_program_args()`) using minimal runtime file/byte-array primitives.
- `std.math` exposes a grouped `double` math surface backed by runtime `libm` wrappers, including trigonometric, exponential/logarithmic, rounding, comparison, and classification helpers.

Recent language/runtime additions are reflected directly in [docs/LANGUAGE_MVP_SPEC_V0.1.md](docs/LANGUAGE_MVP_SPEC_V0.1.md).

## Policy Decisions (MVP)

- Null-dereference checks are runtime-only in v0.1; compile-time static null-dereference analysis is intentionally out of scope.
- Imported class name resolution is symmetric for constructor calls and type annotations: unqualified names are local-first, qualified names are explicit, and ambiguous unqualified imported names are compile-time errors.
- Arrays follow a mixed-ownership policy: current implementation is compiler+runtime-first; stdlib-first array wrappers/abstractions are a follow-up direction after MVP (and easier once generics exist).
- See [docs/LANGUAGE_MVP_SPEC_V0.1.md](docs/LANGUAGE_MVP_SPEC_V0.1.md) for the canonical language/runtime policy details.

## Runtime / GC Tests

Runtime test harnesses live under `tests/runtime/` and are built/run via `runtime/Makefile`.

Runtime sources are split by responsibility:
- `runtime/src/runtime.c` - low-level runtime infrastructure (thread state, roots, allocation, panic support)
- `runtime/src/gc.c` - GC implementation
- `runtime/src/gc_trace.c` - runtime trace-frame bookkeeping and summary reporting
- `runtime/src/gc_tracked_set.c` - tracked-allocation set backing GC bookkeeping
- `runtime/src/io.c` - runtime IO/println implementation
	- includes minimal file-handle primitives used by `std/io.nif` (`open/read/close`), while buffering/growth logic stays in stdlib
- `runtime/src/array.c` - fixed-size array allocation, element access, and slicing helpers
- `runtime/src/panic.c` - panic reporting and trace rendering

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
- `make -C runtime test-interface-metadata test-interface-casts test-interface-casts-negative test-interface-dispatch test-interface-dispatch-negative` runs the dedicated interface metadata, cast, and dispatch harnesses.

## Build and Run Helpers

For quick local workflows, use scripts under `scripts/`:

- Default CLI compilation now uses the semantic-lowering backend when type checking is enabled.
- `--source-ast-codegen` is no longer supported on the checked CLI path.

- `scripts/build.sh <input.nif> [output-executable] [--] [nifc-args...]`
	- Compiles to assembly at `<output-executable>.s`
	- Links the runtime and emits `<output-executable>`
	- Example: `./scripts/build.sh samples/arithmetic_loop.nif build/loopy`
	- Example with compiler logging flags: `./scripts/build.sh samples/arithmetic_loop.nif -- --log-level info -v`
- `scripts/run.sh <input.nif> [output-executable] [build-args...] [-- <program-args...>]`
	- Builds via `build.sh`, then executes the produced binary
	- If output path is omitted, defaults to `build/<input-basename>`
	- Example: `./scripts/run.sh samples/arithmetic_loop.nif`
	- Example with compiler flags and program args: `./scripts/run.sh samples/arithmetic_loop.nif --log-level info -- arg1 arg2`

## Test Helper

- `scripts/test.sh`
	- Runs the full Python test suite (`pytest -q`)
	- Runs golden tests (`./scripts/golden.sh`)
	- Runs runtime C harnesses (`make -C runtime test-all`)
	- Example: `./scripts/test.sh`

## Golden Tests

Golden tests live under `tests/golden/`.

- Every `tests/golden/**/test_*_spec.yaml` file defines a golden test.
- Each spec declares one or more test entries under `tests:`.
- Each test entry must set `mode` and explicitly reference `src_file` relative to the spec file.
	- `mode: run` compiles and runs the produced binary against the listed `runs`.
	- `mode: compile-fail` only performs compilation and can assert a compiler error with `compile_error_match`.
	- Example source: `tests/golden/arithmetic/test_addition.nif`
	- Example spec: `tests/golden/arithmetic/test_addition_spec.yaml`
- Each referenced source is compiled once via `scripts/build.sh` and output goes to `build/golden/...`.
- For one `./scripts/golden.sh` invocation, the C runtime is prebuilt once as a static archive and reused across all `mode: run` builds.
- Each test entry can define multiple runs against the compiled binary.

Run the runner:

- `./scripts/golden.sh`
- `./scripts/golden.sh --jobs 8`
- `./scripts/golden.sh --filter 'arithmetic/**'`

Spec format:

```yaml
tests:
	- mode: "run"
		name: "test_addition"
		src_file: "test_addition.nif"
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
	- mode: "compile-fail"
		name: "test_bad_cast"
		src_file: "error_cast_to_interface.nif"
		compile_error_match: "Invalid cast from 'Car' to 'Fruit'"
```

Notes:

- `tests[*].mode` must currently be either `run` or `compile-fail`.
- `compile-fail` tests must not define `runs`.
- `input.stdin` and `input.stdin_file` are mutually exclusive.
- `expect.stderr` and `expect.stderr_file` are mutually exclusive.
- Unspecified input fields are not provided.
- Unspecified expectation fields are not validated.
