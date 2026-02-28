# Indexing Sugar Design Decision

## Status

Accepted (target direction for next migration phase).

## Context

We want higher-level containers (starting with `Vec`) to be implemented in stdlib Nif code and backed by array types (`Obj[]`, later `u8[]`, etc.), rather than hard-coded runtime/compiler built-ins.

Current implementation has language-level sugar (`[]`, `[:]`, index assignment) plus container-specific compiler special cases (`Vec`, `Str`, arrays).

As more container classes are added (for example primitive-specialized vectors, map-like classes, possible stdlib `Str`/`StrBuf`), duplicated container-specific compiler logic will not scale.

## Decision

Adopt **method-canonical indexing semantics**.

### Canonical Lowering

- `obj[index]` is canonicalized to `obj.get(index)`
- `obj[index] = value` is canonicalized to `obj.set(index, value)`
- `obj[begin:end]` is canonicalized to `obj.slice(begin, end)`

The compiler should keep only one semantic implementation path (method-call path), not independent parallel implementations for index syntax and method syntax.

### Eligibility Rule (Structural)

Sugar is enabled for any type that provides matching method signatures. This is **structural**, not name-based.

Baseline signatures:

- `get(i64) -> T`
- `set(i64, T) -> unit`
- `slice(i64, i64) -> U` (typically `Self`, but policy is method-signature driven)

This allows future stdlib classes to opt in without compiler changes tied to specific class names (`Vec`, `Map`, `Str`, etc.).

## Consequences

### Positive

- Removes container-specific compiler branches over time.
- Keeps language sugar while moving behavior ownership to stdlib classes.
- Makes future container families (`VecU8`, `VecI64`, map wrappers) straightforward.
- Supports potential future stdlib implementations of `Str`/`StrBuf` backed by arrays.

### Trade-offs

- Requires careful migration of existing built-in `Vec` special handling.
- Diagnostics for sugar misuse must remain clear after structural dispatch.
- Runtime ABI and codegen tables need cleanup to avoid stale built-in paths.

## Migration Guidance

1. Implement stdlib `Vec` over `Obj[]`.
2. Keep sugar behavior, but route it through method resolution.
3. Remove hard-coded `Vec` typing/codegen/runtime call tables.
4. Preserve arrays as built-in storage primitive with existing semantics.
5. Extend tests to validate method/index equivalence across stdlib classes.

## Non-Goals (for this decision)

- Immediate implementation changes.
- Generic containers.
- Deciding full map/str sugar policy details beyond the canonicalization rule.
