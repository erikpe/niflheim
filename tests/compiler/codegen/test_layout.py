import pytest

from compiler.codegen.layout import build_constructor_layout, build_layout
from compiler.codegen.model import CONSTRUCTOR_OBJECT_SLOT_NAME
from compiler.codegen.program_generator import ProgramGenerator
from compiler.common.span import SourcePos, SourceSpan
from compiler.resolver import resolve_program
from compiler.semantic.lowered_ir import LoweredSemanticBlock, LoweredSemanticForIn, LoweredSemanticFunction
from compiler.semantic.ir import SemanticParam, SemanticReturn
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowering.executable import lower_linked_semantic_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.symbols import ConstructorId, FunctionId
from compiler.semantic.type_compat import best_effort_semantic_type_ref_from_name


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
    program = lower_linked_semantic_program(link_semantic_program(lower_program(resolve_program(source, project_root=tmp_path))))
    fn = next(fn for fn in program.functions if fn.function_id.module_path == ("main",) and fn.function_id.name == "f")

    layout = build_layout(fn)

    assert [slot.display_name for slot in layout.root_slots] == ["a"]
    assert layout.root_slot_count >= 7
    assert layout.stack_size % 16 == 0


def test_codegen_build_layout_uses_canonical_local_type_refs_after_local_type_cache_removal(tmp_path) -> None:
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
    program = lower_linked_semantic_program(link_semantic_program(lower_program(resolve_program(source, project_root=tmp_path))))
    fn = next(fn for fn in program.functions if fn.function_id.module_path == ("main",) and fn.function_id.name == "f")

    layout = build_layout(fn)

    assert [slot.display_name for slot in layout.root_slots] == ["a"]
    assert not hasattr(next(iter(fn.local_info_by_id.values())), "type_name")


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
    program = lower_linked_semantic_program(link_semantic_program(lower_program(resolve_program(source, project_root=tmp_path))))
    cls = next(cls for cls in program.classes if cls.class_id.module_path == ("main",) and cls.class_id.name == "Box")
    declaration_tables = ProgramGenerator(program).build_declaration_tables()
    ctor_layout = declaration_tables.constructor_layout(ConstructorId(module_path=("main",), class_name="Box"))
    assert ctor_layout is not None

    layout = build_constructor_layout(
        cls,
        ctor_layout,
        constructor_object_slot_name=CONSTRUCTOR_OBJECT_SLOT_NAME,
    )

    assert [slot.key for slot in layout.slots] == ["next", CONSTRUCTOR_OBJECT_SLOT_NAME]
    assert [slot.key for slot in layout.root_slots] == ["next", CONSTRUCTOR_OBJECT_SLOT_NAME]
    assert layout.root_slot_count == 2
    assert layout.stack_size % 16 == 0


def test_codegen_build_layout_assigns_distinct_slots_to_shadowed_locals(tmp_path) -> None:
    source = tmp_path / "main.nif"
    source.write_text(
        """
        class Box {
        }

        fn main(value: Box) -> Box {
            var kept: Box = value;
            {
                var value: Box = Box();
                kept = value;
            }
            return kept;
        }
        """.strip()
        + "\n",
        encoding="utf-8",
    )
    program = lower_linked_semantic_program(link_semantic_program(lower_program(resolve_program(source, project_root=tmp_path))))
    fn = next(fn for fn in program.functions if fn.function_id.module_path == ("main",) and fn.function_id.name == "main")

    layout = build_layout(fn)
    value_local_infos = sorted(
        (local_info for local_info in fn.local_info_by_id.values() if local_info.display_name == "value"),
        key=lambda local_info: local_info.local_id.ordinal,
    )

    assert len(value_local_infos) == 2
    assert layout.local_slot_offsets[value_local_infos[0].local_id] != layout.local_slot_offsets[value_local_infos[1].local_id]


def test_codegen_build_layout_materializes_explicit_for_in_helper_temps(tmp_path) -> None:
    source = tmp_path / "main.nif"
    source.write_text(
        """
        fn main(values: i64[]) -> i64 {
            var total: i64 = 0;
            for value in values {
                total = total + value;
            }
            return total;
        }
        """.strip()
        + "\n",
        encoding="utf-8",
    )
    program = lower_linked_semantic_program(link_semantic_program(lower_program(resolve_program(source, project_root=tmp_path))))
    fn = next(fn for fn in program.functions if fn.function_id.module_path == ("main",) and fn.function_id.name == "main")

    layout = build_layout(fn)
    loop_stmt = fn.body.statements[1]

    assert isinstance(loop_stmt, LoweredSemanticForIn)
    assert loop_stmt.collection_local_id in layout.local_slot_offsets
    assert loop_stmt.length_local_id in layout.local_slot_offsets
    assert loop_stmt.index_local_id in layout.local_slot_offsets


def test_codegen_build_layout_tracks_identity_first_slot_records(tmp_path) -> None:
    source = tmp_path / "main.nif"
    source.write_text(
        """
        class Box {
        }

        fn main(value: Box) -> Box {
            var kept: Box = value;
            return kept;
        }
        """.strip()
        + "\n",
        encoding="utf-8",
    )
    program = lower_linked_semantic_program(link_semantic_program(lower_program(resolve_program(source, project_root=tmp_path))))
    fn = next(fn for fn in program.functions if fn.function_id.module_path == ("main",) and fn.function_id.name == "main")

    layout = build_layout(fn)
    param_info = next(local_info for local_info in fn.local_info_by_id.values() if local_info.binding_kind == "param")
    kept_info = next(local_info for local_info in fn.local_info_by_id.values() if local_info.display_name == "kept")

    param_slot = next(slot for slot in layout.slots if slot.local_id == param_info.local_id)
    kept_slot = next(slot for slot in layout.slots if slot.local_id == kept_info.local_id)

    assert param_slot.display_name == "value"
    assert kept_slot.display_name == "kept"
    assert param_slot.offset == layout.local_slot_offsets[param_info.local_id]
    assert kept_slot.offset == layout.local_slot_offsets[kept_info.local_id]
    assert [slot.local_id for slot in layout.root_slots] == [param_info.local_id, kept_info.local_id]


def test_codegen_build_layout_requires_owner_local_metadata_for_lowered_locals() -> None:
    pos = SourcePos(path="<test>", offset=0, line=1, column=1)
    span = SourceSpan(start=pos, end=pos)
    fn = LoweredSemanticFunction(
        function_id=FunctionId(module_path=("main",), name="main"),
        params=[
            SemanticParam(
                name="value",
                type_ref=best_effort_semantic_type_ref_from_name(("main",), "i64"),
                span=span,
            )
        ],
        return_type_ref=best_effort_semantic_type_ref_from_name(("main",), "i64"),
        body=LoweredSemanticBlock(statements=[SemanticReturn(value=None, span=span)], span=span),
        is_export=False,
        is_extern=False,
        span=span,
    )

    with pytest.raises(ValueError, match="owner-local metadata"):
        build_layout(fn)
