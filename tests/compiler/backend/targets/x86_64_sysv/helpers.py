from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess

from compiler.backend.ir import (
    BACKEND_IR_SCHEMA_VERSION,
    BackendBlock,
    BackendBlockId,
    BackendCallableDecl,
    BackendProgram,
    BackendRegId,
    BackendRegister,
    BackendReturnTerminator,
    BackendSignature,
)
from compiler.backend.analysis.root_slots import BackendCallableRootSlots
from compiler.backend.analysis.pipeline import run_backend_ir_pipeline
from compiler.backend.targets import BackendTargetInput
from compiler.backend.targets import BackendTargetOptions
from compiler.backend.targets.x86_64_sysv import emit_x86_64_sysv_asm
from compiler.semantic.symbols import FunctionId
from compiler.semantic.types import semantic_primitive_type_ref
from tests.compiler.backend.ir.helpers import make_source_span
from tests.compiler.backend.lowering.helpers import lower_source_to_backend_program
from tests.compiler.integration.helpers import build_executable, run_executable


def make_target_input(program) -> BackendTargetInput:
    return BackendTargetInput.from_pipeline_result(run_backend_ir_pipeline(program))


def emit_program(program: BackendProgram, *, options: BackendTargetOptions | None = None) -> str:
    resolved_options = BackendTargetOptions() if options is None else options
    return emit_x86_64_sysv_asm(make_target_input(program), options=resolved_options).assembly_text


def emit_source_asm(
    tmp_path: Path,
    source: str,
    *,
    source_path: str = "main.nif",
    project_root: Path | None = None,
    disabled_passes: tuple[str, ...] = (),
    skip_optimize: bool = False,
    options: BackendTargetOptions | None = None,
) -> str:
    program = lower_source_to_backend_program(
        tmp_path,
        source,
        source_path=source_path,
        project_root=project_root,
        disabled_passes=disabled_passes,
        skip_optimize=skip_optimize,
    )
    return emit_program(program, options=options)


def compile_and_run_source(
    tmp_path: Path,
    source: str,
    *,
    source_path: str = "main.nif",
    project_root: Path | None = None,
    disabled_passes: tuple[str, ...] = (),
    skip_optimize: bool = False,
    options: BackendTargetOptions | None = None,
    asm_name: str = "backend_target_out.s",
) -> subprocess.CompletedProcess[str]:
    asm_text = emit_source_asm(
        tmp_path,
        source,
        source_path=source_path,
        project_root=project_root,
        disabled_passes=disabled_passes,
        skip_optimize=skip_optimize,
        options=options,
    )
    asm_path = tmp_path / asm_name
    asm_path.write_text(asm_text, encoding="utf-8")
    exe_path = build_executable(asm_path)
    return run_executable(exe_path)


def unit_function_backend_program(
    *,
    function_name: str = "main",
    module_path: tuple[str, ...] = ("fixture", "backend_target"),
    param_type_names: tuple[str, ...] = (),
    param_debug_names: tuple[str, ...] | None = None,
    is_export: bool = False,
) -> BackendProgram:
    param_names = param_debug_names if param_debug_names is not None else tuple(f"arg{index}" for index in range(len(param_type_names)))
    if len(param_names) != len(param_type_names):
        raise ValueError("Parameter debug names must match parameter type count")

    callable_id = FunctionId(module_path=module_path, name=function_name)
    block_id = BackendBlockId(owner_id=callable_id, ordinal=0)
    span = make_source_span(path=f"fixtures/{function_name}.nif")
    registers: list[BackendRegister] = []
    param_regs: list[BackendRegId] = []
    for ordinal, (param_name, type_name) in enumerate(zip(param_names, param_type_names, strict=True)):
        reg_id = BackendRegId(owner_id=callable_id, ordinal=ordinal)
        registers.append(
            BackendRegister(
                reg_id=reg_id,
                type_ref=semantic_primitive_type_ref(type_name),
                debug_name=param_name,
                origin_kind="param",
                semantic_local_id=None,
                span=span,
            )
        )
        param_regs.append(reg_id)

    callable_decl = BackendCallableDecl(
        callable_id=callable_id,
        kind="function",
        signature=BackendSignature(
            param_types=tuple(semantic_primitive_type_ref(type_name) for type_name in param_type_names),
            return_type=None,
        ),
        is_export=is_export,
        is_extern=False,
        is_static=None,
        is_private=None,
        registers=tuple(registers),
        param_regs=tuple(param_regs),
        receiver_reg=None,
        entry_block_id=block_id,
        blocks=(
            BackendBlock(
                block_id=block_id,
                debug_name="entry",
                instructions=(),
                terminator=BackendReturnTerminator(span=span, value=None),
                span=span,
            ),
        ),
        span=span,
    )
    return BackendProgram(
        schema_version=BACKEND_IR_SCHEMA_VERSION,
        entry_callable_id=callable_id,
        data_blobs=(),
        interfaces=(),
        classes=(),
        callables=(callable_decl,),
    )


def with_root_slot(target_input: BackendTargetInput, *, callable_id, reg_id, slot_index: int = 0) -> BackendTargetInput:
    callable_analysis = target_input.analysis_for_callable(callable_id)
    updated_analysis = replace(
        callable_analysis,
        root_slots=BackendCallableRootSlots(
            callable_decl=callable_analysis.root_slots.callable_decl,
            root_slot_by_reg={reg_id: slot_index},
            slot_reg_ids=((reg_id,),),
        ),
    )
    updated_analysis_by_callable_id = dict(target_input.analysis_by_callable_id)
    updated_analysis_by_callable_id[callable_id] = updated_analysis
    return replace(target_input, analysis_by_callable_id=updated_analysis_by_callable_id)