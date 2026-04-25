# Traci Scene-Construction Evaluator Plan

This document turns the next Traci milestone into a concrete implementation plan:

- evaluate the existing hand-written frontend output into a typed Scene
- use explicit value classes instead of a single catch-all runtime wrapper
- preserve Java-style copy-on-read semantics for mutable scene-construction objects
- stay close to the Java Traci package structure where that helps
- deviate where the current Niflheim port boundary or language/runtime limitations make the Java shape a poor fit

This is an evaluator-and-scene-construction plan, not a renderer plan.

## Scope

The scope of this document starts from the current port state:

- preprocessor subset is implemented
- hand-written lexer is implemented
- hand-written parser is implemented
- tree-walker to data-only interpreter nodes is implemented
- high-value runtime and stdlib additions are available: `std.math`, `std.random`, `std.io.write_file`, and primitive dynamic buffers

The goal of this phase is to turn the existing `proj/traci_nif/lang/interpreter/node/*.nif` graph into evaluated Traci values and then into a typed `Scene`.

Out of scope for the first evaluator slice:

- renderer implementation
- GUI preview
- PNG encoding
- image decoding
- mesh / PLY loading
- torus and quartic-solver work if it blocks the first scene-construction milestone

## Current Starting Point

The current Nif Traci tree has these relevant boundaries:

- `proj/traci_nif/main/PreprocessAndParse.nif` already runs preprocessor + parser/tree-walker
- `proj/traci_nif/lang/interpreter/node/*.nif` contains data-only nodes produced by the tree-walker
- there is no `proj/traci_nif/lang/interpreter` runtime layer yet beyond the node package
- there is no `proj/traci_nif/model` or `proj/traci_nif/math` package yet

That means the evaluator work should not try to retrofit executable behavior into the current node classes. The current node package should remain a stable data boundary between parsing and interpretation.

## Source Of Truth

For evaluator behavior, the primary Java source of truth is:

- `proj/traci_java/src/se/ejp/traci/lang/interpreter/Interpreter.java`
- `proj/traci_java/src/se/ejp/traci/lang/interpreter/Context.java`
- `proj/traci_java/src/se/ejp/traci/lang/interpreter/TraciValue.java`
- `proj/traci_java/src/se/ejp/traci/lang/interpreter/Entities.java`
- `proj/traci_java/src/se/ejp/traci/lang/interpreter/CallStack.java`
- `proj/traci_java/src/se/ejp/traci/lang/interpreter/functions/*.java`
- `proj/traci_java/src/se/ejp/traci/lang/interpreter/node/*.java`

For typed scene/model construction, the primary Java source of truth is:

- `proj/traci_java/src/se/ejp/traci/model/*.java`
- `proj/traci_java/src/se/ejp/traci/model/light/*.java`
- `proj/traci_java/src/se/ejp/traci/model/material/*.java`
- `proj/traci_java/src/se/ejp/traci/model/material/pigment/*.java`
- `proj/traci_java/src/se/ejp/traci/model/shape/*.java`
- `proj/traci_java/src/se/ejp/traci/model/shape/csg/*.java`
- `proj/traci_java/src/se/ejp/traci/model/shape/primitive/*.java`
- `proj/traci_java/src/se/ejp/traci/math/*.java`

For the Nif side, the current source-of-truth entry points are:

- `proj/traci_nif/main/PreprocessAndParse.nif`
- `proj/traci_nif/lang/parser/ParserRunner.nif`
- `proj/traci_nif/lang/parser/TreeWalker.nif`
- `proj/traci_nif/lang/interpreter/node/*.nif`

## Recommended Design

## 1. Keep The Current Node Package Data-Only

Do not add `eval(...)` methods to the current Nif node classes.

Recommended deviation from Java:

- Java makes the tree-walker output executable by giving each node an `eval(...)` method.
- In Nif, keep `proj/traci_nif/lang/interpreter/node/*.nif` as plain data objects.
- Add an evaluator runtime layer that dispatches on those node objects explicitly.

