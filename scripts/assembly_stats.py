#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from compiler.backend.analysis import run_backend_ir_pipeline
from compiler.backend.lowering import lower_to_backend_ir
from compiler.backend.optimizations import DEFAULT_BACKEND_OPTIMIZATION_PASSES, optimize_backend_ir_program
from compiler.backend.targets import BackendTargetInput, BackendTargetOptions
from compiler.backend.targets.x86_64_sysv import emit_x86_64_sysv_asm
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program, require_main_function
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.pipeline import DEFAULT_SEMANTIC_OPTIMIZATION_PASSES, optimize_semantic_program
from compiler.typecheck.api import typecheck_program


_STACK_SLOT_RE = re.compile(r"\[rbp\s*[+-]\s*\d+\]")
_REGISTER_RE = re.compile(
    r"^(?:[re]?[abcd]x|[re]?[sd]i|[re]?[sb]p|"
    r"r(?:[0-9]+|1[0-5])[bwd]?|[abcd][lh]|[re]?ip|xmm\d+)$"
)
_COMMENT_PREFIXES = ("#", "//", ";")
_DIRECTIVE_PREFIX = "."
_CALLEE_SAVED_REGISTERS = frozenset({"rbx", "r12", "r13", "r14", "r15"})


@dataclass(frozen=True)
class AssemblyStats:
    line_count: int
    non_empty_line_count: int
    directive_count: int
    label_count: int
    comment_count: int
    instruction_count: int
    stack_memory_instruction_count: int
    stack_load_count: int
    stack_store_count: int
    register_copy_count: int
    callee_saved_save_count: int
    callee_saved_restore_count: int
    call_count: int
    jump_count: int
    conditional_jump_count: int
    compare_count: int
    setcc_count: int
    arithmetic_count: int
    lea_count: int
    push_pop_count: int
    root_helper_call_count: int
    safepoint_hook_count: int


@dataclass(frozen=True)
class AssemblyComparison:
    source_path: str
    project_root: str | None
    runtime_trace_enabled: bool
    optimized: bool
    without_register_allocation: AssemblyStats
    with_register_allocation: AssemblyStats
    delta: dict[str, int]


def _strip_inline_comment(text: str) -> str:
    for prefix in _COMMENT_PREFIXES:
        index = text.find(prefix)
        if index >= 0:
            return text[:index].rstrip()
    return text.rstrip()


def _is_register(operand: str) -> bool:
    normalized = operand.strip().lower()
    return _REGISTER_RE.fullmatch(normalized) is not None


def _split_operands(operand_text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in operand_text.split(",") if part.strip())


def _classify_instruction(line: str) -> tuple[str, tuple[str, ...]] | None:
    stripped = _strip_inline_comment(line.strip())
    if not stripped:
        return None
    parts = stripped.split(maxsplit=1)
    mnemonic = parts[0].lower()
    operands = _split_operands(parts[1]) if len(parts) == 2 else ()
    return mnemonic, operands


