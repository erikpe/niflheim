from __future__ import annotations

from dataclasses import replace

from compiler.common.type_names import PRIMITIVE_TYPE_NAMES, REFERENCE_BUILTIN_TYPE_NAMES
from compiler.frontend.ast_nodes import (
    ArrayTypeRef,
    ClassDecl,
    ConstructorDecl,
    FunctionDecl,
    FunctionTypeRef,
    InterfaceDecl,
    InterfaceMethodDecl,
    MethodDecl,
    TypeRef,
    TypeRefNode,
)

from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.model import ClassInfo, ConstructorInfo, FunctionSig, InterfaceInfo, TypeCheckError, TypeInfo
from compiler.typecheck.module_lookup import (
    lookup_interface_by_type_name,
    resolve_imported_class_name,
    resolve_imported_interface_name,
    resolve_qualified_imported_class_name,
    resolve_qualified_imported_interface_name,
)
from compiler.typecheck.relations import format_function_type_name
from compiler.typecheck.type_resolution import resolve_type_ref


def _function_sig_from_decl(ctx: TypeCheckContext, decl: FunctionDecl | MethodDecl) -> FunctionSig:
    params = [resolve_type_ref(ctx, param.type_ref) for param in decl.params]
    return FunctionSig(
        name=decl.name,
        params=params,
        return_type=resolve_type_ref(ctx, decl.return_type),
        is_static=decl.is_static if isinstance(decl, MethodDecl) else False,
        is_private=decl.is_private if isinstance(decl, MethodDecl) else False,
    )


def _interface_sig_from_decl(ctx: TypeCheckContext, decl: InterfaceMethodDecl) -> FunctionSig:
    params = [resolve_type_ref(ctx, param.type_ref) for param in decl.params]
    return FunctionSig(name=decl.name, params=params, return_type=resolve_type_ref(ctx, decl.return_type))


def _constructor_info_from_decl(ctx: TypeCheckContext, decl: ConstructorDecl, ordinal: int) -> ConstructorInfo:
    params = [resolve_type_ref(ctx, param.type_ref) for param in decl.params]
    return ConstructorInfo(
        ordinal=ordinal,
        params=params,
        param_names=[param.name for param in decl.params],
        is_private=decl.is_private,
    )


def _type_signature_key(type_info: TypeInfo) -> tuple:
    element_key = None if type_info.element_type is None else _type_signature_key(type_info.element_type)
    callable_param_keys = None
    if type_info.callable_params is not None:
        callable_param_keys = tuple(_type_signature_key(param) for param in type_info.callable_params)
    callable_return_key = None
    if type_info.callable_return is not None:
        callable_return_key = _type_signature_key(type_info.callable_return)
    return (type_info.name, type_info.kind, element_key, callable_param_keys, callable_return_key)


def _constructor_signature_key(constructor_info: ConstructorInfo) -> tuple:
    return tuple(_type_signature_key(param_type) for param_type in constructor_info.params)


def _compatibility_constructor_info(class_decl, fields: dict[str, TypeInfo], private_fields: set[str]) -> ConstructorInfo:
    param_names = [field_decl.name for field_decl in class_decl.fields if field_decl.initializer is None]
    return ConstructorInfo(
        ordinal=0,
        params=[fields[param_name] for param_name in param_names],
        param_names=param_names,
        is_private=len(private_fields) > 0,
    )


def _collect_constructors(ctx: TypeCheckContext, class_decl, fields: dict[str, TypeInfo], private_fields: set[str]) -> list[ConstructorInfo]:
    if not class_decl.constructors:
        return [_compatibility_constructor_info(class_decl, fields, private_fields)]

    constructors: list[ConstructorInfo] = []
    seen_signatures: set[tuple] = set()
    for ordinal, constructor_decl in enumerate(class_decl.constructors):
        constructor_info = _constructor_info_from_decl(ctx, constructor_decl, ordinal)
        signature_key = _constructor_signature_key(constructor_info)
        if signature_key in seen_signatures:
            raise TypeCheckError("Duplicate constructor signature", constructor_decl.span)
        seen_signatures.add(signature_key)
        constructors.append(constructor_info)
    return constructors


def _contains_interface_type(type_info: TypeInfo) -> bool:
    if type_info.kind == "interface":
        return True
    if type_info.element_type is not None:
        return _contains_interface_type(type_info.element_type)
    if type_info.kind == "callable":
        if type_info.callable_params is not None and any(_contains_interface_type(param) for param in type_info.callable_params):
            return True
        if type_info.callable_return is not None and _contains_interface_type(type_info.callable_return):
            return True
    return False


