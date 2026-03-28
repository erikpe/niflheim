from __future__ import annotations

from dataclasses import replace

from compiler.semantic.ir import *


class SemanticTreeRewriter:
    def rewrite_program(self, program: SemanticProgram) -> SemanticProgram:
        return SemanticProgram(
            entry_module=program.entry_module,
            modules={module_path: self.rewrite_module(module) for module_path, module in program.modules.items()},
        )

    def rewrite_module(self, module: SemanticModule) -> SemanticModule:
        return replace(
            module,
            classes=[self.rewrite_class(cls) for cls in module.classes],
            functions=[self.rewrite_function(fn) for fn in module.functions],
            interfaces=list(module.interfaces),
        )

    def rewrite_class(self, cls: SemanticClass) -> SemanticClass:
        return replace(
            cls,
            fields=[self.rewrite_field(field) for field in cls.fields],
            methods=[self.rewrite_method(method) for method in cls.methods],
        )

    def rewrite_field(self, field: SemanticField) -> SemanticField:
        if field.initializer is None:
            return field
        return replace(field, initializer=self.rewrite_expr(field.initializer))

    def rewrite_function(self, fn: SemanticFunction) -> SemanticFunction:
        if fn.body is None:
            return fn
        return replace(fn, body=self.rewrite_block(fn.body))

    def rewrite_method(self, method: SemanticMethod) -> SemanticMethod:
        return replace(method, body=self.rewrite_block(method.body))

    def rewrite_block(self, block: SemanticBlock) -> SemanticBlock:
        return replace(block, statements=[self.rewrite_stmt(stmt) for stmt in block.statements])

    def rewrite_stmt(self, stmt: SemanticStmt) -> SemanticStmt:
        if isinstance(stmt, SemanticBlock):
            return self.transform_stmt(self.rewrite_block(stmt))
        if isinstance(stmt, SemanticVarDecl):
            initializer = None if stmt.initializer is None else self.rewrite_expr(stmt.initializer)
            return self.transform_stmt(replace(stmt, initializer=initializer))
        if isinstance(stmt, SemanticAssign):
            return self.transform_stmt(
                replace(stmt, target=self.rewrite_lvalue(stmt.target), value=self.rewrite_expr(stmt.value))
            )
        if isinstance(stmt, SemanticExprStmt):
            return self.transform_stmt(replace(stmt, expr=self.rewrite_expr(stmt.expr)))
        if isinstance(stmt, SemanticReturn):
            value = None if stmt.value is None else self.rewrite_expr(stmt.value)
            return self.transform_stmt(replace(stmt, value=value))
        if isinstance(stmt, SemanticIf):
            return self.transform_stmt(
                replace(
                    stmt,
                    condition=self.rewrite_expr(stmt.condition),
                    then_block=self.rewrite_block(stmt.then_block),
                    else_block=None if stmt.else_block is None else self.rewrite_block(stmt.else_block),
                )
            )
        if isinstance(stmt, SemanticWhile):
            return self.transform_stmt(
                replace(stmt, condition=self.rewrite_expr(stmt.condition), body=self.rewrite_block(stmt.body))
            )
        if isinstance(stmt, SemanticForIn):
            return self.transform_stmt(
                replace(stmt, collection=self.rewrite_expr(stmt.collection), body=self.rewrite_block(stmt.body))
            )
        if isinstance(stmt, (SemanticBreak, SemanticContinue)):
            return self.transform_stmt(stmt)
        raise TypeError(f"Unsupported semantic statement for rewriting: {type(stmt).__name__}")

    def rewrite_lvalue(self, target: SemanticLValue) -> SemanticLValue:
        if isinstance(target, LocalLValue):
            return self.transform_lvalue(target)
        if isinstance(target, FieldLValue):
            return self.transform_lvalue(
                replace(target, access=replace(target.access, receiver=self.rewrite_expr(target.access.receiver)))
            )
        if isinstance(target, IndexLValue):
            return self.transform_lvalue(
                replace(target, target=self.rewrite_expr(target.target), index=self.rewrite_expr(target.index))
            )
        if isinstance(target, SliceLValue):
            return self.transform_lvalue(
                replace(
                    target,
                    target=self.rewrite_expr(target.target),
                    begin=self.rewrite_expr(target.begin),
                    end=self.rewrite_expr(target.end),
                )
            )
        raise TypeError(f"Unsupported semantic lvalue for rewriting: {type(target).__name__}")

    def rewrite_expr(self, expr: SemanticExpr) -> SemanticExpr:
        if isinstance(
            expr, (LocalRefExpr, FunctionRefExpr, ClassRefExpr, LiteralExprS, NullExprS, StringLiteralBytesExpr)
        ):
            return self.transform_expr(expr)
        if isinstance(expr, MethodRefExpr):
            receiver = None if expr.receiver is None else self.rewrite_expr(expr.receiver)
            return self.transform_expr(replace(expr, receiver=receiver))
        if isinstance(expr, UnaryExprS):
            return self.transform_expr(replace(expr, operand=self.rewrite_expr(expr.operand)))
        if isinstance(expr, BinaryExprS):
            return self.transform_expr(
                replace(expr, left=self.rewrite_expr(expr.left), right=self.rewrite_expr(expr.right))
            )
        if isinstance(expr, CastExprS):
            return self.transform_expr(replace(expr, operand=self.rewrite_expr(expr.operand)))
        if isinstance(expr, TypeTestExprS):
            return self.transform_expr(replace(expr, operand=self.rewrite_expr(expr.operand)))
        if isinstance(expr, FieldReadExpr):
            return self.transform_expr(
                replace(expr, access=replace(expr.access, receiver=self.rewrite_expr(expr.access.receiver)))
            )
        if isinstance(expr, CallExprS):
            rewritten_args = [self.rewrite_expr(arg) for arg in expr.args]
            if isinstance(expr.target, CallableValueCallTarget):
                return self.transform_expr(
                    replace(
                        expr,
                        target=replace(expr.target, callee=self.rewrite_expr(expr.target.callee)),
                        args=rewritten_args,
                    )
                )
            access = call_target_receiver_access(expr.target)
            if access is None:
                return self.transform_expr(replace(expr, args=rewritten_args))
            return self.transform_expr(
                replace(
                    expr,
                    target=replace(expr.target, access=replace(access, receiver=self.rewrite_expr(access.receiver))),
                    args=rewritten_args,
                )
            )
        if isinstance(expr, ArrayLenExpr):
            return self.transform_expr(replace(expr, target=self.rewrite_expr(expr.target)))
        if isinstance(expr, IndexReadExpr):
            return self.transform_expr(
                replace(expr, target=self.rewrite_expr(expr.target), index=self.rewrite_expr(expr.index))
            )
        if isinstance(expr, SliceReadExpr):
            return self.transform_expr(
                replace(
                    expr,
                    target=self.rewrite_expr(expr.target),
                    begin=self.rewrite_expr(expr.begin),
                    end=self.rewrite_expr(expr.end),
                )
            )
        if isinstance(expr, ArrayCtorExprS):
            return self.transform_expr(replace(expr, length_expr=self.rewrite_expr(expr.length_expr)))
        raise TypeError(f"Unsupported semantic expression for rewriting: {type(expr).__name__}")

    def transform_stmt(self, stmt: SemanticStmt) -> SemanticStmt:
        return stmt

    def transform_lvalue(self, target: SemanticLValue) -> SemanticLValue:
        return target

    def transform_expr(self, expr: SemanticExpr) -> SemanticExpr:
        return expr
