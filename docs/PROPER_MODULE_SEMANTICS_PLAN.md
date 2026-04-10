Status: phase 1 implemented; phases 2-4 design only.

This document defines a concrete implementation plan for proper top-level module semantics.

The target semantics are:

- imports remain required for all cross-module visibility, including qualified access
- unqualified lookup remains local-first, then unique visible imported symbol, otherwise ambiguity error
- same leaf names are allowed across modules for top-level functions, classes, and interfaces
- qualified names are the canonical explicit disambiguation path in source
- entrypoint selection is a separate rule: only the linked program's entry module must provide `fn main() -> i64`

## Scope

This plan covers:

- import-alias syntax needed to preserve ergonomic qualification in existing code
- source-level name resolution policy
- semantic/linker behavior for top-level declarations
- codegen symbol naming for top-level functions
- compatibility risks for diagnostics, metadata, and tests

This plan does not cover:

- adding absolute global names that bypass imports
- changing method, constructor, or runtime ABI semantics beyond what is needed for top-level function identity

## Current State

The current implementation is already partly aligned with the desired direction.

What already matches:

- `compiler/typecheck/module_lookup.py` already separates unqualified imported lookup from qualified imported lookup.
- `compiler/semantic/symbols.py` already models top-level function, class, and interface identity with `module_path` plus leaf name.
- `compiler/semantic/types.py` already uses module-qualified nominal canonical names such as `main::Box`.
- class, constructor, method, and interface metadata symbols are already mostly mangled from canonical type names in the codegen layer.

What still blocks proper module semantics:

- `compiler/frontend/ast_nodes.py` and `compiler/frontend/declaration_parser.py` do not yet represent or parse explicit import aliases.
- `compiler/grammar/niflheim_v0_1.ebnf` and `docs/GRAMMAR_EBNF.md` still describe only `import foo.bar;` and `export import foo.bar;`.
- `compiler/resolver.py` still binds imports under the leaf alias, which matches current syntax but not the stricter full-path qualification target.
- `compiler/semantic/linker.py` still merges top-level functions and classes by bare leaf name across modules.
- `compiler/codegen/emitter_fn.py` still defaults top-level function labels to `fn.function_id.name`.
- `compiler/codegen/emitter_expr.py` still references top-level function symbols by bare name for function refs and direct calls.
- `compiler/codegen/program_generator.py` already treats methods and constructors as declaration-table-backed symbols, but top-level functions do not yet go through the same canonical label path.
- `compiler/codegen/metadata.py` and its tests still assume short class aliases such as `Key` remain globally unambiguous inside one linked program.

## Target Semantics

## Source-Level Name Resolution Policy

The source model should remain import-rooted.

That means:

1. A module cannot refer to another module's symbol unless that module is visible through an `import` or re-export chain.
2. Unqualified lookup stays local-first.
3. If no local declaration matches, resolve against visible imported symbols.
4. If exactly one visible imported symbol of the requested kind matches, use it.
5. If more than one visible imported symbol matches, report an ambiguity error listing module candidates.
6. Qualified lookup stays explicit and import-rooted: the qualification path must start from either an imported module path or an explicit import alias, and later segments walk exported submodules before selecting the final exported symbol.

This deliberately changes the current source spelling model toward full imported module paths plus explicit aliases, where:

- `import long.path.to.modulea;` makes `long.path.to.modulea` visible as the canonical qualification root
- `long.path.to.modulea.MyClass` is a valid explicit qualification
- `import long.path.to.modulea as modulea;` makes `modulea.MyClass` a valid explicit qualification
- `MyClass` also remains valid if it is the only visible imported `MyClass`

This is not the same as introducing absolute global names. `long.path.to.modulea.MyClass` is only legal when that module path is visible through an `import` or re-export chain.

Import aliases should be treated as part of the same semantics migration, not as a later unrelated feature. They are the compatibility mechanism that keeps most existing qualified test code close to its current shape. The intended spelling is:

```nif
import long.path.to.modulea as modulea;
var value: modulea.MyClass = modulea.MyClass(...);
```

Canonical identity still remains full-module-path based even when source syntax uses an alias.

## Module Aliasing Policy

The aliasing rules should be:

- `import long.path.to.modulea;` exposes the full imported module path for explicit qualification
- `import long.path.to.modulea as modulea;` exposes `modulea` as the explicit qualification root
- if no alias is given, the leaf segment must not be treated as an implicit alias after the migration completes
- unqualified imported symbol resolution continues to ignore aliases and works from visible imported exports

This gives a clear and stable meaning to qualification:

- full path for canonical explicit reference
- explicit alias for short explicit reference
- no hidden fallback from plain import to leaf alias