def _reject_interface_types_in_extern_signature(fn_decl: FunctionDecl, signature: FunctionSig) -> None:
    if any(_contains_interface_type(param_type) for param_type in signature.params) or _contains_interface_type(
        signature.return_type
    ):
        raise TypeCheckError("Interface types are not allowed in extern signatures in v1", fn_decl.span)


def _placeholder_class_info(name: str) -> ClassInfo:
    return ClassInfo(
        name=name,
        superclass_name=None,
        fields={},
        field_order=[],
        constructors=[],
        methods={},
        private_fields=set(),
        final_fields=set(),
        private_methods=set(),
        implemented_interfaces=set(),
    )


def _placeholder_interface_info(name: str) -> InterfaceInfo:
    return InterfaceInfo(name=name, methods={})


def _lookup_module_classes(module_ast) -> dict[str, ClassDecl]:
    return {class_decl.name: class_decl for class_decl in module_ast.classes}


def _lookup_module_interfaces(module_ast) -> set[str]:
    return {interface_decl.name for interface_decl in module_ast.interfaces}


def _lookup_context_for_module(ctx: TypeCheckContext, module_path):
    if module_path == ctx.module_path:
        return ctx

    if ctx.modules is None or module_path is None:
        module_ast = ctx.module_ast
    else:
        module_ast = ctx.modules[module_path].ast

    return TypeCheckContext(
        module_ast=module_ast,
        module_path=module_path,
        modules=ctx.modules,
        module_function_sigs=ctx.module_function_sigs,
        module_class_infos=ctx.module_class_infos,
        module_interface_infos=ctx.module_interface_infos,
        classes={class_decl.name: _placeholder_class_info(class_decl.name) for class_decl in module_ast.classes},
        interfaces={
            interface_decl.name: _placeholder_interface_info(interface_decl.name)
            for interface_decl in module_ast.interfaces
        },
    )


def _resolve_superclass_name(ctx: TypeCheckContext, lookup_ctx: TypeCheckContext, class_decl: ClassDecl) -> str | None:
    if class_decl.base_class is None:
        return None

    if isinstance(class_decl.base_class, ArrayTypeRef | FunctionTypeRef):
        raise TypeCheckError("Superclass must be a named class", class_decl.base_class.span)

    assert isinstance(class_decl.base_class, TypeRef)
    superclass_name = class_decl.base_class.name

    if "." in superclass_name:
        qualified_interface_name = resolve_qualified_imported_interface_name(
            lookup_ctx, superclass_name, class_decl.base_class.span, allow_missing=True
        )
        if qualified_interface_name is not None:
            raise TypeCheckError(f"Superclass '{superclass_name}' is not a class", class_decl.base_class.span)

        qualified_class_name = resolve_qualified_imported_class_name(
            lookup_ctx, superclass_name, class_decl.base_class.span
        )
        if qualified_class_name is not None:
            return qualified_class_name

    if superclass_name in lookup_ctx.classes:
        return superclass_name

    imported_class_name = resolve_imported_class_name(lookup_ctx, superclass_name, class_decl.base_class.span)
    if imported_class_name is not None:
        return imported_class_name

    imported_interface_name = resolve_imported_interface_name(lookup_ctx, superclass_name, class_decl.base_class.span)
    if (
        superclass_name in lookup_ctx.interfaces
        or imported_interface_name is not None
        or superclass_name in PRIMITIVE_TYPE_NAMES
        or superclass_name in REFERENCE_BUILTIN_TYPE_NAMES
    ):
        raise TypeCheckError(f"Superclass '{superclass_name}' is not a class", class_decl.base_class.span)

    raise TypeCheckError(f"Unknown superclass '{superclass_name}'", class_decl.base_class.span)


def _canonical_class_name(module_path, class_name: str) -> str:
    if module_path is None:
        return class_name
    return f"{'.'.join(module_path)}::{class_name}"


def _split_resolved_class_name(current_module_path, resolved_name: str):
    if "::" in resolved_name:
        owner_dotted, class_name = resolved_name.split("::", 1)
        return tuple(owner_dotted.split(".")), class_name
    return current_module_path, resolved_name


def _class_decl_for_module(ctx: TypeCheckContext, module_path, class_name: str) -> ClassDecl | None:
    if module_path == ctx.module_path or module_path is None:
        return _lookup_module_classes(ctx.module_ast).get(class_name)

    if ctx.modules is None:
        return None

    module_info = ctx.modules.get(module_path)
    if module_info is None:
        return None
    return _lookup_module_classes(module_info.ast).get(class_name)


