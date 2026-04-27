from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import perf_counter

from compiler.backend.analysis import run_backend_ir_pipeline
from compiler.backend.ir.serialize import dump_backend_program_json
from compiler.backend.ir.text import dump_backend_program_text
from compiler.backend.lowering import lower_to_backend_ir
from compiler.backend.targets import BackendTargetInput, BackendTargetOptions
from compiler.backend.targets.x86_64_sysv import emit_x86_64_sysv_asm
from compiler.common.logging import LOG_LEVEL_NAMES, configure_logging, get_logger, resolve_log_settings
from compiler.codegen.generator import emit_asm
from compiler.frontend.tokens import Token
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program, require_main_function
from compiler.semantic.lowering.executable import lower_linked_semantic_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.pipeline import optimize_semantic_program
from compiler.typecheck.api import typecheck_program


BACKEND_IR_DUMP_FORMATS = ["text", "json"]
BACKEND_IR_STOP_PHASES = frozenset({"backend-ir", "backend-ir-passes"})
STOP_PHASES = ["check", *sorted(BACKEND_IR_STOP_PHASES), "codegen"]
EXPERIMENTAL_BACKEND_BACKEND_IR_X86_64_SYSV = "backend-ir-x86_64_sysv"
EXPERIMENTAL_BACKEND_CHOICES = [EXPERIMENTAL_BACKEND_BACKEND_IR_X86_64_SYSV]


def _requested_backend_ir_surface(args: argparse.Namespace) -> tuple[str, ...]:
    requested: list[str] = []
    if args.dump_backend_ir is not None:
        requested.append("--dump-backend-ir")
    if args.dump_backend_ir_dir is not None:
        requested.append("--dump-backend-ir-dir")
    if args.stop_after in BACKEND_IR_STOP_PHASES:
        requested.append(f"--stop-after {args.stop_after}")
    return tuple(requested)


def _requested_backend_ir_dump_format(args: argparse.Namespace) -> str | None:
    if args.dump_backend_ir is not None:
        return args.dump_backend_ir
    if args.dump_backend_ir_dir is not None or args.stop_after in BACKEND_IR_STOP_PHASES:
        return "text"
    return None


def _uses_backend_ir_surface(args: argparse.Namespace) -> bool:
    return bool(_requested_backend_ir_surface(args))


def _uses_experimental_backend(args: argparse.Namespace) -> bool:
    return args.experimental_backend is not None


def _validate_backend_ir_surface(args: argparse.Namespace) -> None:
    requested = _requested_backend_ir_surface(args)
    if not requested:
        return

    if args.stop_after not in BACKEND_IR_STOP_PHASES and args.dump_backend_ir is not None and args.dump_backend_ir_dir is None:
        raise ValueError(
            "Continuing past backend IR with --dump-backend-ir requires --dump-backend-ir-dir "
            "so backend IR output does not mix with assembly on stdout."
        )


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


def _emit_experimental_backend_assembly_phase(
    logger,
    linked_program,
    *,
    experimental_backend: str,
    runtime_trace_enabled: bool,
) -> str:
    if experimental_backend != EXPERIMENTAL_BACKEND_BACKEND_IR_X86_64_SYSV:
        raise ValueError(f"Unsupported experimental backend '{experimental_backend}'")

    logger.info("Emitting assembly via experimental backend %s", experimental_backend)
    start = perf_counter()
    pipeline_result = _run_backend_ir_passes_phase(logger, linked_program)
    emit_result = emit_x86_64_sysv_asm(
        BackendTargetInput.from_pipeline_result(pipeline_result),
        options=BackendTargetOptions(runtime_trace_enabled=runtime_trace_enabled),
    )
    duration_ms = (perf_counter() - start) * 1000.0
    for diagnostic in emit_result.diagnostics:
        logger.warning("%s", diagnostic)
    logger.debugv(1, "Emitted %d assembly lines in %.2f ms", len(emit_result.assembly_text.splitlines()), duration_ms)
    return emit_result.assembly_text


def _lower_backend_ir_phase(logger, linked_program):
    logger.info("Lowering backend IR")
    start = perf_counter()
    backend_program = lower_to_backend_ir(linked_program)
    duration_ms = (perf_counter() - start) * 1000.0
    logger.debugv(1, "Lowered and verified backend IR in %.2f ms", duration_ms)
    return backend_program


def _run_backend_ir_passes_phase(logger, linked_program):
    backend_program = _lower_backend_ir_phase(logger, linked_program)
    logger.info("Running backend IR passes")
    start = perf_counter()
    pipeline_result = run_backend_ir_pipeline(backend_program)
    duration_ms = (perf_counter() - start) * 1000.0
    logger.debugv(1, "Ran backend IR pass pipeline in %.2f ms", duration_ms)
    return pipeline_result


