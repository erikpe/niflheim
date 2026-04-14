# Niflheim Grammar (EBNF) v0.1

Canonical grammar source: [compiler/grammar/niflheim_v0_1.ebnf](../compiler/grammar/niflheim_v0_1.ebnf)

## Purpose

This grammar defines Niflheim v0.1 concrete syntax for the lexer/parser implementation.
It is intended to be strict enough for parser work while keeping semantic validation in later phases (resolver/type checker).

## Conventions

- EBNF operators:
  - `|` alternative
  - `{ ... }` zero or more
  - `[ ... ]` optional
- Terminals are quoted (example: `"fn"`, `"{"`, `"->"`).
- Non-terminals are lowercase identifiers.
- Token names from lexer are uppercase (example: `IDENT`, `INT_LIT`).

## Precedence and Associativity

Expression precedence from lowest to highest:
1. `||`
2. `&&`
3. `|`
4. `^`
5. `&`
6. `==`, `!=`
7. `<`, `<=`, `>`, `>=`
8. `is`
9. `<<`, `>>`
10. `+`, `-`
11. `*`, `/`, `%`
12. `**`
13. unary (`!`, unary `-`, `~`), cast
14. postfix (call, field access, indexing, slicing)

All binary operators are left-associative in v0.1 except `**`, which is right-associative.

## Notes on Parsing vs Semantics

Grammar permits forms that are filtered later by semantic analysis.

Examples:
- Cast syntax parses as `(Type)expr`, but cast validity is type-checked later.
- Call arguments are positional-only in v0.1.
- `named_type` includes qualified identifiers for user classes/interfaces; actual type resolution is done in resolver/type checker.
- `lvalue` shape is syntactic; mutability checks are semantic, while null-dereference checks are runtime-only in v0.1.
- `for elem in collection { ... }` parses as dedicated loop syntax; iterable eligibility is semantic and requires `iter_len() -> u64` plus `iter_get(i64) -> T`.
- `extends` / `implements` currently parse general type references; type checking later restricts them to valid class/interface targets.
- Class member modifiers parse broadly enough to support targeted diagnostics; invalid combinations such as `final fn ...` or `override constructor ...` are rejected by parser validation rather than pure EBNF shape alone.
- `super(...)` parses as a dedicated statement form; constructor-only placement rules are enforced later.
- Function literals/closures are not part of the grammar surface in expression position.
- Array function types are not supported; `fn(...) -> T[]` is a valid function type returning an array, but `(fn(...) -> T)[]` / `fn(...)[]`-style array-of-function types are rejected.

Frozen array syntax (v0.1 extension track):
- Array type: `T[]`
- Nested array type: `T[][]` (and deeper)
- Array constructor expression: `T[](len)`
- Nested array constructor expression: `T[][](len)`
- Index alias: `arr[index]`
- Slice alias: `arr[start:end]`

Current implementation note:
- This syntax/alias surface is active and tested.
- Lowering and dispatch are currently compiler/runtime-driven for arrays; a stdlib-first array wrapper layer is planned follow-up work.

Design decision (MVP): constructor and type-name resolution are symmetric across modules.
- Unqualified names are local-first.
- Qualified names are explicit (for example `util.Counter(...)` and `util.Counter` in type positions).
- Unqualified imported class names must be unique or produce ambiguity diagnostics.

Implementation status note: unqualified and module-qualified imported class names in type annotations are supported, and unqualified imported constructor-call fallback follows the same local-first + ambiguity rules.

## Current Surface

The current parser surface includes:

- module imports, import aliases, and re-exports
- top-level `class`, `interface`, `fn`, and `extern fn` declarations, each optionally prefixed with `export`
- single inheritance via `extends` and interface conformance via `implements`
- explicit constructors, `private` fields/methods/constructors, `final` fields, `override` instance methods, and `static fn` methods
- `if`, `while`, `for ... in`, `return`, `break`, `continue`, and `super(...)` statements
- array constructors `T[](len)` / `T[][](len)` and function types `fn(T1, T2) -> R`
- type tests with `is`

These forms are active in the current parser/typechecker/codegen pipeline and are covered by parser tests, semantic tests, and integration/golden coverage.

## Module and Export Model in Grammar

- `import foo.bar;`
- `import foo.bar as bar;`
- `export import foo.bar;` (re-export)
- `export import foo.bar as bar;` (re-export under `current_module.bar`)
- `export import foo.bar as baz.qux;` (re-export under `current_module.baz.qux`)
- `export import foo.bar as .;` (merge the exported surface of `foo.bar` into the current module root)
- `export` can prefix `class` and `fn` declarations.

These import/re-export forms are frozen for MVP v0.1.

### Re-export Path Semantics

- Plain `import` aliases remain single identifiers and only affect local source spelling inside the importing module.
- `export import` always re-roots the imported module under the exporting module.
- `export import foo.bar;` is equivalent to re-exporting `foo.bar` under the path `foo.bar` from the current module.
- `export import foo.bar as baz.qux;` re-exports the imported module under `current_module.baz.qux`.
- `export import foo.bar as .;` is the only form that flattens the imported module's exported surface into the current module root.
- Plain `export import foo.bar;` does not implicitly expose `foo.bar`'s direct members at the exporter root.

## Class Member Visibility in Grammar

- Class fields and methods may be prefixed with `private`.
- Supported forms:
  - `private field_name: Type;`
  - `private fn method(...) -> Type { ... }`
  - `private static fn method(...) -> Type { ... }`
- Private visibility is enforced by type checking (class-only access), not by parsing.

## Lexer Expectations

The grammar assumes the lexer:
- Produces `IDENT`, numeric literals, and string literals.
- Distinguishes keywords from identifiers.
- Skips whitespace and `//` line comments.

## Out Of Scope For Current Grammar

- No generics syntax.
- No recoverable error-handling constructs.
- No concurrency syntax.
- No lambda literals / captured-variable closures.
- No array-of-function type syntax (`fn(...) -> T` is supported; `fn(...)[]` is not).

When introducing new syntax, update `compiler/grammar/niflheim_v0_1.ebnf` first, then this document, then parser tests.
