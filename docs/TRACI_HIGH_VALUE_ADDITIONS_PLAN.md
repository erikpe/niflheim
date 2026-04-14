# Traci High-Value Additions Plan

This document turns the short-term additions from [TRACI_PORT_FEASIBILITY_ANALYSIS.md](TRACI_PORT_FEASIBILITY_ANALYSIS.md) into an implementation plan.

Scope:

- add a grouped `std.math` surface for floating-point work
- add high-level file output via `std.io.write_file`
- add deterministic RNG support
- add specialized primitive dynamic-buffer helpers

This is intentionally a runtime/stdlib plan, not a Traci renderer plan.

## Guiding Decisions

- Math should not stop at the exact Traci call sites. Add the common neighboring functions that are usually shipped together so the surface is coherent and does not need immediate follow-up churn.
- Math semantics should be Java-like where practical, but they do not need to be bit-exact. Matching broad behavior around NaN, infinities, signed zero, and domain/range edge cases matters more than reproducing every last bit pattern.
- File output should start as a high-level public API: `std.io.write_file(...)`. Do not expose a large handle-oriented write API in user code yet.
- Primitive dynamic buffers should start as specialized, explicit implementations, even if that means copying the current `std.vec` structure. Do not block this work on generics or a shared container framework.
- Keep the public APIs small and stable. If a helper is only needed internally, keep it in the runtime or in a private stdlib function.

## Recommended Delivery Order

1. `std.math`
2. `std.io.write_file`
3. deterministic RNG
4. primitive dynamic buffers
5. docs/test-plan refresh after the code lands

That order keeps the highest-value Traci blockers first while also avoiding unnecessary coupling between workstreams.

## Workstream 1: `std.math`

## Goal

Provide a coherent floating-point math surface that is good enough for parser/runtime use now and renderer math later.

## Recommended Public API

Add a new module `std/math.nif` exporting top-level functions.

Recommended first pass:

- Trigonometric: `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`
- Exponential / logarithmic: `exp`, `log`, `log10`, `pow`, `sqrt`, `cbrt`
- Rounding: `floor`, `ceil`, `round`, `trunc`
- Magnitude / comparison helpers: `abs`, `min`, `max`, `hypot`

Optional second-pass additions if the first patch stays small enough:

- `expm1`, `log1p`, `sinh`, `cosh`, `tanh`, `is_nan`, `is_infinite`

## Semantic Notes

- Back the implementation with `libm` and keep the Niflheim semantics close to Java `Math` where signatures line up naturally.
- Let NaN and infinity propagate instead of inventing custom panic behavior for normal floating-point math.
- Keep domain/range behavior library-driven unless there is a strong reason to normalize it. The main requirement is predictability and documentation, not bit-for-bit Java parity.
- Because Niflheim has no overloading, prefer a consistent `double -> double` surface for the core math functions. If an integer-returning rounding helper is needed later, add a clearly named companion instead of overloading `round`.

## Files To Change

Add:

- [std/math.nif](../std/math.nif)
- `runtime/include/math_rt.h`
- [runtime/src/math.c](../runtime/src/math.c)
- [tests/golden/std/math/test_math.nif](../tests/golden/std/math/test_math.nif)
- [tests/golden/std/math/test_math_spec.yaml](../tests/golden/std/math/test_math_spec.yaml)
- [tests/runtime/test_math_runtime.c](../tests/runtime/test_math_runtime.c)

Update:

- [runtime/include/runtime.h](../runtime/include/runtime.h) to include the new math header
- [runtime/Makefile](../runtime/Makefile) to compile the new runtime source and link runtime harnesses with `-lm`
- [scripts/build.sh](../scripts/build.sh) to link produced executables with `-lm`
- [tests/compiler/integration/helpers.py](../tests/compiler/integration/helpers.py) to link integration-built executables with the new runtime source and `-lm`
- [README.md](../README.md), [docs/LANGUAGE_MVP_SPEC_V0.1.md](LANGUAGE_MVP_SPEC_V0.1.md), and [docs/REPO_STRUCTURE.md](REPO_STRUCTURE.md) once the feature lands

## Implementation Checklist

- [x] Freeze the first-pass API list and naming in [std/math.nif](../std/math.nif).
- [x] Add runtime declarations in `runtime/include/math_rt.h`.
- [x] Implement thin `libm` wrappers in `runtime/src/math.c`.
- [x] Include the new header from [runtime/include/runtime.h](../runtime/include/runtime.h).
- [x] Add the new runtime source to [runtime/Makefile](../runtime/Makefile).
- [x] Add `-lm` to runtime harness linking in [runtime/Makefile](../runtime/Makefile).
- [x] Add the new runtime source and `-lm` to [scripts/build.sh](../scripts/build.sh).
- [x] Add the new runtime source and `-lm` to [tests/compiler/integration/helpers.py](../tests/compiler/integration/helpers.py).
- [x] Export the public Niflheim wrappers in [std/math.nif](../std/math.nif).
- [x] Add golden coverage for representative normal, boundary, NaN, and infinity cases.
- [x] Add a small C runtime harness that checks wrapper behavior against `libm` on representative inputs.

