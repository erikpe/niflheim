from __future__ import annotations

from enum import Enum, auto

COLLECTION_METHOD_LEN = "len"
COLLECTION_METHOD_INDEX_GET = "index_get"
COLLECTION_METHOD_INDEX_SET = "index_set"
COLLECTION_METHOD_SLICE_GET = "slice_get"
COLLECTION_METHOD_SLICE_SET = "slice_set"
COLLECTION_METHOD_ITER_LEN = "iter_len"
COLLECTION_METHOD_ITER_GET = "iter_get"

COLLECTION_PROTOCOL_METHOD_NAMES = frozenset(
    {
        COLLECTION_METHOD_LEN,
        COLLECTION_METHOD_INDEX_GET,
        COLLECTION_METHOD_INDEX_SET,
        COLLECTION_METHOD_SLICE_GET,
        COLLECTION_METHOD_SLICE_SET,
        COLLECTION_METHOD_ITER_LEN,
        COLLECTION_METHOD_ITER_GET,
    }
)
INDEXING_PROTOCOL_METHOD_NAMES = frozenset({COLLECTION_METHOD_INDEX_GET, COLLECTION_METHOD_INDEX_SET})
SLICING_PROTOCOL_METHOD_NAMES = frozenset({COLLECTION_METHOD_SLICE_GET, COLLECTION_METHOD_SLICE_SET})
ITERATION_PROTOCOL_METHOD_NAMES = frozenset({COLLECTION_METHOD_ITER_LEN, COLLECTION_METHOD_ITER_GET})


class CollectionOpKind(Enum):
    LEN = auto()
    INDEX_GET = auto()
    INDEX_SET = auto()
    SLICE_GET = auto()
    SLICE_SET = auto()
    ITER_LEN = auto()
    ITER_GET = auto()


class ArrayRuntimeKind(Enum):
    I64 = auto()
    U64 = auto()
    U8 = auto()
    BOOL = auto()
    DOUBLE = auto()
    REF = auto()


_COLLECTION_METHOD_NAME_BY_OP_KIND = {
    CollectionOpKind.LEN: COLLECTION_METHOD_LEN,
    CollectionOpKind.INDEX_GET: COLLECTION_METHOD_INDEX_GET,
    CollectionOpKind.INDEX_SET: COLLECTION_METHOD_INDEX_SET,
    CollectionOpKind.SLICE_GET: COLLECTION_METHOD_SLICE_GET,
    CollectionOpKind.SLICE_SET: COLLECTION_METHOD_SLICE_SET,
    CollectionOpKind.ITER_LEN: COLLECTION_METHOD_ITER_LEN,
    CollectionOpKind.ITER_GET: COLLECTION_METHOD_ITER_GET,
}

_COLLECTION_OP_KIND_BY_METHOD_NAME = {
    method_name: op_kind for op_kind, method_name in _COLLECTION_METHOD_NAME_BY_OP_KIND.items()
}


def collection_method_name(op_kind: CollectionOpKind) -> str:
    return _COLLECTION_METHOD_NAME_BY_OP_KIND[op_kind]


def collection_op_from_method_name(method_name: str) -> CollectionOpKind | None:
    return _COLLECTION_OP_KIND_BY_METHOD_NAME.get(method_name)
