# Numeric Literals Refactor Plan

This document describes a concrete implementation plan for refactoring numeric literal handling in the compiler.

Goal:

- parse numeric literals into a canonical compiler representation once
- stop reparsing literal source text in typecheck and codegen
- keep source spelling and span only for diagnostics/debugging
- complete this refactor for the currently supported numeric formats first
- add hexadecimal integer literals only after the refactor is complete

This plan is intentionally scoped to numeric literals only:

- decimal signed-default integers: `42`
- decimal unsigned integers: `42u`
- decimal `u8` integers: `255u8`
- decimal floating-point literals: `1.5`

Not in scope for this refactor itself:

- hexadecimal literals
- digit separators
- hex floats
- general constant folding beyond literal normalization

## Status

Not started.

## Current Problem

The current pipeline handles numeric literals as source text for too long:

1. lexer recognizes token text
2. parser stores literal lexeme as `LiteralExpr.value: str`
3. typecheck infers type and reparses the string for range validation
4. lowering attaches a `type_name` but still carries raw literal text
5. codegen reparses that text again to emit an immediate

This creates several problems:

- parse logic is duplicated
- range logic is duplicated and spread across stages
- codegen depends on source spelling instead of semantic value
- adding hex literals would multiply string parsing paths again
- AST/semantic IR do not clearly distinguish source spelling from value

Relevant current code paths:

- frontend AST literal shape:
  - `compiler/frontend/ast_nodes.py`
- lexer numeric tokenization:
  - `compiler/frontend/lexer.py`
- parser literal construction:
  - `compiler/frontend/parser.py`
- typecheck literal inference/range checks:
  - `compiler/typecheck/expressions.py`
  - `compiler/typecheck/constants.py`
- semantic lowering:
  - `compiler/semantic/lowering.py`
  - `compiler/semantic/ir.py`
- codegen literal emission:
  - `compiler/codegen/emitter_expr.py`
  - `compiler/codegen/types.py`

## Target Design

The compiler should use two distinct literal representations:

1. parsed frontend literal
2. typed semantic constant

### Parsed Frontend Literal

This is syntax-owned, parser-produced, and still independent of final inferred type.

Recommended shape:

```python
@dataclass(frozen=True)
class IntLiteralValue:
    raw_text: str
    magnitude: int
    base: int
    suffix: str | None  # None | "u" | "u8"


@dataclass(frozen=True)
class FloatLiteralValue:
    raw_text: str
    value: float
```

Then the frontend expression node becomes structured rather than stringly:

```python
LiteralValueNode = (
    IntLiteralValue
    | FloatLiteralValue
    | StringLiteralValue
    | CharLiteralValue
    | BoolLiteralValue
)


@dataclass(frozen=True)
class LiteralExpr:
    literal: LiteralValueNode
    span: SourceSpan
```

Notes:

- integers should store unsigned magnitude only; the sign remains represented by unary minus in the AST
- `raw_text` remains available for diagnostics and debug output
- strings/chars/bools can remain source-text based initially if desired, but the refactor should at minimum eliminate string-based numeric handling

### Typed Semantic Constant

This is semantic-owned and codegen-ready.

Recommended shape:

```python
@dataclass(frozen=True)
class IntConstant:
    type_name: str  # i64 | u64 | u8 | bool
    value: int


@dataclass(frozen=True)
class FloatConstant:
    type_name: str  # double
    value: float
```

Recommended semantic union:

```python
SemanticConstant = IntConstant | FloatConstant | StringConstant | CharConstant | BoolConstant
```

Then semantic IR becomes:

```python
@dataclass(frozen=True)
class LiteralExprS:
    constant: SemanticConstant
    type_name: str
    span: SourceSpan
```

## Design Principles

- lexer tokenizes; it does not decide semantic type
- parser parses numeric spelling into canonical literal payload once
- parser rejects malformed numeric syntax, but not semantic type-fit overflow
- typecheck validates/infers; it does not reparse strings
- typecheck owns literal range/type-fit validation
- lowering creates typed constants for semantic IR
- codegen emits from typed constants only
- original source spelling survives only for diagnostics/debugging

More explicitly:

- parser-side errors are syntax/format errors such as an invalid literal spelling
- typecheck-side errors are semantic fit/range errors such as a value not fitting `i64`, `u64`, `u8`, or `double`

