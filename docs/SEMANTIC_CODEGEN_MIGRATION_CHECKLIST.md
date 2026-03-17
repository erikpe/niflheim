# Semantic Codegen Migration Checklist

This checklist gives the recommended implementation order for temporarily bypassing reachability while migrating codegen onto the lowered semantic program.

The intent is:

- keep the current source-AST pipeline working while the new path is built
- allow semantic codegen to operate on the full lowered program before pruning exists
- reintroduce reachability later as a semantic-IR pass instead of blocking the backend migration

## Phase 1: Add An Alternative CLI Path

1. Add a new non-default CLI switch in `compiler/cli.py` for the semantic backend path.
2. Keep the existing default path unchanged:
   - resolve
   - typecheck
   - coarse `prune_unreachable`
   - source-AST merge
   - old codegen
3. Wire the alternative path to do:
   - resolve
   - typecheck
   - `lower_program(program)`
   - semantic codegen entrypoint
4. Do not run reachability on the alternative path yet.
5. Add one small integration test proving the new flag selects the semantic path without changing the default path.

Exit criteria:

- the compiler has two explicit backend paths
- the semantic path can bypass reachability completely
- the old path remains the safety net during migration

## Phase 2: Add A Semantic Codegen Boundary

1. Introduce a semantic-codegen input model instead of forcing lowered IR back through `ModuleAst`.
2. Decide whether this is:
   - direct emission from `SemanticProgram`, or
   - a small semantic linker/builder layer that prepares one codegen-ready semantic view
3. Keep this boundary narrow: symbol ownership, merged declaration ordering, and entry-module selection should live here.
4. Do not port the full emitter yet; first establish the new data boundary and a stub entrypoint.
5. Add tests that validate this layer preserves module ordering and duplicate-symbol checks where those still matter.

Recommended files:

- `compiler/module_linker.py` if extended carefully, or
- a new file such as `compiler/semantic_linker.py`
- `compiler/codegen/generator.py` for the new semantic entrypoint

Exit criteria:

- semantic codegen has a real input boundary
- the backend no longer depends on rebuilding a source AST for the new path

## Phase 3: Port Symbol And Declaration Collection

1. Port global function/class/method collection from source AST assumptions to semantic declarations.
2. Port label/symbol generation to consume canonical IDs where practical.
3. Keep output naming stable unless a deliberate symbol-format change is required.
4. Validate that entrypoint checks, extern declarations, class layout collection, and method tables still build correctly from semantic declarations.
5. Add focused tests for symbol emission and declaration indexing on the semantic path.

Exit criteria:

- the backend can inventory semantic declarations without reading source AST nodes
- codegen symbol planning works before statement/expression emission is migrated

## Phase 4: Port Expression Emission First

1. Introduce semantic-expression emission helpers alongside the existing AST-based ones.
2. Start with the highest-value nodes already normalized by Pass 3 and Pass 4:
   - `FunctionCallExpr`
   - `StaticMethodCallExpr`
   - `InstanceMethodCallExpr`
   - `ConstructorCallExpr`
   - `CallableValueCallExpr`
   - `IndexReadExpr`
   - `SliceReadExpr`
   - string literal helper form
   - string concat helper form
3. Remove semantic recovery logic from the new emitter path:
   - no guessing whether a call is a constructor or method
   - no rebuilding `Str.from_u8_array`
   - no rebuilding `Str.concat`
   - no rebuilding structural method calls from raw syntax
4. Keep the old emitter code in place for the old path until parity is established.
5. Add semantic-emitter unit tests that mirror the current source-emitter coverage for calls, strings, casts, arrays, and structural operations.

Exit criteria:

- semantic expression emission works without depending on source-AST call interpretation
- the new backend demonstrates the payoff of semantic lowering immediately

## Phase 5: Port Statement And Control-Flow Emission

1. Add emission for semantic statements and blocks:
   - `SemanticVarDecl`
   - `SemanticAssign`
   - `SemanticExprStmt`
   - `SemanticReturn`
   - `SemanticIf`
   - `SemanticWhile`
   - `SemanticForIn`
   - `SemanticBreak`
   - `SemanticContinue`
2. Implement assignment emission from semantic lvalues:
   - `LocalLValue`
   - `FieldLValue`
   - `IndexLValue`
   - `SliceLValue`
3. Ensure the semantic emitter uses already-resolved structural method IDs rather than rediscovering them.
4. Add unit tests for statement lowering/emission parity, especially for `for in`, index assignment, and slice assignment.

Exit criteria:

- semantic codegen can emit full lowered function and method bodies
- the new path can compile non-trivial programs end-to-end without using the old statement emitter

## Phase 6: Reach Semantic Backend Feature Parity

1. Run existing codegen unit tests against the semantic backend path where possible.
2. Add backend-parity tests for representative programs:
   - plain function calls
   - constructors
   - static and instance methods
   - callable values
   - arrays and structural indexing
   - slices
   - `for in`
   - strings
   - casts
3. Compare emitted assembly behavior, not necessarily byte-for-byte text, unless stable textual parity is realistic.
4. Fix gaps in layout planning, root handling, ABI lowering, and runtime hooks that only show up once full bodies are emitted from semantic IR.

Exit criteria:

- the semantic backend handles the same language surface as the old backend for supported programs
- the semantic path is credible enough to begin replacing the old path

## Phase 7: Make Semantic Codegen The Preferred Path

1. Flip the CLI switch so the semantic backend becomes the default path.
2. Keep the old source-AST backend behind a temporary fallback flag for one migration window.
3. Run the full unit, integration, golden, and runtime suites on both paths at least once before removing the fallback.
4. Fix any remaining regressions that are due to backend parity rather than reachability.

Exit criteria:

- default compilation uses lowered semantic IR
- reachability is still bypassed on the semantic path
- the old backend is retained only as a temporary rollback option

## Phase 8: Reintroduce Reachability On Semantic IR

1. Replace coarse source-AST reachability with semantic-IR reachability.
2. Make the new walker operate on explicit semantic edges:
   - function calls
   - method calls
   - constructors
   - structural helper edges
   - synthetic helper dependencies
3. Add semantic pruning after lowering and before semantic codegen.
4. Validate that pruning removes dead declarations without changing runtime behavior.
5. Remove the temporary semantic-path bypass once the semantic reachability pass is trusted.

Exit criteria:

- reachability is no longer a blocker for semantic codegen migration
- pruning is once again available, but now at the correct abstraction level

## Phase 9: Remove The Old Source-AST Backend Path

1. Delete the old source-AST-specific codegen entrypoint.
2. Delete source-AST merge/link steps that only existed for the old backend.
3. Remove dead code in call resolution and emitter helpers that depended on AST-shape interpretation.
4. Update docs and tests so semantic IR is the only supported codegen input.
5. Remove any temporary CLI compatibility switches.

Exit criteria:

- codegen consumes only lowered semantic IR
- no production code path depends on the old merged `ModuleAst` backend model

## Phase 10: Finish With Full Validation

1. Run the full pytest suite.
2. Run golden-output checks.
3. Run runtime smoke and harness tests.
4. Verify the default CLI path is now:
   - resolve
   - typecheck
   - lower to semantic IR
   - semantic reachability/prune
   - semantic codegen
5. Verify there are no remaining hidden semantic-lowering responsibilities inside codegen except deliberate backend-only runtime details.

Final exit criteria:

- the lowered IR is the single codegen input
- reachability operates on semantic IR instead of source AST
- all existing tests pass
- the temporary migration switches and fallback backend are gone