Why:

- the current port intentionally stopped at a data-only node layer
- Niflheim has no exceptions, so a direct method-for-method Java port would become awkward quickly
- explicit evaluator helpers will be easier to test in isolation and easier to keep readable than one giant node-method translation

## 2. Use Explicit Value Classes, Not A Single `TraciValue`

Do not reproduce the Java `TraciValue(Object)` wrapper literally.

Recommended Nif design:

- add a `Value` interface under `proj/traci_nif/lang/interpreter/value/`
- add one class per concrete runtime value family
- keep the value layer explicit and typed even if it is still dynamic from the evaluator's perspective

Recommended initial value classes:

- `NumberValue`
- `BoolValue`
- `StringValue`
- `VectorValue`
- `ColorValue`
- `TransformationValue`
- `FinishValue`
- `PigmentValue`
- `TextureValue`
- `InteriorValue`
- `MaterialValue`
- `BoundingBoxValue`
- `PrimitiveShapeValue`
- `CsgShapeValue`
- `LightValue`
- `CameraValue`

Deferred value classes for later object support:

- `SkyboxValue`
- `MeshValue`

Recommended `Value` interface shape:

- `fn type_name() -> Str`
- `fn copy_for_read() -> Value`
- `fn debug_render() -> Str`

The key point is not the exact method list. The key point is to make the mutable-vs-immutable distinction explicit in the type system and in the copy semantics.

## 3. Preserve Java-Style Copy Semantics Explicitly

This is the most important behavioral rule in the evaluator.

Java behavior today:

- variables store `TraciValue`
- `Context.getValue(...)` clones on read
- immutable values return themselves from clone
- mutable scene-construction values return distinct copies
- `RefNode` relies on this to avoid accidental aliasing when trailing blocks mutate reused objects

The Nif evaluator should preserve that behavior explicitly.

Recommended rule:

- writes store the evaluated `Value` as-is
- reads call `copy_for_read()` before returning the value to the caller
- immutable values return `self`
- mutable scene-construction values return a new wrapper around a copied model object

Recommended initial copy table:

Immutable, return `self` from `copy_for_read()`:

- `NumberValue`
- `BoolValue`
- `StringValue`
- `VectorValue`
- `ColorValue`
- `TransformationValue`
- `FinishValue`
- `PigmentValue`
- `TextureValue`
- `InteriorValue`
- `MaterialValue`

Mutable, deep-copy on read:

- `BoundingBoxValue`
- `PrimitiveShapeValue`
- `CsgShapeValue`
- `LightValue`
- `CameraValue`

Deferred, define when the feature lands:

- `SkyboxValue`
- `MeshValue`

This is a place where the Nif port should be more explicit than Java. Add the copy rule directly to each value class instead of hiding it behind a wrapper switch.

## 4. Use Explicit Runtime Results Instead Of Exceptions

Java uses exceptions for:

- runtime failures
- illegal arguments
- undefined identifiers
- function return unwinding

That is not a good direct fit for Niflheim.

Recommended Nif design:

- use explicit runtime error objects
- use explicit expression/statement execution result objects
- use explicit return propagation instead of exception unwinding

Recommended runtime result types:

- `RuntimeError`
- `ValueResult` for expression evaluation: either `value` or `error`
- `ExecResult` for statement/block evaluation: `ok`, `return_value`, or `error`

Recommended control-flow rule:

- expression evaluators return `ValueResult`
- statement evaluators return `ExecResult`
- blocks short-circuit on either `return_value` or `error`
- user function invocation returns either `value` or `error`

This is the biggest structural deviation from Java, and it is worth making deliberately instead of trying to simulate Java exceptions indirectly.

## 5. Use An Explicit Object Registry, Not Reflection

Java `ObjectNode` resolves constructors via reflection and static factory methods.

Do not reproduce that literally.

Recommended Nif design:

