# Sugaring Design Decision

## Status

Accepted (locked direction for sugaring protocols).

## Context

Niflheim already has sugar forms (`[]`, `[:]`, index assignment) and structural lowering behavior for container-like types. We also want a future `for elem in collection { ... }` sugar without introducing hard-coded container names.

Some types (for example maps) intentionally use `get(key)` where the argument is a key, not a positional index. Reusing the same method contract for both indexing sugar and iteration sugar would create ambiguity and accidental eligibility.

## Decision

Adopt two distinct structural sugar protocols.

### 1) Indexing/Slicing Sugar Protocol

Canonical lowering:

- `obj[index]` -> `obj.get(index)`
- `obj[index] = value` -> `obj.set(index, value)`
- `obj[begin:end]` -> `obj.slice(begin, end)`
- `obj[begin:end] = value` -> `obj.set_slice(begin, end, value)`

Structural eligibility:

- `get(K) -> R`
- `set(K, W) -> unit`
- `slice(i64, i64) -> U`
- `set_slice(i64, i64, U) -> unit`

Notes:

- `K` is method-signature driven and may be any type (not hard-coded to `i64`).
- Read and write sugar are independent (`R` and `W` may differ).
- Slice bounds stay `i64`.

### 2) For-In Iteration Sugar Protocol

Planned surface syntax:

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
- A type with `get(K)` (for example map key lookup) is not automatically iterable by `for ... in` unless it also defines `iter_len`/`iter_get(i64)`.

## Consequences

### Positive

- Keeps indexing sugar flexible (`get` key type remains arbitrary).
- Prevents map key-lookup APIs from being misinterpreted as index iteration APIs.
- Allows iterable behavior to be explicit and opt-in.
- Maintains structural, name-agnostic extensibility for stdlib container families.

### Trade-offs

- Introduces additional protocol surface (`iter_len`/`iter_get`) for iterable types.
- Requires clear diagnostics when one protocol exists but the other does not.

## Migration Guidance

1. Keep existing indexing/slicing lowering on `get/set/slice/set_slice`.
2. Implement `for ... in` lowering only against `iter_len/iter_get(i64)`.
3. Ensure parser/typechecker/codegen diagnostics mention the specific missing protocol methods.
4. Add tests for both positive and negative eligibility (especially map-like key-based `get`).

## Non-Goals

- Immediate implementation of all future sugar forms.
- Generic container/typeclass features.
- Implicitly treating `get(i64)` as iteration protocol without explicit `iter_*` methods.
