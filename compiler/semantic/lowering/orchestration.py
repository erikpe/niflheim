from __future__ import annotations

from dataclasses import dataclass

from compiler.frontend.ast_nodes import *
from compiler.resolver import ModulePath, ProgramInfo
from compiler.semantic.ir import *
from compiler.semantic.lowering.type_refs import semantic_type_ref_from_checked_type
from compiler.semantic.symbols import *
from compiler.semantic.types import SemanticTypeRef
from compiler.typecheck.bodies import check_bodies
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.declarations import collect_module_declarations, validate_interface_conformance
from compiler.typecheck.model import ClassInfo, FunctionSig, TypeInfo
from compiler.typecheck.type_resolution import resolve_type_ref

from compiler.semantic.lowering.expressions import lower_expr
from compiler.semantic.lowering.ids import interface_id_for_type_name
from compiler.semantic.lowering.statements import lower_function_like_body


@dataclass
class ModuleLoweringContext:
    typecheck_ctx: TypeCheckContext
    symbol_index: ProgramSymbolIndex


def lower_program(program: ProgramInfo) -> SemanticProgram:
    symbol_index = build_program_symbol_index(program)
    module_contexts = build_typecheck_contexts(program)
    modules = {
        module_path: lower_module(program, module_path, module_contexts[module_path], symbol_index)
        for module_path in program.modules
    }
    return SemanticProgram(entry_module=program.entry_module, modules=modules)


def build_typecheck_contexts(program: ProgramInfo) -> dict[ModulePath, TypeCheckContext]:
    module_function_sigs: dict[ModulePath, dict[str, FunctionSig]] = {
        module_path: {} for module_path in program.modules
    }
    module_class_infos: dict[ModulePath, dict[str, ClassInfo]] = {module_path: {} for module_path in program.modules}
    module_interface_infos = {module_path: {} for module_path in program.modules}
    contexts: dict[ModulePath, TypeCheckContext] = {}

    for module_path, module_info in program.modules.items():
        contexts[module_path] = TypeCheckContext(
            module_ast=module_info.ast,
            module_path=module_path,
            modules=program.modules,
            module_function_sigs=module_function_sigs,
            module_class_infos=module_class_infos,
            module_interface_infos=module_interface_infos,
            functions=module_function_sigs[module_path],
            classes=module_class_infos[module_path],
            interfaces=module_interface_infos[module_path],
        )

    for ctx in contexts.values():
        collect_module_declarations(ctx)

    for ctx in contexts.values():
        validate_interface_conformance(ctx)

    for ctx in contexts.values():
        check_bodies(ctx)

    return contexts


def lower_module(
    program: ProgramInfo, module_path: ModulePath, typecheck_ctx: TypeCheckContext, symbol_index: ProgramSymbolIndex
) -> SemanticModule:
    module_info = program.modules[module_path]
    lower_ctx = ModuleLoweringContext(typecheck_ctx=typecheck_ctx, symbol_index=symbol_index)
    return SemanticModule(
        module_path=module_path,
        file_path=module_info.file_path,
        classes=[lower_class(lower_ctx, module_path, class_decl) for class_decl in module_info.ast.classes],
        functions=[
            lower_function(lower_ctx, module_path, function_decl) for function_decl in module_info.ast.functions
        ],
        span=module_info.ast.span,
        interfaces=[
            lower_interface(lower_ctx, module_path, interface_decl) for interface_decl in module_info.ast.interfaces
        ],
    )


def lower_interface(
    lower_ctx: ModuleLoweringContext, module_path: ModulePath, interface_decl: InterfaceDecl
) -> SemanticInterface:
    return SemanticInterface(
        interface_id=InterfaceId(module_path=module_path, name=interface_decl.name),
        is_export=interface_decl.is_export,
        methods=[
            lower_interface_method(lower_ctx, module_path, interface_decl, method_decl)
            for method_decl in interface_decl.methods
        ],
        span=interface_decl.span,
    )


def lower_interface_method(
    lower_ctx: ModuleLoweringContext,
    module_path: ModulePath,
    interface_decl: InterfaceDecl,
    method_decl: InterfaceMethodDecl,
) -> SemanticInterfaceMethod:
    return SemanticInterfaceMethod(
        method_id=InterfaceMethodId(module_path=module_path, interface_name=interface_decl.name, name=method_decl.name),
        params=[lower_param(lower_ctx.typecheck_ctx, param) for param in method_decl.params],
        return_type_name=resolved_type_name(lower_ctx.typecheck_ctx, method_decl.return_type),
        return_type_ref=resolved_semantic_type_ref(lower_ctx.typecheck_ctx, method_decl.return_type),
        span=method_decl.span,
    )


