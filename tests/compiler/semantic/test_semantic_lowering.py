from __future__ import annotations

from pathlib import Path

from compiler.semantic_ir import (
    BinaryExprS,
    ClassRefExpr,
    ConstructorCallExpr,
    FieldLValue,
    FieldReadExpr,
    FunctionCallExpr,
    FunctionRefExpr,
    IndexReadExpr,
    InstanceMethodCallExpr,
    LocalLValue,
    LocalRefExpr,
    SemanticAssign,
    SemanticExprStmt,
    SemanticIf,
    SemanticReturn,
    SemanticVarDecl,
    SemanticWhile,
    StaticMethodCallExpr,
)
from compiler.resolver import resolve_program
from compiler.semantic_lowering import lower_program


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_lower_program_builds_semantic_declarations_and_ids(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export class Counter {
            value: i64;

            fn get() -> i64 {
                return 1;
            }
        }

        export fn twice(x: i64) -> i64 {
            return x + x;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)

    util_module = semantic.modules[("util",)]
    assert util_module.classes[0].class_id.module_path == ("util",)
    assert util_module.classes[0].class_id.name == "Counter"
    assert util_module.classes[0].fields[0].type_name == "i64"
    assert util_module.classes[0].methods[0].method_id.class_name == "Counter"
    assert util_module.classes[0].methods[0].return_type_name == "i64"
    assert util_module.functions[0].function_id.module_path == ("util",)
    assert util_module.functions[0].params[0].type_name == "i64"
    assert util_module.functions[0].return_type_name == "i64"


def test_lower_program_preserves_statement_and_field_structure(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Box {
            value: i64;
        }

        fn sum(box: Box, flag: bool) -> i64 {
            var total: i64 = 0;
            if flag {
                box.value = box.value + 1;
            }
            while total < 3 {
                total = total + 1;
            }
            return box.value;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    function = semantic.modules[("main",)].functions[0]

    assert isinstance(function.body.statements[0], SemanticVarDecl)
    assert function.body.statements[0].type_name == "i64"

    if_stmt = function.body.statements[1]
    assert isinstance(if_stmt, SemanticIf)
    assign_stmt = if_stmt.then_block.statements[0]
    assert isinstance(assign_stmt, SemanticAssign)
    assert isinstance(assign_stmt.target, FieldLValue)
    assert assign_stmt.target.field_name == "value"
    assert isinstance(assign_stmt.value, BinaryExprS)
    assert isinstance(assign_stmt.value.left, FieldReadExpr)

    while_stmt = function.body.statements[2]
    assert isinstance(while_stmt, SemanticWhile)
    while_assign = while_stmt.body.statements[0]
    assert isinstance(while_assign, SemanticAssign)
    assert isinstance(while_assign.target, LocalLValue)
    assert while_assign.target.name == "total"
    assert isinstance(while_assign.value, BinaryExprS)
    assert isinstance(while_assign.value.left, LocalRefExpr)

    return_stmt = function.body.statements[3]
    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, FieldReadExpr)


def test_lower_program_handles_simple_function_constructor_method_and_index_forms(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export class Box {
            value: i64;

            fn get() -> i64 {
                return 1;
            }

            static fn from_i64(value: i64) -> Box {
                return Box(value);
            }
        }

        export fn twice(x: i64) -> i64 {
            return x + x;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn helper(x: i64) -> i64 {
            return x;
        }

        fn main() -> i64 {
            var a: i64 = helper(1);
            var b: i64 = util.twice(a);
            var box: util.Box = util.Box(b);
            var alt: util.Box = util.Box.from_i64(b);
            var c: i64 = box.get();
            var arr: i64[] = i64[](2u);
            var x: i64 = arr[0];
            helper;
            util.Box;
            return c + x;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    statements = semantic.modules[("main",)].functions[1].body.statements

    assert isinstance(statements[0], SemanticVarDecl)
    assert isinstance(statements[0].initializer, FunctionCallExpr)

    assert isinstance(statements[1], SemanticVarDecl)
    assert isinstance(statements[1].initializer, FunctionCallExpr)

    assert isinstance(statements[2], SemanticVarDecl)
    assert isinstance(statements[2].initializer, ConstructorCallExpr)

    assert isinstance(statements[3], SemanticVarDecl)
    assert isinstance(statements[3].initializer, StaticMethodCallExpr)

    assert isinstance(statements[4], SemanticVarDecl)
    assert isinstance(statements[4].initializer, InstanceMethodCallExpr)

    assert isinstance(statements[6], SemanticVarDecl)
    assert isinstance(statements[6].initializer, IndexReadExpr)

    assert isinstance(statements[7], SemanticExprStmt)
    assert isinstance(statements[7].expr, FunctionRefExpr)

    assert isinstance(statements[8], SemanticExprStmt)
    assert isinstance(statements[8].expr, ClassRefExpr)