- add an `ObjectRegistry` under `proj/traci_nif/lang/interpreter/`
- map the object id string to an explicit constructor handler
- validate argument count and types explicitly
- return typed `Value` objects directly

Recommended constructor groups:

- vector/color constructors
- transformation constructors
- pigment/texture/finish/interior/material constructors
- shape constructors
- light/camera constructors
- scene-only constructors later such as `skybox`

This keeps the evaluator behavior close to Java while using a design that matches current Niflheim capabilities.

## 6. Keep Java Package Boundaries, But Split The Evaluator By Concern

Recommended Nif package shape:

```text
proj/traci_nif/
  main/
    PreprocessAndParse.nif
    PreprocessParseAndInterpret.nif
    Result.nif
    Settings.nif
  lang/
    interpreter/
      CallStack.nif
      RuntimeError.nif
      EvalResult.nif
      Context.nif
      Entities.nif
      ObjectRegistry.nif
      Interpreter.nif
      EvalExpr.nif
      EvalStmt.nif
      EvalObject.nif
      functions/
        Function.nif
        FunctionSet.nif
        UserFunction.nif
        BuiltinFunctions.nif
      value/
        Value.nif
        NumberValue.nif
        BoolValue.nif
        StringValue.nif
        VectorValue.nif
        ColorValue.nif
        TransformationValue.nif
        FinishValue.nif
        PigmentValue.nif
        TextureValue.nif
        InteriorValue.nif
        MaterialValue.nif
        BoundingBoxValue.nif
        PrimitiveShapeValue.nif
        CsgShapeValue.nif
        LightValue.nif
        CameraValue.nif
    parser/
    preprocessor/
  math/
    Vector.nif
    Matrix.nif
    Transformation.nif
    Transformations.nif
    Transformable.nif
  model/
    Scene.nif
    Camera.nif
    Color.nif
    Skybox.nif
    light/
      Light.nif
      AmbientLight.nif
      PointLight.nif
    material/
      Finish.nif
      Interior.nif
      Texture.nif
      Material.nif
      pigment/
        Pigment.nif
        Solid.nif
        Checker.nif
        FileImage.nif
    shape/
      Shape.nif
      BoundingBox.nif
      csg/
        Csg.nif
        Union.nif
        Difference.nif
        Intersection.nif
      primitive/
        Primitive.nif
        Box.nif
        Sphere.nif
        Cylinder.nif
        Plane.nif
        Cone.nif
        Torus.nif
```

Important deviation from Java:

- keep `Interpreter.nif` thin
- split executable logic across `EvalExpr.nif`, `EvalStmt.nif`, and `EvalObject.nif`
- keep model code out of the language package

That matches the current repo style better and reduces the risk of one giant evaluator file.

## Recommended First Evaluator Milestones

Do not start by trying to evaluate the full Lego airplane scene.

Recommended milestone order:

1. evaluator core for numeric/string/bool/function/control-flow programs
2. immutable scene-construction values: vector, color, transformations, material stack
3. mutable scene-construction values: shapes, bbox, lights, camera, scene application
4. real scene construction on `basic-shapes.traci`
5. wider lego scene construction
6. only later: `image`, `skybox`, `mesh`, `torus`

This lets the evaluator become useful before the full model tree is ported.

## Missing Or Helpful Niflheim Additions

The high-value additions already landed and are enough to begin evaluator work.

There are still a few additions that would materially improve the evaluator implementation.

## 1. `std.path` Would Help Immediately

Recommended new stdlib module:

- `std/path.nif`

Recommended initial API:

- `dirname(path: Str) -> Str`
- `basename(path: Str) -> Str`
- `join(base: Str, child: Str) -> Str`
- `is_abs(path: Str) -> bool`
- `normalize(path: Str) -> Str`

Why it helps:

- the preprocessor already has local include-resolution helpers because there is no common path module
- later evaluator object handlers for `image`, `skybox`, and `mesh` will need to resolve asset paths relative to the current input file
- even before those features land, a shared path helper avoids duplicating path code again