## Canonical Top-Level Identity

The compiler should treat these as the real top-level identities:

- `FunctionId(module_path, name)`
- `ClassId(module_path, name)`
- `InterfaceId(module_path, name)`

These IDs already exist. The main change is to make all later phases consistently respect them.

Consequences:

- two modules may both define `main`, `helper`, `Box`, or `Hashable`
- the linker must preserve both declarations instead of folding by leaf name
- diagnostics should prefer module-qualified wording when talking about canonical identity
- codegen must use a label scheme derived from canonical IDs instead of leaf names

## Entrypoint Rule

Entrypoint selection should remain separate from top-level symbol identity.

The rule should be:

- exactly one semantic entrypoint is required: `fn main() -> i64` in the linked program's `entry_module`
- other modules may legally define their own `main`
- those other `main` functions are ordinary top-level functions and must not collide with the process entry symbol

This removes the current accidental behavior where non-entry `main` only works if optimization removes it before codegen.

## Linker Plan

## Desired Behavior

The linker should concatenate semantic modules while preserving canonical top-level IDs.

Top-level classes:

- stop rejecting duplicate class leaf names across different modules
- preserve classes in deterministic module order
- continue rejecting only true same-module declaration duplicates, which the resolver already enforces

Top-level functions:

- stop merging functions by bare `fn_name`
- stop treating cross-module `extern` plus body as a single symbol
- preserve both declarations when their `FunctionId`s differ
- keep same-module duplicate declaration rejection in the resolver

This is the right semantic outcome because cross-module symbols are no longer “duplicates”; they are different symbols with the same leaf name.

## Concrete Linker Changes

In `compiler/semantic/linker.py`:

- replace `function_index_by_name`, `function_has_body`, and `function_owner_by_name` with structures keyed by `FunctionId`, or remove them entirely if no dedup remains necessary
- replace `class_owner_by_name` with either nothing or an optional sanity check keyed by `ClassId`
- preserve module-order concatenation of `module_info.functions` and `module_info.classes`
- keep `require_main_function` exactly entry-module scoped

Expected outcome:

- `tests/golden/vm_benchmark/test_vm_benchmark_spec.yaml` can use `--skip-optimize` without tripping duplicate `main`
- same-name top-level functions and classes across modules are accepted
- semantic identity no longer depends on optimization removing unreachable modules or functions

## Source Resolution And Lowering Plan

The typechecker and lowering layers are already close to the target policy. The goal here is to freeze and test the intended behavior, not redesign the resolver.

Required policy checks:

- add explicit import alias syntax without changing the canonical internal module identity
- keep unique imported unqualified resolution for classes, interfaces, and functions
- keep ambiguity diagnostics for multiple visible imported matches
- change qualified resolution from implicit leaf aliases to full imported paths or explicit aliases
- keep qualified resolution import-rooted and export-checked
- keep local declarations shadowing imported ones in unqualified lookup
- keep canonical type names module-qualified even when source syntax is unqualified

Likely edit points:

- `compiler/frontend/ast_nodes.py`
- `compiler/frontend/declaration_parser.py`
- `compiler/grammar/niflheim_v0_1.ebnf`
- `docs/GRAMMAR_EBNF.md`
- `tests/compiler/frontend/parser/test_parser.py`
- `tests/compiler/frontend/parser/golden/`
- `compiler/resolver.py`
- `compiler/typecheck/module_lookup.py`
- `compiler/semantic/lowering/ids.py`
- `compiler/semantic/lowering/resolution.py`
- `compiler/semantic/display.py`

The recommended implementation posture is conservative: land alias syntax support first, bulk-update source fixtures that rely on leaf-module qualification to use explicit aliases, and only then flip the resolver/typechecker over to the stricter qualification rule.

## Migration Strategy For Tests And Samples

Many existing `.nif` tests and samples currently rely on the implicit leaf-alias behavior:

```nif
import long.path.to.modulea;
var value: modulea.MyClass = modulea.MyClass(...);
```

The plan should explicitly preserve a manageable migration path:

1. Add parser and resolver support for `import ... as alias;` first.
2. Bulk-update tests, samples, and parser goldens that use leaf-qualified imported names so they instead spell the import explicitly with `as`.
3. Only after that bulk migration is in place, switch qualified lookup to reject implicit leaf aliases from plain imports.

That sequencing keeps the source churn small because most existing code only needs the import line changed.

## Handling The Temporary Failure Gap

The implementation must not assume that the repository can sit in a long-lived red state while the language transition is in progress.

Recommended handling:

