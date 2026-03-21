from compiler.common.collection_protocols import (
    CollectionOpKind,
    COLLECTION_METHOD_INDEX_GET,
    COLLECTION_METHOD_ITER_LEN,
    COLLECTION_METHOD_SLICE_SET,
    collection_method_name,
    collection_op_from_method_name,
)


def test_collection_method_name_maps_operation_kinds_to_protocol_names() -> None:
    assert collection_method_name(CollectionOpKind.INDEX_GET) == COLLECTION_METHOD_INDEX_GET
    assert collection_method_name(CollectionOpKind.ITER_LEN) == COLLECTION_METHOD_ITER_LEN
    assert collection_method_name(CollectionOpKind.SLICE_SET) == COLLECTION_METHOD_SLICE_SET


def test_collection_op_from_method_name_maps_protocol_names_to_operation_kinds() -> None:
    assert collection_op_from_method_name(COLLECTION_METHOD_INDEX_GET) is CollectionOpKind.INDEX_GET
    assert collection_op_from_method_name(COLLECTION_METHOD_ITER_LEN) is CollectionOpKind.ITER_LEN
    assert collection_op_from_method_name(COLLECTION_METHOD_SLICE_SET) is CollectionOpKind.SLICE_SET
    assert collection_op_from_method_name("not_a_protocol") is None