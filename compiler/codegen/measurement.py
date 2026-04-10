from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AssemblyMetrics:
    line_count: int
    instruction_count: int
    root_slot_store_call_count: int
    named_root_sync_block_count: int
    dead_named_root_clear_block_count: int
    safepoint_hook_count: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def analyze_assembly_metrics(asm: str) -> AssemblyMetrics:
    lines = asm.splitlines()
    return AssemblyMetrics(
        line_count=len(lines),
        instruction_count=sum(1 for line in lines if line.startswith("    ") and not line.startswith("    #")),
        root_slot_store_call_count=sum(1 for line in lines if "call rt_root_slot_store" in line),
        named_root_sync_block_count=sum(
            1 for line in lines if line.strip() == "# mirror named reference slots into shadow-stack slots"
        ),
        dead_named_root_clear_block_count=sum(
            1 for line in lines if line.strip() == "# clear dead named reference shadow-stack slots"
        ),
        safepoint_hook_count=sum(1 for line in lines if "# runtime safepoint hook" in line),
    )


def extract_function_asm(asm: str, symbol: str) -> str | None:
    lines = asm.splitlines()
    start_index: int | None = None
    start_label: str | None = None
    canonical_matches = [
        index
        for index, line in enumerate(lines)
        if line.startswith("__nif_fn_") and line.endswith(f"__{symbol}:")
    ]
    for index, line in enumerate(lines):
        if line == f"{symbol}:":
            start_index = index
            start_label = symbol
            break
    if start_index is None and len(canonical_matches) == 1:
        start_index = canonical_matches[0]
        start_label = lines[start_index][:-1]
    if start_index is None:
        return None
    if start_label is None:
        return None

    end_label = f".L{start_label}_epilogue:"
    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        if lines[index] == end_label:
            end_index = index
            break
    return "\n".join(lines[start_index:end_index]) + "\n"