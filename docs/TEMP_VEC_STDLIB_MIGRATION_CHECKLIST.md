# TEMP: Vec stdlib migration checklist

Temporary working checklist for migrating Vec from compiler/runtime builtin handling to stdlib Nif implementation backed by Obj[].

Remove this file when all items are complete.

Persistent policy and rationale live in docs/INDEXING_SUGAR_DESIGN.md.

---

## Phase 1: Minimal compile-green migration

Goal: land stdlib-backed Vec and remove critical compiler hardcoding while keeping the tree green.

### 0) Guardrails (do first)

- [x] Keep docs/INDEXING_SUGAR_DESIGN.md as the canonical policy source.
- [ ] Avoid adding any new Vec hardcoding during migration.
- [x] Preserve language sugar behavior:
  - [x] obj[idx] == obj.get(idx)
  - [x] obj[idx] = v == obj.set(idx, v)
  - [x] obj[a:b] == obj.slice(a, b)

---

### 1) Add stdlib Vec implementation (Obj[] backing)

- [x] Prerequisite: general class field read/write codegen support exists (needed for Vec internal state fields).
- [x] Create std/vec.nif with exported class Vec.
- [x] Implement internal storage with Obj[] + capacity/len bookkeeping.
- [ ] Provide baseline API parity expected by existing programs/tests:
  - [x] Vec() constructor path (or static new, then update callers consistently)
  - [x] len
  - [x] push
  - [x] get(i64)
  - [x] set(i64, Obj)
  - [x] optional slice(i64, i64) if Vec slicing is to be supported now
- [x] Ensure index type is i64 and bounds behavior is deterministic.

---

  ### 2) Remove Vec as builtin token/type special-case

  Depends on: 1 (stdlib Vec skeleton in place)

### Lexer/parser surface

- [x] compiler/tokens.py
  - [x] Remove Vec keyword token and keyword mapping.
  - [x] Ensure Vec is lexed as IDENT.
  - [x] Remove VEC from TYPE_NAME_TOKENS.
- [x] compiler/parser.py
  - [x] Remove TokenKind.VEC from BUILTIN_CALLABLE_TYPE_TOKENS.
  - [x] Ensure type and call parsing works via IDENT path for Vec.
- [x] compiler/grammar/niflheim_v0_1.ebnf
  - [x] Remove Vec from builtin named_type list if no longer language-builtin.

### Type system model

- [x] compiler/typecheck_model.py
  - [x] Remove Vec from REFERENCE_BUILTIN_TYPE_NAMES.
  - [x] Remove Vec from BUILTIN_INDEX_RESULT_TYPE_NAMES.

---

### 3) Typechecker: delete Vec hardcoding; keep structural sugar

Depends on: 2

- [x] compiler/typecheck_checker.py
  - [x] Remove BUILTIN_VEC_METHOD_SPECS.
  - [x] Remove IdentifierExpr special case that treats Vec as builtin callable.
  - [x] Remove FieldAccessExpr special case for object_type.name == "Vec".
  - [x] Remove CallExpr special case for Vec constructor/method signatures.
  - [x] Remove IndexExpr Vec fallback through BUILTIN_INDEX_RESULT_TYPE_NAMES.
- [x] Keep array behavior unchanged.
- [x] Ensure class method resolution handles Vec from std module exactly like any class.

---

### 4) Codegen: remove rt_vec_* builtin call routing

Depends on: 3

### Builtin tables

- [x] compiler/codegen_model.py
  - [x] Remove Vec from BUILTIN_CONSTRUCTOR_RUNTIME_CALLS.
  - [x] Remove Vec entries from BUILTIN_METHOD_RUNTIME_CALLS.
  - [x] Remove Vec entries from BUILTIN_METHOD_RETURN_TYPES.
  - [x] Remove Vec from BUILTIN_INDEX_RUNTIME_CALLS.
  - [x] Remove rt_vec_* entries from RUNTIME_REF_ARG_INDICES.
  - [x] Remove Vec from BUILTIN_RUNTIME_TYPE_SYMBOLS.
  - [x] Remove rt_vec_* from RUNTIME_RETURN_TYPES.

### Vec branches in lowering

- [x] compiler/codegen.py
  - [x] Remove Vec-specific return-type inference branches.
  - [x] Remove Vec-specific path in _emit_index_expr.
  - [x] Ensure index/slice/set sugar lowers through generic method-call path.
  - [x] Ensure assignment-to-index remains canonicalized to set call.

---

### 5) Minimum runtime/build updates required for Phase 1

Depends on: 4

- [x] scripts/build.sh
  - [x] Keep vec.c linked temporarily unless all callsites are migrated.
