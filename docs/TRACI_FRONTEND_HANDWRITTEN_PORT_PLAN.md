# Traci Frontend Hand-Written Port Plan

This document turns the Traci Java frontend into a concrete Niflheim implementation plan for the first porting stage:

- Traci preprocessor subset
- hand-written lexer
- hand-written parser
- tree-walker to Traci node objects

The output of this stage does not need to be runnable by a Traci interpreter yet. It does need to preserve the Java frontend's accepted source surface, diagnostics model, and node shape closely enough that the evaluator can be ported later without redoing the frontend.

## Scope And Source Of Truth

For the Java frontend, the source of truth is:

- `proj/traci_java/src/se/ejp/traci/lang/grammar/TraciLexer.g`
- `proj/traci_java/src/se/ejp/traci/lang/grammar/TraciParser.g`
- `proj/traci_java/src/se/ejp/traci/lang/grammar/TraciTreeWalker.g`
- `proj/traci_java/src/se/ejp/traci/lang/preprocessor/PreprocessorRunner.java`
- `proj/traci_java/src/se/ejp/traci/lang/parser/ParserRunner.java`
- `proj/traci_java/src/se/ejp/traci/lang/parser/TraciToken.java`
- `proj/traci_java/src/se/ejp/traci/lang/parser/IncludeLocation.java`
- `proj/traci_java/src/se/ejp/traci/lang/parser/ParseError.java`

The generated ANTLR outputs are not the source of truth:

- `proj/traci_java/src/.../TraciLexer.java`
- `proj/traci_java/src/.../TraciParser.java`
- `proj/traci_java/src/.../TraciTreeWalker.java`

Those generated files are useful only for confirming ANTLR behavior during debugging.

## What The Java Frontend Actually Does

The Java frontend is a four-stage pipeline.

### 1. Preprocessor

`PreprocessorRunner` wraps `org.anarres.cpp.Preprocessor`.

Important behavior:

- adds the input file's directory to the quote-include path
- adds extra include directories from settings
- adds command-line macros from settings
- enables line markers with `Feature.LINEMARKERS`
- keeps comments with `Feature.KEEPCOMMENTS`
- produces one flattened source string

That flattened string contains `#line` directives. The Java lexer consumes those directives as hidden tokens and uses them to maintain include-aware source locations.

### 2. Lexer

The lexer does more than tokenization.

Important behavior:

- recognizes normal language tokens
- recognizes hidden comments and whitespace
- recognizes hidden `PPLINE` tokens for `#line ...`
- updates `currentFilename` and an include stack when a `#line` token is seen
- emits `TraciToken` rather than plain tokens
- attaches `IncludeLocation` to each token

The `#line` handling is part of the diagnostic model, not an incidental preprocessing detail.

### 3. Parser

The parser does not produce final interpreter nodes. It produces a normalized AST with synthetic tags:

- `BLOCK`
- `ARGS`
- `FUNCALL`
- `REF`
- `UNARY_OP`
- `GLOBAL_ASSIGN`
- `VECTOR`

Important grammar properties:

- recursive-descent style precedence levels for expression parsing are enough to replace the ANTLR grammar here
- assignment is disambiguated by lookahead on `ID =`
- simplified transformation statements are disambiguated by seeing a transformation token not followed by `(`, `{`, or `;`
- many object forms allow an optional trailing block
- `vector` and `color` are special syntactic forms rather than ordinary function calls

### 4. Tree-Walker

The tree-walker turns the normalized AST into interpreter nodes.

Important behavior:

- block scope collects nested function definitions into the block's function table
- block statements exclude nested function definitions
- object forms become `ObjectNode`
- ordinary calls become `FunctionCallNode`
- variable references become `RefNode`
- control-flow becomes `IfNode`, `WhileNode`, `ForNode`, `ReturnNode`

The node names and package layout are a good target for the Niflheim port even if their first Nif version is data-only.

## Practical Subset Used In The Corpus

The Java grammar surface is broader than the part used by shipped content.

