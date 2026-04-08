# VM Benchmark Plan

Status: slice 1 implemented.

This document defines a concrete plan for implementing a larger regression benchmark program based on a small bytecode virtual machine.

The primary goal is not to build the most elegant or efficient VM.

The primary goal is to exercise the Niflheim compiler and runtime as broadly as possible with a program that is:

- materially larger than the current AoC-style samples
- deterministic and easy to verify exactly
- sensitive to small semantic regressions
- understandable to users reading the benchmark source

If there is a choice between implementation simplicity or runtime efficiency on one side, and broader compiler-feature coverage on the other side, prefer broader compiler-feature coverage.

## Purpose

The current sample and golden programs are good for focused feature coverage, but they are still relatively narrow workloads.

What is missing is a larger end-to-end program that combines many language features in one place and produces outputs that are easy to validate mechanically.

The benchmark should help catch regressions caused by:

- optimization changes
- semantic refactors
- lowering refactors
- codegen refactors
- runtime behavior changes
- ABI or calling-convention bugs
- module-loading and import-resolution bugs
- subtle dispatch or cast correctness bugs

The benchmark should be useful in three modes:

1. a manually runnable sample program under `samples/`
2. an exact-output golden test
3. a larger regression program that can be rerun after substantial compiler work

## Why A VM Benchmark Is A Good Fit

A small interpreter is a good regression workload because it naturally combines:

- loops and branch-heavy control flow
- interface and virtual dispatch in the host implementation
- arrays, indexing, slicing, and `for ... in`
- object construction and constructor-heavy setup
- checked casts, type tests, and `Obj`-typed storage
- string handling and exact textual output
- function and method calls across many abstraction boundaries

It also produces exact expected results.

Even small semantic bugs usually change:

- return values
- instruction counts
- branch counts
- register state
- memory state
- emitted output
- final aggregate checksums

That makes the benchmark a strong regression detector.

## Success Criteria

The finished benchmark should satisfy all of the following:

- the guest language is recognizable and understandable to a user
- the host VM implementation uses a broad slice of implemented Niflheim features
- the host VM implementation is split across a small number of meaningful modules so module loading and cross-module resolution are exercised implicitly
- exact expected outputs are known and easy to compare in golden tests
- small semantic deviations are likely to change one or more reported values immediately
- the program is large enough to be meaningfully beyond current AoC-style workloads
- the benchmark remains feasible to implement incrementally

## Testing-First Design Rules

The benchmark should follow these rules throughout implementation:

1. prefer broader compiler feature coverage over host-side efficiency
2. prefer deterministic exact checks over approximate or visual validation
3. prefer multiple independently checked outputs over one final number only
4. prefer understandable guest programs over clever but opaque encodings
5. prefer host-side abstractions that create meaningful dispatch opportunities
6. deliberately include both monomorphic and truly polymorphic host call sites
7. avoid depending on undefined behavior or unspecified output ordering

Concretely, that means:

- do not add a guest-language parser if direct host-side program construction is simpler
- do use interfaces and inheritance in the host VM even where a flatter implementation would be faster
- do store some values in `Obj[]` and recover them through checked casts, even if a more concrete representation would be smaller
- do expose both interface-typed and base-class-typed arrays in the host implementation so dispatch optimizations have real opportunities
- do split the host VM across several purposeful modules so imports, cross-module references, and module wiring are part of the exercised compiler surface

## Proposed Benchmark Shape

Implement a small deterministic bytecode VM for a toy language that looks like a stripped-down imperative scripting VM.

Recommended guest model:

- register-based VM with a small fixed register file per frame
- `i64`-first semantics, with selected support for `bool`, `double`, and object-like values through boxed constants
- linear `i64[]` memory plus `Obj[]` constant pool
- explicit branch and call instructions
- a small builtin interface for host-provided operations

The guest language does not need to be practical for real-world use.

It should only be recognizable enough that a user can understand the benchmark cases quickly.

## Guest Language Design

The guest language should be presented as a simple bytecode assembly with mnemonics such as:

