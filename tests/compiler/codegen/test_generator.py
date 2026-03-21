from compiler.codegen.program_generator import ProgramGenerator
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.symbols import ClassId, ConstructorId, MethodId


def _write(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_codegen_uses_builder_for_aligned_call_and_comments(tmp_path) -> None:
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
    generator = ProgramGenerator(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )

    asm = generator.generate()

    assert generator.asm.build() == asm
    assert any(line.startswith("    # ") for line in generator.asm.lines)
    assert "    test rsp, 8" in asm
    assert ".L__nif_aligned_call_0:" in asm


def test_codegen_builds_constructor_and_field_tables(tmp_path) -> None:
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
    generator = ProgramGenerator(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )

    tables = generator.build_declaration_tables()
    box_id = ClassId(module_path=("main",), name="Box")
    ctor_id = ConstructorId(module_path=("main",), class_name="Box")
    make_id = MethodId(module_path=("main",), class_name="Box", name="make")
    get_id = MethodId(module_path=("main",), class_name="Box", name="get")

    assert tables.method_label(make_id) == "__nif_method_Box_make"
    assert tables.method_label(get_id) == "__nif_method_Box_get"
    assert tables.class_field_offset(box_id, "value") == 24
    assert tables.constructor_layout(ctor_id).label == "__nif_ctor_Box"
    assert tables.constructor_layout(ctor_id).param_field_names == ["value", "next"]


def test_codegen_emits_main_prologue_and_epilogue(tmp_path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )
    generator = ProgramGenerator(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )

    asm = generator.generate()

    assert ".globl main" in asm
    assert "main:" in asm
    assert ".Lmain_epilogue:" in asm
    assert "    ret" in asm


def test_codegen_orchestrates_sections_and_class_symbols(tmp_path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Box {
            value: i64;

            fn get() -> i64 {
                return __self.value;
            }
        }

        fn main() -> i64 {
            return Box(0).get();
        }
        """,
    )
    generator = ProgramGenerator(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )

    asm = generator.generate()

    assert ".text" in asm
    assert "__nif_method_Box_get" in asm
    assert "__nif_ctor_Box" in asm
    assert '.section .note.GNU-stack,"",@progbits' in asm