- [x] tests/compiler/integration/test_cli_multimodule.py
  - [x] Keep vec.c link entries temporarily unless all tests are migrated.
- [x] Ensure no new codegen path emits rt_vec_*.

---

### 6) Phase 1 test migration

Depends on: 3, 4

#### Compiler tests

- [ ] tests/compiler/typecheck/test_typecheck.py
  - [ ] Replace builtin Vec tests with std.vec-import-based tests.
- [ ] tests/compiler/codegen/test_codegen.py
  - [ ] Remove assertions expecting rt_vec_* runtime calls.
  - [ ] Add assertions for normal method-call lowering where appropriate.

#### Golden tests

- [ ] tests/golden/old/e2e_codegen/test_e2e_vec_baseline_ops_links_and_runs.nif
- [ ] tests/golden/old/e2e_codegen/test_e2e_vec_cast_receiver_field_value_links_and_runs.nif
- [ ] tests/golden/old/e2e_codegen/test_e2e_vec_inline_boxed_args_survive_runtime_gc_links_and_runs.nif
  - [ ] Update all to import/use std.vec contract.

---

### 7) Phase 1 exit gate

Depends on: 6

- [ ] No compiler hardcoding for Vec remains.
- [ ] No rt_vec_* symbol emission remains from compiler.
- [ ] Vec behavior is provided by stdlib class implementation over Obj[].
- [ ] Full test pass via scripts/test.sh.

---

## Phase 2: Cleanup and hardening

Goal: remove transitional runtime remnants and finish ecosystem/docs alignment.

### 8) Runtime cleanup (after Phase 1 is stable)

Depends on: 7

- [ ] runtime/include/vec.h
  - [ ] Delete if no longer needed.
- [ ] runtime/src/vec.c
  - [ ] Delete Vec runtime implementation if fully migrated.
- [ ] runtime/include/runtime.h
  - [ ] Remove include of vec.h.
- [ ] scripts/build.sh
  - [ ] Remove runtime/src/vec.c from native link list.
- [ ] tests/compiler/integration/test_cli_multimodule.py
  - [ ] Remove vec.c from explicit runtime source link list.

---

### 9) Runtime tests cleanup

Depends on: 8

- [ ] tests/runtime/
  - [ ] Remove Vec runtime harnesses if they become obsolete.
  - [ ] Keep array runtime tests as foundation for std containers.

---

### 10) Sample and docs migration

Depends on: 7 (can be parallelized once behavior is stable)

#### Samples

- [ ] samples/vec_primes_2_to_1000000.nif
- [ ] samples/vec_primes_sieve_2_to_1000000.nif
- [ ] samples/index_out_of_bounds.nif
- [ ] samples/examples/03_vec_and_map.nif
- [ ] samples/examples/04_algorithm_style.nif
  - [ ] Update Vec usage to stdlib Vec imports/behavior.

#### Documentation

- [ ] docs/LANGUAGE_MVP_SPEC_V0.1.md
  - [ ] Reword Vec from runtime builtin to stdlib class status.
- [ ] docs/ABI_NOTES.md
  - [ ] Remove rt_vec_* ABI surface when gone.
- [ ] docs/REPO_STRUCTURE.md
  - [ ] Remove vec runtime API/object entries when deleted.
- [ ] README.md
  - [ ] Update runtime source list and builtins status.

---

### 11) Sugar extensibility prep (optional but recommended)

Depends on: 7

- [ ] Add/clarify checker logic so sugar eligibility is structural by method signature.
- [ ] Add tests proving non-Vec class can opt into [] / [:] / []= by implementing get/slice/set.
- [ ] Add negative tests for missing/incorrect method signatures.

---

### 12) Final exit criteria

Depends on: 8, 9, 10

- [ ] No compiler hardcoding for Vec remains.
- [ ] No rt_vec_* symbol emission remains.
- [ ] Vec behavior is provided by stdlib class implementation over Obj[].
- [ ] Full test pass via scripts/test.sh.
- [ ] All runtime Vec C implementation artifacts removed (if no longer required).
- [ ] Remove this temporary file: docs/TEMP_VEC_STDLIB_MIGRATION_CHECKLIST.md.

---

## Notes on current status (pre-migration baseline)

- [x] Decision and persistent documentation are in place:
  - [x] docs/INDEXING_SUGAR_DESIGN.md
  - [x] docs/LANGUAGE_MVP_SPEC_V0.1.md section 5.7
- [x] Existing compiler behavior already supports index/slice/set sugar syntax.
- [ ] Vec is still treated as builtin in compiler/runtime and has not been migrated to stdlib yet.
