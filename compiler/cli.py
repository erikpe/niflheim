from __future__ import annotations

import argparse
import sys
from pathlib import Path

from compiler.ast_dump import ast_to_debug_json
from compiler.ast_nodes import ModuleAst
from compiler.codegen import emit_asm
from compiler.lexer import Token, lex
from compiler.parser import parse
from compiler.reachability import prune_unreachable
from compiler.resolver import ProgramInfo, resolve_program
from compiler.typecheck import typecheck_program


STOP_PHASES = ["lex", "parse", "check", "codegen"]


def _format_token(token: Token) -> str:
    start = token.span.start
    return f"{token.kind.name:<14} {token.lexeme!r:<18} {start.path}:{start.line}:{start.column}"


def _print_tokens(tokens: list[Token]) -> None:
    for token in tokens:
        print(_format_token(token))


def _require_main_function(module_ast: ModuleAst) -> None:
    main_decl = next((fn for fn in module_ast.functions if fn.name == "main"), None)
    if main_decl is None:
        raise ValueError("Program entrypoint missing: expected 'fn main() -> i64'")
    if main_decl.is_extern or main_decl.body is None:
        raise ValueError("Invalid main signature: expected concrete definition 'fn main() -> i64'")
    if main_decl.params:
        raise ValueError("Invalid main signature: expected 'fn main() -> i64' (no parameters)")
    if main_decl.return_type.name != "i64":
        raise ValueError("Invalid main signature: expected return type 'i64'")


def _build_codegen_module(program: ProgramInfo) -> ModuleAst:
    entry_module = program.modules[program.entry_module]
    ordered_module_paths = [
        module_path
        for module_path in sorted(program.modules)
        if module_path != program.entry_module
    ]
    ordered_module_paths.append(program.entry_module)

    merged_functions = []
    merged_classes = []
    function_index_by_name: dict[str, int] = {}
    function_has_body: dict[str, bool] = {}
    function_owner_by_name: dict[str, tuple[str, ...]] = {}
    class_owner_by_name: dict[str, tuple[str, ...]] = {}

    for module_path in ordered_module_paths:
        module_info = program.modules[module_path]
        for class_decl in module_info.ast.classes:
            existing_owner = class_owner_by_name.get(class_decl.name)
            if existing_owner is not None:
                first_owner = ".".join(existing_owner)
                current_owner = ".".join(module_path)
                raise ValueError(
                    f"Duplicate class symbol '{class_decl.name}' across modules ({first_owner}, {current_owner})"
                )

            class_owner_by_name[class_decl.name] = module_path
            merged_classes.append(class_decl)

        for fn_decl in module_info.ast.functions:
            existing_index = function_index_by_name.get(fn_decl.name)
            has_body = fn_decl.body is not None

            if existing_index is None:
                function_index_by_name[fn_decl.name] = len(merged_functions)
                function_has_body[fn_decl.name] = has_body
                function_owner_by_name[fn_decl.name] = module_path
                merged_functions.append(fn_decl)
                continue

            if function_has_body[fn_decl.name] and has_body:
                first_owner = ".".join(function_owner_by_name[fn_decl.name])
                current_owner = ".".join(module_path)
                raise ValueError(
                    f"Duplicate function symbol '{fn_decl.name}' across modules ({first_owner}, {current_owner})"
                )

            if not function_has_body[fn_decl.name] and has_body:
                merged_functions[existing_index] = fn_decl
                function_has_body[fn_decl.name] = True
                function_owner_by_name[fn_decl.name] = module_path

    return ModuleAst(
        imports=entry_module.ast.imports,
        classes=merged_classes,
        functions=merged_functions,
        span=entry_module.ast.span,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="nifc",
        description="Niflheim stage-0 compiler (default: emit assembly).",
    )
    parser.add_argument("input", help="Input .nif source file")
    parser.add_argument("-o", "--output", help="Output assembly file path (default: stdout)")
    parser.add_argument("--project-root", help="Project root for multi-module resolution (default: input file directory)")
    parser.add_argument(
        "--stop-after",
        choices=STOP_PHASES,
        default="codegen",
        help="Stop after a compiler phase for debugging",
    )
    parser.add_argument("--skip-check", action="store_true", help="Skip type checking")
    parser.add_argument("--print-tokens", action="store_true", help="Print tokens after lexing")
    parser.add_argument("--print-ast", action="store_true", help="Print parsed AST as JSON")
    parser.add_argument("--print-ast-spans", action="store_true", help="Include spans in --print-ast output")
    parser.add_argument("--print-asm", action="store_true", help="Also print emitted assembly to stdout")
    args = parser.parse_args()

    try:
        input_path = Path(args.input)
        source = input_path.read_text(encoding="utf-8")

        tokens = lex(source, source_path=str(input_path))
        if args.print_tokens:
            _print_tokens(tokens)
        if args.stop_after == "lex":
            return 0

        module_ast = parse(tokens)
        if args.print_ast:
            print(ast_to_debug_json(module_ast, include_spans=args.print_ast_spans))
        if args.stop_after == "parse":
            return 0

        if not args.skip_check:
            program = resolve_program(input_path, project_root=args.project_root)
            typecheck_program(program)
            program = prune_unreachable(program)
            codegen_module = _build_codegen_module(program)
        if args.stop_after == "check":
            return 0

        if args.skip_check:
            codegen_module = module_ast

        _require_main_function(codegen_module)

        asm = emit_asm(codegen_module)
        if args.output:
            Path(args.output).write_text(asm, encoding="utf-8")
        if args.print_asm or not args.output:
            print(asm, end="" if asm.endswith("\n") else "\n")
        return 0
    except Exception as error:
        print(f"nifc: {error}", file=sys.stderr)
        return 1
