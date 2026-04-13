# Niflheim Samples

Runnable `.nif` programs for the current compiler/runtime surface.

The sample set now covers a broader implemented surface, including:
- primitive arithmetic and control flow
- classes, constructors, `Obj` casts, and nullable references
- arrays, slicing, and `for ... in`
- single inheritance, `override`, interfaces, and interface dispatch
- stdlib I/O plus `Vec`/`Map`/box-based programs
- larger end-to-end workloads such as the VM benchmark

Try with:
- `python3 -m compiler.main samples/arithmetic_loop.nif`
- `python3 -m compiler.main samples/null_and_cast.nif -o out.s`
- `./scripts/run.sh samples/stdlib_io_println.nif`
- `./scripts/run.sh samples/vec_primes_2_to_1000000.nif`

For smaller tutorial-style examples, see `samples/examples/`.

Entrypoint rule:
- Valid programs are expected to define `fn main() -> i64`.

Additional debugging-oriented sample:
- `samples/runtime_safepoint_gc.nif` (uses `extern fn rt_gc_collect(...)` across multiple functions to inspect safepoint/root-slot codegen)

Stdlib IO sample:
- `samples/stdlib_io_println.nif` (`import std.io as io; io.println_i64(...)` without direct runtime calls)

Vec + BoxI64 prime sample:
- `samples/vec_primes_2_to_1000000.nif` (collects primes into `Vec` of `BoxI64`, then prints aggregate output)

Multi-module regression sample:
- `samples/vm_benchmark/` (larger host-VM workload used as a correctness/regression stress program)
