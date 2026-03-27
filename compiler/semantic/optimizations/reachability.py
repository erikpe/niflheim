from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace

from compiler.common.logging import get_logger
from compiler.common.type_names import NON_CLASS_TYPE_NAMES
from compiler.resolver import ModulePath
from compiler.semantic.ir import *
from compiler.semantic.symbols import ClassId, FunctionId, MethodId
from compiler.semantic.type_compat import compat_semantic_type_ref_from_name
from compiler.semantic.types import (
    SemanticTypeRef,
    iter_semantic_nominal_ids,
    semantic_type_canonical_name,
    semantic_type_is_null,
    semantic_type_is_primitive,
)


@dataclass(frozen=True)
class SemanticReachability:
    reachable_functions: set[FunctionId]
    reachable_classes: set[ClassId]
    reachable_interfaces: set[InterfaceId]
    reachable_methods: set[MethodId]


class _SemanticReachabilityWalker:
    def __init__(self, program: SemanticProgram) -> None:
        self.program = program
        self.functions_by_id: dict[FunctionId, SemanticFunction] = {}
        self.classes_by_id: dict[ClassId, SemanticClass] = {}
        self.methods_by_id: dict[MethodId, SemanticMethod] = {}
        self.interfaces_by_id: dict[InterfaceId, SemanticInterface] = {}

        for module in program.modules.values():
            for function in module.functions:
                self.functions_by_id[function.function_id] = function
            for cls in module.classes:
                self.classes_by_id[cls.class_id] = cls
                for method in cls.methods:
                    self.methods_by_id[method.method_id] = method
            for interface in module.interfaces:
                self.interfaces_by_id[interface.interface_id] = interface

        self.reachable_functions: set[FunctionId] = set()
        self.reachable_classes: set[ClassId] = set()
        self.reachable_interfaces: set[InterfaceId] = set()
        self.reachable_methods: set[MethodId] = set()

        self.function_queue: deque[FunctionId] = deque()
        self.class_queue: deque[ClassId] = deque()
        self.interface_queue: deque[InterfaceId] = deque()
        self.method_queue: deque[MethodId] = deque()

    def walk(self) -> SemanticReachability:
        self._enqueue_function(FunctionId(module_path=self.program.entry_module, name="main"))

        while self.function_queue or self.class_queue or self.interface_queue or self.method_queue:
            while self.function_queue:
                function_id = self.function_queue.popleft()
                function = self.functions_by_id.get(function_id)
                if function is not None:
                    self._visit_function(function)

            while self.method_queue:
                method_id = self.method_queue.popleft()
                method = self.methods_by_id.get(method_id)
                if method is not None:
                    self._visit_method(method)

            while self.class_queue:
                class_id = self.class_queue.popleft()
                cls = self.classes_by_id.get(class_id)
                if cls is not None:
                    self._visit_class(cls)

            while self.interface_queue:
                interface_id = self.interface_queue.popleft()
                interface = self.interfaces_by_id.get(interface_id)
                if interface is not None:
                    self._visit_interface(interface)

        return SemanticReachability(
            reachable_functions=self.reachable_functions,
            reachable_classes=self.reachable_classes,
            reachable_interfaces=self.reachable_interfaces,
            reachable_methods=self.reachable_methods,
        )

    def _enqueue_function(self, function_id: FunctionId) -> None:
        if function_id not in self.functions_by_id or function_id in self.reachable_functions:
            return
        self.reachable_functions.add(function_id)
        self.function_queue.append(function_id)

    def _enqueue_class(self, class_id: ClassId) -> None:
        if class_id not in self.classes_by_id or class_id in self.reachable_classes:
            return
        self.reachable_classes.add(class_id)
        self.class_queue.append(class_id)

    def _enqueue_interface(self, interface_id: InterfaceId) -> None:
        if interface_id not in self.interfaces_by_id or interface_id in self.reachable_interfaces:
            return
        self.reachable_interfaces.add(interface_id)
        self.interface_queue.append(interface_id)

    def _enqueue_method(self, method_id: MethodId | None) -> None:
        if method_id is None or method_id not in self.methods_by_id or method_id in self.reachable_methods:
            return
        self.reachable_methods.add(method_id)
        self.method_queue.append(method_id)
        self._enqueue_class(ClassId(module_path=method_id.module_path, name=method_id.class_name))

    def _visit_function(self, function: SemanticFunction) -> None:
        for param in function.params:
            self._enqueue_type_ref(function.function_id.module_path, param.type_ref)
        self._enqueue_type_ref(function.function_id.module_path, function.return_type_ref)
        if function.body is not None:
            self._walk_block(function.function_id.module_path, function.body, function)

    def _visit_method(self, method: SemanticMethod) -> None:
        self._enqueue_class(ClassId(module_path=method.method_id.module_path, name=method.method_id.class_name))
        for param in method.params:
            self._enqueue_type_ref(method.method_id.module_path, param.type_ref)
        self._enqueue_type_ref(method.method_id.module_path, method.return_type_ref)
        self._walk_block(method.method_id.module_path, method.body, method)

    def _visit_class(self, cls: SemanticClass) -> None:
        for field in cls.fields:
            self._enqueue_type_ref(cls.class_id.module_path, field.type_ref)
            if field.initializer is not None:
                self._walk_expr(cls.class_id.module_path, field.initializer)
        for interface_id in cls.implemented_interfaces:
            self._enqueue_interface(interface_id)
            interface = self.interfaces_by_id.get(interface_id)
            if interface is None:
                continue
            for interface_method in interface.methods:
                self._enqueue_method(
                    MethodId(
                        module_path=cls.class_id.module_path,
                        class_name=cls.class_id.name,
                        name=interface_method.method_id.name,
                    )
                )

    def _visit_interface(self, interface: SemanticInterface) -> None:
        for method in interface.methods:
            for param in method.params:
                self._enqueue_type_ref(interface.interface_id.module_path, param.type_ref)
            self._enqueue_type_ref(interface.interface_id.module_path, method.return_type_ref)

    def _walk_block(self, module_path: ModulePath, block: SemanticBlock, owner: SemanticFunctionLike) -> None:
        for stmt in block.statements:
            self._walk_stmt(module_path, stmt, owner)

    def _walk_stmt(self, module_path: ModulePath, stmt: SemanticStmt, owner: SemanticFunctionLike) -> None:
        if isinstance(stmt, SemanticBlock):
            self._walk_block(module_path, stmt, owner)
            return
        if isinstance(stmt, SemanticVarDecl):
            self._enqueue_type_ref(module_path, local_type_ref_for_owner(owner, stmt.local_id))
            if stmt.initializer is not None:
                self._walk_expr(module_path, stmt.initializer)
            return
        if isinstance(stmt, SemanticAssign):
            self._walk_lvalue(module_path, stmt.target)
            self._walk_expr(module_path, stmt.value)
            return
        if isinstance(stmt, SemanticExprStmt):
            self._walk_expr(module_path, stmt.expr)
            return
        if isinstance(stmt, SemanticReturn):
            if stmt.value is not None:
                self._walk_expr(module_path, stmt.value)
            return
        if isinstance(stmt, SemanticIf):
            self._walk_expr(module_path, stmt.condition)
            self._walk_block(module_path, stmt.then_block, owner)
            if stmt.else_block is not None:
                self._walk_block(module_path, stmt.else_block, owner)
            return
        if isinstance(stmt, SemanticWhile):
            self._walk_expr(module_path, stmt.condition)
            self._walk_block(module_path, stmt.body, owner)
            return
        if isinstance(stmt, SemanticForIn):
            self._walk_expr(module_path, stmt.collection)
            self._enqueue_method(dispatch_method_id(stmt.iter_len_dispatch))
            self._enqueue_method(dispatch_method_id(stmt.iter_get_dispatch))
            self._enqueue_type_ref(module_path, stmt.element_type_ref)
            self._walk_block(module_path, stmt.body, owner)
            return
        if isinstance(stmt, (SemanticBreak, SemanticContinue)):
            return
        raise TypeError(f"Unsupported semantic statement for reachability: {type(stmt).__name__}")

    def _walk_lvalue(self, module_path: ModulePath, lvalue) -> None:
        if isinstance(lvalue, FieldLValue):
            self._walk_expr(module_path, lvalue.receiver)
            self._enqueue_type_ref(module_path, lvalue.receiver_type_ref)
            self._enqueue_type_ref(module_path, lvalue.type_ref)
            return
        if isinstance(lvalue, IndexLValue):
            self._walk_expr(module_path, lvalue.target)
            self._walk_expr(module_path, lvalue.index)
            self._enqueue_type_ref(module_path, lvalue.value_type_ref)
            self._enqueue_method(dispatch_method_id(lvalue.dispatch))
            return
        if isinstance(lvalue, SliceLValue):
            self._walk_expr(module_path, lvalue.target)
            self._walk_expr(module_path, lvalue.begin)
            self._walk_expr(module_path, lvalue.end)
            self._enqueue_type_ref(module_path, lvalue.value_type_ref)
            self._enqueue_method(dispatch_method_id(lvalue.dispatch))

    def _walk_expr(self, module_path: ModulePath, expr: SemanticExpr) -> None:
        if isinstance(expr, FunctionRefExpr):
            self._enqueue_function(expr.function_id)
            return
        if isinstance(expr, ClassRefExpr):
            self._enqueue_class(expr.class_id)
            return
        if isinstance(expr, MethodRefExpr):
            self._enqueue_method(expr.method_id)
            if expr.receiver is not None:
                self._walk_expr(module_path, expr.receiver)
            return
        if isinstance(expr, (ArrayLenExpr,)):
            self._walk_expr(module_path, expr.target)
            return
        if isinstance(expr, UnaryExprS):
            self._walk_expr(module_path, expr.operand)
            return
        if isinstance(expr, BinaryExprS):
            self._walk_expr(module_path, expr.left)
            self._walk_expr(module_path, expr.right)
            return
        if isinstance(expr, CastExprS):
            self._walk_expr(module_path, expr.operand)
            self._enqueue_type_ref(module_path, expr.target_type_ref)
            return
        if isinstance(expr, TypeTestExprS):
            self._walk_expr(module_path, expr.operand)
            self._enqueue_type_ref(module_path, expr.target_type_ref)
            return
        if isinstance(expr, FieldReadExpr):
            self._walk_expr(module_path, expr.access.receiver)
            self._enqueue_type_ref(module_path, expr.receiver_type_ref)
            self._enqueue_type_ref(module_path, expr.type_ref)
            return
        if isinstance(expr, CallExprS):
            if isinstance(expr.target, FunctionCallTarget):
                self._enqueue_function(expr.target.function_id)
            elif isinstance(expr.target, StaticMethodCallTarget):
                self._enqueue_method(expr.target.method_id)
            elif isinstance(expr.target, InstanceMethodCallTarget):
                self._enqueue_method(expr.target.method_id)
                self._walk_expr(module_path, expr.target.access.receiver)
                self._enqueue_type_ref(module_path, expr.target.access.receiver_type_ref)
            elif isinstance(expr.target, InterfaceMethodCallTarget):
                self._enqueue_interface(expr.target.interface_id)
                self._walk_expr(module_path, expr.target.access.receiver)
                self._enqueue_type_ref(module_path, expr.target.access.receiver_type_ref)
            elif isinstance(expr.target, ConstructorCallTarget):
                self._enqueue_class(
                    ClassId(module_path=expr.target.constructor_id.module_path, name=expr.target.constructor_id.class_name)
                )
            else:
                self._walk_expr(module_path, expr.target.callee)
            for arg in expr.args:
                self._walk_expr(module_path, arg)
            return
        if isinstance(expr, IndexReadExpr):
            self._walk_expr(module_path, expr.target)
            self._walk_expr(module_path, expr.index)
            self._enqueue_method(dispatch_method_id(expr.dispatch))
            return
        if isinstance(expr, SliceReadExpr):
            self._walk_expr(module_path, expr.target)
            self._walk_expr(module_path, expr.begin)
            self._walk_expr(module_path, expr.end)
            self._enqueue_method(dispatch_method_id(expr.dispatch))
            return
        if isinstance(expr, ArrayCtorExprS):
            self._walk_expr(module_path, expr.length_expr)
            self._enqueue_type_ref(module_path, expr.element_type_ref)
            return
        if isinstance(expr, StringLiteralBytesExpr):
            return

    def _enqueue_type_name(self, current_module_path: ModulePath, type_name: str) -> None:
        text = type_name.strip()
        if not text or text in NON_CLASS_TYPE_NAMES or text.startswith("__"):
            return

        # Fallback type-name reconstruction stays compatibility-only. Real semantic
        # edges should arrive through canonical SemanticTypeRef metadata.
        self._enqueue_type_ref(
            current_module_path,
            compat_semantic_type_ref_from_name(current_module_path, text, nominal_kind="reference"),
        )
        self._enqueue_type_ref(
            current_module_path,
            compat_semantic_type_ref_from_name(current_module_path, text, nominal_kind="interface"),
        )

    def _enqueue_type_ref(self, current_module_path: ModulePath, type_ref: SemanticTypeRef) -> None:
        for nominal_id in iter_semantic_nominal_ids(type_ref):
            if isinstance(nominal_id, ClassId):
                self._enqueue_class(nominal_id)
            else:
                self._enqueue_interface(nominal_id)

        if (
            type_ref.class_id is None
            and type_ref.interface_id is None
            and type_ref.element_type is None
            and not type_ref.param_types
            and type_ref.return_type is None
            and not semantic_type_is_primitive(type_ref)
            and not semantic_type_is_null(type_ref)
        ):
            self._enqueue_type_name(current_module_path, semantic_type_canonical_name(type_ref))