## Recommended Migration Order

Implement in this order:

1. introduce frontend literal value dataclasses
2. switch parser to construct structured numeric literal nodes
3. switch typecheck to consume structured literals instead of strings
4. introduce typed semantic constants
5. switch lowering to produce typed constants
6. switch codegen to emit typed constants only
7. remove old string-based numeric literal helpers and dead paths
8. add hexadecimal integer literals on top of the refactored pipeline

This order keeps breakage localized and allows tests to be updated incrementally.

## Detailed Implementation Plan

## Step 1: Add Frontend Literal Value Types

Files:

- `compiler/frontend/ast_nodes.py`

Tasks:

- Replace the current string-only `LiteralExpr.value: str` design with a structured literal payload
- Add dedicated literal value dataclasses for:
  - integer literals
  - floating-point literals
  - boolean literals
  - character literals
  - string literals
- Keep `raw_text` on each value type where useful for diagnostics and debug-only display

Recommended minimum first pass:

- fully structure numeric literals
- optionally keep strings/chars/bools source-text based for now

Suggested concrete shape:

```python
@dataclass(frozen=True)
class IntLiteralValue:
    raw_text: str
    magnitude: int
    base: int
    suffix: str | None


@dataclass(frozen=True)
class FloatLiteralValue:
    raw_text: str
    value: float


@dataclass(frozen=True)
class BoolLiteralValue:
    value: bool
    raw_text: str


@dataclass(frozen=True)
class CharLiteralValue:
    raw_text: str


@dataclass(frozen=True)
class StringLiteralValue:
    raw_text: str
```

What should be true after this step:

- AST literal nodes can represent canonical numeric values without relying on later string parsing

## Step 2: Parse Numeric Literals Once In The Parser

Files:

- `compiler/frontend/parser.py`
- optionally a new helper module such as `compiler/frontend/literals.py`

Tasks:

- Add helper functions that parse numeric token lexemes into structured literal payloads
- When the parser sees `TokenKind.INT_LIT` or `TokenKind.FLOAT_LIT`, construct structured literal payloads immediately
- Keep the token lexeme available as `raw_text`
- Reject malformed numeric spellings here
- Do not perform target-type overflow checks here

Recommended helper API:

```python
def parse_int_literal_text(text: str) -> IntLiteralValue: ...
def parse_float_literal_text(text: str) -> FloatLiteralValue: ...
```

These helpers should parse only the currently supported formats:

- decimal `i64`-default integers
- decimal `u64` suffixed integers
- decimal `u8` suffixed integers
- decimal floats

Do not add hex support in this step.

Suggested location for parsing helpers:

- `compiler/frontend/literals.py`

Reason:

- avoids overloading the lexer with semantic parsing responsibilities
- makes the parsing logic reusable in tests

What should be true after this step:

- parser constructs numeric literals from canonical payloads instead of plain text
- there is exactly one place where source spelling is parsed into numeric magnitude/base/suffix
- parser is responsible only for syntactic validity of the literal spelling

## Step 3: Refactor Typecheck To Consume Structured Literal Values

Files:

- `compiler/typecheck/expressions.py`
- `compiler/typecheck/constants.py`

Tasks:

- Replace `_infer_literal_expression_type(...)` string inspection with structured literal inspection
- Remove checks like:
  - `expr.value.endswith("u8")`
  - `expr.value.endswith("u")`
  - `expr.value.isdigit()`
  - `"." in expr.value`
- Use `IntLiteralValue.magnitude`, `suffix`, and `base`
- Use `FloatLiteralValue.value` or `raw_text`
- Perform numeric fit/range checks here
- Raise diagnostics here when a parsed literal does not fit its inferred or suffix-constrained target type

Important detail: unary minus handling must stay outside literal parsing.

Current rule to preserve:

- `-9223372036854775808` is represented as unary minus applied to positive literal magnitude `9223372036854775808`

Overflow ownership after the refactor:

- `255u8` fitting or overflowing `u8`: typecheck
- `18446744073709551616u` fitting or overflowing `u64`: typecheck
- unsuffixed decimal integer fitting or overflowing default `i64`: typecheck
- unary-minus minimum-boundary case for `i64`: typecheck
- floating literal not representable as a finite `double`: typecheck

