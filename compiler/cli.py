from __future__ import annotations

import argparse
import sys
from pathlib import Path

from compiler.ast_dump import ast_to_debug_json
from compiler.codegen import emit_asm
from compiler.lexer import Token, lex
from compiler.parser import parse
from compiler.resolver import resolve_program
from compiler.typecheck import typecheck, typecheck_program


STOP_PHASES = ["lex", "parse", "check", "codegen"]


def _format_token(token: Token) -> str:
    start = token.span.start
    return f"{token.kind.name:<14} {token.lexeme!r:<18} {start.path}:{start.line}:{start.column}"


def _print_tokens(tokens: list[Token]) -> None:
    for token in tokens:
        print(_format_token(token))


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
        if args.stop_after == "check":
            return 0

        if args.skip_check:
            codegen_module = module_ast
        else:
            codegen_module = program.modules[program.entry_module].ast

        asm = emit_asm(codegen_module)
        if args.output:
            Path(args.output).write_text(asm, encoding="utf-8")
        if args.print_asm or not args.output:
            print(asm, end="" if asm.endswith("\n") else "\n")
        return 0
    except Exception as error:
        print(f"nifc: {error}", file=sys.stderr)
        return 1