- `load_const dst, const_id`
- `move dst, src`
- `add dst, a, b`
- `sub dst, a, b`
- `mul dst, a, b`
- `div dst, a, b`
- `mod dst, a, b`
- `cmp_eq dst, a, b`
- `cmp_lt dst, a, b`
- `jump target`
- `jump_if_true reg, target`
- `jump_if_false reg, target`
- `load_mem dst, base, index`
- `store_mem base, index, src`
- `slice_copy dst_base, src_base, begin, end`
- `call func_id, argc`
- `call_builtin builtin_id, argc`
- `ret src`
- `halt`

Optional later opcodes, only if needed for more coverage:

- `load_global`
- `store_global`
- `type_test`
- `checked_cast`
- `load_field`
- `store_field`

The benchmark should construct these programs directly in Niflheim source using host-side constructors or a small builder helper.

Do not add a parser for the guest language in the first implementation.

## Host VM Design In Niflheim

The host VM should intentionally use a broad set of Niflheim features.

Recommended core types:

- `interface Instruction`
  - `fn execute(vm: Vm, frame: Frame) -> unit;`
- `class BaseInstruction implements Instruction`
  - shared opcode metadata, debug id, and default helpers
- instruction families:
  - `class BinaryOp extends BaseInstruction`
  - `class JumpOp extends BaseInstruction`
  - `class MemoryOp extends BaseInstruction`
  - `class CallOp extends BaseInstruction`
- concrete instruction classes:
  - `AddOp`, `SubOp`, `MulOp`, `DivOp`, `ModOp`
  - `JumpOp`, `JumpIfTrueOp`, `JumpIfFalseOp`
  - `LoadMemOp`, `StoreMemOp`, `SliceCopyOp`
  - `CallOp`, `CallBuiltinOp`, `RetOp`, `HaltOp`
- `interface Builtin`
  - `fn invoke(vm: Vm, frame: Frame, argc: u64) -> unit;`
- `class Vm`
- `class Frame`
- `class Program`
- `class FunctionInfo`
- `class BenchmarkCase`
- `class BenchmarkResult`

Recommended storage:

- `Instruction[]` for instruction stream
- `FunctionInfo[]` for guest functions
- `Obj[]` for constant pool
- `i64[]` for linear memory
- `Obj[]` for builtin table or boxed guest data
- `Str[]` or `u8[]` trace/output buffers if needed

## Recommended Module Split

The benchmark should not live in one large `.nif` file.

Split it across a small number of meaningful modules so module loading and cross-module resolution become part of the benchmarked compiler surface.

Recommended sample layout:

- `samples/vm_benchmark/main.nif`
  - benchmark entrypoint that assembles the cases, runs them, and prints exact results
- `samples/vm_benchmark/opcodes.nif`
  - opcode ids, shared constants, and small shared helpers
- `samples/vm_benchmark/model.nif`
  - `Program`, `FunctionInfo`, `BenchmarkCase`, `BenchmarkResult`, and related data structures
- `samples/vm_benchmark/instructions.nif`
  - `Instruction` interface, base instruction families, and concrete instruction classes
- `samples/vm_benchmark/builtins.nif`
  - `Builtin` interface and builtin implementations
- `samples/vm_benchmark/runtime.nif`
  - `Vm`, `Frame`, execution loop, validation helpers, and checksum helpers
- `samples/vm_benchmark/cases.nif`
  - benchmark-case builders and expected metadata

Why this split is recommended:

- it exercises module loading and import resolution implicitly
- it exercises cross-module interface implementation and inheritance
- it exercises cross-module constructor, function, and method calls
- it exercises qualified and unqualified symbol resolution across modules
- it keeps the benchmark understandable by separating model, execution, and case construction concerns

Guidelines for the split:

- keep interfaces in one module and implementations in another where practical
- keep some base classes in one module and derived classes in another where practical
- keep case builders separate from execution machinery so object construction crosses module boundaries
- use qualified module access where it improves clarity or intentionally exercises module-qualified resolution
- avoid artificial import cycles; negative cycle coverage belongs in focused resolver tests, not in this benchmark

