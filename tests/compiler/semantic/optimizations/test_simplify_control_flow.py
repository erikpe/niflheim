from __future__ import annotations

from pathlib import Path

from compiler.common.logging import configure_logging, resolve_log_settings
from compiler.resolver import resolve_program
from compiler.semantic.ir import BoolConstant, LiteralExprS, SemanticIf, SemanticReturn, SemanticWhile
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.constant_folding import fold_constants
from compiler.semantic.optimizations.simplify_control_flow import simplify_control_flow


def _write(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_simplify_control_flow_chooses_then_branch_for_true_condition(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            if 1 < 2 {
                return 7;
            } else {
                return 9;
            }
        }
        """,
    )

    semantic = fold_constants(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    simplified = simplify_control_flow(semantic)
    statements = simplified.modules[("main",)].functions[0].body.statements

    assert len(statements) == 1
    assert isinstance(statements[0], SemanticReturn)
    assert isinstance(statements[0].value, LiteralExprS)
    assert statements[0].value.constant.value == 7


def test_simplify_control_flow_chooses_else_branch_for_false_condition(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            if false {
                return 7;
            } else {
                return 9;
            }
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    simplified = simplify_control_flow(semantic)
    statements = simplified.modules[("main",)].functions[0].body.statements

    assert len(statements) == 1
    assert isinstance(statements[0], SemanticReturn)
    assert isinstance(statements[0].value, LiteralExprS)
    assert statements[0].value.constant.value == 9


def test_simplify_control_flow_removes_while_false_loop(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            while false {
                return 1;
            }
            return 0;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    simplified = simplify_control_flow(semantic)
    statements = simplified.modules[("main",)].functions[0].body.statements

    assert len(statements) == 1
    assert isinstance(statements[0], SemanticReturn)
    assert isinstance(statements[0].value, LiteralExprS)
    assert statements[0].value.constant.value == 0


def test_simplify_control_flow_prunes_unreachable_statements_after_return(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            return 1;
            return 2;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    simplified = simplify_control_flow(semantic)
    statements = simplified.modules[("main",)].functions[0].body.statements

    assert len(statements) == 1
    assert isinstance(statements[0], SemanticReturn)
    assert isinstance(statements[0].value, LiteralExprS)
    assert statements[0].value.constant.value == 1


def test_simplify_control_flow_preserves_non_constant_if_structure(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main(flag: bool) -> i64 {
            if flag {
                return 1;
            }
            return 0;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    simplified = simplify_control_flow(semantic)
    statements = simplified.modules[("main",)].functions[0].body.statements

    assert len(statements) == 2
    assert isinstance(statements[0], SemanticIf)
    assert not (
        isinstance(statements[0].condition, LiteralExprS) and isinstance(statements[0].condition.constant, BoolConstant)
    )


def test_simplify_control_flow_preserves_non_constant_while_structure(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main(flag: bool) -> i64 {
            while flag {
                return 1;
            }
            return 0;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    simplified = simplify_control_flow(semantic)
    statements = simplified.modules[("main",)].functions[0].body.statements

    assert len(statements) == 2
    assert isinstance(statements[0], SemanticWhile)
    assert not (
        isinstance(statements[0].condition, LiteralExprS) and isinstance(statements[0].condition.constant, BoolConstant)
    )


def test_simplify_control_flow_logs_exact_summary_counts(tmp_path: Path, capsys) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            if true {
                while false {
                    return 1;
                }
            } else {
                return 2;
            }
            return 3;
            return 4;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    capsys.readouterr()
    configure_logging(resolve_log_settings("debug", verbose=1, quiet=0))

    simplify_control_flow(semantic)
    captured = capsys.readouterr()

    assert captured.err.strip() == (
        "nifc: debug: Optimization pass simplify_control_flow simplified 1 conditionals, "
        "removed 1 while loops, pruned 1 unreachable statements"
    )
