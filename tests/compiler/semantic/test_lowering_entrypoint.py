from __future__ import annotations

import compiler.semantic.lowering as lowering


def test_lowering_package_does_not_reexport_lower_program() -> None:
    assert not hasattr(lowering, "lower_program")
