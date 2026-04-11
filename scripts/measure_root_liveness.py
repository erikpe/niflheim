#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from compiler.codegen.measurement import analyze_assembly_metrics, extract_function_asm


SAMPLE_ROOT = REPO_ROOT / "samples" / "measurements" / "root_liveness"
BUILD_ROOT = REPO_ROOT / "build" / "measurements" / "root_liveness"


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
class KernelMeasurement:
    kernel: str
    source_path: str
    focus_symbol: str
    total_metrics: dict[str, int]
    focus_metrics: dict[str, int] | None
    binary_size_bytes: int
    runtime: dict[str, float | int] | None


KERNEL_SPECS: tuple[KernelSpec, ...] = (
    KernelSpec("array_iteration", SAMPLE_ROOT / "array_iteration.nif", "measure"),
    KernelSpec("casts_and_type_tests", SAMPLE_ROOT / "casts_and_type_tests.nif", "probe"),
    KernelSpec("interface_dispatch", SAMPLE_ROOT / "interface_dispatch.nif", "dispatch_loop"),
    KernelSpec("constructor_heavy", SAMPLE_ROOT / "constructor_heavy.nif", "constructor_loop"),
)


def _build_kernel(spec: KernelSpec) -> tuple[Path, Path]:
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    binary_path = BUILD_ROOT / spec.name
    asm_path = binary_path.with_suffix(".s")
    subprocess.run(
        [str(REPO_ROOT / "scripts" / "build.sh"), str(spec.source_path), str(binary_path)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return binary_path, asm_path


def _benchmark_binary(binary_path: Path, *, repeats: int) -> RuntimeMetrics:
    timings: list[float] = []
    subprocess.run([str(binary_path)], cwd=REPO_ROOT, check=True, capture_output=True, text=True)
    for _ in range(repeats):
        start = time.perf_counter()
        subprocess.run([str(binary_path)], cwd=REPO_ROOT, check=True, capture_output=True, text=True)
        timings.append(time.perf_counter() - start)
    return RuntimeMetrics(
        repeat_count=repeats,
        median_seconds=statistics.median(timings),
        mean_seconds=statistics.fmean(timings),
        min_seconds=min(timings),
        max_seconds=max(timings),
    )


def _measure_kernel(spec: KernelSpec, *, runtime_repeats: int, skip_runtime: bool) -> KernelMeasurement:
    binary_path, asm_path = _build_kernel(spec)
    asm_text = asm_path.read_text(encoding="utf-8")
    total_metrics = analyze_assembly_metrics(asm_text)
    focus_asm = extract_function_asm(asm_text, spec.focus_symbol)
    focus_metrics = None if focus_asm is None else analyze_assembly_metrics(focus_asm)
    runtime_metrics = None if skip_runtime else _benchmark_binary(binary_path, repeats=runtime_repeats)
    return KernelMeasurement(
        kernel=spec.name,
        source_path=str(spec.source_path.relative_to(REPO_ROOT)),
        focus_symbol=spec.focus_symbol,
        total_metrics=total_metrics.to_dict(),
        focus_metrics=None if focus_metrics is None else focus_metrics.to_dict(),
        binary_size_bytes=binary_path.stat().st_size,
        runtime=None if runtime_metrics is None else asdict(runtime_metrics),
    )


def _print_table(measurements: list[KernelMeasurement]) -> None:
    header = (
        "kernel",
        "focus",
        "asm_lines",
        "instr",
        "shadow_stack_helpers",
        "sync_blocks",
        "clear_blocks",
        "binary_bytes",
        "median_ms",
    )
    rows: list[tuple[str, ...]] = []
    for measurement in measurements:
        focus_metrics = measurement.focus_metrics or measurement.total_metrics
        runtime = measurement.runtime
        median_ms = "-" if runtime is None else f"{float(runtime['median_seconds']) * 1000.0:.3f}"
        rows.append(
            (
                measurement.kernel,
                measurement.focus_symbol,
                str(focus_metrics["line_count"]),
                str(focus_metrics["instruction_count"]),
                str(focus_metrics["shadow_stack_helper_call_count"]),
                str(focus_metrics["named_root_sync_block_count"]),
                str(focus_metrics["dead_named_root_clear_block_count"]),
                str(measurement.binary_size_bytes),
                median_ms,
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
    parser = argparse.ArgumentParser(description="Measure root-liveness-related codegen scaffolding and kernels")
    parser.add_argument(
        "--kernel",
        action="append",
        choices=[spec.name for spec in KERNEL_SPECS],
        help="Limit measurement to one or more named kernels",
    )
    parser.add_argument("--runtime-repeats", type=int, default=5, help="Number of timed runtime repeats per kernel")
    parser.add_argument("--skip-runtime", action="store_true", help="Only build and inspect assembly metrics")
    parser.add_argument("--json", action="store_true", help="Emit the full measurement payload as JSON")
    args = parser.parse_args()

    selected = [spec for spec in KERNEL_SPECS if args.kernel is None or spec.name in set(args.kernel)]
    measurements = [
        _measure_kernel(spec, runtime_repeats=args.runtime_repeats, skip_runtime=args.skip_runtime)
        for spec in selected
    ]

    report_path = BUILD_ROOT / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = [asdict(measurement) for measurement in measurements]
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_table(measurements)
        print(f"\nWrote JSON report to {report_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())