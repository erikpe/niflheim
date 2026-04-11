import pytest

from compiler.codegen.abi import runtime_layout
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

    assert [slot.display_name for slot in layout.root_slots] == []
    assert layout.named_root_slot_plan.slot_count == 0
    assert layout.root_slot_count == 6
    assert layout.temp_root_slot_start_index == 0
    assert len(layout.temp_root_slot_offsets) == 6
    assert layout.thread_state_offset - layout.root_frame_offset == runtime_layout.RT_ROOT_FRAME_SIZE_BYTES
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

    assert [slot.display_name for slot in layout.root_slots] == []
    assert layout.named_root_slot_plan.slot_count == 0
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
    assert layout.thread_state_offset - layout.root_frame_offset == runtime_layout.RT_ROOT_FRAME_SIZE_BYTES
    assert layout.stack_size % 16 == 0


def test_codegen_build_explicit_constructor_layout_tracks_receiver_params_and_locals(tmp_path) -> None:
    source = tmp_path / "main.nif"
    source.write_text(
        """
        class Box {
            next: Obj;

            constructor(next: Obj) {
                var tmp: Obj = next;
                __self.next = tmp;
                return;
            }
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
    constructor = cls.constructors[0]
    declaration_tables = ProgramGenerator(program).build_declaration_tables()
    ctor_layout = declaration_tables.constructor_layout(ConstructorId(module_path=("main",), class_name="Box"))
    assert ctor_layout is not None

    layout = build_constructor_layout(
        cls,
        ctor_layout,
        constructor_object_slot_name=CONSTRUCTOR_OBJECT_SLOT_NAME,
        constructor=constructor,
    )

    assert [slot.key for slot in layout.slots] == ["__self", "next", "tmp"]
    assert [slot.key for slot in layout.root_slots] == ["__self", "next"]
    assert CONSTRUCTOR_OBJECT_SLOT_NAME not in layout.slot_names
    assert layout.root_slot_count == 8
    assert layout.temp_root_slot_start_index == 2


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
    assert [slot.local_id for slot in layout.root_slots] == []
    assert layout.root_slot_count == 0


def test_codegen_build_layout_skips_named_root_slots_for_reference_locals_without_safepoints(tmp_path) -> None:
    source = tmp_path / "main.nif"
    source.write_text(
        """
        fn main(value: Obj) -> Obj {
            var kept: Obj = value;
            return kept;
        }
        """.strip()
        + "\n",
        encoding="utf-8",
    )
    program = lower_linked_semantic_program(link_semantic_program(lower_program(resolve_program(source, project_root=tmp_path))))
    fn = next(fn for fn in program.functions if fn.function_id.module_path == ("main",) and fn.function_id.name == "main")

    layout = build_layout(fn)

    assert layout.named_root_slot_plan.slot_count == 0
    assert layout.root_slots == []
    assert layout.root_slot_offsets_by_local_id == {}
    assert layout.temp_root_slot_start_index == 0
    assert layout.root_slot_count == 0


def test_codegen_build_layout_reuses_named_root_slots_for_disjoint_safepoints(tmp_path) -> None:
    source = tmp_path / "main.nif"
    source.write_text(
        """
        extern fn rt_gc_collect(value: Obj) -> unit;

        fn main(value: Obj) -> Obj {
            var first: Obj = value;
            rt_gc_collect(first);
            var second: Obj = first;
            rt_gc_collect(second);
            return second;
        }
        """.strip()
        + "\n",
        encoding="utf-8",
    )
    program = lower_linked_semantic_program(link_semantic_program(lower_program(resolve_program(source, project_root=tmp_path))))
    fn = next(fn for fn in program.functions if fn.function_id.module_path == ("main",) and fn.function_id.name == "main")

    layout = build_layout(fn)
    first_info = next(local_info for local_info in fn.local_info_by_id.values() if local_info.display_name == "first")
    second_info = next(local_info for local_info in fn.local_info_by_id.values() if local_info.display_name == "second")
    first_slot = next(slot for slot in layout.root_slots if slot.local_id == first_info.local_id)
    second_slot = next(slot for slot in layout.root_slots if slot.local_id == second_info.local_id)

    assert layout.named_root_slot_plan.slot_count == 1
    assert first_slot.root_index == second_slot.root_index == 0
    assert first_slot.root_offset == second_slot.root_offset
    assert layout.temp_root_slot_start_index == 1
    assert len(layout.temp_root_slot_offsets) == 6


def test_codegen_build_layout_orders_root_slots_by_physical_slot_index(tmp_path) -> None:
    source = tmp_path / "main.nif"
    source.write_text(
        """
        extern fn rt_gc_collect(value: Obj) -> unit;

        fn pick(left: Obj, right: Obj) -> Obj {
            return left;
        }

        fn main(value: Obj) -> Obj {
            var first: Obj = value;
            var middle: Obj = value;
            var last: Obj = null;
            rt_gc_collect(first);
            last = first;
            rt_gc_collect(middle);
            return pick(middle, last);
        }
        """.strip()
        + "\n",
        encoding="utf-8",
    )
    program = lower_linked_semantic_program(link_semantic_program(lower_program(resolve_program(source, project_root=tmp_path))))
    fn = next(fn for fn in program.functions if fn.function_id.module_path == ("main",) and fn.function_id.name == "main")

    layout = build_layout(fn)

    assert [slot.display_name for slot in layout.root_slots] == ["middle", "first", "last"]
    assert [slot.root_index for slot in layout.root_slots] == [0, 1, 1]
    assert layout.root_slots[0].root_offset == min(slot.root_offset for slot in layout.root_slots if slot.root_offset is not None)


def test_codegen_build_layout_allocates_call_scratch_slots_for_nested_register_only_direct_calls(tmp_path) -> None:
    source = tmp_path / "main.nif"
    source.write_text(
        """
        fn inner(a: i64, b: i64) -> i64 {
            return a + b;
        }

        fn outer(a: i64, b: i64) -> i64 {
            return a + b;
        }

        fn main() -> i64 {
            return outer(inner(1, 2), 3);
        }
        """.strip()
        + "\n",
        encoding="utf-8",
    )
    program = lower_linked_semantic_program(link_semantic_program(lower_program(resolve_program(source, project_root=tmp_path))))
    fn = next(fn for fn in program.functions if fn.function_id.module_path == ("main",) and fn.function_id.name == "main")

    layout = build_layout(fn)

    assert layout.call_scratch_slot_offsets == [-8, -16, -24]
    assert layout.stack_size % 16 == 0


def test_codegen_build_layout_skips_temp_roots_for_non_gc_runtime_helper_on_temporary_ref(tmp_path) -> None:
    source = tmp_path / "main.nif"
    source.write_text(
        """
        extern fn rt_array_len(values: Obj[]) -> u64;

        fn main() -> i64 {
            return (i64)rt_array_len(Obj[](1u));
        }
        """.strip()
        + "\n",
        encoding="utf-8",
    )
    program = lower_linked_semantic_program(link_semantic_program(lower_program(resolve_program(source, project_root=tmp_path))))
    fn = next(fn for fn in program.functions if fn.function_id.module_path == ("main",) and fn.function_id.name == "main")

    layout = build_layout(fn)

    assert layout.root_slot_count == 0
    assert layout.temp_root_slot_offsets == []


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