def _backend_ir_dump_project_root(input_path: Path, project_root: str | None) -> Path:
    return input_path.parent if project_root is None else Path(project_root)


def _render_backend_ir_dump(backend_program, *, dump_format: str, project_root: Path) -> str:
    return _render_backend_ir_dump_with_options(
        backend_program,
        dump_format=dump_format,
        project_root=project_root,
        preserve_block_order=False,
    )


def _render_backend_ir_dump_with_options(
    backend_program,
    *,
    dump_format: str,
    project_root: Path,
    preserve_block_order: bool,
) -> str:
    if dump_format == "text":
        return dump_backend_program_text(backend_program, preserve_block_order=preserve_block_order)
    if dump_format == "json":
        return dump_backend_program_json(
            backend_program,
            project_root=project_root,
            preserve_block_order=preserve_block_order,
        )
    raise ValueError(f"Unsupported backend IR dump format '{dump_format}'")


def _write_backend_ir_dump(
    backend_program,
    *,
    input_path: Path,
    dump_dir: str,
    dump_format: str,
    project_root: Path,
    preserve_block_order: bool = False,
) -> Path:
    output_dir = Path(dump_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".txt" if dump_format == "text" else ".json"
    dump_path = output_dir / f"{input_path.stem}.backend-ir{suffix}"
    dump_path.write_text(
        _render_backend_ir_dump_with_options(
            backend_program,
            dump_format=dump_format,
            project_root=project_root,
            preserve_block_order=preserve_block_order,
        ),
        encoding="utf-8",
    )
    return dump_path


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="nifc", description="Niflheim stage-0 compiler (default: type check and emit assembly)."
    )
    parser.add_argument("input", help="Input .nif source file")

    output_group = parser.add_argument_group("Output")
    output_group.add_argument("-o", "--output", help="Output assembly file path (default: stdout)")
    output_group.add_argument("--print-asm", action="store_true", help="Also print emitted assembly to stdout")
    output_group.add_argument(
        "--dump-backend-ir",
        choices=BACKEND_IR_DUMP_FORMATS,
        help="Dump verified backend IR in the selected format",
    )
    output_group.add_argument(
        "--dump-backend-ir-dir",
        metavar="DIR",
        help="Directory for deterministic whole-program backend IR dumps",
    )

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
    compilation_group.add_argument(
        "--experimental-backend",
        choices=EXPERIMENTAL_BACKEND_CHOICES,
        help="Use a non-default checked-path backend instead of the legacy semantic-lowering codegen path",
    )

    args = parser.parse_args()
    log_settings = resolve_log_settings(args.log_level, args.verbose, args.quiet)
    configure_logging(log_settings)
    logger = get_logger(__name__)

    try:
        _validate_backend_ir_surface(args)

        input_path = Path(args.input)

        program = _resolve_program_graph(logger, input_path, args.project_root)
        _typecheck_program_phase(logger, program)
        lowered_program = _lower_program_phase(logger, program)
        optimized_program = lowered_program if args.skip_optimize else _optimize_program_phase(logger, lowered_program)
        linked_program = _link_program_phase(logger, optimized_program)
        require_main_function(linked_program)
        if args.stop_after == "check":
            return 0

        if _uses_backend_ir_surface(args):
            if args.stop_after == "backend-ir-passes":
                pipeline_result = _run_backend_ir_passes_phase(logger, linked_program)
                backend_program = pipeline_result.program
            else:
                backend_program = _lower_backend_ir_phase(logger, linked_program)
            dump_format = _requested_backend_ir_dump_format(args)
            dump_project_root = _backend_ir_dump_project_root(input_path, args.project_root)
            preserve_block_order = args.stop_after == "backend-ir-passes"

            if dump_format is not None:
                if args.dump_backend_ir_dir is not None:
                    dump_path = _write_backend_ir_dump(
                        backend_program,
                        input_path=input_path,
                        dump_dir=args.dump_backend_ir_dir,
                        dump_format=dump_format,
                        project_root=dump_project_root,
                        preserve_block_order=preserve_block_order,
                    )
                    logger.infov(1, "Wrote backend IR to %s", dump_path)
                elif args.stop_after in BACKEND_IR_STOP_PHASES:
                    rendered = _render_backend_ir_dump_with_options(
                        backend_program,
                        dump_format=dump_format,
                        project_root=dump_project_root,
                        preserve_block_order=preserve_block_order,
                    )
                    print(rendered, end="" if rendered.endswith("\n") else "\n")

            if args.stop_after in BACKEND_IR_STOP_PHASES:
                return 0

        if _uses_experimental_backend(args):
            asm = _emit_experimental_backend_assembly_phase(
                logger,
                linked_program,
                experimental_backend=args.experimental_backend,
                runtime_trace_enabled=not args.omit_runtime_trace,
            )
        else:
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