## Deliberate Feature Coverage

The host VM should intentionally exercise the following compiler features.

### Module Loading And Cross-Module Resolution

The host VM should deliberately exercise:

- imports across several modules
- cross-module class references
- cross-module interface implementation
- cross-module inheritance
- cross-module constructor and method calls
- qualified module member access where helpful

This broadens coverage beyond expression lowering and runtime behavior alone.

It makes the benchmark more useful for regressions in:

- resolver behavior
- imported type lookup
- ambiguity handling
- cross-module declaration wiring
- refactors that accidentally break import or symbol-table assumptions

### Interfaces

Use interfaces for:

- instruction execution
- builtin dispatch
- optional trace or validation sinks if needed

This creates direct opportunities to exercise:

- interface calls
- interface-typed arrays and locals
- closed-world monomorphic interface optimization opportunities

### Inheritance And Virtual Dispatch

Use base instruction families and subclasses for:

- arithmetic instruction families
- control-flow instruction families
- memory instruction families

Some subclasses should inherit a shared implementation body unchanged.

This deliberately creates host-side cases where:

- virtual dispatch should remain dynamic
- virtual dispatch should collapse by exact type
- virtual dispatch should collapse by closed-world monomorphism because multiple subclasses still share one inherited body

### Arrays And Structural Sugar

Use arrays heavily for:

- instruction streams
- register files
- guest memory
- case definitions
- trace accumulation

The host implementation should use:

- indexing `x[i]`
- indexed writes `x[i] = v`
- slices `x[a:b]`
- slice writes where useful
- `for ... in` where semantics remain easy to verify

### Constructors And Object Setup

Use constructor-heavy setup for:

- benchmark-case creation
- function metadata creation
- constant-pool setup
- instruction object creation

The benchmark should intentionally create a large object graph during startup so constructor lowering and initialization paths are exercised meaningfully.

### `Obj`, Checked Casts, And Type Tests

Use `Obj[]` constant pools and recover typed values through:

- checked casts
- `is` tests where appropriate
- boxed primitive wrapper classes from `std.box`

This should exercise:

- reference casts
- interface casts
- subtype-aware class casts
- failures caused by incorrect cast/type-test semantics

### Calls And ABI Surface

The host VM should intentionally create many ordinary calls through:

- free functions
- instance methods
- interface methods
- builtin invocations

This increases sensitivity to:

- argument ordering bugs
- return-path bugs
- register/stack ABI mistakes
- root-liveness mistakes around calls

### Doubles

Include one small exact-double case using values that are exactly representable in binary, such as:

- `0.5`
- `1.25`
- `2.0`
- `8.0`

This broadens feature coverage without introducing fuzzy verification.

## Verification Strategy

Verification must be exact and multi-layered.

Do not validate the benchmark only through one final checksum.

Each benchmark case should report:

- case name
- return value
- executed instruction count
- branch-taken count
- register checksum
- memory checksum
- output checksum

Suggested output shape:

```text
case=arith ret=4187 steps=12044 branches=2021 regs=8821 mem=281993 out=0
case=recursion ret=10946 steps=9033 branches=1422 regs=6711 mem=112 out=0
case=sieve ret=1229 steps=45510 branches=19876 regs=1742 mem=991287 out=0
final=18446744073123456789
```

Why this matters:

- wrong control flow changes `steps` or `branches`
- wrong arithmetic changes `ret` or `regs`
- wrong memory semantics change `mem`
- wrong string or builtin behavior changes `out`
- aggregate checksum catches mismatches not obvious in one field alone

The exact stdout for the benchmark should be captured in a golden test.

## Benchmark Case Suite

Implement the benchmark as a suite of named guest programs inside one host program.

Recommended cases:

### 1. Arithmetic Mixer

Purpose:

- exercise arithmetic, comparisons, branches, and loops
- stress simple instruction dispatch hot paths

Checks:

- final return value
- steps
- branch count
- register checksum

### 2. Recursive Calls