## Testing Checklist

- [x] Golden tests for ordinary results: `sin(0)`, `cos(0)`, `sqrt(9)`, `pow(2, 10)`, `floor(1.75)`, `ceil(-1.25)`.
- [x] Golden tests for sign/edge cases: negative zero handling where observable, `abs(-0.0)`, `atan2` quadrants, `min`/`max` ordering.
- [x] Golden tests for exceptional values: NaN propagation, infinity propagation, domain-ish cases such as `sqrt(-1.0)` and `log(-1.0)` if the chosen `libm` behavior is accepted.
- [x] Runtime harness checks that the exported C wrappers return values close to direct `libm` calls for representative inputs.
- [x] Integration smoke test that imports `std.math`, compiles, links, and executes through the full CLI path.

Recommended commands once implemented:

- `./scripts/golden.sh --filter 'std/math/**' --print-per-run`
- `make -C runtime test-math-runtime`
- `pytest tests/compiler/integration -k math -q`

## Workstream 2: High-Level File Output

## Goal

Add the smallest useful output surface for generated content and renderer output without committing yet to a full streaming file API.

## Recommended Public API

Extend [std/io.nif](../std/io.nif) with:

- `write_file(path: Str, content: Str) -> unit`

The public API should stay high-level for now. User code should not need to manage file handles to write one file.

## Runtime Shape

Prefer a single runtime helper for the first patch, for example:

- `rt_file_write_all(path: u8[], value: u8[]) -> unit`

That keeps the public API small and avoids immediately duplicating the handle-oriented read design on the write side.

## Files To Change

Update:

- [std/io.nif](../std/io.nif)
- [runtime/include/io.h](../runtime/include/io.h)
- [runtime/src/io.c](../runtime/src/io.c)
- [README.md](../README.md)
- [docs/LANGUAGE_MVP_SPEC_V0.1.md](LANGUAGE_MVP_SPEC_V0.1.md)

Add:

- `tests/golden/std/io/test_write_file.nif`
- `tests/golden/std/io/test_write_file_spec.yaml`
- `tests/compiler/integration/test_cli_runtime_smoke/test_write_file_runtime.py`

## Implementation Checklist

- [x] Choose one minimal runtime write helper shape and document it in [runtime/include/io.h](../runtime/include/io.h).
- [x] Implement the helper in [runtime/src/io.c](../runtime/src/io.c) using ordinary buffered C file IO.
- [x] Add `write_file(path: Str, content: Str) -> unit` to [std/io.nif](../std/io.nif).
- [x] Overwrite/truncate existing files by default and panic when the path cannot be opened.
- [x] Reuse existing panic style for failed open/write/close operations.
- [x] Keep stdout writing behavior unchanged; this workstream is additive.
- [x] Add at least one integration test that verifies bytes on disk through a real compiled binary.

## Testing Checklist

- [x] Golden test that writes a small string payload to a file path passed in via argv, reads it back with `read_file`, and prints the content.
- [x] Golden test for overwriting an existing file.
- [x] Golden test for empty writes.
- [x] Golden test for failure behavior on an invalid path.
- [x] Python integration test that runs the compiled binary under `tmp_path` and asserts the resulting file bytes directly.

Recommended commands once implemented:

- `./scripts/golden.sh --filter 'std/io/**' --print-per-run`
- `pytest tests/compiler/integration/test_cli_runtime_smoke/test_write_file_runtime.py -q`

## Workstream 3: Deterministic RNG

## Goal

Provide deterministic, seedable randomness that is stable enough for tests and scene-language use.

## Recommended Public API

Add a new module `std/random.nif` with an explicit RNG object.

Recommended first pass:

- `class Random`
- `constructor(seed: u64)`
- `fn next_u64() -> u64`
- `fn next_bool() -> bool`
- `fn next_double() -> double` returning a value in `[0.0, 1.0)`
- `fn next_bounded(bound: u64) -> u64`
- `fn randint(min_inclusive: i64, max_inclusive: i64) -> i64`

## Design Recommendation

- Implement the generator in stdlib Nif code if possible so the algorithm is fully visible and deterministic across environments.
- Use a simple, well-understood algorithm with explicit test vectors. `SplitMix64` is a good first choice because it is tiny and deterministic.
- Implement bounded integer sampling with rejection sampling rather than plain modulo to avoid accidental bias.

## Files To Change

Add:

- `std/random.nif`
- `tests/golden/std/random/test_random.nif`
- `tests/golden/std/random/test_random_spec.yaml`

Update:

- [docs/LANGUAGE_MVP_SPEC_V0.1.md](LANGUAGE_MVP_SPEC_V0.1.md)
- [README.md](../README.md)
- [docs/REPO_STRUCTURE.md](REPO_STRUCTURE.md)

## Implementation Checklist

