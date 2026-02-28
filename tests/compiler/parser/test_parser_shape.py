from pathlib import Path

import pytest

from compiler.ast_dump import ast_to_debug_json
from compiler.lexer import lex
from compiler.parser import parse, parse_expression


GOLDEN_DIR = Path(__file__).parent / "golden"


@pytest.mark.parametrize(
    "source_path",
    sorted(GOLDEN_DIR.glob("module_shape*.nif"), key=lambda path: path.name),
)
def test_module_ast_debug_dump_matches_golden(source_path: Path) -> None:
    expected_path = source_path.with_suffix(".golden.json")

    source = source_path.read_text(encoding="utf-8")
    module = parse(lex(source, source_path=source_path.as_posix()))
    actual = ast_to_debug_json(module)
    expected = expected_path.read_text(encoding="utf-8")

    assert actual.rstrip() == expected.rstrip()


@pytest.mark.parametrize(
    "source_path",
    sorted(GOLDEN_DIR.glob("expression_shape*.nif"), key=lambda path: path.name),
)
def test_expression_ast_debug_dump_matches_golden(source_path: Path) -> None:
    expected_path = source_path.with_suffix(".golden.json")

    source = source_path.read_text(encoding="utf-8")
    expr = parse_expression(lex(source, source_path=source_path.as_posix()))
    actual = ast_to_debug_json(expr)
    expected = expected_path.read_text(encoding="utf-8")

    assert actual.rstrip() == expected.rstrip()