- preferred: land alias syntax support and the bulk `.nif` test update atomically in the same branch or PR series before enabling the strict rule
- acceptable fallback: temporarily accept both explicit aliases and legacy implicit leaf aliases for a short migration window, then remove the legacy fallback immediately after the corpus rewrite lands
- avoid landing a mainline commit that enables strict full-path-or-alias qualification before the existing test corpus has been migrated

The second option is a migration aid, not a target semantics change. If used, it should be tracked as a bounded compatibility shim with a planned removal step.

## Emitted Symbol Mangling Plan

## Problem

Top-level functions still use bare labels in assembly.

Current examples:

- `compiler/codegen/emitter_fn.py` defaults `target_label` to `fn.function_id.name`
- `compiler/codegen/emitter_expr.py` emits `lea` for `FunctionRefExpr` using the bare leaf name
- `compiler/codegen/emitter_expr.py` emits direct top-level calls using the bare leaf name

That is incompatible with allowing multiple modules to define `helper` or `main`.

## Recommended Design

Introduce a canonical codegen label for every top-level function, derived from `FunctionId`.

Recommended helper:

```python
def mangle_function_symbol(module_path: ModulePath, name: str) -> str:
    ...
```

Recommended output shape:

- `main.main` body label becomes something like `__nif_fn_main_main`
- `samples.vm_benchmark.main.main` body label becomes something like `__nif_fn_samples_vm_benchmark_main_main`
- ordinary helpers follow the same rule

The exact separator is less important than these properties:

- deterministic
- derived from full module path plus leaf name
- uses the same escaping rules as the rest of `compiler/codegen/symbols.py`
- impossible to collide for distinct `FunctionId`s

## Entry Symbol Strategy

Do not make the raw process entry symbol the canonical semantic function label.

Recommended approach:

1. Emit every semantic top-level function under its mangled canonical label.
2. Emit one ABI-visible `main` wrapper or alias only for the linked program's entry-module `main`.
3. Have that wrapper tail-call or jump to the mangled canonical entry function.

Why this is preferred:

- internal semantic identity stays uniform for all functions, including entry `main`
- duplicate non-entry `main` no longer affects the process entry symbol
- tests can distinguish semantic symbol naming from host ABI glue

## Codegen Plumbing Changes

In `compiler/codegen/symbols.py`:

- add `mangle_function_symbol(...)`
- reuse the existing type-fragment escaping helper so function, type, and debug symbol naming stay consistent

In `compiler/codegen/program_generator.py`:

- add function label storage keyed by `FunctionId`, parallel to existing method and constructor label tables
- expose a declaration-table lookup for top-level functions

In `compiler/codegen/emitter_fn.py`:

- default `emit_function(...)` to the declaration-table-backed mangled label for top-level functions
- stop using bare leaf names as the default assembly label
- emit the ABI `main` wrapper only when `fn.function_id.module_path == linked_program.entry_module` and `fn.function_id.name == "main"`

In `compiler/codegen/emitter_expr.py`:

- route `FunctionRefExpr` through the declaration-table label map
- route `FunctionCallTarget` through the same label map
- remove any remaining assumptions that `function_id.name` is an assembly symbol

Expected outcome:

- function references and direct calls remain correct even with colliding leaf names across modules
- top-level function identity becomes as robust as method and constructor identity already are

## Runtime Metadata And Alias Policy

Classes and interfaces are already much closer to the desired state because their metadata and vtable symbols are based on canonical type names.

The remaining compatibility issue is short aliases.

Today, class metadata tests still expect aliases like:

- `("Key", "main::Key")`

That becomes unsound once two loaded modules both define `Key`.

Recommended rule:

- always emit the canonical module-qualified alias
- emit the short leaf alias only when it is unique across the linked program's loaded classes or interfaces

This preserves convenient names in simple programs without lying about ambiguous ones.

Files likely involved:

- `compiler/codegen/metadata.py`
- `compiler/codegen/program_generator.py`

If this proves awkward, the fallback simplification is to emit canonical aliases only. That is more breaking for tests, but semantically cleaner.

## Diagnostics And Compatibility Risks

## Diagnostics

Expected changes:

- some diagnostics should start naming module-qualified identities where today they mention only the leaf name
- ambiguity errors should keep listing module candidates
- duplicate cross-module class or function errors should disappear, because they are no longer valid errors

Care is needed not to regress the current good diagnostics around:

- `Ambiguous imported function 'add'`
- `Ambiguous imported type 'Counter'`
- `Module 'util' has no exported class 'Hidden'`
- `Module 'util' has no exported module 'missing'`

Those errors are still correct under the target semantics.

## Behavior Changes

