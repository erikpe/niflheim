# Niflheim

This repository contains the stage-0 compiler and minimal C runtime for Niflheim, a learning-oriented, statically typed compiled language.

Niflheim source files use the `.nif` extension.

Key design docs:
- [LANGUAGE_MVP_SPEC_V0.1.md](LANGUAGE_MVP_SPEC_V0.1.md)
- [ROADMAP_v0.1.md](ROADMAP_v0.1.md)
- [ABI_NOTES.md](ABI_NOTES.md)
- [TEST_PLAN_v0.1.md](TEST_PLAN_v0.1.md)
- [docs/GRAMMAR_EBNF.md](docs/GRAMMAR_EBNF.md)
- [docs/REPO_STRUCTURE.md](docs/REPO_STRUCTURE.md)

## Repository Areas

- `compiler/` - Python stage-0 compiler
- `runtime/` - C runtime and GC
- `tests/` - unit, golden, integration, and stress tests
- `examples/` - small language programs
- `docs/` - repository-level reference docs

## Current Status

Scaffolded structure for MVP v0.1 implementation.

## Policy Decisions (MVP)

- Null-dereference checks are runtime-only in v0.1; compile-time static null-dereference analysis is intentionally out of scope.
- See [LANGUAGE_MVP_SPEC_V0.1.md](LANGUAGE_MVP_SPEC_V0.1.md) for the canonical language/runtime policy details.
