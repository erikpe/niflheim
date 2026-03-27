from __future__ import annotations

from pathlib import Path

from compiler.frontend.ast_nodes import CallExpr, ExprStmt, FieldAccessExpr, IdentifierExpr, VarDeclStmt
from compiler.resolver import resolve_program
from compiler.semantic.lowering.orchestration import build_typecheck_contexts
from compiler.semantic.lowering.resolution import (
    ResolvedClassValueTarget,
    ResolvedFieldMemberTarget,
    ResolvedFunctionValueTarget,
    ResolvedInstanceMethodMemberTarget,
    ResolvedStaticMethodMemberTarget,
    resolve_field_access_member_target,
    resolve_identifier_value_target,
    resolve_module_member_value_target,
)
from compiler.semantic.symbols import build_program_symbol_index
from compiler.typecheck.context import declare_variable, pop_scope, push_scope
from compiler.typecheck.model import TypeInfo


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_resolution_helpers_classify_unqualified_imported_identifier_values(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export class Box {
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

        fn main() -> i64 {
            twice;
            Box;
            return 0;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    contexts = build_typecheck_contexts(program)
    symbol_index = build_program_symbol_index(program)
    statements = program.modules[("main",)].ast.functions[0].body.statements

    function_expr = statements[0]
    class_expr = statements[1]
    assert isinstance(function_expr, ExprStmt)
    assert isinstance(class_expr, ExprStmt)
    assert isinstance(function_expr.expression, IdentifierExpr)
    assert isinstance(class_expr.expression, IdentifierExpr)

    function_target = resolve_identifier_value_target(contexts[("main",)], symbol_index, function_expr.expression)
    class_target = resolve_identifier_value_target(contexts[("main",)], symbol_index, class_expr.expression)

    assert isinstance(function_target, ResolvedFunctionValueTarget)
    assert function_target.function_id.module_path == ("util",)
    assert function_target.function_id.name == "twice"

    assert isinstance(class_target, ResolvedClassValueTarget)
    assert class_target.class_id.module_path == ("util",)
    assert class_target.class_id.name == "Box"
    assert class_target.constructor_id.module_path == ("util",)
    assert class_target.constructor_id.class_name == "Box"


def test_resolution_helpers_classify_qualified_module_member_values(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export class Box {
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

        fn main() -> i64 {
            util.twice;
            util.Box;
            return 0;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    contexts = build_typecheck_contexts(program)
    symbol_index = build_program_symbol_index(program)
    statements = program.modules[("main",)].ast.functions[0].body.statements

    function_expr = statements[0]
    class_expr = statements[1]
    assert isinstance(function_expr, ExprStmt)
    assert isinstance(class_expr, ExprStmt)
    assert isinstance(function_expr.expression, FieldAccessExpr)
    assert isinstance(class_expr.expression, FieldAccessExpr)

    function_target = resolve_module_member_value_target(contexts[("main",)], symbol_index, function_expr.expression)
    class_target = resolve_module_member_value_target(contexts[("main",)], symbol_index, class_expr.expression)

    assert isinstance(function_target, ResolvedFunctionValueTarget)
    assert function_target.function_id.module_path == ("util",)
    assert function_target.function_id.name == "twice"

    assert isinstance(class_target, ResolvedClassValueTarget)
    assert class_target.class_id.module_path == ("util",)
    assert class_target.class_id.name == "Box"
    assert class_target.constructor_id.module_path == ("util",)
    assert class_target.constructor_id.class_name == "Box"


def test_resolution_helpers_classify_static_instance_and_field_member_targets(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Box {
            value: i64;

            fn get() -> i64 {
                return __self.value;
            }

            static fn from_i64(value: i64) -> Box {
                return Box(value);
            }
        }

        fn main() -> i64 {
            var ctor: fn(i64) -> Box = Box.from_i64;
            var box: Box = Box(7);
            box.value;
            var value: i64 = box.get();
            return 0;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    contexts = build_typecheck_contexts(program)
    ctx = contexts[("main",)]
    statements = program.modules[("main",)].ast.functions[0].body.statements

    static_method_expr = statements[0]
    field_expr = statements[2]
    instance_method_expr = statements[3]
    assert isinstance(static_method_expr, VarDeclStmt)
    assert isinstance(static_method_expr.initializer, FieldAccessExpr)
    assert isinstance(field_expr, ExprStmt)
    assert isinstance(field_expr.expression, FieldAccessExpr)
    assert isinstance(instance_method_expr, VarDeclStmt)
    assert isinstance(instance_method_expr.initializer, CallExpr)
    assert isinstance(instance_method_expr.initializer.callee, FieldAccessExpr)

    push_scope(ctx)
    try:
        declare_variable(ctx, "box", TypeInfo(name="Box", kind="reference"), field_expr.expression.object_expr.span)

        static_target = resolve_field_access_member_target(ctx, static_method_expr.initializer)
        field_target = resolve_field_access_member_target(ctx, field_expr.expression)
        instance_method_target = resolve_field_access_member_target(ctx, instance_method_expr.initializer.callee)
    finally:
        pop_scope(ctx)

    assert isinstance(static_target, ResolvedStaticMethodMemberTarget)
    assert static_target.method_id.module_path == ("main",)
    assert static_target.method_id.class_name == "Box"
    assert static_target.method_id.name == "from_i64"

    assert isinstance(field_target, ResolvedFieldMemberTarget)
    assert field_target.owner_class_id.module_path == ("main",)
    assert field_target.owner_class_id.name == "Box"
    assert field_target.field_name == "value"
    assert field_target.type_ref.canonical_name == "i64"
    assert field_target.access.receiver_type_ref.canonical_name == "main::Box"

    assert isinstance(instance_method_target, ResolvedInstanceMethodMemberTarget)
    assert instance_method_target.method_id.module_path == ("main",)
    assert instance_method_target.method_id.class_name == "Box"
    assert instance_method_target.method_id.name == "get"
    assert instance_method_target.access.receiver_type_ref.canonical_name == "main::Box"