Priority:

- medium for the first evaluator slice
- high before `image`, `skybox`, or `mesh`

## 2. `std.io` Byte-Oriented Read Helpers Will Help Later

Recommended future additions:

- `read_bytes(path: Str) -> u8[]`
- `try_read_bytes(path: Str) -> u8[]`

These are not required for the first evaluator slice, but they will help when `FileImage`, `Skybox`, and mesh loading are implemented.

## 3. A Small Shared Diagnostic Formatting Helper Would Be Nice, But Is Not Required

This can stay local to Traci for now.

Do not block the evaluator on a generic diagnostic framework.

## Ordered Implementation Steps

## 1. Add Interpreter Diagnostics And Explicit Control-Flow Results

Goal:

- establish the non-exception runtime foundation for the evaluator

What to do:

- add `CallStack.nif` and `CallFrame` formatting close to Java
- add `RuntimeError.nif` with `full_msg()` formatting close to Java
- add `EvalResult.nif` with `ValueResult` and `ExecResult`
- define one shared rule for success, return, and error propagation

Where to do it:

- `proj/traci_nif/lang/interpreter/CallStack.nif`
- `proj/traci_nif/lang/interpreter/RuntimeError.nif`
- `proj/traci_nif/lang/interpreter/EvalResult.nif`

How to test:

- add a focused golden suite under `tests/golden/traci/lang/interpreter/`
- verify runtime error formatting for:
  - undefined variable
  - undefined function
  - illegal argument count
  - illegal argument type
- verify call stack formatting on nested function calls
- verify explicit return propagation formatting/state without exceptions

Checklist:

- [ ] Add `CallStack.nif` and frame formatting.
- [ ] Add `RuntimeError.nif` and `full_msg()`.
- [ ] Add `ValueResult` and `ExecResult`.
- [ ] Add golden tests for runtime error and call-stack formatting.

## 2. Add The Core Context And Function Registry Layer

Goal:

- reproduce the Java `Context` and `FunctionSet` semantics with explicit copy-on-read behavior

What to do:

- add `Context.nif` with:
  - function scope
  - global memory
  - local memory
  - surrounding entity target
  - call stack
- add `functions/Function.nif`
- add `functions/FunctionSet.nif`
- add `functions/UserFunction.nif` that wraps the existing data-only `FunctionNode`
- make `Context.get_value(...)` call `copy_for_read()` before returning

Where to do it:

- `proj/traci_nif/lang/interpreter/Context.nif`
- `proj/traci_nif/lang/interpreter/functions/Function.nif`
- `proj/traci_nif/lang/interpreter/functions/FunctionSet.nif`
- `proj/traci_nif/lang/interpreter/functions/UserFunction.nif`

How to test:

- golden tests for function lookup shadowing
- golden tests for nested helper functions from the current tree-walker output shape
- direct tests for local/global lookup order
- direct tests that `get_value(...)` returns copies for mutable values and self for immutable values

Checklist:

- [ ] Add `Context.nif`.
- [ ] Add `Function` and `FunctionSet`.
- [ ] Add `UserFunction` wrapper over `FunctionNode`.
- [ ] Implement copy-on-read in `Context.get_value(...)`.
- [ ] Add golden coverage for scope and lookup behavior.

## 3. Add Primitive Value Classes And Evaluate The Non-Object Core First

Goal:

- get the evaluator working on the standalone numerical/control-flow testcode before scene objects are involved

What to do:

- add `Value.nif`, `NumberValue.nif`, `BoolValue.nif`, and `StringValue.nif`
- add `EvalExpr.nif` and `EvalStmt.nif` for:
  - constants
  - refs
  - assignments
  - unary operators
  - binary operators
  - if / while / for
  - function call
  - return
  - block execution
- implement the Java operator matrix explicitly
- keep top-level return values available for tests even if the scene-construction pipeline later ignores them

