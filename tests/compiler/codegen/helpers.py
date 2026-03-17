from __future__ import annotations

from compiler.ast_nodes import FunctionDecl, ModuleAst
from compiler.codegen.generator import emit_asm
from compiler.codegen.generator import CodeGenerator
from compiler.codegen.generator import emit_semantic_asm
from compiler.codegen.layout import build_layout
from compiler.codegen.model import EmitContext
from compiler.lexer import lex
from compiler.parser import parse
from compiler.resolver import resolve_program
from compiler.semantic_linker import build_semantic_codegen_program
from compiler.semantic_lowering import lower_program
from compiler.semantic_reachability import prune_unreachable_semantic


def parse_module(source: str, *, source_path: str = "examples/codegen.nif") -> ModuleAst:
    return parse(lex(source, source_path=source_path))


def emit_source_asm(source: str, *, source_path: str = "examples/codegen.nif") -> str:
    return emit_asm(parse_module(source, source_path=source_path))


def emit_semantic_source_asm(
    tmp_path,
    source: str,
    *,
    source_path: str = "main.nif",
    project_root=None,
) -> str:
    entry_path = tmp_path / source_path
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    entry_path.write_text(source.strip() + "\n", encoding="utf-8")
    root = tmp_path if project_root is None else project_root
    program = resolve_program(entry_path, project_root=root)
    semantic_program = build_semantic_codegen_program(prune_unreachable_semantic(lower_program(program)))
    return emit_semantic_asm(semantic_program)


def build_generator(module_ast: ModuleAst, *, build_symbols: bool = True) -> CodeGenerator:
    generator = CodeGenerator(module_ast)
    if build_symbols:
        generator.build_symbol_tables()
    return generator


def select_function(module_ast: ModuleAst, function_name: str | None = None) -> FunctionDecl:
    if function_name is None:
        if not module_ast.functions:
            raise AssertionError("expected module to contain at least one function")
        return module_ast.functions[0]

    for fn in module_ast.functions:
        if fn.name == function_name:
            return fn

    raise AssertionError(f"expected module to contain function '{function_name}'")


def make_function_emit_context(
    source: str,
    *,
    source_path: str = "examples/codegen.nif",
    function_name: str | None = None,
    label_counter: list[int] | None = None,
    temp_root_depth: list[int] | None = None,
) -> tuple[ModuleAst, CodeGenerator, FunctionDecl, EmitContext]:
    module_ast = parse_module(source, source_path=source_path)
    generator = build_generator(module_ast)
    fn = select_function(module_ast, function_name)
    emit_context = EmitContext(
        layout=build_layout(fn),
        fn_name=fn.name,
        label_counter=[0] if label_counter is None else label_counter,
        method_labels=generator.method_labels,
        method_return_types=generator.method_return_types,
        method_is_static=generator.method_is_static,
        constructor_labels=generator.constructor_labels,
        function_return_types=generator.function_return_types,
        string_literal_labels=generator.string_literal_labels,
        class_field_type_names=generator.class_field_type_names,
        temp_root_depth=[0] if temp_root_depth is None else temp_root_depth,
    )
    return module_ast, generator, fn, emit_context
