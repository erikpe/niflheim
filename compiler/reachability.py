from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from compiler.ast_nodes import (
    AssignStmt,
    BinaryExpr,
    BlockStmt,
    CallExpr,
    CastExpr,
    ClassDecl,
    ExprStmt,
    Expression,
    FieldAccessExpr,
    FunctionDecl,
    IdentifierExpr,
    IfStmt,
    IndexExpr,
    LiteralExpr,
    ModuleAst,
    ReturnStmt,
    Statement,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)
from compiler.resolver import ProgramInfo


@dataclass
class WalkContext:
    local_types: dict[str, str]
    found_functions: set[str]
    found_classes: set[str]

    def child_scope(self) -> WalkContext:
        return WalkContext(
            local_types=self.local_types.copy(),
            found_functions=self.found_functions,
            found_classes=self.found_classes,
        )


def _is_reference_type_name(type_name: str) -> bool:
    return type_name and type_name[0].isupper()


def _flatten_field_chain(expr: Expression) -> list[str] | None:
    if isinstance(expr, IdentifierExpr):
        return [expr.name]
    if isinstance(expr, FieldAccessExpr):
        left = _flatten_field_chain(expr.object_expr)
        if left is None:
            return None
        return [*left, expr.field_name]
    return None


class ReachabilityWalker:
    def __init__(self, program: ProgramInfo) -> None:
        self.program = program
        self.known_functions: dict[str, list[FunctionDecl]] = {}
        self.known_classes: dict[str, ClassDecl] = {}

        for module_info in self.program.modules.values():
            for fn_decl in module_info.ast.functions:
                self.known_functions.setdefault(fn_decl.name, []).append(fn_decl)
            for cls_decl in module_info.ast.classes:
                self.known_classes.setdefault(cls_decl.name, cls_decl)

        self.known_function_names = set(self.known_functions)
        self.known_class_names = set(self.known_classes)

        self.reachable_functions: set[str] = set()
        self.reachable_classes: set[str] = set()
        self.function_queue: deque[str] = deque()
        self.class_queue: deque[str] = deque()

    def _enqueue_class(self, type_name: str) -> None:
        if type_name not in self.known_class_names or type_name in self.reachable_classes:
            return
        self.reachable_classes.add(type_name)
        self.class_queue.append(type_name)

    def _enqueue_function(self, function_name: str) -> None:
        if function_name not in self.known_function_names or function_name in self.reachable_functions:
            return
        self.reachable_functions.add(function_name)
        self.function_queue.append(function_name)

    def _walk_expr(self, expr: Expression, *, ctx: WalkContext) -> None:
        if isinstance(expr, IdentifierExpr):
            return

        if isinstance(expr, CastExpr):
            if expr.type_ref.name in self.known_class_names or _is_reference_type_name(expr.type_ref.name):
                ctx.found_classes.add(expr.type_ref.name)
            self._walk_expr(expr.operand, ctx=ctx)
            return

        if isinstance(expr, UnaryExpr):
            self._walk_expr(expr.operand, ctx=ctx)
            return

        if isinstance(expr, BinaryExpr):
            self._walk_expr(expr.left, ctx=ctx)
            self._walk_expr(expr.right, ctx=ctx)
            return

        if isinstance(expr, FieldAccessExpr):
            if isinstance(expr.object_expr, LiteralExpr) and expr.object_expr.value.startswith('"'):
                ctx.found_classes.add("Str")
            self._walk_expr(expr.object_expr, ctx=ctx)
            return

        if isinstance(expr, IndexExpr):
            self._walk_expr(expr.object_expr, ctx=ctx)
            self._walk_expr(expr.index_expr, ctx=ctx)
            return

        if isinstance(expr, CallExpr):
            for arg in expr.arguments:
                self._walk_expr(arg, ctx=ctx)

            callee = expr.callee
            if isinstance(callee, IdentifierExpr):
                if callee.name in self.known_class_names:
                    ctx.found_classes.add(callee.name)
                elif callee.name in self.known_function_names:
                    ctx.found_functions.add(callee.name)
                return

            chain = _flatten_field_chain(callee)
            if chain is None or len(chain) < 2:
                self._walk_expr(callee, ctx=ctx)
                return

            first = chain[0]
            last = chain[-1]
            receiver_type = ctx.local_types.get(first)
            if receiver_type is not None:
                ctx.found_classes.add(receiver_type)
                return

            if last in self.known_class_names:
                ctx.found_classes.add(last)
            elif last in self.known_function_names:
                ctx.found_functions.add(last)

    def _walk_stmt(self, stmt: Statement, *, ctx: WalkContext) -> None:
        if isinstance(stmt, VarDeclStmt):
            ctx.local_types[stmt.name] = stmt.type_ref.name
            if stmt.type_ref.name in self.known_class_names or _is_reference_type_name(stmt.type_ref.name):
                ctx.found_classes.add(stmt.type_ref.name)
            if stmt.initializer is not None:
                self._walk_expr(stmt.initializer, ctx=ctx)
            return

        if isinstance(stmt, AssignStmt):
            self._walk_expr(stmt.target, ctx=ctx)
            self._walk_expr(stmt.value, ctx=ctx)
            return

        if isinstance(stmt, ExprStmt):
            self._walk_expr(stmt.expression, ctx=ctx)
            return

        if isinstance(stmt, ReturnStmt):
            if stmt.value is not None:
                self._walk_expr(stmt.value, ctx=ctx)
            return

        if isinstance(stmt, BlockStmt):
            self._walk_block(stmt, ctx=ctx.child_scope())
            return

        if isinstance(stmt, IfStmt):
            self._walk_expr(stmt.condition, ctx=ctx)
            self._walk_block(stmt.then_branch, ctx=ctx.child_scope())
            if isinstance(stmt.else_branch, BlockStmt):
                self._walk_block(stmt.else_branch, ctx=ctx.child_scope())
            elif isinstance(stmt.else_branch, IfStmt):
                self._walk_stmt(stmt.else_branch, ctx=ctx.child_scope())
            return

        if isinstance(stmt, WhileStmt):
            self._walk_expr(stmt.condition, ctx=ctx)
            self._walk_block(stmt.body, ctx=ctx.child_scope())

    def _walk_block(self, block: BlockStmt, *, ctx: WalkContext) -> None:
        for stmt in block.statements:
            self._walk_stmt(stmt, ctx=ctx)

    def _visit_function_decl(self, fn_decl: FunctionDecl) -> None:
        for param in fn_decl.params:
            self._enqueue_class(param.type_ref.name)
        self._enqueue_class(fn_decl.return_type.name)

        if fn_decl.body is None:
            return

        walk_ctx = WalkContext(
            local_types={param.name: param.type_ref.name for param in fn_decl.params},
            found_functions=set(),
            found_classes=set(),
        )
        self._walk_block(fn_decl.body, ctx=walk_ctx)

        for discovered_name in walk_ctx.found_functions:
            self._enqueue_function(discovered_name)
        for discovered_type in walk_ctx.found_classes:
            self._enqueue_class(discovered_type)

    def _visit_class_decl(self, cls_decl: ClassDecl) -> None:
        for field in cls_decl.fields:
            self._enqueue_class(field.type_ref.name)

        for method in cls_decl.methods:
            for param in method.params:
                self._enqueue_class(param.type_ref.name)
            self._enqueue_class(method.return_type.name)

            walk_ctx = WalkContext(
                local_types={param.name: param.type_ref.name for param in method.params},
                found_functions=set(),
                found_classes=set(),
            )
            self._walk_block(method.body, ctx=walk_ctx)

            for discovered_name in walk_ctx.found_functions:
                self._enqueue_function(discovered_name)
            for discovered_type in walk_ctx.found_classes:
                self._enqueue_class(discovered_type)

    def walk(self) -> tuple[set[str], set[str]]:
        self._enqueue_function("main")

        while self.function_queue or self.class_queue:
            while self.function_queue:
                function_name = self.function_queue.popleft()
                for fn_decl in self.known_functions.get(function_name, []):
                    self._visit_function_decl(fn_decl)

            while self.class_queue:
                class_name = self.class_queue.popleft()
                cls_decl = self.known_classes.get(class_name)
                if cls_decl is None:
                    continue
                self._visit_class_decl(cls_decl)

        return self.reachable_functions, self.reachable_classes


def prune_unreachable(program: ProgramInfo) -> ProgramInfo:
    reachable_functions, reachable_classes = ReachabilityWalker(program).walk()

    for module_info in program.modules.values():
        filtered_functions = [
            fn_decl for fn_decl in module_info.ast.functions if fn_decl.name in reachable_functions
        ]
        filtered_classes = [
            cls_decl for cls_decl in module_info.ast.classes if cls_decl.name in reachable_classes
        ]
        module_info.ast = ModuleAst(
            imports=module_info.ast.imports,
            classes=filtered_classes,
            functions=filtered_functions,
            span=module_info.ast.span,
        )

    return program
