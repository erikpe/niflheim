from __future__ import annotations

from tests.compiler.backend.lowering.helpers import callable_by_name, lower_source_to_backend_program
from tests.compiler.backend.targets.x86_64_sysv.helpers import compile_and_run_source, emit_source_asm, make_target_input
from compiler.codegen.symbols import epilogue_label, mangle_function_symbol


def test_emit_source_asm_uses_phase3_ordered_block_labels_from_block_ids(tmp_path) -> None:
    source = """
    fn choose(flag: bool) -> i64 {
        var total: i64 = 0;
        if flag {
            total = 1;
        } else {
            total = 2;
        }
        return total;
    }

    fn main() -> i64 {
        return 0;
    }
    """
    target_input = make_target_input(lower_source_to_backend_program(tmp_path / "analysis", source, skip_optimize=True))
    choose_callable = callable_by_name(target_input.program, "choose")
    choose_label = mangle_function_symbol(("main",), "choose")
    expected_labels = [f".L{choose_label}_b{block.block_id.ordinal}:" for block in choose_callable.blocks]

    asm = emit_source_asm(tmp_path / "emit", source, skip_optimize=True)
    label_positions = [asm.index(label) for label in expected_labels]

    assert label_positions == sorted(label_positions)


def test_emit_source_asm_emits_branch_edges_and_single_epilogue(tmp_path) -> None:
    source = """
    fn choose(flag: bool) -> i64 {
        if flag {
            return 1;
        }
        return 2;
    }

    fn main() -> i64 {
        return 0;
    }
    """
    target_input = make_target_input(lower_source_to_backend_program(tmp_path / "analysis", source, skip_optimize=True))
    choose_callable = callable_by_name(target_input.program, "choose")
    choose_label = mangle_function_symbol(("main",), "choose")
    entry_block = choose_callable.blocks[0]
    branch = entry_block.terminator
    true_label = f".L{choose_label}_b{branch.true_block_id.ordinal}"
    false_label = f".L{choose_label}_b{branch.false_block_id.ordinal}"

    asm = emit_source_asm(tmp_path / "emit", source, skip_optimize=True)
    choose_body = asm[asm.index(f"{choose_label}:") : asm.index(f"{epilogue_label(choose_label)}:")]

    assert "    cmp rax, 0" in choose_body
    assert f"    je {false_label}" in choose_body
    assert f"    jmp {true_label}" in choose_body
    assert asm.count(f"{epilogue_label(choose_label)}:") == 1
    assert asm.count(f"    jmp {epilogue_label(choose_label)}") >= 2


def test_emit_source_asm_emits_loop_backedges_and_exit_edges(tmp_path) -> None:
    source = """
    fn loop(limit: i64) -> i64 {
        var total: i64 = 0;
        while total < limit {
            total = total + 1;
            if total == 2 {
                continue;
            }
            if total == 3 {
                break;
            }
        }
        return total;
    }

    fn main() -> i64 {
        return 0;
    }
    """
    target_input = make_target_input(lower_source_to_backend_program(tmp_path / "analysis", source, skip_optimize=True))
    loop_callable = callable_by_name(target_input.program, "loop")
    loop_label = mangle_function_symbol(("main",), "loop")
    cond_block = next(block for block in loop_callable.blocks if block.debug_name == "while.cond")
    exit_block = next(block for block in loop_callable.blocks if block.debug_name == "while.exit")
    continue_edge = next(block for block in loop_callable.blocks if block.debug_name == "continue.edge")
    backedge_block = next(block for block in loop_callable.blocks if block.debug_name == "while.continue")

    asm = emit_source_asm(tmp_path / "emit", source, skip_optimize=True)

    assert f"    je .L{loop_label}_b{exit_block.block_id.ordinal}" in asm
    assert f"    jmp .L{loop_label}_b{cond_block.block_id.ordinal}" in asm
    assert f".L{loop_label}_b{continue_edge.block_id.ordinal}:" in asm
    assert f".L{loop_label}_b{backedge_block.block_id.ordinal}:" in asm


def test_emit_source_asm_can_execute_branch_and_loop_program(tmp_path) -> None:
    run = compile_and_run_source(
        tmp_path,
        """
        fn main() -> i64 {
            var total: i64 = 0;
            while total < 6 {
                total = total + 1;
                if total == 2 {
                    continue;
                }
                if total == 4 {
                    return total;
                }
            }
            return total;
        }
        """,
        skip_optimize=True,
    )

    assert run.returncode == 4