from __future__ import annotations

from compiler.common.collection_protocols import ArrayRuntimeKind, CollectionOpKind
from compiler.codegen.abi.runtime import (
    ARRAY_INDEX_GET_RUNTIME_CALLS,
    ARRAY_INDEX_SET_RUNTIME_CALLS,
    ARRAY_LEN_RUNTIME_CALL,
    ARRAY_SLICE_GET_RUNTIME_CALLS,
    ARRAY_SLICE_SET_RUNTIME_CALLS,
)
from compiler.semantic.ir import RuntimeDispatch


_RUNTIME_CALLS_BY_OPERATION: dict[CollectionOpKind, str | dict[ArrayRuntimeKind, str]] = {
    CollectionOpKind.LEN: ARRAY_LEN_RUNTIME_CALL,
    CollectionOpKind.ITER_LEN: ARRAY_LEN_RUNTIME_CALL,
    CollectionOpKind.INDEX_GET: ARRAY_INDEX_GET_RUNTIME_CALLS,
    CollectionOpKind.ITER_GET: ARRAY_INDEX_GET_RUNTIME_CALLS,
    CollectionOpKind.INDEX_SET: ARRAY_INDEX_SET_RUNTIME_CALLS,
    CollectionOpKind.SLICE_GET: ARRAY_SLICE_GET_RUNTIME_CALLS,
    CollectionOpKind.SLICE_SET: ARRAY_SLICE_SET_RUNTIME_CALLS,
}


def runtime_dispatch_call_name(dispatch: RuntimeDispatch) -> str:
    target = _RUNTIME_CALLS_BY_OPERATION.get(dispatch.operation)
    if target is None:
        raise ValueError(f"Unsupported runtime dispatch operation '{dispatch.operation}'")
    if isinstance(target, str):
        return target

    runtime_kind = dispatch.runtime_kind
    if runtime_kind is None:
        raise ValueError(f"Runtime dispatch for {dispatch.operation} requires an array runtime kind")
    return target[runtime_kind]
