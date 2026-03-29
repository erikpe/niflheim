#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from compiler.codegen.generator import emit_asm
from compiler.codegen.measurement import analyze_assembly_metrics, extract_function_asm
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowering.executable import lower_linked_semantic_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.pipeline import optimize_semantic_program


SAMPLE_ROOT = REPO_ROOT / "samples" / "measurements" / "collection_fast_paths"
BUILD_ROOT = REPO_ROOT / "build" / "measurements" / "collection_fast_paths"
RUNTIME_INCLUDE = REPO_ROOT / "runtime" / "include"
RUNTIME_SOURCES = (
    REPO_ROOT / "runtime" / "src" / "runtime.c",
    REPO_ROOT / "runtime" / "src" / "gc.c",
    REPO_ROOT / "runtime" / "src" / "gc_trace.c",
    REPO_ROOT / "runtime" / "src" / "gc_tracked_set.c",
    REPO_ROOT / "runtime" / "src" / "io.c",
    REPO_ROOT / "runtime" / "src" / "array.c",
    REPO_ROOT / "runtime" / "src" / "panic.c",
)


@dataclass(frozen=True)
class KernelSpec:
    name: str
    source_path: Path
    focus_symbol: str


@dataclass(frozen=True)
class RuntimeMetrics:
    repeat_count: int
    median_seconds: float
    mean_seconds: float
    min_seconds: float
    max_seconds: float


@dataclass(frozen=True)
class VariantMeasurement:
    focus_metrics: dict[str, int] | None
    total_metrics: dict[str, int]
    array_len_call_count: int
    array_get_call_count: int
    array_set_call_count: int
    binary_size_bytes: int
    runtime: dict[str, float | int] | None


@dataclass(frozen=True)
class KernelMeasurement:
    kernel: str
    source_path: str
    focus_symbol: str
    fast: VariantMeasurement
    fallback: VariantMeasurement


KERNEL_SPECS: tuple[KernelSpec, ...] = (
    KernelSpec("len_hot_loop", SAMPLE_ROOT / "len_hot_loop.nif", "measure"),
    KernelSpec("index_reads_i64", SAMPLE_ROOT / "index_reads_i64.nif", "measure"),
    KernelSpec("index_writes_i64", SAMPLE_ROOT / "index_writes_i64.nif", "measure"),
    KernelSpec("index_writes_ref", SAMPLE_ROOT / "index_writes_ref.nif", "measure"),
    KernelSpec("index_writes_ref_pure", SAMPLE_ROOT / "index_writes_ref_pure.nif", "measure"),
    KernelSpec("for_in_i64", SAMPLE_ROOT / "for_in_i64.nif", "measure"),
    KernelSpec("for_in_ref", SAMPLE_ROOT / "for_in_ref.nif", "measure"),
)


def _require_cc() -> str:
    cc = shutil.which("cc")
    if cc is None:
        raise SystemExit("cc not available")
    return cc


def _emit_kernel_asm(source_path: Path, *, collection_fast_paths_enabled: bool) -> str:
    program = resolve_program(source_path, project_root=REPO_ROOT)
    linked_program = link_semantic_program(optimize_semantic_program(lower_program(program)))
    lowered_program = lower_linked_semantic_program(linked_program)
    return emit_asm(lowered_program, collection_fast_paths_enabled=collection_fast_paths_enabled)