Where to do it:

- `proj/traci_nif/lang/interpreter/value/Value.nif`
- `proj/traci_nif/lang/interpreter/value/NumberValue.nif`
- `proj/traci_nif/lang/interpreter/value/BoolValue.nif`
- `proj/traci_nif/lang/interpreter/value/StringValue.nif`
- `proj/traci_nif/lang/interpreter/EvalExpr.nif`
- `proj/traci_nif/lang/interpreter/EvalStmt.nif`

How to test:

- use the copied standalone testcode under `tests/golden/traci/testcode/`
- add golden tests for:
  - `fibonacci.traci`
  - `prime-checker.traci`
  - `boolean-literals.traci`
  - `boolean-simple.traci`
  - `boolean-comprehensive.traci`
  - `if-statement.traci`
  - `while-loop.traci`
  - `for-loop.traci`
  - `global-value.traci`
  - `nested-function.traci`
- assert returned values and any printed output, not just success codes

Checklist:

- [ ] Add primitive value classes.
- [ ] Implement expression evaluation for number/bool/string forms.
- [ ] Implement statement/block evaluation with explicit return propagation.
- [ ] Implement Java-like operator behavior for primitive values.
- [ ] Add standalone evaluator corpus goldens for current testcode files.

## 4. Add The First Typed Math And Model Slice Needed By The Evaluator

Goal:

- support vector/color/transform/material values that scenes use heavily, while staying out of render-hot-path optimization work for now

What to do:

- add `proj/traci_nif/math/Vector.nif`
- add `proj/traci_nif/model/Color.nif`
- add `proj/traci_nif/math/Transformation.nif`, `Transformations.nif`, and `Transformable.nif`
- add immutable model classes needed by scene construction:
  - `Finish`
  - `Pigment`
  - `Solid`
  - `Checker`
  - `Texture`
  - `Interior`
  - `Material`
- skip weak interning/cache work in the first pass

Where to do it:

- `proj/traci_nif/math/*.nif`
- `proj/traci_nif/model/Color.nif`
- `proj/traci_nif/model/material/*.nif`
- `proj/traci_nif/model/material/pigment/*.nif`

How to test:

- golden tests for vector and color arithmetic matching Java behavior used by `BinaryOpNode` and `UnaryOpNode`
- direct tests for transformation composition order
- direct tests for material/texture/finish/interior replacement semantics
- evaluator tests that build these values from object nodes and apply trailing blocks to them

Checklist:

- [ ] Add `Vector`, `Color`, and transformation modules.
- [ ] Add the immutable material/pigment stack.
- [ ] Add evaluator tests for vector/color arithmetic.
- [ ] Add object-construction tests for `color`, `vector[]`, `solid`, `checker`, `finish`, `texture`, `interior`, and `material`.

## 5. Add The Full Explicit Value Layer For Scene Construction

Goal:

- make mutable-vs-immutable behavior explicit in one coherent value hierarchy

What to do:

- add wrapper classes for the typed model/math objects
- implement `copy_for_read()` on each wrapper
- add a shared helper for converting constants and constructor results into the correct `Value` subclass

Where to do it:

- `proj/traci_nif/lang/interpreter/value/*.nif`

How to test:

- direct tests for `copy_for_read()` behavior
- aliasing tests where a value is stored in a variable, read, transformed, and the original is checked afterwards
- regression tests for global prototypes reused through `RefNode` plus trailing block

Checklist:

- [ ] Add the full evaluator `Value` family.
- [ ] Implement `copy_for_read()` on every value class.
- [ ] Add aliasing regression tests for immutable and mutable values.

## 6. Add The Object Registry And Constructor Handlers

Goal:

- replace Java reflection with explicit, testable constructor dispatch

What to do:

- add `ObjectRegistry.nif`
- add one explicit handler per object keyword family
- validate argument count and types close to the Java behavior
- keep unsupported/deferred handlers explicit instead of silently accepting them

