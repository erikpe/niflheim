from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace

from compiler.common.logging import get_logger
from compiler.common.type_names import NON_CLASS_TYPE_NAMES
from compiler.common.type_shapes import is_array_type_name, is_function_type_name
from compiler.resolver import ModulePath
from compiler.semantic.ir import *
from compiler.semantic.symbols import ClassId, FunctionId, MethodId


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
            self._enqueue_type_name(function.function_id.module_path, param.type_name)
        self._enqueue_type_name(function.function_id.module_path, function.return_type_name)
        if function.body is not None:
            self._walk_block(function.function_id.module_path, function.body)

    def _visit_method(self, method: SemanticMethod) -> None:
        self._enqueue_class(ClassId(module_path=method.method_id.module_path, name=method.method_id.class_name))
        for param in method.params:
            self._enqueue_type_name(method.method_id.module_path, param.type_name)
        self._enqueue_type_name(method.method_id.module_path, method.return_type_name)
        self._walk_block(method.method_id.module_path, method.body)

    def _visit_class(self, cls: SemanticClass) -> None:
        for field in cls.fields:
            self._enqueue_type_name(cls.class_id.module_path, field.type_name)
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
                self._enqueue_type_name(interface.interface_id.module_path, param.type_name)
            self._enqueue_type_name(interface.interface_id.module_path, method.return_type_name)

    def _walk_block(self, module_path: ModulePath, block: SemanticBlock) -> None:
        for stmt in block.statements:
            self._walk_stmt(module_path, stmt)

    def _walk_stmt(self, module_path: ModulePath, stmt: SemanticStmt) -> None:
        if isinstance(stmt, SemanticBlock):
            self._walk_block(module_path, stmt)
            return
        if isinstance(stmt, SemanticVarDecl):
            self._enqueue_type_name(module_path, stmt.type_name)
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
            self._walk_block(module_path, stmt.then_block)
            if stmt.else_block is not None:
                self._walk_block(module_path, stmt.else_block)
            return
        if isinstance(stmt, SemanticWhile):
            self._walk_expr(module_path, stmt.condition)
            self._walk_block(module_path, stmt.body)
            return
        if isinstance(stmt, SemanticForIn):
            self._walk_expr(module_path, stmt.collection)
            self._enqueue_method(dispatch_method_id(stmt.iter_len_dispatch))
            self._enqueue_method(dispatch_method_id(stmt.iter_get_dispatch))
            self._enqueue_type_name(module_path, stmt.element_type_name)
            self._walk_block(module_path, stmt.body)
            return
        if isinstance(stmt, (SemanticBreak, SemanticContinue)):
            return
        raise TypeError(f"Unsupported semantic statement for reachability: {type(stmt).__name__}")

    def _walk_lvalue(self, module_path: ModulePath, lvalue) -> None:
        if isinstance(lvalue, FieldLValue):
            self._walk_expr(module_path, lvalue.receiver)
            self._enqueue_type_name(module_path, lvalue.receiver_type_name)
            self._enqueue_type_name(module_path, lvalue.type_name)
            return
        if isinstance(lvalue, IndexLValue):
            self._walk_expr(module_path, lvalue.target)
            self._walk_expr(module_path, lvalue.index)
            self._enqueue_type_name(module_path, lvalue.value_type_name)
            self._enqueue_method(dispatch_method_id(lvalue.dispatch))
            return
        if isinstance(lvalue, SliceLValue):
            self._walk_expr(module_path, lvalue.target)
            self._walk_expr(module_path, lvalue.begin)
            self._walk_expr(module_path, lvalue.end)
            self._enqueue_type_name(module_path, lvalue.value_type_name)
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
            self._enqueue_type_name(module_path, expr.target_type_name)
            return
        if isinstance(expr, TypeTestExprS):
            self._walk_expr(module_path, expr.operand)
            self._enqueue_type_name(module_path, expr.target_type_name)
            return
        if isinstance(expr, FieldReadExpr):
            self._walk_expr(module_path, expr.receiver)
            self._enqueue_type_name(module_path, expr.receiver_type_name)
            self._enqueue_type_name(module_path, expr.type_name)
            return
        if isinstance(expr, FunctionCallExpr):
            self._enqueue_function(expr.function_id)
            for arg in expr.args:
                self._walk_expr(module_path, arg)
            return
        if isinstance(expr, StaticMethodCallExpr):
            self._enqueue_method(expr.method_id)
            for arg in expr.args:
                self._walk_expr(module_path, arg)
            return
        if isinstance(expr, InstanceMethodCallExpr):
            self._enqueue_method(expr.method_id)
            self._walk_expr(module_path, expr.receiver)
            self._enqueue_type_name(module_path, expr.receiver_type_name)
            for arg in expr.args:
                self._walk_expr(module_path, arg)
            return
        if isinstance(expr, InterfaceMethodCallExpr):
            self._enqueue_interface(expr.interface_id)
            self._walk_expr(module_path, expr.receiver)
            self._enqueue_type_name(module_path, expr.receiver_type_name)
            for arg in expr.args:
                self._walk_expr(module_path, arg)
            return
        if isinstance(expr, ConstructorCallExpr):
            self._enqueue_class(
                ClassId(module_path=expr.constructor_id.module_path, name=expr.constructor_id.class_name)
            )
            for arg in expr.args:
                self._walk_expr(module_path, arg)
            return
        if isinstance(expr, CallableValueCallExpr):
            self._walk_expr(module_path, expr.callee)
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
            self._enqueue_type_name(module_path, expr.element_type_name)
            return
        if isinstance(expr, SyntheticExpr):
            for arg in expr.args:
                self._walk_expr(module_path, arg)
            return

    def _enqueue_type_name(self, current_module_path: ModulePath, type_name: str) -> None:
        for class_id in _iter_class_ids_for_type_name(current_module_path, type_name):
            self._enqueue_class(class_id)
            self._enqueue_interface(InterfaceId(module_path=class_id.module_path, name=class_id.name))


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


def _iter_class_ids_for_type_name(current_module_path: ModulePath, type_name: str):
    text = type_name.strip()
    if not text or text in NON_CLASS_TYPE_NAMES or text.startswith("__"):
        return
    if is_array_type_name(text):
        yield from _iter_class_ids_for_type_name(current_module_path, text[:-2])
        return
    if is_function_type_name(text):
        params_text, return_text = _split_function_type(text)
        for param_text in _split_top_level(params_text):
            if param_text:
                yield from _iter_class_ids_for_type_name(current_module_path, param_text)
        yield from _iter_class_ids_for_type_name(current_module_path, return_text)
        return
    yield _class_id_from_type_name(current_module_path, text)


def _split_function_type(type_name: str) -> tuple[str, str]:
    depth = 0
    close_index = -1
    for index, char in enumerate(type_name[2:], start=2):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                close_index = index
                break
    if close_index < 0:
        raise ValueError(f"Invalid function type name '{type_name}'")
    suffix = type_name[close_index + 1 :].lstrip()
    if not suffix.startswith("->"):
        raise ValueError(f"Invalid function type name '{type_name}'")
    return type_name[3:close_index], suffix[2:].strip()


def _split_top_level(text: str) -> list[str]:
    if not text:
        return []
    parts: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    return parts


def _class_id_from_type_name(current_module_path: ModulePath, type_name: str) -> ClassId:
    if "::" in type_name:
        owner_dotted, class_name = type_name.split("::", 1)
        return ClassId(module_path=tuple(owner_dotted.split(".")), name=class_name)
    return ClassId(module_path=current_module_path, name=type_name)