Purpose:

- exercise frame setup/teardown and nested calls
- stress control flow and call ABI correctness

Suggested guest workload:

- factorial
- fibonacci-like recurrence with bounded input

Checks:

- final return value
- steps
- call count checksum if tracked

### 3. Sieve Or Dense Array Workload

Purpose:

- stress indexed reads/writes, loops, and memory integrity
- create long-running deterministic array-heavy behavior

Checks:

- prime count or equivalent exact return value
- memory checksum
- register checksum

### 4. Slice And Copy Workload

Purpose:

- exercise slice creation and copy semantics in the host VM
- stress off-by-one correctness

Suggested guest workload:

- copy segment
- reverse segment
- overlapping or staged copy patterns, if practical

Checks:

- memory checksum
- exact selected-cell values

### 5. Builtin Dispatch Workload

Purpose:

- exercise interface-dispatched builtins and boxed argument handling
- stress `Obj` constant pool access and checked casts

Suggested builtins:

- checksum mix
- append trace tag
- fold range

Checks:

- output checksum
- final return value

### 6. Type And Cast Workload

Purpose:

- exercise `Obj`, checked casts, type tests, and subtype/interface behavior

Suggested guest model:

- boxed constants in `Obj[]`
- host-side cast recovery for builtin operands

Checks:

- exact return values from successful casts/tests
- explicit panic tests may be added separately for negative cases if useful

### 7. Branch Maze

Purpose:

- maximize sensitivity to branch-target or condition bugs
- make tiny control-flow deviations easy to detect

Checks:

- instruction count
- branch count
- final aggregate value

### 8. Exact-Double Case

Purpose:

- exercise double lowering and mixed numeric paths without tolerance-based verification

Checks:

- exact integer-cast final result
- output checksum if a formatted trace is emitted

## Keep The Guest Programs Understandable

The guest benchmark cases should be recognizable to a user reading the source.

Avoid opaque generated data blobs.

Prefer readable helpers such as:

- `build_arithmetic_case()`
- `build_recursive_case()`
- `build_sieve_case()`
- `build_slice_case()`

Each helper should construct a named `BenchmarkCase` with:

- a human-readable case name
- a small comment describing the intended behavior
- expected result metadata stored next to the case definition

## Output And Test Samples

The implementation should provide three layers of runnable artifacts.

### Manual Sample

- `samples/vm_benchmark/`
  - `main.nif`
  - `opcodes.nif`
  - `model.nif`
  - `instructions.nif`
  - `builtins.nif`
  - `runtime.nif`
  - `cases.nif`

Purpose:

- easy manual runs during development
- readable example of a larger Niflheim program

### Golden Test

- `tests/golden/lang/test_vm_benchmark/...`

Purpose:

- exact stdout validation
- stable regression coverage in the golden suite

The golden test should validate the full output line-by-line.

### Optional Faster Smoke Variant

- `samples/vm_benchmark_smoke/` or a build-time flag inside one sample

Purpose:

- quicker local iteration while preserving the same host-side design

This is optional, but useful if the full benchmark becomes noticeably larger than ordinary samples.

## Repo Touch Points

Recommended first implementation footprint:

- `samples/vm_benchmark/`
  - `main.nif`
  - `opcodes.nif`
  - `model.nif`
  - `instructions.nif`
  - `builtins.nif`
  - `runtime.nif`
  - `cases.nif`
- `tests/golden/lang/test_vm_benchmark/test_vm_benchmark.nif`
- `tests/golden/lang/test_vm_benchmark/test_vm_benchmark_spec.yaml`

Optional later additions:

- `samples/vm_benchmark_smoke/`
  - `main.nif`
  - mirrored supporting modules or a reduced subset
- a README file under the golden test directory documenting expected output layout

Avoid introducing compiler changes solely to make the benchmark easier unless the benchmark exposes a genuine missing language or runtime capability.

## Ordered Implementation Checklist

## Slice 1: Define The Host VM Skeleton