def _ordered_class_decls(ctx: TypeCheckContext) -> tuple[list[ClassDecl], dict[str, str | None]]:
    resolved_superclasses: dict[str, str | None] = {}
    visit_state: dict[str, str] = {}
    visit_stack: list[str] = []
    ordered: list[ClassDecl] = []

    def visit(module_path, class_decl: ClassDecl) -> None:
        canonical_name = _canonical_class_name(module_path, class_decl.name)
        current_state = visit_state.get(canonical_name)
        if current_state == "done":
            return
        if current_state == "visiting":
            cycle_start = visit_stack.index(canonical_name)
            cycle_names = visit_stack[cycle_start:] + [canonical_name]
            display = " -> ".join(name.split("::", 1)[-1] for name in cycle_names)
            raise TypeCheckError(f"Inheritance cycle detected: {display}", class_decl.base_class.span)

        lookup_ctx = _lookup_context_for_module(ctx, module_path)
        resolved_superclass_name = _resolve_superclass_name(ctx, lookup_ctx, class_decl)
        if module_path == ctx.module_path:
            resolved_superclasses[class_decl.name] = resolved_superclass_name

        visit_state[canonical_name] = "visiting"
        visit_stack.append(canonical_name)

        if resolved_superclass_name is not None:
            superclass_module_path, superclass_name = _split_resolved_class_name(module_path, resolved_superclass_name)
            superclass_canonical_name = _canonical_class_name(superclass_module_path, superclass_name)
            if superclass_canonical_name == canonical_name:
                raise TypeCheckError(f"Class '{class_decl.name}' cannot extend itself", class_decl.base_class.span)

            superclass_decl = _class_decl_for_module(ctx, superclass_module_path, superclass_name)
            if superclass_decl is None:
                raise TypeCheckError(f"Unknown superclass '{resolved_superclass_name}'", class_decl.base_class.span)
            visit(superclass_module_path, superclass_decl)

        visit_stack.pop()
        visit_state[canonical_name] = "done"
        if module_path == ctx.module_path:
            ordered.append(class_decl)

    for class_decl in ctx.module_ast.classes:
        visit(ctx.module_path, class_decl)

    return ordered, resolved_superclasses


def collect_module_declarations(ctx: TypeCheckContext) -> None:
    for interface_decl in ctx.module_ast.interfaces:
        if interface_decl.name in ctx.interfaces or interface_decl.name in ctx.classes or interface_decl.name in ctx.functions:
            raise TypeCheckError(f"Duplicate declaration '{interface_decl.name}'", interface_decl.span)
        ctx.interfaces[interface_decl.name] = InterfaceInfo(name=interface_decl.name, methods={})

    for class_decl in ctx.module_ast.classes:
        if class_decl.name in ctx.classes or class_decl.name in ctx.functions or class_decl.name in ctx.interfaces:
            raise TypeCheckError(f"Duplicate declaration '{class_decl.name}'", class_decl.span)
        ctx.classes[class_decl.name] = ClassInfo(
            name=class_decl.name,
            superclass_name=None,
            fields={},
            field_order=[],
            constructors=[],
            methods={},
            private_fields=set(),
            final_fields=set(),
            private_methods=set(),
            implemented_interfaces=set(),
        )

    for interface_decl in ctx.module_ast.interfaces:
        methods: dict[str, FunctionSig] = {}
        for method_decl in interface_decl.methods:
            if method_decl.name in methods:
                raise TypeCheckError(f"Duplicate interface method '{method_decl.name}'", method_decl.span)
            methods[method_decl.name] = _interface_sig_from_decl(ctx, method_decl)

        ctx.interfaces[interface_decl.name] = InterfaceInfo(name=interface_decl.name, methods=methods)

    ordered_class_decls, resolved_superclasses = _ordered_class_decls(ctx)

    for class_decl in ordered_class_decls:
        fields: dict[str, TypeInfo] = {}
        field_order: list[str] = []
        for field_decl in class_decl.fields:
            if field_decl.name in fields:
                raise TypeCheckError(f"Duplicate field '{field_decl.name}'", field_decl.span)
            field_type = resolve_type_ref(ctx, field_decl.type_ref)
            fields[field_decl.name] = field_type
            field_order.append(field_decl.name)

        methods: dict[str, FunctionSig] = {}
        for method_decl in class_decl.methods:
            if method_decl.name in methods:
                raise TypeCheckError(f"Duplicate method '{method_decl.name}'", method_decl.span)
            if method_decl.name in fields:
                raise TypeCheckError(f"Duplicate member '{method_decl.name}'", method_decl.span)
            methods[method_decl.name] = _function_sig_from_decl(ctx, method_decl)

        private_fields = {field_decl.name for field_decl in class_decl.fields if field_decl.is_private}
        final_fields = {field_decl.name for field_decl in class_decl.fields if field_decl.is_final}
        private_methods = {method_decl.name for method_decl in class_decl.methods if method_decl.is_private}
        constructors = _collect_constructors(ctx, class_decl, fields, private_fields)

        ctx.classes[class_decl.name] = ClassInfo(
            name=class_decl.name,
            superclass_name=resolved_superclasses[class_decl.name],
            fields=fields,
            field_order=field_order,
            constructors=constructors,
            methods=methods,
            private_fields=private_fields,
            final_fields=final_fields,
            private_methods=private_methods,
            implemented_interfaces=set(),
        )

    for fn_decl in ctx.module_ast.functions:
        if fn_decl.is_extern and fn_decl.body is not None:
            raise TypeCheckError("Extern function must not have a body", fn_decl.span)
        if not fn_decl.is_extern and fn_decl.body is None:
            raise TypeCheckError("Function declaration missing body", fn_decl.span)
        if fn_decl.name in ctx.functions or fn_decl.name in ctx.classes or fn_decl.name in ctx.interfaces:
            raise TypeCheckError(f"Duplicate declaration '{fn_decl.name}'", fn_decl.span)
        fn_sig = _function_sig_from_decl(ctx, fn_decl)
        if fn_decl.is_extern:
            _reject_interface_types_in_extern_signature(fn_decl, fn_sig)
        ctx.functions[fn_decl.name] = fn_sig


