from __future__ import annotations

from pathlib import Path

import pytest

from compiler.frontend.ast_nodes import CallExpr, ExprStmt, FieldAccessExpr, IdentifierExpr, ReturnStmt, VarDeclStmt
from compiler.resolver import resolve_program
from compiler.semantic.lowering.orchestration import build_typecheck_contexts
from compiler.semantic.lowering.calls import ResolvedConstructorCallTarget, resolve_call_target
from compiler.semantic.lowering.resolution import (
    ResolvedClassValueTarget,
    ResolvedFieldMemberTarget,
    ResolvedFunctionValueTarget,
    ResolvedInstanceMethodMemberTarget,
    ResolvedStaticMethodMemberTarget,
    ResolvedVirtualMethodMemberTarget,
    resolve_field_access_member_target,
    resolve_identifier_value_target,
    resolve_module_member_value_target,
)
from compiler.semantic.symbols import ClassId, ConstructorId, MethodId, build_program_symbol_index
from compiler.typecheck.context import declare_variable, pop_scope, push_scope
from compiler.typecheck.model import TypeCheckError, TypeInfo


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


def test_resolution_helpers_classify_full_path_qualified_module_member_values(tmp_path: Path) -> None:
    _write(
        tmp_path / "util" / "math.nif",
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
        import util.math;

        fn main() -> i64 {
            util.math.twice;
            util.math.Box;
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
    assert function_target.function_id.module_path == ("util", "math")
    assert function_target.function_id.name == "twice"

    assert isinstance(class_target, ResolvedClassValueTarget)
    assert class_target.class_id.module_path == ("util", "math")
    assert class_target.class_id.name == "Box"
    assert class_target.constructor_id.module_path == ("util", "math")
    assert class_target.constructor_id.class_name == "Box"


def test_resolution_helpers_classify_alias_qualified_module_member_values(tmp_path: Path) -> None:
    _write(
        tmp_path / "util" / "math.nif",
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
        import util.math as math;

        fn main() -> i64 {
            math.twice;
            math.Box;
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
    assert function_target.function_id.module_path == ("util", "math")
    assert function_target.function_id.name == "twice"

    assert isinstance(class_target, ResolvedClassValueTarget)
    assert class_target.class_id.module_path == ("util", "math")
    assert class_target.class_id.name == "Box"
    assert class_target.constructor_id.module_path == ("util", "math")
    assert class_target.constructor_id.class_name == "Box"


def test_resolution_helpers_prefer_local_class_value_over_imported_class_with_same_leaf_name(tmp_path: Path) -> None:
    _write(
        tmp_path / "util" / "shadow.nif",
        """
        export class Token {
            value: i64;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util.shadow as shadow;

        class Token {
            value: i64;
        }

        fn main() -> i64 {
            var local: Token = Token(7);
            var imported: shadow.Token = shadow.Token(11);
            return 0;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    contexts = build_typecheck_contexts(program)
    symbol_index = build_program_symbol_index(program)
    statements = program.modules[("main",)].ast.functions[0].body.statements

    local_decl = statements[0]
    imported_decl = statements[1]
    assert isinstance(local_decl, VarDeclStmt)
    assert isinstance(imported_decl, VarDeclStmt)
    assert isinstance(local_decl.initializer, CallExpr)
    assert isinstance(imported_decl.initializer, CallExpr)

    local_target = resolve_call_target(contexts[("main",)], symbol_index, local_decl.initializer)
    imported_target = resolve_call_target(contexts[("main",)], symbol_index, imported_decl.initializer)

    assert isinstance(local_target, ResolvedConstructorCallTarget)
    assert local_target.constructor_id == ConstructorId(module_path=("main",), class_name="Token", ordinal=0)
    assert isinstance(imported_target, ResolvedConstructorCallTarget)
    assert imported_target.constructor_id == ConstructorId(module_path=("util", "shadow"), class_name="Token", ordinal=0)


def test_resolution_helpers_reject_legacy_leaf_alias_module_member_values_after_alias_migration(tmp_path: Path) -> None:
    _write(
        tmp_path / "util" / "math.nif",
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
        import util.math;

        fn main() -> i64 {
            math.twice;
            math.Box;
            return 0;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)

    with pytest.raises(TypeCheckError, match="Unknown identifier 'math'"):
        build_typecheck_contexts(program)


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

    assert isinstance(instance_method_target, ResolvedVirtualMethodMemberTarget)
    assert instance_method_target.slot_owner_class_id == ClassId(module_path=("main",), name="Box")
    assert instance_method_target.method_name == "get"
    assert instance_method_target.selected_method_id.module_path == ("main",)
    assert instance_method_target.selected_method_id.class_name == "Box"
    assert instance_method_target.selected_method_id.name == "get"
    assert instance_method_target.access.receiver_type_ref.canonical_name == "main::Box"


def test_resolve_call_target_selects_constructor_overload_ordinal(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Hashable {
            fn hash_code() -> u64;
        }

        class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }

        class Sink {
            constructor(value: Obj) {
                return;
            }

            constructor(value: Hashable) {
                return;
            }
        }

        fn main() -> i64 {
            var sink: Sink = Sink(Key());
            return 0;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    contexts = build_typecheck_contexts(program)
    symbol_index = build_program_symbol_index(program)
    statements = program.modules[("main",)].ast.functions[0].body.statements
    sink_decl = statements[0]
    assert isinstance(sink_decl, VarDeclStmt)
    assert isinstance(sink_decl.initializer, CallExpr)

    call_target = resolve_call_target(contexts[("main",)], symbol_index, sink_decl.initializer)

    assert isinstance(call_target, ResolvedConstructorCallTarget)
    assert call_target.constructor_id == ConstructorId(module_path=("main",), class_name="Sink", ordinal=1)


def test_resolution_helpers_use_declaring_owner_for_inherited_members(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Base {
            value: i64 = 1;

            fn read() -> i64 {
                return __self.value;
            }
        }

        class Derived extends Base {
            extra: i64 = 2;
        }

        fn main() -> i64 {
            var d: Derived = Derived();
            d.value;
            var value: i64 = d.read();
            return 0;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    contexts = build_typecheck_contexts(program)
    ctx = contexts[("main",)]
    statements = program.modules[("main",)].ast.functions[0].body.statements

    field_expr = statements[1]
    instance_method_expr = statements[2]
    assert isinstance(field_expr, ExprStmt)
    assert isinstance(field_expr.expression, FieldAccessExpr)
    assert isinstance(instance_method_expr, VarDeclStmt)
    assert isinstance(instance_method_expr.initializer, CallExpr)
    assert isinstance(instance_method_expr.initializer.callee, FieldAccessExpr)

    push_scope(ctx)
    try:
        declare_variable(ctx, "d", TypeInfo(name="Derived", kind="reference"), field_expr.expression.object_expr.span)
        field_target = resolve_field_access_member_target(ctx, field_expr.expression)
        instance_method_target = resolve_field_access_member_target(ctx, instance_method_expr.initializer.callee)
    finally:
        pop_scope(ctx)

    assert isinstance(field_target, ResolvedFieldMemberTarget)
    assert field_target.owner_class_id == ClassId(module_path=("main",), name="Base")

    assert isinstance(instance_method_target, ResolvedVirtualMethodMemberTarget)
    assert instance_method_target.slot_owner_class_id == ClassId(module_path=("main",), name="Base")
    assert instance_method_target.method_name == "read"
    assert instance_method_target.selected_method_id == MethodId(module_path=("main",), class_name="Base", name="read")


def test_resolution_helpers_keep_selected_implementation_while_exposing_virtual_slot_origin(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Base {
            fn read() -> i64 {
                return 1;
            }
        }

        class Derived extends Base {
            override fn read() -> i64 {
                return 2;
            }
        }

        fn main() -> i64 {
            var d: Derived = Derived();
            return d.read();
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    contexts = build_typecheck_contexts(program)
    ctx = contexts[("main",)]
    return_stmt = program.modules[("main",)].ast.functions[0].body.statements[1]

    assert isinstance(return_stmt, ReturnStmt)
    assert isinstance(return_stmt.value, CallExpr)
    assert isinstance(return_stmt.value.callee, FieldAccessExpr)

    push_scope(ctx)
    try:
        declare_variable(ctx, "d", TypeInfo(name="Derived", kind="reference"), return_stmt.value.callee.object_expr.span)
        member_target = resolve_field_access_member_target(ctx, return_stmt.value.callee)
    finally:
        pop_scope(ctx)

    assert isinstance(member_target, ResolvedVirtualMethodMemberTarget)
    assert member_target.slot_owner_class_id == ClassId(module_path=("main",), name="Base")
    assert member_target.selected_method_id == MethodId(module_path=("main",), class_name="Derived", name="read")


def test_resolution_helpers_keep_private_instance_methods_direct(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Box {
            private fn read() -> i64 {
                return 1;
            }

            fn use() -> i64 {
                return __self.read();
            }
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    contexts = build_typecheck_contexts(program)
    ctx = contexts[("main",)]
    return_stmt = program.modules[("main",)].ast.classes[0].methods[1].body.statements[0]

    assert isinstance(return_stmt, ReturnStmt)
    assert isinstance(return_stmt.value, CallExpr)
    assert isinstance(return_stmt.value.callee, FieldAccessExpr)

    push_scope(ctx)
    try:
        declare_variable(ctx, "__self", TypeInfo(name="Box", kind="reference"), return_stmt.value.callee.object_expr.span)
        member_target = resolve_field_access_member_target(ctx, return_stmt.value.callee)
    finally:
        pop_scope(ctx)

    assert isinstance(member_target, ResolvedInstanceMethodMemberTarget)
    assert member_target.method_id == MethodId(module_path=("main",), class_name="Box", name="read")
