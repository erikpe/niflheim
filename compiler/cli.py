from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import perf_counter

from compiler.common.logging import LOG_LEVEL_NAMES, configure_logging, get_logger, resolve_log_settings
from compiler.codegen.generator import emit_asm
from compiler.frontend.tokens import Token
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program, require_main_function
from compiler.semantic.lowering.executable import lower_linked_semantic_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.pipeline import optimize_semantic_program
from compiler.typecheck.api import typecheck_program


STOP_PHASES = ["check", "codegen"]


def _format_token(token: Token) -> str:
    start = token.span.start
    return f"{token.kind.name:<14} {token.lexeme!r:<18} {start.path}:{start.line}:{start.column}"


def _print_tokens(tokens: list[Token]) -> None:
    for token in tokens:
        print(_format_token(token))


def _resolve_program_graph(logger, input_path: Path, project_root: str | None):
    logger.info("Resolving program graph")
    start = perf_counter()
    program = resolve_program(input_path, project_root=project_root)
    duration_ms = (perf_counter() - start) * 1000.0
    logger.debugv(1, "Resolver resolved program in %.2f ms", duration_ms)
    return program


def _typecheck_program_phase(logger, program) -> None:
    logger.info("Type checking")
    start = perf_counter()
    typecheck_program(program)
    duration_ms = (perf_counter() - start) * 1000.0
    logger.debugv(1, "Type checked program in %.2f ms", duration_ms)


def _lower_program_phase(logger, program):
    logger.info("Lowering semantic program")
    start = perf_counter()
    lowered_program = lower_program(program)
    duration_ms = (perf_counter() - start) * 1000.0
    logger.debugv(1, "Lowered semantic program in %.2f ms", duration_ms)
    return lowered_program


def _optimize_program_phase(logger, lowered_program):
    logger.info("Optimizing semantic program")
    start = perf_counter()
    optimized_program = optimize_semantic_program(lowered_program)
    duration_ms = (perf_counter() - start) * 1000.0
    logger.debugv(1, "Optimized semantic program in %.2f ms", duration_ms)
    return optimized_program


def _link_program_phase(logger, optimized_program):
    logger.info("Linking semantic program")
    start = perf_counter()
    linked_program = link_semantic_program(optimized_program)
    duration_ms = (perf_counter() - start) * 1000.0
    logger.debugv(1, "Linked semantic program in %.2f ms", duration_ms)
    return linked_program


def _emit_assembly_phase(logger, linked_program, *, runtime_trace_enabled: bool) -> str:
    logger.info("Emitting assembly")
    start = perf_counter()
    lowered_linked_program = lower_linked_semantic_program(linked_program)
    asm = emit_asm(lowered_linked_program, runtime_trace_enabled=runtime_trace_enabled)
    duration_ms = (perf_counter() - start) * 1000.0
    logger.debugv(1, "Emitted %d assembly lines in %.2f ms", len(asm.splitlines()), duration_ms)
    return asm


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="nifc", description="Niflheim stage-0 compiler (default: type check and emit assembly)."
    )
    parser.add_argument("input", help="Input .nif source file")

    output_group = parser.add_argument_group("Output")
    output_group.add_argument("-o", "--output", help="Output assembly file path (default: stdout)")
    output_group.add_argument("--print-asm", action="store_true", help="Also print emitted assembly to stdout")

    logging_group = parser.add_argument_group("Logging")
    logging_group.add_argument(
        "--log-level", choices=LOG_LEVEL_NAMES, help="Minimum log severity to emit; defaults to warning when omitted"
    )
    logging_group.add_argument("-v", "--verbose", action="count", default=0, help="Increase log detail")
    logging_group.add_argument("-q", "--quiet", action="count", default=0, help="Reduce log detail")

    compilation_group = parser.add_argument_group("Compilation")
    compilation_group.add_argument(
        "--project-root", help="Project root for multi-module resolution (default: input file directory)"
    )
    compilation_group.add_argument(
        "--stop-after",
        choices=STOP_PHASES,
        default="codegen",
        help="Stop after a compiler phase instead of continuing to full codegen",
    )
    compilation_group.add_argument(
        "--omit-runtime-trace",
        action="store_true",
        help="Do not emit rt_trace_push/pop/set_location calls in generated assembly",
    )
    compilation_group.add_argument(
        "--skip-optimize",
        action="store_true",
        help="Skip semantic optimization and continue from lowered semantic IR",
    )

    args = parser.parse_args()
    log_settings = resolve_log_settings(args.log_level, args.verbose, args.quiet)
    configure_logging(log_settings)
    logger = get_logger(__name__)

    try:
        input_path = Path(args.input)

        program = _resolve_program_graph(logger, input_path, args.project_root)
        _typecheck_program_phase(logger, program)
        lowered_program = _lower_program_phase(logger, program)
        optimized_program = lowered_program if args.skip_optimize else _optimize_program_phase(logger, lowered_program)
        linked_program = _link_program_phase(logger, optimized_program)
        require_main_function(linked_program)
        if args.stop_after == "check":
            return 0

        asm = _emit_assembly_phase(logger, linked_program, runtime_trace_enabled=not args.omit_runtime_trace)
        if args.output:
            Path(args.output).write_text(asm, encoding="utf-8")
            logger.infov(1, "Wrote assembly to %s", args.output)
        if args.print_asm or not args.output:
            print(asm, end="" if asm.endswith("\n") else "\n")
        return 0
    except Exception as error:
        logger.error("%s", error)
        return 1