def validate_interface_conformance(ctx: TypeCheckContext) -> None:
    for class_decl in ctx.module_ast.classes:
        class_info = ctx.classes[class_decl.name]
        method_decls_by_name = {method_decl.name: method_decl for method_decl in class_decl.methods}
        implemented_interfaces: set[str] = set()

        for interface_ref in class_decl.implements:
            interface_type_name, interface_info, interface_owner_module = _resolve_implemented_interface(ctx, interface_ref)
            if interface_owner_module is not None and "::" not in interface_type_name:
                implemented_interfaces.add(f"{'.'.join(interface_owner_module)}::{interface_type_name}")
            else:
                implemented_interfaces.add(interface_type_name)
            for method_name, interface_method_sig in interface_info.methods.items():
                class_method_sig = class_info.methods.get(method_name)
                if class_method_sig is None:
                    raise TypeCheckError(
                        f"Class '{class_decl.name}' is missing method '{method_name}' required by interface '{interface_type_name}'",
                        interface_ref.span,
                    )

                method_decl = method_decls_by_name[method_name]
                if class_method_sig.is_private:
                    raise TypeCheckError(
                        f"Method '{class_decl.name}.{method_name}' is private and cannot satisfy interface '{interface_type_name}'",
                        method_decl.span,
                    )

                if class_method_sig.is_static:
                    raise TypeCheckError(
                        f"Method '{class_decl.name}.{method_name}' is static and cannot satisfy interface '{interface_type_name}'",
                        method_decl.span,
                    )

                _require_matching_interface_signature(
                    ctx=ctx,
                    class_name=class_decl.name,
                    method_decl=method_decl,
                    class_sig=class_method_sig,
                    interface_type_name=interface_type_name,
                    interface_method_name=method_name,
                    interface_sig=interface_method_sig,
                    class_owner_module=ctx.module_path,
                    interface_owner_module=interface_owner_module,
                )

        ctx.classes[class_decl.name] = replace(class_info, implemented_interfaces=implemented_interfaces)


def _resolve_implemented_interface(
    ctx: TypeCheckContext, interface_ref: TypeRefNode
) -> tuple[str, InterfaceInfo, tuple[str, ...] | None]:
    interface_type_name = _resolve_interface_reference_name(ctx, interface_ref)
    interface_info = lookup_interface_by_type_name(ctx, interface_type_name)
    if interface_info is None:
        raise TypeCheckError(f"Unknown interface '{interface_type_name}'", interface_ref.span)

    if "::" in interface_type_name:
        owner_dotted, _interface_name = interface_type_name.split("::", 1)
        owner_module = tuple(owner_dotted.split("."))
    else:
        owner_module = ctx.module_path

    return interface_type_name, interface_info, owner_module


