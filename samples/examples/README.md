# Niflheim Examples

These examples are intentionally small and map to the current implemented language surface.

- `hello.nif` - minimal entrypoint.
- `01_primitives_and_control.nif` - primitives, explicit casts, loops, conditionals.
- `02_classes_and_obj_casts.nif` - class instances, nullable references, `Obj` up/down casts.
- `03_vec_and_map.nif` - boxed primitives, `Vec`, `Map`, and `Hashable`/`Equalable`-based key behavior.
- `04_algorithm_style.nif` - coding-competition style frequency counting pattern.
- `modules/math_utils.nif` + `modules/main_import_demo.nif` - `export`/`import`/re-export style module usage.

Note: these examples track the current parser/typechecker/runtime behavior; when the language surface changes, the examples and the canonical docs should change together.
