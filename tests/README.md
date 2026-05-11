# Tests

Test layout (aligned with `docs/TEST_PLAN_v0.1.md`):

- `compiler/`
	- `frontend/`, `resolver/`, `typecheck/`: parser and semantic unit coverage
  - `backend/targets/x86_64_sysv/` and `backend/targets/aarch64/`: emit-only target and ABI-shape coverage; these tests run on all hosts
	- `integration/`: compile-only CLI checks plus native-runtime contract suites
- `golden/`
- `runtime/`

Each test should focus on one scenario and include clear expected behavior.

## Python Compiler Suite Structure

- `tests/compiler/backend/targets/x86_64_sysv/` and `tests/compiler/backend/targets/aarch64/` are the canonical homes for target-emission assertions.
  These tests inspect emitted assembly shape only and stay runnable on both `x86_64` and ARM hosts.

- `tests/compiler/integration/test_cli_codegen.py`, `tests/compiler/integration/test_cli_backend_ir_*.py`, and similar compile-only integration files are architecture-agnostic.
  They assert CLI wiring, emitted assembly, and flag behavior without requiring native execution.

- `tests/compiler/integration/test_cli_runtime_smoke/`, `tests/compiler/integration/test_cli_semantic_codegen_runtime/`, and `tests/compiler/integration/test_cli_interfaces_runtime/` are the canonical native-runtime contract suites.
  They compile and execute programs through the CLI helper surface and are gated by the shared native-runtime capability fixture.
  `x86_64` hosts run them with `x86_64_sysv`, while ARM hosts run them with `aarch64`.

- `tests/compiler/integration/test_build_script.py` follows the same split.
  Portable script validation runs on all hosts, while `build.sh` and `run.sh` success-path execution tests require a native runtime backend.

## Runtime / GC Harnesses

Runtime/GC tests are C harnesses under `tests/runtime/` and are executed via make targets:

- `make -C runtime test` → GC stress scenarios (`test_gc_stress`)
- `make -C runtime test-positive` → root API happy-path checks (`test_roots_positive`)
- `make -C runtime test-negative` → root/global-root misuse checks (expected process failure)
- `make -C runtime test-all` → all runtime harnesses

These runtime harnesses complement Python tests and focus on collector/root ABI behavior directly.

- `make -C runtime test-interface-metadata` → interface metadata layout and slot-table shape checks
- `make -C runtime test-interface-casts` → successful interface cast behavior checks
- `make -C runtime test-interface-casts-negative` → expected-failure interface cast checks
- `make -C runtime test-interface-dispatch` → successful interface slot-table dispatch checks
- `make -C runtime test-interface-dispatch-negative` → expected-failure interface slot-table dispatch checks