def _build_variant(spec: KernelSpec, *, collection_fast_paths_enabled: bool) -> tuple[Path, Path, str]:
    variant_name = "fast" if collection_fast_paths_enabled else "fallback"
    variant_root = BUILD_ROOT / variant_name
    variant_root.mkdir(parents=True, exist_ok=True)
    binary_path = variant_root / spec.name
    asm_path = binary_path.with_suffix(".s")
    asm_text = _emit_kernel_asm(spec.source_path, collection_fast_paths_enabled=collection_fast_paths_enabled)
    asm_path.write_text(asm_text, encoding="utf-8")

    subprocess.run(
        [
            _require_cc(),
            "-std=c11",
            "-I",
            str(RUNTIME_INCLUDE),
            *(str(source_path) for source_path in RUNTIME_SOURCES),
            str(asm_path),
            "-o",
            str(binary_path),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return binary_path, asm_path, asm_text


def _count_lines_with_prefix(asm: str, prefix: str) -> int:
    return sum(1 for line in asm.splitlines() if prefix in line)


def _benchmark_binary(binary_path: Path, *, repeats: int) -> RuntimeMetrics:
    timings: list[float] = []
    warmup = subprocess.run([str(binary_path)], cwd=REPO_ROOT, check=False, capture_output=True, text=True)
    if warmup.returncode != 0:
        raise RuntimeError(f"benchmark warmup failed for {binary_path}")
    for _ in range(repeats):
        start = time.perf_counter()
        run = subprocess.run([str(binary_path)], cwd=REPO_ROOT, check=False, capture_output=True, text=True)
        timings.append(time.perf_counter() - start)
        if run.returncode != 0:
            raise RuntimeError(f"benchmark run failed for {binary_path}")
    return RuntimeMetrics(
        repeat_count=repeats,
        median_seconds=statistics.median(timings),
        mean_seconds=statistics.fmean(timings),
        min_seconds=min(timings),
        max_seconds=max(timings),
    )


def _measure_variant(
    spec: KernelSpec,
    *,
    collection_fast_paths_enabled: bool,
    runtime_repeats: int,
    skip_runtime: bool,
) -> VariantMeasurement:
    binary_path, _asm_path, asm_text = _build_variant(spec, collection_fast_paths_enabled=collection_fast_paths_enabled)
    focus_asm = extract_function_asm(asm_text, spec.focus_symbol)
    focus_metrics = None if focus_asm is None else analyze_assembly_metrics(focus_asm)
    runtime_metrics = None if skip_runtime else _benchmark_binary(binary_path, repeats=runtime_repeats)
    focus_body = asm_text if focus_asm is None else focus_asm
    return VariantMeasurement(
        focus_metrics=None if focus_metrics is None else focus_metrics.to_dict(),
        total_metrics=analyze_assembly_metrics(asm_text).to_dict(),
        array_len_call_count=_count_lines_with_prefix(focus_body, "call rt_array_len"),
        array_get_call_count=_count_lines_with_prefix(focus_body, "call rt_array_get_"),
        array_set_call_count=_count_lines_with_prefix(focus_body, "call rt_array_set_"),
        binary_size_bytes=binary_path.stat().st_size,
        runtime=None if runtime_metrics is None else asdict(runtime_metrics),
    )


def _measure_kernel(spec: KernelSpec, *, runtime_repeats: int, skip_runtime: bool) -> KernelMeasurement:
    return KernelMeasurement(
        kernel=spec.name,
        source_path=str(spec.source_path.relative_to(REPO_ROOT)),
        focus_symbol=spec.focus_symbol,
        fast=_measure_variant(
            spec,
            collection_fast_paths_enabled=True,
            runtime_repeats=runtime_repeats,
            skip_runtime=skip_runtime,
        ),
        fallback=_measure_variant(
            spec,
            collection_fast_paths_enabled=False,
            runtime_repeats=runtime_repeats,
            skip_runtime=skip_runtime,
        ),
    )


def _format_runtime_ms(runtime: dict[str, float | int] | None) -> str:
    if runtime is None:
        return "-"
    return f"{float(runtime['median_seconds']) * 1000.0:.3f}"


def _print_table(measurements: list[KernelMeasurement]) -> None:
    header = (
        "kernel",
        "fast_instr",
        "fallback_instr",
        "fast_len_calls",
        "fallback_len_calls",
        "fast_get_calls",
        "fallback_get_calls",
        "fast_set_calls",
        "fallback_set_calls",
        "fast_ms",
        "fallback_ms",
        "speedup",
    )
    rows: list[tuple[str, ...]] = []
    for measurement in measurements:
        fast_focus = measurement.fast.focus_metrics or measurement.fast.total_metrics
        fallback_focus = measurement.fallback.focus_metrics or measurement.fallback.total_metrics
        fast_runtime_ms = _format_runtime_ms(measurement.fast.runtime)
        fallback_runtime_ms = _format_runtime_ms(measurement.fallback.runtime)
        speedup = "-"
        if measurement.fast.runtime is not None and measurement.fallback.runtime is not None:
            fast_median = float(measurement.fast.runtime["median_seconds"])
            fallback_median = float(measurement.fallback.runtime["median_seconds"])
            if fast_median > 0.0:
                speedup = f"{fallback_median / fast_median:.2f}x"
        rows.append(
            (
                measurement.kernel,
                str(fast_focus["instruction_count"]),
                str(fallback_focus["instruction_count"]),
                str(measurement.fast.array_len_call_count),
                str(measurement.fallback.array_len_call_count),
                str(measurement.fast.array_get_call_count),
                str(measurement.fallback.array_get_call_count),
                str(measurement.fast.array_set_call_count),
                str(measurement.fallback.array_set_call_count),
                fast_runtime_ms,
                fallback_runtime_ms,
                speedup,
            )
        )

    widths = [len(column) for column in header]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def format_row(row: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row))

    print(format_row(header))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print(format_row(row))


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure collection fast-path codegen and runtime deltas")
    parser.add_argument(
        "--kernel",
        action="append",
        choices=[spec.name for spec in KERNEL_SPECS],
        help="Limit measurement to one or more named kernels",
    )
    parser.add_argument("--runtime-repeats", type=int, default=5, help="Timed runtime repeats per variant")
    parser.add_argument("--skip-runtime", action="store_true", help="Only build and inspect assembly metrics")
    parser.add_argument("--json", action="store_true", help="Emit the full measurement payload as JSON")
    args = parser.parse_args()

    selected_kernel_names = None if args.kernel is None else set(args.kernel)
    selected_specs = [
        spec for spec in KERNEL_SPECS if selected_kernel_names is None or spec.name in selected_kernel_names
    ]
    measurements = [
        _measure_kernel(spec, runtime_repeats=args.runtime_repeats, skip_runtime=args.skip_runtime)
        for spec in selected_specs
    ]

    report = [asdict(measurement) for measurement in measurements]
    report_path = BUILD_ROOT / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_table(measurements)
        print(f"\nWrote JSON report to {report_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())