Parser should only answer:

- is this numeric spelling well-formed for a supported literal syntax?

Typecheck should answer:

- given this parsed literal and its suffix/default rules, does it fit the target type?

Recommended typecheck helpers:

```python
def infer_int_literal_type(literal: IntLiteralValue, span: SourceSpan) -> TypeInfo: ...
def check_unary_minus_literal_boundary(literal: IntLiteralValue, span: SourceSpan) -> None: ...
```

Use existing limits from `compiler/typecheck/constants.py`.

What should be true after this step:

- typecheck never reparses numeric strings
- numeric range/type inference logic operates on structured literal payloads only
- all literal overflow diagnostics are emitted from typecheck, not parser or codegen

## Step 4: Introduce Typed Semantic Constants

Files:

- `compiler/semantic/ir.py`

Tasks:

- Replace `LiteralExprS(value: str, type_name: str, ...)` with a typed semantic constant payload
- Add semantic constant dataclasses for at least:
  - `IntConstant`
  - `FloatConstant`
  - `BoolConstant`
  - `CharConstant`
- Keep string literals on their current lowering path if that remains simpler for now, but numeric semantic literals must be typed constants

Recommended shape:

```python
@dataclass(frozen=True)
class IntConstant:
    value: int
    type_name: str


@dataclass(frozen=True)
class FloatConstant:
    value: float
    type_name: str
```

What should be true after this step:

- semantic IR numeric literals are semantic values, not source strings

## Step 5: Change Lowering To Produce Typed Constants

Files:

- `compiler/semantic/lowering.py`

Tasks:

- Replace `_literal_type_name(...)`-style string classification for numeric literals
- Lower structured frontend numeric literals into typed semantic constants using inferred type information
- Keep string literal lowering as-is unless explicitly included in the same cleanup pass

Recommended approach:

- introduce helper functions such as:

```python
def _lower_numeric_literal(lower_ctx, expr: LiteralExpr) -> LiteralExprS: ...
def _typed_numeric_constant(lower_ctx, expr: LiteralExpr) -> IntConstant | FloatConstant: ...
```

- use `infer_expression_type(...)` only to decide final type, not to reparse text

What should be true after this step:

- lowering no longer carries numeric source text into semantic IR

## Step 6: Refactor Codegen To Emit Typed Constants Only

Files:

- `compiler/codegen/emitter_expr.py`
- `compiler/codegen/types.py`

Tasks:

- Replace `_emit_literal_expr(...)` string classification with typed constant emission
- Remove logic such as:
  - `expr.value.isdigit()`
  - `expr.value.endswith("u")`
  - `expr.value.endswith("u8")`
  - `is_double_literal_text(expr.value)`
  - `double_literal_bits(expr.value)`

Recommended post-refactor behavior:

- integer constants emit directly from canonical integer value
- float constants emit directly from canonical float value / float bits
- char/bool constants emit from already-decoded semantic value

Recommended helper evolution in `compiler/codegen/types.py`:

- replace `double_literal_bits(text: str)` with something like:

```python
def double_value_bits(value: float) -> int: ...
```

What should be true after this step:

- codegen does not parse numeric source text at all

## Step 7: Remove Old String-Based Numeric Literal Paths

This is an explicit cleanup step and should not be skipped.

Files likely requiring cleanup:

- `compiler/frontend/ast_nodes.py`
- `compiler/frontend/parser.py`
- `compiler/typecheck/expressions.py`
- `compiler/semantic/ir.py`
- `compiler/semantic/lowering.py`
- `compiler/codegen/emitter_expr.py`
- `compiler/codegen/types.py`

Cleanup checklist:

- remove `LiteralExpr.value: str` for numeric literals
- remove `_literal_type_name(...)` logic that depends on string spelling for numerics
- remove string-based numeric classification in codegen
- remove numeric parsing duplication from typecheck
- rename or delete helper functions whose only purpose was reparsing text in late stages

Examples of traces that should be gone after cleanup:

- `expr.value.isdigit()` in typecheck/codegen
- `expr.value.endswith("u")`
- `expr.value.endswith("u8")`
- `"." in expr.value` as float detection in typecheck
- codegen raising `literal codegen not implemented for '{expr.value}'` for numeric paths