def _resolve_interface_reference_name(ctx: TypeCheckContext, interface_ref: TypeRefNode) -> str:
    if isinstance(interface_ref, ArrayTypeRef | FunctionTypeRef):
        raise TypeCheckError("Implemented type must be a named interface", interface_ref.span)

    assert isinstance(interface_ref, TypeRef)
    name = interface_ref.name

    if "." in name:
        qualified_name = resolve_qualified_imported_interface_name(ctx, name, interface_ref.span)
        if qualified_name is not None:
            return qualified_name

        qualified_class_name = resolve_qualified_imported_class_name(ctx, name, interface_ref.span)
        if qualified_class_name is not None:
            raise TypeCheckError(f"Implemented type '{name}' is not an interface", interface_ref.span)

    if name in ctx.interfaces:
        return name

    imported_name = resolve_imported_interface_name(ctx, name, interface_ref.span)
    if imported_name is not None:
        return imported_name

    if name in ctx.classes or resolve_imported_class_name(ctx, name, interface_ref.span) is not None:
        raise TypeCheckError(f"Implemented type '{name}' is not an interface", interface_ref.span)

    raise TypeCheckError(f"Unknown interface '{name}'", interface_ref.span)


def _require_matching_interface_signature(
    *,
    ctx: TypeCheckContext,
    class_name: str,
    method_decl: MethodDecl,
    class_sig: FunctionSig,
    interface_type_name: str,
    interface_method_name: str,
    interface_sig: FunctionSig,
    class_owner_module: tuple[str, ...] | None,
    interface_owner_module: tuple[str, ...] | None,
) -> None:
    if len(class_sig.params) != len(interface_sig.params):
        raise TypeCheckError(
            f"Method '{class_name}.{interface_method_name}' has {len(class_sig.params)} parameters but interface '{interface_type_name}.{interface_method_name}' requires {len(interface_sig.params)}",
            method_decl.span,
        )

    normalized_class_params = [_normalize_type_for_owner_module(ctx, param, class_owner_module) for param in class_sig.params]
    normalized_interface_params = [
        _normalize_type_for_owner_module(ctx, param, interface_owner_module) for param in interface_sig.params
    ]
    for index, (class_param, interface_param) in enumerate(zip(normalized_class_params, normalized_interface_params), start=1):
        if class_param != interface_param:
            raise TypeCheckError(
                f"Method '{class_name}.{interface_method_name}' parameter {index} has type '{class_param.name}' but interface '{interface_type_name}.{interface_method_name}' requires '{interface_param.name}'",
                method_decl.span,
            )

    normalized_class_return = _normalize_type_for_owner_module(ctx, class_sig.return_type, class_owner_module)
    normalized_interface_return = _normalize_type_for_owner_module(ctx, interface_sig.return_type, interface_owner_module)
    if normalized_class_return != normalized_interface_return:
        raise TypeCheckError(
            f"Method '{class_name}.{interface_method_name}' returns '{normalized_class_return.name}' but interface '{interface_type_name}.{interface_method_name}' requires '{normalized_interface_return.name}'",
            method_decl.span,
        )


def _normalize_type_for_owner_module(
    ctx: TypeCheckContext, type_info: TypeInfo, owner_module: tuple[str, ...] | None
) -> TypeInfo:
    if type_info.element_type is not None:
        normalized_element_type = _normalize_type_for_owner_module(ctx, type_info.element_type, owner_module)
        if normalized_element_type == type_info.element_type:
            return type_info
        return TypeInfo(name=f"{normalized_element_type.name}[]", kind=type_info.kind, element_type=normalized_element_type)

    if type_info.kind == "callable":
        if type_info.callable_params is None or type_info.callable_return is None:
            return type_info
        normalized_params = [
            _normalize_type_for_owner_module(ctx, param, owner_module) for param in type_info.callable_params
        ]
        normalized_return = _normalize_type_for_owner_module(ctx, type_info.callable_return, owner_module)
        return TypeInfo(
            name=format_function_type_name(normalized_params, normalized_return),
            kind="callable",
            callable_params=normalized_params,
            callable_return=normalized_return,
        )

    if type_info.kind not in {"reference", "interface"}:
        return type_info
    if owner_module is None or "::" in type_info.name:
        return type_info

    owner_dotted = ".".join(owner_module)
    owner_classes = None if ctx.module_class_infos is None else ctx.module_class_infos.get(owner_module)
    if owner_classes is not None and type_info.name in owner_classes:
        return TypeInfo(name=f"{owner_dotted}::{type_info.name}", kind=type_info.kind)

    owner_interfaces = None if ctx.module_interface_infos is None else ctx.module_interface_infos.get(owner_module)
    if owner_interfaces is not None and type_info.name in owner_interfaces:
        return TypeInfo(name=f"{owner_dotted}::{type_info.name}", kind=type_info.kind)

    return type_info
