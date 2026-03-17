from compiler.codegen.semantic_generator import SemanticCodeGenerator
from compiler.resolver import resolve_program
from compiler.semantic_linker import build_semantic_codegen_program
from compiler.semantic_lowering import lower_program
from compiler.semantic_symbols import ClassId, ConstructorId, MethodId


def _write(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_semantic_codegen_uses_builder_for_aligned_call_and_comments(tmp_path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn callee() -> i64 {
            return 7;
        }

        fn caller() -> i64 {
            return callee();
        }

        fn main() -> i64 {
            return caller();
        }
        """,
    )
    generator = SemanticCodeGenerator(
        build_semantic_codegen_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )

    asm = generator.generate()

    assert generator.asm.build() == asm
    assert any(line.startswith("    # ") for line in generator.asm.lines)
    assert "    test rsp, 8" in asm
    assert ".L__nif_aligned_call_0:" in asm


def test_semantic_codegen_builds_constructor_and_field_tables(tmp_path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Box {
            value: i64;
            next: Obj;

            static fn make(value: i64) -> Box {
                return Box(value, null);
            }

            fn get() -> i64 {
                return __self.value;
            }
        }

        fn helper() -> bool {
            return true;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
    )
    generator = SemanticCodeGenerator(
        build_semantic_codegen_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )

    tables = generator.build_declaration_tables()
    box_id = ClassId(module_path=("main",), name="Box")
    ctor_id = ConstructorId(module_path=("main",), class_name="Box")
    make_id = MethodId(module_path=("main",), class_name="Box", name="make")
    get_id = MethodId(module_path=("main",), class_name="Box", name="get")

    assert tables.method_labels_by_id[make_id] == "__nif_method_Box_make"
    assert tables.method_labels_by_id[get_id] == "__nif_method_Box_get"
    assert tables.constructor_labels_by_id[ctor_id] == "__nif_ctor_Box"
    assert tables.class_field_offsets_by_id[(box_id, "value")] == 24
    assert tables.class_field_type_names_by_id[(box_id, "next")] == "Obj"
    assert tables.constructor_layouts_by_id[ctor_id].param_field_names == ["value", "next"]
