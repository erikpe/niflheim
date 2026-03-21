from compiler.codegen.layout import build_constructor_layout, build_layout
from compiler.codegen.model import CONSTRUCTOR_OBJECT_SLOT_NAME
from compiler.codegen.program_generator import ProgramGenerator
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowering import lower_program
from compiler.semantic.symbols import ConstructorId


def test_codegen_build_layout_tracks_reference_roots_and_temp_roots(tmp_path) -> None:
    source = tmp_path / "main.nif"
    source.write_text(
        """
        fn g(value: Obj) -> unit {
            return;
        }

        fn f(a: Obj) -> unit {
            g(a);
        }

        fn main() -> i64 {
            return 0;
        }
        """.strip()
        + "\n",
        encoding="utf-8",
    )
    program = link_semantic_program(lower_program(resolve_program(source, project_root=tmp_path)))
    fn = next(fn for fn in program.functions if fn.function_id.module_path == ("main",) and fn.function_id.name == "f")

    layout = build_layout(fn)

    assert layout.root_slot_names == ["a"]
    assert layout.root_slot_count >= 7
    assert layout.stack_size % 16 == 0


def test_codegen_build_constructor_layout_tracks_params_and_allocated_object_root(tmp_path) -> None:
    source = tmp_path / "main.nif"
    source.write_text(
        """
        class Box {
            next: Obj;
            value: i64 = 7;
        }

        fn main() -> i64 {
            return 0;
        }
        """.strip()
        + "\n",
        encoding="utf-8",
    )
    program = link_semantic_program(lower_program(resolve_program(source, project_root=tmp_path)))
    cls = next(cls for cls in program.classes if cls.class_id.module_path == ("main",) and cls.class_id.name == "Box")
    declaration_tables = ProgramGenerator(program).build_declaration_tables()
    ctor_layout = declaration_tables.constructor_layout(ConstructorId(module_path=("main",), class_name="Box"))
    assert ctor_layout is not None

    layout = build_constructor_layout(
        cls,
        ctor_layout,
        constructor_object_slot_name=CONSTRUCTOR_OBJECT_SLOT_NAME,
    )

    assert layout.slot_names == ["next", CONSTRUCTOR_OBJECT_SLOT_NAME]
    assert layout.root_slot_names == ["next", CONSTRUCTOR_OBJECT_SLOT_NAME]
    assert layout.root_slot_count == 2
    assert layout.stack_size % 16 == 0
