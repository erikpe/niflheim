from compiler.codegen.layout import build_layout
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowering import lower_program


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
