from compiler.codegen.model import (
    ARRAY_INDEX_GET_RUNTIME_CALLS,
    ARRAY_LEN_RUNTIME_CALL,
    ARRAY_SLICE_SET_RUNTIME_CALLS,
)
from compiler.codegen.runtime_calls import runtime_dispatch_call_name
from compiler.common.collection_protocols import ArrayRuntimeKind, CollectionOpKind
from compiler.semantic.ir import RuntimeDispatch


def test_runtime_dispatch_call_name_uses_codegen_constant_tables() -> None:
    assert runtime_dispatch_call_name(
        RuntimeDispatch(operation=CollectionOpKind.LEN, runtime_kind=None)
    ) == ARRAY_LEN_RUNTIME_CALL
    assert runtime_dispatch_call_name(
        RuntimeDispatch(operation=CollectionOpKind.ITER_GET, runtime_kind=ArrayRuntimeKind.U8)
    ) == ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.U8]
    assert runtime_dispatch_call_name(
        RuntimeDispatch(operation=CollectionOpKind.SLICE_SET, runtime_kind=ArrayRuntimeKind.REF)
    ) == ARRAY_SLICE_SET_RUNTIME_CALLS[ArrayRuntimeKind.REF]


def test_runtime_dispatch_call_name_rejects_missing_runtime_kind() -> None:
    dispatch = RuntimeDispatch(operation=CollectionOpKind.INDEX_GET, runtime_kind=None)

    try:
        runtime_dispatch_call_name(dispatch)
    except ValueError as exc:
        assert "requires an array runtime kind" in str(exc)
    else:
        assert False, "expected runtime dispatch lookup to reject missing runtime kind"