def analyze_semantic_reachability(program: SemanticProgram) -> SemanticReachability:
    return _SemanticReachabilityWalker(program).walk()


def prune_unreachable_semantic(program: SemanticProgram) -> SemanticProgram:
    logger = get_logger(__name__)
    reachability = analyze_semantic_reachability(program)
    pruned_modules: dict[ModulePath, SemanticModule] = {}
    removed_function_count = 0
    removed_method_count = 0
    removed_class_count = 0
    removed_interface_count = 0

    for module_path, module in program.modules.items():
        classes: list[SemanticClass] = []
        for cls in module.classes:
            if cls.class_id not in reachability.reachable_classes:
                removed_class_count += 1
                removed_method_count += len(cls.methods)
                continue
            methods = [method for method in cls.methods if method.method_id in reachability.reachable_methods]
            removed_method_count += len(cls.methods) - len(methods)
            classes.append(replace(cls, methods=methods))

        functions = [fn for fn in module.functions if fn.function_id in reachability.reachable_functions]
        removed_function_count += len(module.functions) - len(functions)
        interfaces = [
            interface for interface in module.interfaces if interface.interface_id in reachability.reachable_interfaces
        ]
        removed_interface_count += len(module.interfaces) - len(interfaces)
        pruned_modules[module_path] = replace(module, classes=classes, functions=functions, interfaces=interfaces)

    logger.debugv(
        1,
        "Optimization pass prune_unreachable removed %d functions, %d methods, %d classes, %d interfaces",
        removed_function_count,
        removed_method_count,
        removed_class_count,
        removed_interface_count,
    )

    return SemanticProgram(entry_module=program.entry_module, modules=pruned_modules)