Recommended first-pass handlers:

- `vector[]`
- `color`
- `identity`, `translate`, `scale`, `scalex`, `scaley`, `scalez`, `rotx`, `roty`, `rotz`, `rotVecToVec`, `rotAround`
- `solid`, `checker`
- `finish`, `texture`, `interior`, `material`
- `bbox`

Recommended second-pass handlers once mutable scene types exist:

- `box`, `sphere`, `plane`, `cylinder`, `cone`
- `union`, `difference`, `intersection`
- `pointlight`, `ambientlight`, `camera`

Deferred handlers:

- `torus`
- `image`
- `skybox`
- `mesh`

Where to do it:

- `proj/traci_nif/lang/interpreter/ObjectRegistry.nif`
- `proj/traci_nif/lang/interpreter/EvalObject.nif`

How to test:

- golden tests for successful constructor calls
- golden tests for wrong arity
- golden tests for wrong types
- explicit tests for trailing-block application on constructor results

Checklist:

- [ ] Add `ObjectRegistry.nif`.
- [ ] Implement first-pass immutable constructor handlers.
- [ ] Implement second-pass mutable scene constructor handlers.
- [ ] Add golden coverage for good and bad constructor calls.

## 7. Add Mutable Scene Objects And The `Entities` Application Layer

Goal:

- reproduce Java's block-application semantics for shapes, CSG, scene, lights, camera, bbox, and transformations

What to do:

- add `Scene.nif`
- add `Shape`, `Primitive`, `Csg`, `Union`, `Difference`, `Intersection`, and `BoundingBox`
- add `Light`, `AmbientLight`, and `PointLight`
- add `Camera`
- add `Entities.nif` with explicit target adapters close to Java `Entities`
- make trailing blocks on `RefNode`, `FunctionCallNode`, and `ObjectNode` run through an entity target adapter

Important rule:

- keep the Java apply matrix explicit
- do not push generic "duck typed" mutation logic into the model classes
- the adapter layer should be the place where "a color applied to a shape becomes a solid pigment" and similar rules live

Where to do it:

- `proj/traci_nif/model/*.nif`
- `proj/traci_nif/model/light/*.nif`
- `proj/traci_nif/model/shape/*.nif`
- `proj/traci_nif/model/shape/csg/*.nif`
- `proj/traci_nif/model/shape/primitive/*.nif`
- `proj/traci_nif/lang/interpreter/Entities.nif`

How to test:

- block-application tests for:
  - applying material/texture/pigment/finish/color/interior to primitives and CSG
  - applying transformations to transformables
  - adding shapes/lights/camera to `Scene`
- copy-semantics tests showing that reused shape prototypes are not accidentally aliased after trailing blocks
- real scene-construction tests on `tests/golden/traci/scenes/lego/common/basic-shapes.traci`

Checklist:

- [ ] Add `Scene`, shape, light, and camera model classes needed by evaluator.
- [ ] Add `Entities.nif` target adapters.
- [ ] Add block-application tests matching Java semantics.
- [ ] Add aliasing regression tests for reusable shapes and cameras.

## 8. Add Builtins And Type Validation

Goal:

- match the Java builtin surface that the current scenes and testcode rely on

What to do:

- add `BuiltinFunctions.nif`
- add builtins matching the current Java Traci evaluator:
  - `print`
  - `sin`
  - `cos`
  - `sqrt`
  - `length`
  - `dot`
  - `cross`
  - `rand`
  - `randint`
- add explicit argument-count and argument-type validation in one place

Where to do it:

- `proj/traci_nif/lang/interpreter/functions/BuiltinFunctions.nif`

How to test:

- golden tests for each builtin on normal inputs
- error tests for wrong counts and wrong types
- tests that deterministic RNG behavior stays stable through the interpreter wrapper

Checklist:

- [ ] Add builtin function registry.
- [ ] Add Java-matching builtin surface.
- [ ] Add argument validation and golden tests.