The most important intentional behavior change is removal of cross-module top-level merging.

That means the current behavior tested in `tests/compiler/semantic/test_linker.py` for “prefer body over extern duplicate” should be replaced.

New semantics:

- `decls.helper` and `main.helper` are distinct functions
- local `helper()` in `main` still resolves to `main.helper`
- imported `decls.helper` remains available through imported resolution rules

## Test Fragility

The biggest test churn will be in codegen tests that currently assert raw labels such as:

- `main:`
- `.Lmain_epilogue:`
- `lea rax, [rip + add]`

Those tests should migrate toward one of two patterns:

1. assert through the mangling helper directly
2. assert against the emitted canonical mangled label, while keeping one focused test for the ABI `main` wrapper

There is a separate source-level churn risk in parser, typecheck, semantic, golden, and sample `.nif` files that currently rely on implicit leaf aliases from plain imports. Those should be bulk-updated to explicit `as` imports before the strict resolver change is turned on.

## Ordered Implementation Checklist

The implementation should be done in phases. Phase 1 is explicitly the alias migration phase.

### Phase 1: Alias Migration Phase

Goal: add explicit import aliases, migrate existing source code to use them, and keep the repository buildable throughout the transition.

- [x] Add import alias syntax to the frontend AST and parser.
    Files:
    `compiler/frontend/ast_nodes.py`, `compiler/frontend/declaration_parser.py`
    Expected outcome:
    The language accepts `import foo.bar as baz;` and carries the alias through the frontend model.

- [x] Update the grammar and syntax documentation for aliased imports.
    Files:
    `compiler/grammar/niflheim_v0_1.ebnf`, `docs/GRAMMAR_EBNF.md`
    Expected outcome:
    The grammar docs match the new import syntax and no longer imply that plain imports are the only explicit qualification mechanism.

- [x] Add parser coverage for aliased imports.
    Files:
    `tests/compiler/frontend/parser/test_parser.py`, `tests/compiler/frontend/parser/golden/`
    Expected outcome:
    Parser tests cover plain imports, aliased imports, and exported aliased imports.

- [x] Teach the resolver and qualified lookup to understand explicit aliases.
    Files:
    `compiler/resolver.py`, `compiler/typecheck/module_lookup.py`, `compiler/semantic/lowering/resolution.py`
    Expected outcome:
    Both `long.path.to.modulea.MyClass` and `modulea.MyClass` after `import long.path.to.modulea as modulea;` resolve correctly.

- [x] Decide whether to use a short-lived compatibility shim.
    Files:
    `compiler/resolver.py`, `compiler/typecheck/module_lookup.py`
    Expected outcome:
    Either:
    the branch lands alias support and corpus migration atomically, or
    a temporary compatibility path accepts legacy implicit leaf aliases until the migration is complete.

- [x] Bulk-update existing `.nif` tests, samples, and docs snippets that rely on implicit leaf-module qualification.
    Files:
    `tests/`, `samples/`, parser golden fixtures, affected docs snippets
    Expected outcome:
    Existing source code mostly changes only in the import line, for example from `import long.path.to.modulea;` to `import long.path.to.modulea as modulea;`.

Tests for phase 1:

- [x] Run `tests/compiler/frontend/parser/test_parser.py`.
- [x] Refresh and verify parser goldens for aliased imports.
- [x] Run `tests/compiler/typecheck/test_program_imports.py`.
- [x] Run `tests/compiler/semantic/test_lowering_resolution.py`.

### Phase 2: Strict Qualification And Semantic Acceptance

Goal: switch from implicit leaf aliases to the target qualification rule, then make the linker respect canonical top-level identities.

- [ ] Flip qualified resolution to the strict target rule.
    Files:
    `compiler/resolver.py`, `compiler/typecheck/module_lookup.py`
    Expected outcome:
    Plain imports no longer create hidden leaf aliases. Explicit qualification must use the full imported path or an explicit alias.

- [ ] Remove any temporary compatibility shim from phase 1.
    Files:
    `compiler/resolver.py`, `compiler/typecheck/module_lookup.py`
    Expected outcome:
    The final semantics are enforced directly, with no migration-only fallback left behind.

- [ ] Add negative coverage for the old implicit leaf-alias behavior.
    Files:
    `tests/compiler/typecheck/test_program_imports.py`, `tests/compiler/semantic/test_lowering_resolution.py`
    Expected outcome:
    Plain-import leaf qualification now fails, while explicit alias and full-path qualification still succeed.

- [ ] Remove cross-module top-level dedup in the linker.
    Files:
    `compiler/semantic/linker.py`
    Expected outcome:
    Top-level functions and classes are preserved by canonical ID instead of merged by leaf name.

