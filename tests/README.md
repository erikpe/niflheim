# Tests

Test layout (aligned with `docs/TEST_PLAN_v0.1.md`):

- `lexer/`
- `parser/`
- `resolver/`
- `typecheck/`
- `codegen/`
- `runtime/`
- `gc/`
- `integration/`
- `stress/`

Each test should focus on one scenario and include clear expected behavior.

## Runtime / GC Harnesses

Runtime GC tests are C harnesses under `runtime/tests/` and are executed via make targets:

- `make -C runtime test` → GC stress scenarios (`test_gc_stress`)
- `make -C runtime test-positive` → root API happy-path checks (`test_roots_positive`)
- `make -C runtime test-negative` → root/global-root misuse checks (expected process failure)
- `make -C runtime test-all` → all runtime harnesses

These runtime harnesses complement Python tests and focus on collector/root ABI behavior directly.
