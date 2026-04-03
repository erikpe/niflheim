# Sugaring Design Decision

## Status

Accepted (locked direction for sugaring protocols).

## Context

Niflheim already has sugar forms (`[]`, `[:]`, index assignment) and structural lowering behavior for container-like types. `for elem in collection { ... }` is also implemented, and it should remain free of hard-coded container names.

Some types (for example maps) intentionally use `index_get(key)` where the argument is a key, not a positional index. Reusing the same method contract for both indexing sugar and iteration sugar would create ambiguity and accidental eligibility.

## Decision

Adopt two distinct structural sugar protocols.

### 1) Indexing/Slicing Sugar Protocol

Canonical lowering:

- `obj[index]` -> `obj.index_get(index)`
- `obj[index] = value` -> `obj.index_set(index, value)`
- `obj[begin:end]` -> `obj.slice_get(begin, end)`
- `obj[begin:end] = value` -> `obj.slice_set(begin, end, value)`

Structural eligibility:

- `index_get(K) -> R`
- `index_set(K, W) -> unit`
- `slice_get(i64, i64) -> U`
- `slice_set(i64, i64, U) -> unit`

Notes:

- `K` is method-signature driven and may be any type (not hard-coded to `i64`).
- Read and write sugar are independent (`R` and `W` may differ).
- Slice bounds stay `i64`.

### 2) For-In Iteration Sugar Protocol

Surface syntax:

- `for elem in collection { ... }`

Canonical lowering target (conceptual):

```nif
{
	var __for_coll: C = collection;
	var __for_len: i64 = (i64)__for_coll.iter_len();
	var __for_i: i64 = 0;
	while __for_i < __for_len {
		var elem: T = __for_coll.iter_get(__for_i);
		// body
		__for_i = __for_i + 1;
	}
}
```

Structural eligibility:

- `iter_len() -> u64`
- `iter_get(i64) -> T`

Notes:

- `T` is inferred from `iter_get(i64)` return type.
- This protocol is intentionally distinct from indexing sugar.
- A type with non-iteration lookup methods (for example map key lookup) is not automatically iterable by `for ... in` unless it also defines `iter_len`/`iter_get(i64)`.

Current implementation status:

- `for ... in` is implemented today for arrays and for concrete class-typed values that satisfy the structural `iter_len`/`iter_get(i64)` protocol.
- The collection expression is evaluated once, and `iter_len()` is snapshotted once before the loop body begins.
- Arrays are handled as a built-in fast path rather than by requiring user-visible `iter_len`/`iter_get` methods.
- Inherited `iter_len`/`iter_get` methods on class types participate in `for ... in` eligibility.
- Interface-typed `for ... in` is not yet implemented. Even if an interface declares `iter_len() -> u64` and `iter_get(i64) -> T`, the current compiler still rejects iterating a value whose static type is that interface.

## Consequences

### Positive

- Keeps indexing sugar flexible (`get` key type remains arbitrary).
- Prevents map key-lookup APIs from being misinterpreted as index iteration APIs.
- Allows iterable behavior to be explicit and opt-in.
- Maintains structural, name-agnostic extensibility for stdlib container families.

### Trade-offs

- Introduces additional protocol surface (`iter_len`/`iter_get`) for iterable types.
- Requires clear diagnostics when one protocol exists but the other does not.
- Leaves a temporary gap between the structural design and the current implementation because interface-typed iteration is not supported yet.

## Migration Guidance

1. Keep indexing/slicing lowering on `index_get/index_set/slice_get/slice_set`.
2. Keep `for ... in` lowering aligned with evaluate-once collection semantics and snapshotted `iter_len()` semantics.
3. Keep structural class-based eligibility on `iter_len/iter_get(i64)`, while treating array iteration as the built-in fast path.
4. Ensure parser/typechecker/codegen diagnostics mention the specific missing protocol methods.
5. Add tests for both positive and negative eligibility, especially map-like key-based `get` and the current interface-typed limitation.

## Non-Goals

- Immediate implementation of all future sugar forms.
- Generic container/typeclass features.
- Implicitly treating `index_get(i64)` as iteration protocol without explicit `iter_*` methods.
