from __future__ import annotations

from compiler.frontend.ast_nodes import ArrayTypeRef, FunctionDecl, FunctionTypeRef, InterfaceDecl, InterfaceMethodDecl, MethodDecl, TypeRef, TypeRefNode

from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.model import ClassInfo, FunctionSig, InterfaceInfo, TypeCheckError, TypeInfo
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
            fields={},
            field_order=[],
            constructor_param_order=[],
            methods={},
            private_fields=set(),
            final_fields=set(),
            private_methods=set(),
            constructor_is_private=False,
        )

    for interface_decl in ctx.module_ast.interfaces:
        methods: dict[str, FunctionSig] = {}
        for method_decl in interface_decl.methods:
            if method_decl.name in methods:
                raise TypeCheckError(f"Duplicate interface method '{method_decl.name}'", method_decl.span)
            methods[method_decl.name] = _interface_sig_from_decl(ctx, method_decl)

        ctx.interfaces[interface_decl.name] = InterfaceInfo(name=interface_decl.name, methods=methods)

    for class_decl in ctx.module_ast.classes:
        fields: dict[str, TypeInfo] = {}
        field_order: list[str] = []
        constructor_param_order: list[str] = []
        for field_decl in class_decl.fields:
            if field_decl.name in fields:
                raise TypeCheckError(f"Duplicate field '{field_decl.name}'", field_decl.span)
            field_type = resolve_type_ref(ctx, field_decl.type_ref)
            if field_decl.initializer is None:
                constructor_param_order.append(field_decl.name)
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

        ctx.classes[class_decl.name] = ClassInfo(
            name=class_decl.name,
            fields=fields,
            field_order=field_order,
            constructor_param_order=constructor_param_order,
            methods=methods,
            private_fields=private_fields,
            final_fields=final_fields,
            private_methods=private_methods,
            constructor_is_private=len(private_fields) > 0,
        )

    for fn_decl in ctx.module_ast.functions:
        if fn_decl.is_extern and fn_decl.body is not None:
            raise TypeCheckError("Extern function must not have a body", fn_decl.span)
        if not fn_decl.is_extern and fn_decl.body is None:
            raise TypeCheckError("Function declaration missing body", fn_decl.span)
        if fn_decl.name in ctx.functions or fn_decl.name in ctx.classes or fn_decl.name in ctx.interfaces:
            raise TypeCheckError(f"Duplicate declaration '{fn_decl.name}'", fn_decl.span)
        ctx.functions[fn_decl.name] = _function_sig_from_decl(ctx, fn_decl)


def validate_interface_conformance(ctx: TypeCheckContext) -> None:
    for class_decl in ctx.module_ast.classes:
        class_info = ctx.classes[class_decl.name]
        method_decls_by_name = {method_decl.name: method_decl for method_decl in class_decl.methods}

        for interface_ref in class_decl.implements:
            interface_type_name, interface_info, interface_owner_module = _resolve_implemented_interface(ctx, interface_ref)
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
