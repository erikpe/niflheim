from __future__ import annotations

import pytest

from compiler.semantic.symbols import FunctionId, LocalId, MethodId


def test_local_id_equality_is_defined_by_owner_and_ordinal() -> None:
    owner_id = FunctionId(module_path=("main",), name="compute")

    assert LocalId(owner_id=owner_id, ordinal=0) == LocalId(owner_id=owner_id, ordinal=0)


def test_local_id_distinguishes_between_ordinals_in_same_owner() -> None:
    owner_id = FunctionId(module_path=("main",), name="compute")

    assert LocalId(owner_id=owner_id, ordinal=0) != LocalId(owner_id=owner_id, ordinal=1)


def test_local_id_distinguishes_between_owners() -> None:
    function_owner = FunctionId(module_path=("main",), name="compute")
    method_owner = MethodId(module_path=("main",), class_name="Box", name="compute")

    assert LocalId(owner_id=function_owner, ordinal=0) != LocalId(owner_id=method_owner, ordinal=0)


def test_local_id_rejects_negative_ordinals() -> None:
    owner_id = FunctionId(module_path=("main",), name="compute")

    with pytest.raises(ValueError, match="LocalId ordinal must be non-negative"):
        LocalId(owner_id=owner_id, ordinal=-1)