## 9. Wire The Top-Level Interpreter Pipeline

Goal:

- make scene construction invocable as a normal next phase after `PreprocessAndParse`

What to do:

- add `Interpreter.nif` as the main entrypoint for executing a `BlockNode`
- add `PreprocessParseAndInterpret.nif` in `proj/traci_nif/main/`
- return:
  - phase `Result`
  - frontend diagnostics
  - interpreter runtime error if any
  - constructed `Scene`
  - optional last top-level return value for tests

Recommended deviation from Java:

- keep `last_top_level_return_value` available in the run object for testcode-oriented golden tests
- keep the normal scene-construction path focused on the constructed `Scene`

Where to do it:

- `proj/traci_nif/lang/interpreter/Interpreter.nif`
- `proj/traci_nif/main/PreprocessParseAndInterpret.nif`

How to test:

- end-to-end golden tests for:
  - `fibonacci.traci` returning a numeric value
  - `prime-checker.traci` returning a numeric or boolean-like result as appropriate
  - `basic-shapes.traci` building a scene with expected top-level shape/light/camera counts
- main-pipeline tests that combine preprocessing, parsing, tree-walking, and interpretation

Checklist:

- [ ] Add `Interpreter.nif`.
- [ ] Add `PreprocessParseAndInterpret.nif`.
- [ ] Expose constructed `Scene` and top-level return value for tests.
- [ ] Add end-to-end interpreter pipeline goldens.

## 10. Expand To Real Scene Corpus In Controlled Order

Goal:

- validate the evaluator on real copied Traci files without blocking the first milestone on deferred asset features

Recommended validation order:

1. standalone copied testcode files
2. `tests/golden/traci/scenes/lego/common/basic-shapes.traci`
3. the copied lego brick files that do not require `image`, `skybox`, or `mesh`
4. only then the airplane scene, after the needed asset features land

Where to do it:

- `tests/golden/traci/lang/interpreter/test_interpreter_corpus.nif`
- `tests/golden/traci/lang/interpreter/test_interpreter_corpus_spec.yaml`

How to test:

- scene summaries
- object counts
- selected property snapshots
- runtime-error goldens for unsupported deferred object kinds until those handlers land

Checklist:

- [ ] Add interpreter corpus goldens for standalone testcode.
- [ ] Add interpreter corpus goldens for `basic-shapes.traci`.
- [ ] Add controlled lego scene coverage.
- [ ] Keep `airplane.traci` as a later asset-enabled milestone.

## Recommended Test Tree

Recommended new golden suites:

```text
tests/golden/traci/lang/interpreter/
  test_runtime_error.nif
  test_runtime_error_spec.yaml
  test_values.nif
  test_values_spec.yaml
  test_interpreter_core.nif
  test_interpreter_core_spec.yaml
  test_objects.nif
  test_objects_spec.yaml
  test_copy_semantics.nif
  test_copy_semantics_spec.yaml
  test_interpreter_corpus.nif
  test_interpreter_corpus_spec.yaml
tests/golden/traci/main/
  test_interpret_main.nif
  test_interpret_main_spec.yaml
```

Use the copied fixtures already under:

- `tests/golden/traci/testcode/`
- `tests/golden/traci/scenes/lego/`

Do not reintroduce direct test dependencies on `proj/traci_java` paths.

## First Milestone Definition

The first evaluator milestone is complete when all of these are true:

- the evaluator runs the current numerical/control-flow testcode corpus successfully
- explicit value classes are in place
- `Context.get_value(...)` uses explicit copy-on-read semantics
- `RefNode`, `FunctionCallNode`, and `ObjectNode` trailing blocks work through `Entities`
- `basic-shapes.traci` constructs a typed `Scene` without runtime errors
- runtime errors are reported with include location and call stack formatting close to Java

The evaluator milestone does not require:

- renderer output
- image textures
- skybox support
- mesh loading
- torus support

Those should remain follow-up work after the scene-construction evaluator is stable.