- [x] create the multi-file `samples/vm_benchmark/` layout with `main.nif`, `opcodes.nif`, `model.nif`, `instructions.nif`, `builtins.nif`, `runtime.nif`, and `cases.nif`
- [x] create `Vm`, `Frame`, `Program`, `FunctionInfo`, `BenchmarkCase`, and `BenchmarkResult`
- [x] define the `Instruction` and `Builtin` interfaces across module boundaries
- [x] add a base instruction hierarchy with a few concrete instructions
- [x] build one minimal runnable case with exact output

Test:

- [x] run the sample manually
- [x] add one golden case for the minimal benchmark output
- [x] confirm imports and cross-module references stay readable and deterministic

## Slice 2: Add Core Arithmetic And Branch Execution

- implement register-based arithmetic instructions
- implement comparisons and conditional jumps
- add the arithmetic mixer and branch maze cases
- report exact return values, steps, and branch counts

Test:

- extend the golden expected output
- verify branch-sensitive cases change predictably under local debugging

## Slice 3: Add Calls And Nested Frames

- implement guest function metadata and `call`/`ret`
- add the recursive calls case
- ensure frame-local registers and return-value handling are exact

Test:

- add recursive benchmark outputs to the golden file
- verify exact instruction counts and return values

## Slice 4: Add Array-Heavy Memory Workloads

- implement linear memory over `i64[]`
- implement memory read/write instructions
- add sieve or dense array benchmark
- add slice/copy benchmark

Test:

- verify memory checksum lines exactly
- ensure small indexing mistakes visibly change expected output

## Slice 5: Add Builtin Dispatch And `Obj` Constant Pools

- store constants in `Obj[]`
- recover them through checked casts
- implement builtin dispatch through the `Builtin` interface
- add builtin-driven benchmark cases

Test:

- verify builtin output checksums and return values
- ensure interface-dispatch paths are exercised in the host VM

## Slice 6: Add Inheritance-Heavy Instruction Families

- refactor concrete instructions under base instruction families
- deliberately keep some shared inherited execution bodies unchanged
- add comments identifying intended monomorphic and polymorphic host dispatch sites

Test:

- keep golden output unchanged
- add comments or small internal checks so the benchmark remains understandable to future maintainers

## Slice 7: Add Exact-Double Coverage

- add one exact-double guest case using only binary-exact literals
- fold its result into the same exact-output reporting scheme

Test:

- verify exact final integer-cast or checksum results in the golden output

## Slice 8: Finalize Aggregate Verification

- combine per-case results into one final aggregate checksum
- ensure every case contributes to the aggregate in a deterministic way
- make the final output stable and line-oriented

Test:

- lock the full stdout in golden coverage
- run the full pytest and golden suites

## Additional Deliberate Stress Points

While implementing the host VM, prefer patterns that stress compiler behavior even if they are not the smallest implementation.

Examples:

- walk `Instruction[]` through an `Instruction` interface reference rather than flattening everything into one giant switch-like function
- keep builtin invocation on an interface rather than special-casing builtin ids directly everywhere
- use `Obj[]` constant pools and checked casts instead of only concrete typed pools
- use base instruction families and subclasses to create real override opportunities
- keep some loops over base-typed or interface-typed receivers so current and future devirtualization passes have real opportunities to specialize

## Non-Goals

This plan does not include:

- implementing a guest-language parser in the first version
- building a practical production VM
- prioritizing raw runtime throughput over feature coverage
- introducing nondeterministic workloads
- relying on approximate or fuzzy output comparison
- turning the benchmark into a performance benchmark before it is a strong correctness benchmark

## Recommended End State

The recommended final benchmark should look like this:

- one readable Niflheim sample program that constructs and runs several guest programs
- one exact golden stdout expectation covering all benchmark cases
- one aggregate final checksum derived from many independently checked per-case values
- a host VM implementation that intentionally exercises interfaces, inheritance, arrays, structural sugar, constructors, calls, casts, and exact-double paths

That gives the repository a larger regression workload whose purpose is first and foremost compiler validation.

It should be treated as a correctness stress program, not primarily as a VM project.