What should remain text-based after this cleanup:

- source spans
- raw text for diagnostics/debugging
- string literal storage keys where needed for string-literal lowering

## Step 8: Add Hexadecimal Integer Literals After Refactor

Only begin this step after Steps 1-7 are complete and validated.

Recommended syntax:

- `0x2a`
- `0x2au`
- `0xffu8`

Tasks:

- extend numeric literal parsing helper(s) to accept base-16 integer forms
- keep suffix rules identical to decimal integer literals
- keep unary minus outside the literal itself
- add range tests for hex literals using final inferred type

No codegen changes should be required at this point if the refactor is complete.

That is a key success criterion for the refactor.

## Testing Plan

## Frontend Lexer/Parser Tests

Files:

- `tests/compiler/frontend/lexer/test_lexer.py`
- `tests/compiler/frontend/parser/test_parser.py`

Add tests for currently supported formats under the new structured representation:

- `42`
- `42u`
- `255u8`
- `1.5`
- unary minus applied to integer literal remains separate AST structure

After hex is added later, add:

- `0x2a`
- `0x2au`
- `0xffu8`
- invalid hex spellings

## Typecheck Tests

Files:

- `tests/compiler/typecheck/test_expressions.py`

Add/refactor tests around:

- decimal integer type inference
- decimal float inference
- `u64` bounds
- `u8` bounds
- `i64` max bound
- unary minus and `i64` minimum magnitude special case
- later: hex range coverage

## Lowering Tests

Files:

- `tests/compiler/semantic/test_lowering.py`

Add tests verifying:

- lowered numeric literals become typed semantic constants
- semantic constant values match expected canonical values
- source spellings are not required by numeric codegen path anymore

## Codegen Tests

Files:

- `tests/compiler/codegen/test_emit_asm_basics.py`
- possibly `tests/compiler/codegen/test_emitter_expr.py`

Add tests verifying:

- numeric immediates emit correctly from typed constants
- float constants emit correct bit patterns from semantic values
- no codegen dependency remains on numeric literal source text form

## Golden/Integration Tests

Add a targeted golden or integration test once hex is introduced, not before.

Suggested future file:

- `tests/golden/lang/test_hex_literals.nif`

## Proposed File-By-File Change Summary

### `compiler/frontend/ast_nodes.py`

- add structured literal value dataclasses
- refactor `LiteralExpr`

### `compiler/frontend/lexer.py`

- keep token kinds as-is for now
- do not add semantic parsing here
- later hex support may require tokenization changes if current `_read_number` is decimal-only

### `compiler/frontend/parser.py`

- parse token lexeme into structured numeric literal payloads
- update synthetic zero literal creation to use structured literal payload rather than raw string

Current known call site to update:

- slice sugar zero literal in `parser.py`

### `compiler/typecheck/expressions.py`

- consume structured literal payloads
- remove string-based numeric inference logic

### `compiler/semantic/ir.py`

- introduce semantic constants
- refactor `LiteralExprS`

### `compiler/semantic/lowering.py`

- lower structured literals into typed semantic constants
- remove string-based numeric literal classification helper(s)

### `compiler/codegen/emitter_expr.py`

- emit numeric constants from typed semantic constants only

### `compiler/codegen/types.py`

- rename/replace float text parsing helpers with value-based helpers

### Tests

- update lexer/parser/typecheck/lowering/codegen tests to reflect structured literal representation

## Acceptance Criteria

This refactor is complete when all of the following are true:

- numeric literals are parsed into canonical frontend values once
- typecheck does not reparse numeric source text
- semantic IR stores typed numeric constants instead of source strings
- codegen emits numeric literals without parsing source text
- old string-based numeric literal branches are removed
- full existing test suite passes before adding hex support
- hexadecimal integer literal support can be added by extending literal parsing and tests only, without changing semantic IR or codegen architecture

## Non-Goals For This Refactor

- changing string literal lowering architecture
- adding arbitrary constant folding
- changing runtime numeric semantics
- changing suffix rules for existing decimal literals

## Recommended Next Step After This Document

Implement only Steps 1-7 first.

Do not add hex support in the same change series.

Once the refactor is complete and validated, add hex literals as a narrow follow-up that proves the new design actually removed the old coupling.