def analyze_assembly_stats(asm: str) -> AssemblyStats:
    lines = asm.splitlines()
    scanning_prologue_saves = False
    saw_stack_reserve = False
    scanning_epilogue_restores = False
    instruction_count = 0
    stack_memory_instruction_count = 0
    stack_load_count = 0
    stack_store_count = 0
    register_copy_count = 0
    callee_saved_save_count = 0
    callee_saved_restore_count = 0
    call_count = 0
    jump_count = 0
    conditional_jump_count = 0
    compare_count = 0
    setcc_count = 0
    arithmetic_count = 0
    lea_count = 0
    push_pop_count = 0
    root_helper_call_count = 0
    safepoint_hook_count = 0

    for raw_line in lines:
        if raw_line and not raw_line.startswith(" ") and raw_line.endswith(":"):
            scanning_prologue_saves = not raw_line.startswith(".")
            saw_stack_reserve = False
            scanning_epilogue_restores = raw_line.endswith("_epilogue:")

        classified = _classify_instruction(raw_line)
        if classified is None or not raw_line.startswith("    "):
            continue

        mnemonic, operands = classified
        instruction_count += 1
        has_stack_slot = any(_STACK_SLOT_RE.search(operand) for operand in operands)
        if has_stack_slot:
            stack_memory_instruction_count += 1
        if mnemonic == "mov" and len(operands) == 2:
            dest, src = operands
            dest_has_stack = _STACK_SLOT_RE.search(dest) is not None
            src_has_stack = _STACK_SLOT_RE.search(src) is not None
            if dest_has_stack and not src_has_stack:
                stack_store_count += 1
            if src_has_stack and not dest_has_stack:
                stack_load_count += 1
            if _is_register(dest) and _is_register(src) and dest.lower() != src.lower():
                register_copy_count += 1
            if (
                scanning_prologue_saves
                and saw_stack_reserve
                and dest_has_stack
                and src.lower() in _CALLEE_SAVED_REGISTERS
            ):
                callee_saved_save_count += 1
            if scanning_epilogue_restores and src_has_stack and dest.lower() in _CALLEE_SAVED_REGISTERS:
                callee_saved_restore_count += 1
        if scanning_prologue_saves:
            if mnemonic == "sub" and operands[:1] == ("rsp",):
                saw_stack_reserve = True
            elif saw_stack_reserve and not (
                mnemonic == "mov"
                and len(operands) == 2
                and _STACK_SLOT_RE.search(operands[0]) is not None
                and operands[1].lower() in _CALLEE_SAVED_REGISTERS
            ):
                scanning_prologue_saves = False
        if scanning_epilogue_restores and mnemonic == "mov" and operands == ("rsp", "rbp"):
            scanning_epilogue_restores = False
        if mnemonic == "call":
            call_count += 1
            if operands and (operands[0].startswith("rt_") or operands[0].startswith("__nif_rt_")):
                root_helper_call_count += int("root" in operands[0])
        if mnemonic == "jmp" or mnemonic.startswith("j"):
            jump_count += 1
            conditional_jump_count += int(mnemonic != "jmp")
        if mnemonic in {"cmp", "test"}:
            compare_count += 1
        if mnemonic.startswith("set"):
            setcc_count += 1
        if mnemonic in {
            "add",
            "sub",
            "imul",
            "mul",
            "idiv",
            "div",
            "inc",
            "dec",
            "neg",
            "and",
            "or",
            "xor",
            "shl",
            "shr",
            "sar",
        }:
            arithmetic_count += 1
        if mnemonic == "lea":
            lea_count += 1
        if mnemonic in {"push", "pop"}:
            push_pop_count += 1
        if "# runtime safepoint hook" in raw_line:
            safepoint_hook_count += 1

    return AssemblyStats(
        line_count=len(lines),
        non_empty_line_count=sum(1 for line in lines if line.strip()),
        directive_count=sum(
            1
            for line in lines
            if line.strip().startswith(_DIRECTIVE_PREFIX) and not line.strip().endswith(":")
        ),
        label_count=sum(1 for line in lines if line and not line.startswith(" ") and line.endswith(":")),
        comment_count=sum(1 for line in lines if line.strip().startswith(_COMMENT_PREFIXES)),
        instruction_count=instruction_count,
        stack_memory_instruction_count=stack_memory_instruction_count,
        stack_load_count=stack_load_count,
        stack_store_count=stack_store_count,
        register_copy_count=register_copy_count,
        callee_saved_save_count=callee_saved_save_count,
        callee_saved_restore_count=callee_saved_restore_count,
        call_count=call_count,
        jump_count=jump_count,
        conditional_jump_count=conditional_jump_count,
        compare_count=compare_count,
        setcc_count=setcc_count,
        arithmetic_count=arithmetic_count,
        lea_count=lea_count,
        push_pop_count=push_pop_count,
        root_helper_call_count=root_helper_call_count,
        safepoint_hook_count=safepoint_hook_count,
    )


