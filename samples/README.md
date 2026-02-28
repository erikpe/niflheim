# Niflheim Samples

Small sample `.nif` programs for the current stage-0 compiler backend.

These samples intentionally stay within currently implemented codegen features:
- integer/bool/null expressions
- control flow (`if`, `while`, `return`)
- direct function calls with positional args
- reference casts via `Obj`

Try with:
- `python3 -m compiler.main samples/arithmetic_loop.nif`
- `python3 -m compiler.main samples/function_calls.nif --print-ast`
- `python3 -m compiler.main samples/null_and_cast.nif -o out.s`
- `./scripts/run.sh samples/stdlib_io_println.nif`
- `./scripts/run.sh samples/vec_primes_2_to_1000000.nif`

Entrypoint rule:
- Valid programs are expected to define `fn main() -> i64`.

Additional debugging-oriented sample:
- `samples/runtime_safepoint_gc.nif` (uses `extern fn rt_gc_collect(...)` across multiple functions to inspect safepoint/root-slot codegen)

Stdlib IO sample:
- `samples/stdlib_io_println.nif` (`import std.io; println_i64(...)` without direct runtime calls)

Vec + NewBoxI64 prime sample:
- `samples/vec_primes_2_to_1000000.nif` (collects primes into `Vec` of `NewBoxI64`, then prints aggregate output)
