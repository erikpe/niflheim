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
3. `==`, `!=`
4. `<`, `<=`, `>`, `>=`
5. `+`, `-`
6. `*`, `/`, `%`
7. unary (`!`, unary `-`), cast
8. postfix (call, field access, indexing)

All binary operators are left-associative in v0.1.

## Notes on Parsing vs Semantics

Grammar permits forms that are filtered later by semantic analysis.

Examples:
- Cast syntax parses as `(Type)expr`, but cast validity is type-checked later.
- Call arguments are positional-only in v0.1.
- `named_type` includes `IDENT` for user classes; actual type resolution is done in resolver/type checker.
- `lvalue` shape is syntactic; mutability checks are semantic, while null-dereference checks are runtime-only in v0.1.

Frozen array syntax (v0.1 extension track):
- Array type: `T[]`
- Array constructor expression: `T[](len)`
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

## Module and Export Model in Grammar

- `import foo.bar;`
- `export import foo.bar;` (re-export)
- `export` can prefix `class` and `fn` declarations.

These import/re-export forms are frozen for MVP v0.1.

## Lexer Expectations

The grammar assumes the lexer:
- Produces `IDENT`, numeric literals, and string literals.
- Distinguishes keywords from identifiers.
- Skips whitespace and `//` line comments.

## MVP Limits Reflected in Grammar

- No inheritance or interface syntax.
- No generics syntax.
- No recoverable error-handling constructs.
- No concurrency syntax.

When introducing post-v0.1 features, update `compiler/grammar/niflheim_v0_1.ebnf` first, then this document, then parser tests.