def _compile_source_to_assembly(
    source_path: Path,
    *,
    project_root: Path | None,
    register_allocation_enabled: bool,
    runtime_trace_enabled: bool,
    optimized: bool,
) -> str:
    program = resolve_program(source_path, project_root=None if project_root is None else str(project_root))
    typecheck_program(program)
    semantic_program = lower_program(program)
    if optimized:
        semantic_program = optimize_semantic_program(semantic_program, passes=DEFAULT_SEMANTIC_OPTIMIZATION_PASSES)
    linked_program = link_semantic_program(semantic_program)
    require_main_function(linked_program)
    backend_program = lower_to_backend_ir(linked_program)
    if optimized:
        backend_program = optimize_backend_ir_program(backend_program, passes=DEFAULT_BACKEND_OPTIMIZATION_PASSES)
    pipeline_result = run_backend_ir_pipeline(backend_program)
    emit_result = emit_x86_64_sysv_asm(
        BackendTargetInput.from_pipeline_result(pipeline_result),
        options=BackendTargetOptions(
            runtime_trace_enabled=runtime_trace_enabled,
            register_allocation_enabled=register_allocation_enabled,
        ),
    )
    return emit_result.assembly_text


def compare_assembly_stats(
    source_path: Path,
    *,
    project_root: Path | None,
    runtime_trace_enabled: bool,
    optimized: bool,
) -> AssemblyComparison:
    without_ra = analyze_assembly_stats(
        _compile_source_to_assembly(
            source_path,
            project_root=project_root,
            register_allocation_enabled=False,
            runtime_trace_enabled=runtime_trace_enabled,
            optimized=optimized,
        )
    )
    with_ra = analyze_assembly_stats(
        _compile_source_to_assembly(
            source_path,
            project_root=project_root,
            register_allocation_enabled=True,
            runtime_trace_enabled=runtime_trace_enabled,
            optimized=optimized,
        )
    )
    without_dict = asdict(without_ra)
    with_dict = asdict(with_ra)
    delta = {key: with_dict[key] - without_dict[key] for key in without_dict}
    return AssemblyComparison(
        source_path=str(source_path),
        project_root=None if project_root is None else str(project_root),
        runtime_trace_enabled=runtime_trace_enabled,
        optimized=optimized,
        without_register_allocation=without_ra,
        with_register_allocation=with_ra,
        delta=delta,
    )


def _format_signed(value: int) -> str:
    return f"{value:+d}"


def _print_comparison(comparison: AssemblyComparison) -> None:
    without_dict = asdict(comparison.without_register_allocation)
    with_dict = asdict(comparison.with_register_allocation)
    rows = [
        (
            name,
            str(without_dict[name]),
            str(with_dict[name]),
            _format_signed(comparison.delta[name]),
        )
        for name in without_dict
    ]
    header = ("metric", "without_ra", "with_ra", "delta")
    widths = [len(part) for part in header]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def format_row(row: tuple[str, str, str, str]) -> str:
        return "  ".join(
            cell.rjust(widths[index]) if index > 0 else cell.ljust(widths[index])
            for index, cell in enumerate(row)
        )

    print(f"source: {comparison.source_path}")
    print(f"project_root: {comparison.project_root or '-'}")
    print(f"runtime_trace_enabled: {comparison.runtime_trace_enabled}")
    print(f"optimized: {comparison.optimized}")
    print()
    print(format_row(header))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print(format_row(row))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare x86_64_sysv assembly statistics with and without register allocation"
    )
    parser.add_argument("source", type=Path, help="Input .nif source file")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=REPO_ROOT,
        help="Project root for multi-module resolution (default: repository root)",
    )
    parser.add_argument(
        "--omit-runtime-trace",
        action="store_true",
        help="Match compiler --omit-runtime-trace by disabling runtime trace calls",
    )
    parser.add_argument(
        "--disable-all-optimization",
        action="store_true",
        help="Disable semantic and backend optimization before measuring",
    )
    parser.add_argument("--json", action="store_true", help="Print the comparison as JSON")
    args = parser.parse_args()

    comparison = compare_assembly_stats(
        args.source,
        project_root=args.project_root,
        runtime_trace_enabled=not args.omit_runtime_trace,
        optimized=not args.disable_all_optimization,
    )
    if args.json:
        print(json.dumps(asdict(comparison), indent=2))
    else:
        _print_comparison(comparison)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