def lower_class(lower_ctx: ModuleLoweringContext, module_path: ModulePath, class_decl: ClassDecl) -> SemanticClass:
    return SemanticClass(
        class_id=class_id_for_decl(module_path, class_decl),
        is_export=class_decl.is_export,
        fields=[lower_field(lower_ctx, field_decl) for field_decl in class_decl.fields],
        methods=[lower_method(lower_ctx, module_path, class_decl, method_decl) for method_decl in class_decl.methods],
        span=class_decl.span,
        implemented_interfaces=[
            interface_id_for_type_name(module_path, resolved_type_name(lower_ctx.typecheck_ctx, interface_ref))
            for interface_ref in class_decl.implements
        ],
    )


def lower_field(lower_ctx: ModuleLoweringContext, field_decl) -> SemanticField:
    initializer = (
        None
        if field_decl.initializer is None
        else lower_expr(lower_ctx.typecheck_ctx, lower_ctx.symbol_index, field_decl.initializer)
    )
    return SemanticField(
        name=field_decl.name,
        type_name=resolved_type_name(lower_ctx.typecheck_ctx, field_decl.type_ref),
        type_ref=resolved_semantic_type_ref(lower_ctx.typecheck_ctx, field_decl.type_ref),
        initializer=initializer,
        is_private=field_decl.is_private,
        is_final=field_decl.is_final,
        span=field_decl.span,
    )


def lower_function(
    lower_ctx: ModuleLoweringContext, module_path: ModulePath, function_decl: FunctionDecl
) -> SemanticFunction:
    body: SemanticBlock | None = None
    local_info_by_id: dict[LocalId, SemanticLocalInfo] = {}
    if function_decl.body is not None:
        lowered_body = lower_function_like_body(
            lower_ctx.typecheck_ctx,
            owner_id=function_id_for_decl(module_path, function_decl),
            symbol_index=lower_ctx.symbol_index,
            params=function_decl.params,
            body=function_decl.body,
            receiver_type=None,
            owner_class_name=None,
        )
        body = lowered_body.body
        local_info_by_id = lowered_body.local_info_by_id

    return SemanticFunction(
        function_id=function_id_for_decl(module_path, function_decl),
        params=[lower_param(lower_ctx.typecheck_ctx, param) for param in function_decl.params],
        return_type_name=resolved_type_name(lower_ctx.typecheck_ctx, function_decl.return_type),
        return_type_ref=resolved_semantic_type_ref(lower_ctx.typecheck_ctx, function_decl.return_type),
        body=body,
        is_export=function_decl.is_export,
        is_extern=function_decl.is_extern,
        span=function_decl.span,
        local_info_by_id=local_info_by_id,
    )


def lower_method(
    lower_ctx: ModuleLoweringContext, module_path: ModulePath, class_decl: ClassDecl, method_decl: MethodDecl
) -> SemanticMethod:
    receiver_type = None
    if not method_decl.is_static:
        receiver_type = TypeInfo(name=class_decl.name, kind="reference")

    lowered_body = lower_function_like_body(
        lower_ctx.typecheck_ctx,
        owner_id=method_id_for_decl(module_path, class_decl, method_decl),
        symbol_index=lower_ctx.symbol_index,
        params=method_decl.params,
        body=method_decl.body,
        receiver_type=receiver_type,
        owner_class_name=class_decl.name,
    )
    return SemanticMethod(
        method_id=method_id_for_decl(module_path, class_decl, method_decl),
        params=[lower_param(lower_ctx.typecheck_ctx, param) for param in method_decl.params],
        return_type_name=resolved_type_name(lower_ctx.typecheck_ctx, method_decl.return_type),
        return_type_ref=resolved_semantic_type_ref(lower_ctx.typecheck_ctx, method_decl.return_type),
        body=lowered_body.body,
        is_static=method_decl.is_static,
        is_private=method_decl.is_private,
        span=method_decl.span,
        local_info_by_id=lowered_body.local_info_by_id,
    )


def lower_param(typecheck_ctx: TypeCheckContext, param: ParamDecl) -> SemanticParam:
    return SemanticParam(
        name=param.name,
        type_name=resolved_type_name(typecheck_ctx, param.type_ref),
        type_ref=resolved_semantic_type_ref(typecheck_ctx, param.type_ref),
        span=param.span,
    )


def resolved_type_name(typecheck_ctx: TypeCheckContext, type_ref) -> str:
    return resolve_type_ref(typecheck_ctx, type_ref).name


def resolved_semantic_type_ref(typecheck_ctx: TypeCheckContext, type_ref) -> SemanticTypeRef:
    return semantic_type_ref_from_checked_type(typecheck_ctx, resolve_type_ref(typecheck_ctx, type_ref))