### Preprocessor Subset Used In Practice

Observed in shipped scenes and testcode:

- `#include "..."`
- include guards via `#ifndef NAME`, `#define NAME`, `#endif`
- object-like `#define NAME`
- object-like `#define NAME value`
- `#if NAME`
- `#elif NAME`
- `#else`
- `#endif`

Observed examples:

- `proj/traci_java/scenes/lego/common/basic-units.traci`
- `proj/traci_java/scenes/lego/common/basic-shapes.traci`
- `proj/traci_java/scenes/lego/bricks/lego-primitives.traci`
- `proj/traci_java/scenes/lego/airplane.traci`
- `proj/traci_java/testcode/a.traci`

Not observed in shipped scenes or testcode:

- `#ifdef`
- `#undef`
- function-like macros
- macro arguments
- token pasting
- stringification
- arithmetic preprocessor expressions
- complex `defined(...)` expressions

This is the strongest argument for implementing a deliberately small handwritten preprocessor instead of trying to reproduce full C preprocessor behavior.

### Language Subset Used In Shipped Scenes

Shipped scene files rely heavily on:

- `def`
- `return`
- `global`
- assignments
- nested helper functions
- `for (x in a .. b)` loops
- vectors like `[x, y, z]`
- colors like `color [r, g, b]` and `color [r, g, b, a]`
- function calls with optional trailing blocks
- object literals with optional trailing blocks
- transformation shorthand statements like `translate [1, 2, 3];`

Object forms used often in shipped scenes:

- `union`
- `difference`
- `intersection`
- `bbox`
- `box`
- `cylinder`
- `sphere`
- `torus`
- `translate`
- `scale`, `scalex`, `scaley`, `scalez`
- `rotx`, `roty`, `rotz`
- `rotAround`, `rotVecToVec`
- `color`
- `finish`
- `texture`
- `solid`, `checker`, `image`
- `interior`
- `material`
- `pointlight`, `ambientlight`
- `camera`
- `skybox`

Rare in shipped scenes:

- `image(...)` appears in the airplane scene
- `skybox(...)` appears in the airplane scene
- `mesh(...)` appears only as commented-out code in the airplane scene
- `plane` was not observed in shipped scenes
- `cone` was not observed in shipped scenes

### Language Used In Testcode But Not In Shipped Scenes

The `testcode` corpus adds the rest of the current language surface that should still be supported by the handwritten parser:

- `if` / `elif` / `else`
- `while`
- boolean literals `true` / `false`
- boolean comparisons and unary `!`
- includes in tiny parser fixtures

Examples:

- `proj/traci_java/testcode/fibonacci.traci`
- `proj/traci_java/testcode/prime-checker.traci`
- `proj/traci_java/testcode/if-statement.traci`
- `proj/traci_java/testcode/boolean-literals.traci`
- `proj/traci_java/testcode/while-loop.traci`

## Recommended Port Boundary

For this stage, port the full Java frontend grammar, but prioritize the practiced preprocessor subset.

That means:

- the preprocessor should intentionally support only the subset listed above
- the lexer/parser/tree-walker should support the full current Java language surface described by the grammar files
- evaluator support for rare object kinds may still be deferred later

This avoids frontend drift while still keeping the risky part, the preprocessor, intentionally small.

## Recommended Nif Project Shape

Stay close to the Java package structure, but use the repo's existing hand-written frontend style where it helps.

Naming principle for files under `proj/traci_nif`:

- prefer Java-style CamelCase filenames for Traci modules
- if a Nif module corresponds directly to a Java Traci class, reuse that class name for the file, for example `Settings.nif`, `PreprocessorRunner.nif`, `ParserRunner.nif`, `TraciLexer.nif`
- for Nif-specific helper modules inside the Traci port, still prefer CamelCase so the package reads consistently, for example `PreprocessAndParse.nif` and `TokenKind.nif`
- keep snake_case for local functions, methods, variables, and for existing non-Traci test naming conventions elsewhere in the repository

Recommended layout:

```text
proj/traci_nif/
  main/
    Settings.nif
    Result.nif
    PreprocessAndParse.nif
  lang/
    preprocessor/
      PreprocessorRunner.nif
      Preprocessor.nif
      IncludeResolver.nif
      MacroTable.nif
    parser/
      TokenKind.nif
      TraciToken.nif
      IncludeLocation.nif
      ParseError.nif
      ParserUtilities.nif
      TraciLexer.nif
      SyntaxNodes.nif
      Parser.nif
      ExpressionParser.nif
      StatementParser.nif
      DeclarationParser.nif
      TreeWalker.nif
      ParserRunner.nif
    interpreter/
      node/
        TraciNode.nif
        BlockNode.nif
        FunctionNode.nif
        AssignNode.nif
        BinaryOpNode.nif
        ConstNode.nif
        ForNode.nif
        FunctionCallNode.nif
        IfNode.nif
        ObjectNode.nif
        Op.nif
        RefNode.nif
        ReturnNode.nif
        UnaryOpNode.nif
        WhileNode.nif
```

Why this shape:

- `lang/preprocessor` stays close to Java
- `lang/parser` stays close to Java
- `lang/interpreter/node` preserves the Java node package and names for the later evaluator port
- parser internals can still follow the main compiler frontend convention of keeping `Parser.nif` thin and delegating real grammar work to focused sub-parsers

## Recommended Deviations From Java

These deviations are worthwhile in Niflheim.

### 1. Keep the pipeline split, but do not reproduce ANTLR's internal AST machinery literally

The Java parser rewrites into ANTLR `CommonTree` nodes with synthetic tags. In Niflheim, the handwritten parser should produce explicit syntax nodes instead.

Recommended syntax-node layer:

- `SceneSyntax`
- `BlockSyntax`
- `FunctionSyntax`
- `AssignSyntax`
- `GlobalAssignSyntax`
- `IfSyntax`
- `WhileSyntax`
- `ForSyntax`
- `ReturnSyntax`
- `BinaryExprSyntax`
- `UnaryExprSyntax`
- `RefSyntax`
- `FunctionCallSyntax`
- `ObjectSyntax`
- `VectorSyntax`
- `ColorSyntax`
- `ConstSyntax`

The tree-walker then becomes a regular mapper from syntax nodes to `...Node` objects.

### 2. Keep Java-style `#line` handling for v1

The cleanest first port is:

- preprocessor emits flat text with Java-compatible `#line` directives
- lexer recognizes hidden `#line` markers
- lexer updates include-aware location state exactly as Java does

This minimizes semantic drift and lets the Java lexer tests be ported almost directly.

An explicit source-map representation can be considered later if the textual `#line` approach becomes awkward.

### 3. Make the first node layer data-only

The first Nif `BlockNode`, `FunctionNode`, `ObjectNode`, and friends should not try to evaluate anything yet.

They only need:

- fields matching the Java tree-walker output shape
- source spans or include-aware locations
- readable dump or debug formatting

This keeps the frontend deliverable separate from the later evaluator port.

### 4. Use explicit diagnostics collections instead of exception-driven recovery

The Java frontend is ANTLR- and exception-oriented. In Niflheim, prefer:

- `Vec` or typed vector of diagnostics
- explicit result objects per phase
- early stop after fatal errors

This fits the current language and stdlib better.

## Missing Or Weak Niflheim Features To Address First

Most prerequisites for this frontend stage already exist.

Already available and sufficient:

- file reading via `std.io.read_file`
- strings via `std.str.Str`
- mutable string assembly via `StrBuf`
- vectors and maps in stdlib
- hand-written lexer/parser precedent in the main compiler frontend

The one feature worth adding before the Traci preprocessor port is a recoverable file-open API.

Current problem:

- `std.io.read_file` panics on missing files
- the Traci preprocessor needs to report include-resolution errors as diagnostics with include chains
- panicking on the first missing include is the wrong failure mode for this stage

Recommended prerequisite workstream:

- add `std.io.try_read_file(path: Str) -> Str`, returning `null` on failure, or
- add `std.io.file_exists(path: Str) -> bool` plus a non-panicking read path, or
- add a Traci-local runtime wrapper that converts open failures into an explicit result

Without that, include diagnostics will be much uglier than the Java behavior.

Path helpers would also be useful, but they are not a hard blocker. Include resolution can be implemented locally in the Traci port if needed.

## Concrete Implementation Plan

### Phase 0: Small Prerequisite

Goal:

- get non-panicking file-open behavior for include handling

Deliverables:

- recoverable file-read API
- focused golden tests for missing-file behavior

Done when:

- the Traci preprocessor can detect a missing include and return a diagnostic instead of crashing the program

### Phase 1: Diagnostics And Frontend Skeleton

Goal:

- establish the frontend package layout and shared types

Deliverables:

- `Settings` subset for input file, include dirs, and predefined macros
- `FileLocation`
- `IncludeLocation`
- `ParseError` or a renamed `Diagnostic`
- `TraciToken`
- `PreprocessorRunner`
- `ParserRunner`

Notes:

- keep names close to Java where they are user-visible or useful for later porting
- keep `Parser.nif` and `ParserRunner.nif` thin

Done when:

- the pipeline can be invoked end-to-end with stubs and produce structured diagnostics

### Phase 2: Preprocessor Subset

Goal:

- reproduce only the subset that the Traci corpus actually uses

Required features:

- quote includes
- include search through input-file directory plus configured include dirs
- include guards
- object-like macro definitions
- command-line macro injection
- conditional stack for `#if NAME`, `#elif NAME`, `#else`, `#endif`
- preserved comments and ordinary source text
- emitted `#line` markers compatible with the lexer phase

Explicitly out of scope in this phase:

- function-like macros
- full preprocessor expression evaluation
- full C preprocessor compatibility

Test inputs:

- `proj/traci_java/testcode/a.traci`
- `proj/traci_java/scenes/lego/common/basic-units.traci`
- `proj/traci_java/scenes/lego/common/basic-shapes.traci`
- `proj/traci_java/scenes/lego/bricks/lego-primitives.traci`

Done when:

- `a.traci` preprocesses into the same include ordering behavior as Java
- include guard files flatten correctly without duplicate content
- `FAST_LEGO`-style toggles choose the correct branch
- missing includes produce a structured include-chain diagnostic

### Phase 3: Hand-Written Lexer

Goal:

- port the token surface and location behavior of `TraciLexer.g`

Required features:

- all punctuation and operator tokens
- keywords and specialized object-token categories
- `ID`, `INT`, `FLOAT`, `QSTRING`
- comments and whitespace as hidden tokens
- hidden `PPLINE` token handling for source-location state updates
- token emission with attached include-aware location

Implementation notes:

- keep token categories aligned with the grammar names to simplify parser and test porting
- do not special-case rare runtime features out of the lexer; lexing them is cheap

Tests to port conceptually:

- `TraciLexerTest.testLexer`
- `testFloat`
- `testString`
- `testFibonacciWithPreprocessor`
- `testInclude`
- keyword-category tests for transformations, shapes, pigment, camera, finish, interior

Done when:

- the lexer reproduces include-aware token locations across preprocessed includes
- the current parser fixtures tokenize cleanly

### Phase 4: Hand-Written Parser

Goal:

- parse the Java language surface into explicit syntax nodes

Required features:

- top-level scene and blocks
- nested function definitions
- statement parsing
- expression precedence
- special parsing for vectors and colors
- optional trailing blocks after references, function calls, and object forms
- assignment lookahead
- simplified transformation statement lookahead

Implementation notes:

- follow the main compiler frontend's pattern: keep `parser.nif` thin and split expression, statement, and declaration parsing by concern
- keep syntax-node names descriptive rather than trying to imitate ANTLR tree tags in raw form

Tests to port conceptually:

- `TraciParserTest.testParser`
- `testInterior`
- `testColor`
- `testVector`
- `testString`
- `testRef`
- `testFloat`
- full-file parsing of `fibonacci.traci` and `prime-checker.traci`

Done when:

- parser unit tests cover the existing Java parser test surface
- all shipped scene files parse into syntax trees without diagnostics

### Phase 5: Tree-Walker To Data Nodes

Goal:

- convert syntax nodes into Nif `...Node` classes with Java-compatible names and structure

Required node set:

- `BlockNode`
- `FunctionNode`
- `AssignNode`
- `BinaryOpNode`
- `ConstNode`
- `ForNode`
- `FunctionCallNode`
- `IfNode`
- `ObjectNode`
- `RefNode`
- `ReturnNode`
- `UnaryOpNode`
- `WhileNode`
- `Op`

Important semantic detail to preserve:

- nested function definitions belong to block-local function scope and are not normal block statements

Implementation notes:

- copy the Java node names and broad field layout
- omit eval logic for now
- add debug printers or dump helpers so test output can assert structure

Tests to port conceptually:

- `TraciTreeWalkerTest.testTreeWalker`
- `TraciTreeWalkerTest.testString`
- full-file tree-walks of `fibonacci.traci` and `prime-checker.traci`

Done when:

- tree-walker tests pass
- full shipped scenes can preprocess, lex, parse, and tree-walk into node graphs

### Phase 6: Corpus Validation And Snapshots

Goal:

- lock in frontend behavior before the evaluator port begins

Recommended validation corpus:

- all files under `proj/traci_java/testcode`
- all files under `proj/traci_java/scenes`

Recommended test artifacts:

- preprocessor output snapshots for a few representative files
- token dump snapshots with include-aware locations
- syntax tree dumps
- final node graph dumps

Representative golden choices:

- `testcode/a.traci` for include transitions
- `testcode/if-statement.traci` for control flow
- `testcode/prime-checker.traci` for expressions plus loops
- `scenes/lego/common/basic-shapes.traci` for nested defs and object-heavy syntax
- `scenes/lego/airplane.traci` for deep include stack and the broadest practical scene surface

Done when:

- the whole corpus completes frontend processing without crashes
- diagnostics for malformed fixtures are stable and readable
- rare forms like `skybox` and `image` parse successfully even if their evaluator support is still deferred

## Recommended Test Strategy

Use three layers of tests.

### 1. Ported unit tests from the Java frontend

These should stay close to the current Java tests because they encode the existing frontend behavior precisely.

### 2. New snapshot or golden tests for Nif dumps

The Nif frontend should emit stable textual dumps for:

- tokens
- syntax trees
- node graphs

Those are a better fit than trying to compare in-memory trees directly in large cases.

### 3. Corpus tests over real Traci files

The lexer/parser should be continuously validated against the real scene corpus, not just tiny fixtures.

## Recommended Stop Conditions

Stop and do prerequisite work before continuing if either of these becomes true.

### 1. Missing include files still crash the process

Do not continue with the preprocessor if missing includes still surface only as runtime panics.

### 2. Parser code starts collapsing into one giant file

If the parser starts accumulating everything in `parser.nif`, stop and split it by concern. The main compiler frontend already established that boundary for a reason.

## What Should Be Deferred

These should parse now but do not need evaluator support for the first frontend milestone:

- `image`
- `skybox`
- `mesh`
- `plane`
- `cone`

These should not be expanded in the preprocessor milestone:

- full CPP compatibility
- macro arguments
- complex preprocessor expressions

## Milestone Definition

This frontend milestone is complete when:

- the practiced preprocessor subset works on the shipped Traci corpus
- the handwritten lexer accepts the Java token surface and preserves include-aware locations
- the handwritten parser accepts the Java grammar surface and builds explicit syntax nodes
- the tree-walker produces Java-shaped `...Node` objects
- the result is validated on both parser fixtures and real scenes
- no evaluator functionality is required for success

At that point the next stage should be the Traci evaluator and value model, not more frontend churn.