# Function Values Implementation Checklist (No-Capture MVP)

Use this checklist to implement first-class function values without closures.

## 1) Scope Freeze

- [x] Freeze syntax: `fn(T1, T2, ...) -> R`.
- [x] Freeze value sources:
  - top-level functions
  - qualified static methods
- [x] Freeze non-goals:
  - closures/captures
  - lambda literals
  - instance method values
  - callable interface objects

## 2) Lexer and Grammar

- [ ] Keep `fn` keyword behavior unchanged for declarations.
- [ ] Extend type grammar to parse function types in type positions.
- [ ] Ensure function type parsing composes with array types only if explicitly allowed by design.
- [ ] Add/refresh EBNF in `compiler/grammar/niflheim_v0_1.ebnf`.

## 3) AST and Type Model

- [ ] Add function type node to AST type references.
- [ ] Add corresponding `TypeInfo` shape for function signatures.
- [ ] Add canonical function-type string or structural identity representation.

## 4) Parser

- [ ] Parse `fn(...) -> ...` in all type annotation contexts:
  - var declarations
  - params
  - return types
  - fields
- [ ] Keep declaration parsing unambiguous:
  - declaration form remains `fn name(...) -> ... { ... }`
  - type form remains `fn(...) -> ...`
- [ ] Add negative parse diagnostics for malformed function types.

## 5) Resolver and Symbol Binding

- [ ] Ensure top-level function symbols can be used as expression values.
- [ ] Ensure qualified static method symbols can be resolved as value expressions.
- [ ] Reject non-static method value forms with clear diagnostics.

## 6) Type Checker

- [ ] Add function-type equality checks (exact arity and exact param/return types).
- [ ] Permit assignments from function symbol to matching function-typed variables/fields.
- [ ] Validate indirect-call expression typing when callee is function-typed.
- [ ] Reject unsupported forms:
  - instance method values
  - lambdas
  - capture-like constructs
- [ ] Keep current callable handling for normal direct calls intact.

## 7) Codegen

- [ ] Define runtime representation for function values (code pointer in MVP).
- [ ] Lower function symbol expressions to pointer constants/labels.
- [ ] Lower qualified static method values to method labels.
- [ ] Lower function-typed calls to indirect calls.
- [ ] Preserve existing SysV integer/floating argument handling for indirect calls.
- [ ] Ensure GC/rooting policy remains correct around indirect calls.

## 8) Diagnostics

- [ ] Add targeted diagnostics for unsupported constructs:
  - "instance methods are not first-class values in MVP"
  - "closures/captures are not supported"
- [ ] Keep messages deterministic with source spans.

## 9) Tests

### 9.1 Parser

- [ ] Positive parse tests for nested function-type signatures.
- [ ] Negative parse tests for malformed `fn(...) -> ...` forms.

### 9.2 Type Checker

- [ ] Assign top-level function to matching function type (positive).
- [ ] Assign static method to matching function type (positive).
- [ ] Mismatched arity/type assignment (negative).
- [ ] Indirect call argument/return mismatch (negative).
- [ ] Instance method value rejection (negative).

### 9.3 Codegen/Integration

- [ ] End-to-end indirect call through function variable (primitive args/return).
- [ ] End-to-end indirect call through static method value.
- [ ] Mixed int/double argument path through function values.
- [ ] Golden tests for expected output and panic behavior.

## 10) Stdlib Follow-Up (Optional in Same Milestone)

- [ ] Add callback-ready APIs for `Vec`:
  - `map`
  - `remove_if`
  - `reduce`
- [ ] Provide sample program showing pipeline usage with no-capture functions.

## 11) Documentation and Release Notes

- [ ] Update language spec examples.
- [ ] Update README and docs index links.
- [ ] Add migration notes for future closure support (explicitly marked deferred).
