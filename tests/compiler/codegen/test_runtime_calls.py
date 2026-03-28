from compiler.codegen.abi.runtime import (
    ARRAY_CONSTRUCTOR_RUNTIME_CALLS,
    ARRAY_INDEX_GET_RUNTIME_CALLS,
    ARRAY_LEN_RUNTIME_CALL,
    ARRAY_FROM_BYTES_U8_RUNTIME_CALL,
    ARRAY_SLICE_SET_RUNTIME_CALLS,
    DOUBLE_TO_I64_RUNTIME_CALL,
    runtime_call_metadata,
)
from compiler.codegen.runtime_calls import runtime_dispatch_call_name
from compiler.common.collection_protocols import ArrayRuntimeKind, CollectionOpKind
from compiler.semantic.ir import RuntimeDispatch


def test_runtime_dispatch_call_name_uses_codegen_constant_tables() -> None:
    assert (
        runtime_dispatch_call_name(RuntimeDispatch(operation=CollectionOpKind.LEN, runtime_kind=None))
        == ARRAY_LEN_RUNTIME_CALL
    )
    assert (
        runtime_dispatch_call_name(
            RuntimeDispatch(operation=CollectionOpKind.ITER_GET, runtime_kind=ArrayRuntimeKind.U8)
        )
        == ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.U8]
    )
    assert (
        runtime_dispatch_call_name(
            RuntimeDispatch(operation=CollectionOpKind.SLICE_SET, runtime_kind=ArrayRuntimeKind.REF)
        )
        == ARRAY_SLICE_SET_RUNTIME_CALLS[ArrayRuntimeKind.REF]
    )


def test_runtime_dispatch_call_name_rejects_missing_runtime_kind() -> None:
    dispatch = RuntimeDispatch(operation=CollectionOpKind.INDEX_GET, runtime_kind=None)

    try:
        runtime_dispatch_call_name(dispatch)
    except ValueError as exc:
        assert "requires an array runtime kind" in str(exc)
    else:
        assert False, "expected runtime dispatch lookup to reject missing runtime kind"


def test_runtime_call_metadata_marks_non_gc_helpers() -> None:
    len_metadata = runtime_call_metadata(ARRAY_LEN_RUNTIME_CALL)
    ref_set_metadata = runtime_call_metadata(ARRAY_SLICE_SET_RUNTIME_CALLS[ArrayRuntimeKind.REF])
    cast_metadata = runtime_call_metadata(DOUBLE_TO_I64_RUNTIME_CALL)

    assert len_metadata.ref_arg_indices == (0,)
    assert len_metadata.may_gc is False
    assert len_metadata.emits_safepoint_hooks is False

    assert ref_set_metadata.ref_arg_indices == (0, 3)
    assert ref_set_metadata.may_gc is False
    assert ref_set_metadata.emits_safepoint_hooks is False

    assert cast_metadata.ref_arg_indices == ()
    assert cast_metadata.may_gc is False
    assert cast_metadata.emits_safepoint_hooks is False


def test_runtime_call_metadata_marks_gc_capable_helpers() -> None:
    ctor_metadata = runtime_call_metadata(ARRAY_CONSTRUCTOR_RUNTIME_CALLS["ref"])
    bytes_metadata = runtime_call_metadata(ARRAY_FROM_BYTES_U8_RUNTIME_CALL)

    assert ctor_metadata.may_gc is True
    assert ctor_metadata.emits_safepoint_hooks is True
    assert bytes_metadata.may_gc is True
    assert bytes_metadata.emits_safepoint_hooks is True


def test_runtime_call_metadata_defaults_unknown_runtime_names_to_conservative_behavior() -> None:
    metadata = runtime_call_metadata("rt_gc_collect")

    assert metadata.name == "rt_gc_collect"
    assert metadata.ref_arg_indices == ()
    assert metadata.may_gc is True
    assert metadata.emits_safepoint_hooks is True
