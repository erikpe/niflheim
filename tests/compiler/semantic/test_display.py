from __future__ import annotations

from compiler.common.span import SourcePos, SourceSpan
from compiler.semantic.display import (
    semantic_bound_member_receiver_display_name,
    semantic_call_target_display_name,
    semantic_local_display_name,
    semantic_local_type_display_name,
    semantic_type_display_name_relative,
)
from compiler.semantic.ir import (
    BoundMemberAccess,
    CallableValueCallTarget,
    FieldReadExpr,
    FunctionCallTarget,
    InstanceMethodCallTarget,
    InterfaceMethodCallTarget,
    LocalRefExpr,
    SemanticBlock,
    SemanticFunction,
    SemanticLocalInfo,
)
from compiler.semantic.symbols import FunctionId, InterfaceMethodId, LocalId, MethodId
from compiler.semantic.type_compat import best_effort_semantic_type_ref_from_name
from compiler.semantic.types import (
    semantic_type_ref_for_class_id,
    semantic_type_ref_for_interface_id,
)
from compiler.semantic.symbols import ClassId, InterfaceId


def _span() -> SourceSpan:
    pos = SourcePos(path="<test>", offset=0, line=1, column=1)
    return SourceSpan(start=pos, end=pos)


def test_semantic_display_helpers_render_locals_from_canonical_type_refs() -> None:
    span = _span()
    function_id = FunctionId(module_path=("main",), name="demo")
    local_id = LocalId(owner_id=function_id, ordinal=0)
    owner = SemanticFunction(
        function_id=function_id,
        params=[],
        return_type_ref=best_effort_semantic_type_ref_from_name(("main",), "unit"),
        body=SemanticBlock(statements=[], span=span),
        is_export=False,
        is_extern=False,
        span=span,
        local_info_by_id={
            local_id: SemanticLocalInfo(
                local_id=local_id,
                owner_id=function_id,
                display_name="value",
                type_ref=semantic_type_ref_for_class_id(ClassId(module_path=("main",), name="Box"), display_name="Box"),
                span=span,
                binding_kind="local",
            )
        },
    )

    assert semantic_local_display_name(owner, local_id) == "value"
    assert semantic_local_type_display_name(owner, local_id) == "Box"


def test_semantic_display_helpers_render_bound_member_and_call_targets_from_canonical_refs() -> None:
    span = _span()
    receiver = LocalRefExpr(
        local_id=LocalId(owner_id=FunctionId(module_path=("main",), name="demo"), ordinal=0),
        type_ref=semantic_type_ref_for_interface_id(
            InterfaceId(module_path=("util",), name="Hashable"), display_name="util::Hashable"
        ),
        span=span,
    )
    access = BoundMemberAccess(
        receiver=receiver,
        receiver_type_ref=semantic_type_ref_for_interface_id(
            InterfaceId(module_path=("util",), name="Hashable"), display_name="util::Hashable"
        ),
    )

    assert semantic_bound_member_receiver_display_name(access, current_module_path=("main",)) == "util::Hashable"
    assert semantic_call_target_display_name(
        FunctionCallTarget(function_id=FunctionId(module_path=("util",), name="helper")),
        current_module_path=("main",),
    ) == "util::helper"
    assert semantic_call_target_display_name(
        InstanceMethodCallTarget(
            method_id=MethodId(module_path=("main",), class_name="Box", name="read"),
            access=BoundMemberAccess(
                receiver=receiver,
                receiver_type_ref=semantic_type_ref_for_class_id(
                    ClassId(module_path=("main",), name="Box"), display_name="Box"
                ),
            ),
        ),
        current_module_path=("main",),
    ) == "Box.read"
    assert semantic_call_target_display_name(
        InterfaceMethodCallTarget(
            interface_id=InterfaceId(module_path=("util",), name="Hashable"),
            method_id=InterfaceMethodId(module_path=("util",), interface_name="Hashable", name="hash_code"),
            access=access,
        ),
        current_module_path=("main",),
    ) == "util::Hashable.hash_code"
    assert semantic_type_display_name_relative(
        ("main",), semantic_type_ref_for_interface_id(InterfaceId(module_path=("main",), name="Hashable"), display_name="main::Hashable")
    ) == "Hashable"


def test_semantic_display_helpers_render_callable_value_targets_from_callee_type() -> None:
    span = _span()
    callee = FieldReadExpr(
        access=BoundMemberAccess(
            receiver=LocalRefExpr(
                local_id=LocalId(owner_id=FunctionId(module_path=("main",), name="demo"), ordinal=0),
                type_ref=semantic_type_ref_for_class_id(ClassId(module_path=("main",), name="Box"), display_name="Box"),
                span=span,
            ),
            receiver_type_ref=semantic_type_ref_for_class_id(ClassId(module_path=("main",), name="Box"), display_name="Box"),
        ),
        owner_class_id=ClassId(module_path=("main",), name="Box"),
        field_name="invoke",
        type_ref=best_effort_semantic_type_ref_from_name(("main",), "fn(i64) -> i64"),
        span=span,
    )

    assert semantic_call_target_display_name(
        CallableValueCallTarget(callee=callee), current_module_path=("main",)
    ) == "callable fn(i64) -> i64"