- [ ] Update linker tests for the new semantics.
    Files:
    `tests/compiler/semantic/test_linker.py`
    Expected outcome:
    Same-name declarations in different modules are accepted. The old extern-plus-body merge behavior is replaced by distinct-symbol expectations.

Tests for phase 2:

- [ ] Re-run `tests/compiler/typecheck/test_program_imports.py`.
- [ ] Re-run `tests/compiler/semantic/test_lowering_resolution.py`.
- [ ] Run `tests/compiler/semantic/test_linker.py`.

### Phase 3: Top-Level Function Codegen Phase

Goal: make top-level function emission use canonical labels so same-name functions across modules remain codegen-safe.

- [ ] Add canonical top-level function mangling.
    Files:
    `compiler/codegen/symbols.py`, `tests/compiler/codegen/test_symbols.py`
    Expected outcome:
    A single helper defines stable assembly labels for `FunctionId` values.

- [ ] Route top-level function labels through declaration tables.
    Files:
    `compiler/codegen/program_generator.py`, related declaration-table model files
    Expected outcome:
    Top-level functions use the same kind of canonical label plumbing that methods and constructors already use.

- [ ] Switch function emission, function references, and direct calls to canonical labels.
    Files:
    `compiler/codegen/emitter_fn.py`, `compiler/codegen/emitter_expr.py`
    Expected outcome:
    Assembly no longer depends on bare top-level leaf names, so top-level symbol collisions disappear.

- [ ] Separate semantic entrypoint identity from the ABI `main` symbol.
    Files:
    top-level program emission code, `compiler/codegen/emitter_fn.py`, CLI and integration test files
    Expected outcome:
    Only the entry module exports the process `main`, while every semantic `main` keeps its own canonical mangled label.

Tests for phase 3:

- [ ] Run `tests/compiler/codegen/test_symbols.py`.
- [ ] Run focused `tests/compiler/codegen/` tests that currently assert raw top-level function labels or direct calls.
- [ ] Add and run a regression test with two imported `helper` functions and explicit qualified calls.
- [ ] Add and run an integration test with two modules that both define `main`, confirming the CLI-selected entry module is the one that becomes the ABI entrypoint.

### Phase 4: Metadata And End-To-End Validation Phase

Goal: finish the remaining compatibility work and confirm the full compiler pipeline behaves correctly under the new module semantics.

- [ ] Make runtime metadata alias emission safe under duplicate leaf names.
    Files:
    `compiler/codegen/metadata.py`, `compiler/codegen/program_generator.py`, `tests/compiler/codegen/test_program_generator.py`
    Expected outcome:
    Metadata always includes canonical aliases and only includes short leaf aliases when they are genuinely unique.

- [ ] Update end-to-end regression coverage and golden expectations.
    Files:
    `tests/golden/runner.py` only as needed, `tests/golden/vm_benchmark/test_vm_benchmark_spec.yaml`, relevant integration and golden tests
    Expected outcome:
    `--skip-optimize` and duplicate leaf names are safe in real linked programs, not just in isolated unit tests.

Tests for phase 4:

- [ ] Run `tests/compiler/codegen/test_program_generator.py`.
- [ ] Run the VM benchmark golden with `build_args: ["--skip-optimize"]`.
- [ ] Run the full pytest suite.

## Suggested Test Sequence

Recommended validation order while implementing:

1. `tests/compiler/frontend/parser/test_parser.py`
2. parser golden refresh and verification for aliased imports
3. `tests/compiler/typecheck/test_program_imports.py`
4. `tests/compiler/semantic/test_lowering_resolution.py`
5. `tests/compiler/semantic/test_linker.py`
6. `tests/compiler/codegen/test_symbols.py`
7. focused `tests/compiler/codegen/` tests that mention raw top-level function labels
8. `tests/compiler/codegen/test_program_generator.py`
9. the VM benchmark golden with `--skip-optimize`
10. full pytest

This order isolates syntax and migration fallout first, linker regressions second, and assembly-label fallout last.

## Recommended Rollout Notes

Keep this work in four implementation phases even if committed together:

1. alias migration phase: parser, resolver, temporary compatibility handling if needed, and bulk test rewrites
2. strict qualification and semantic acceptance phase: final qualified lookup behavior plus linker changes
3. top-level function codegen phase: mangled function labels plus ABI `main` wrapper
4. metadata and end-to-end validation phase

That split makes failures easier to localize while still giving a clear way to keep the repository green. The important constraint is that phase 2 must not land before phase 1 has migrated the test corpus or provided a bounded compatibility shim.