- [x] Choose and document the RNG algorithm in `std/random.nif`.
- [x] Keep the initial implementation stdlib-only unless profiling proves a runtime helper is needed.
- [x] Define exact seed behavior and sequence stability as part of the public contract.
- [x] Implement `next_bounded` with rejection sampling.
- [x] Implement `next_double` with a stable conversion strategy from integer state to `[0.0, 1.0)`.
- [x] Add deterministic golden tests with fixed seeds and expected outputs.

## Testing Checklist

- [x] Same-seed / same-sequence golden test.
- [x] Different-seed / different-sequence golden test.
- [x] `next_bounded` tests for `bound = 1`, small bounds, and large bounds.
- [x] `randint` tests for inclusive endpoints and negative ranges.
- [x] `next_double` tests for range only (`>= 0.0`, `< 1.0`) rather than brittle exact decimal text unless the formatting is intentionally frozen.

Recommended commands once implemented:

- `./scripts/golden.sh --filter 'std/random/**' --print-per-run`

## Workstream 4: Specialized Primitive Dynamic Buffers

## Goal

Add a small family of growable primitive buffers that remove the need to route parser/output/math-heavy code through `Obj` boxing.

## Recommended Public API

Start with explicit specialized modules rather than a shared abstraction.

Recommended modules and classes:

- `std/bytebuf.nif` exporting `ByteBuf`
- `std/i64vec.nif` exporting `I64Vec`
- `std/u64vec.nif` exporting `U64Vec`
- `std/doublevec.nif` exporting `DoubleVec`

Recommended common surface:

- `new()`
- `with_capacity(capacity: u64)`
- `len()`
- `clear()`
- `push(value)`
- `index_get(index: i64)`
- `index_set(index: i64, value)`
- `slice_get(begin: i64, end: i64)`
- `slice_set(begin: i64, end: i64, value)`
- `to_array()`

Recommended `ByteBuf` extras:

- `append_u8(value: u8)`
- `append_bytes(value: u8[])`

## Design Recommendation

- Copy the current [std/vec.nif](../std/vec.nif) structure instead of trying to invent a generic container substrate now.
- Use primitive arrays for backing storage: `u8[]`, `i64[]`, `u64[]`, `double[]`.
- Keep the modules independent even if that means repeated code. The duplication is acceptable at this stage because the semantics are simple and the specialization is the point.

## Files To Change

Add:

- `std/bytebuf.nif`
- `std/i64vec.nif`
- `std/u64vec.nif`
- `std/doublevec.nif`
- `tests/golden/std/buffers/test_primitive_buffers.nif`
- `tests/golden/std/buffers/test_primitive_buffers_spec.yaml`

Update:

- [README.md](../README.md)
- [docs/REPO_STRUCTURE.md](REPO_STRUCTURE.md)
- [docs/LANGUAGE_MVP_SPEC_V0.1.md](LANGUAGE_MVP_SPEC_V0.1.md) if these become part of the documented stdlib baseline

## Implementation Checklist

- [ ] Freeze the initial module names and class names.
- [ ] Copy the current growth/shrink/index-normalization structure from [std/vec.nif](../std/vec.nif).
- [ ] Replace `Obj[]` storage with primitive array storage in each specialized module.
- [ ] Add `to_array()` to each module so the buffers integrate with existing array-based APIs.
- [ ] Add `ByteBuf.append_bytes(u8[])` so parser/file-output code has a direct fast path.
- [ ] Keep `ByteBuf` first-class and finish it before adding the numeric buffers.
- [ ] Add at least one negative-path bounds/slice test per module family.

## Testing Checklist

- [ ] Golden tests for push/grow/index/slice behavior on each specialized buffer type.
- [ ] Golden tests for negative indexing if the `Vec`-style normalization policy is preserved.
- [ ] Golden tests for `to_array()` round-trips.
- [ ] Golden tests for `ByteBuf.append_bytes` across multi-grow workloads.
- [ ] Golden tests for bounds and slice panics.

Recommended commands once implemented:

- `./scripts/golden.sh --filter 'std/buffers/**' --print-per-run`

## Cross-Cutting Follow-Through

After each workstream lands, update the live docs so the implementation and the docs do not drift again.

## Docs Checklist

- [ ] Update [README.md](../README.md) feature summary and stdlib/runtime file lists.
- [ ] Update [docs/REPO_STRUCTURE.md](REPO_STRUCTURE.md) with any new stdlib/runtime docs or modules.
- [ ] Update [docs/LANGUAGE_MVP_SPEC_V0.1.md](LANGUAGE_MVP_SPEC_V0.1.md) where the additions become part of the baseline language/runtime surface.
- [ ] Update [docs/TEST_PLAN_v0.1.md](TEST_PLAN_v0.1.md) with the new testing coverage expectations.

## Suggested Patch Breakdown

To keep review and debugging manageable, split the work into small patches:

1. `std.math` runtime + stdlib + tests
2. `write_file` runtime + stdlib + tests
3. `std.random` + tests
4. `ByteBuf`
5. numeric primitive vectors
6. docs refresh

That sequence keeps link/debug failures local and avoids mixing unrelated runtime changes in one patch.