from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import run_cli, write


def test_cli_log_level_info_emits_phase_logs_to_stderr(tmp_path: Path, monkeypatch, capsys) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    rc = run_cli(monkeypatch, ["nifc", str(entry), "--log-level", "info", "-o", str(out_file)])
    captured = capsys.readouterr()

    assert rc == 0
    assert "nifc: info: Resolving program graph" in captured.err
    assert "nifc: info: Emitting assembly" in captured.err
    assert captured.out == ""


def test_cli_verbose_flag_promotes_default_log_level_to_info(tmp_path: Path, monkeypatch, capsys) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    rc = run_cli(monkeypatch, ["nifc", str(entry), "-v", "-o", str(out_file)])
    captured = capsys.readouterr()

    assert rc == 0
    assert "nifc: info: Resolving program graph" in captured.err


def test_cli_debug_logs_respect_verbosity_threshold(tmp_path: Path, monkeypatch, capsys) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        import util;

        fn main() -> i64 {
            return util.zero();
        }
        """,
    )
    write(
        tmp_path / "util.nif",
        """
        export fn zero() -> i64 {
            return 0;
        }
        """,
    )

    rc = run_cli(monkeypatch, ["nifc", str(entry), "--log-level", "debug", "-vv", "-o", str(out_file)])
    captured = capsys.readouterr()

    assert rc == 0
    assert "nifc: debug: Resolver loading module main from " in captured.err
    assert "nifc: debug: Resolver loading module util from " in captured.err
    assert "nifc: debug: Resolver resolved program in" in captured.err
    assert "nifc: debug: Resolver lexed " in captured.err
    assert " tokens from 2 files in " in captured.err
    assert "nifc: debug: Resolver parsed " in captured.err
    assert " tokens from 2 token streams in " in captured.err
    assert "nifc: debug: Type checked program in" in captured.err
    assert captured.err.count("nifc: debug: Optimization pass constant_fold performed ") == 2
    assert captured.err.count("nifc: debug: Optimization pass constant_fold completed in") == 2
    assert "nifc: debug: Optimization pass simplify_control_flow simplified " in captured.err
    assert "nifc: debug: Optimization pass simplify_control_flow completed in" in captured.err
    assert "nifc: debug: Optimization pass copy_propagation performed " in captured.err
    assert "nifc: debug: Optimization pass copy_propagation completed in" in captured.err
    assert "nifc: debug: Optimization pass prune_unreachable removed " in captured.err
    assert "nifc: debug: Optimization pass prune_unreachable completed in" in captured.err
    assert "nifc: debug: Emitted" in captured.err
    assert "nifc: info: Wrote assembly to" in captured.err


def test_cli_quiet_flag_suppresses_info_logs(tmp_path: Path, monkeypatch, capsys) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    rc = run_cli(monkeypatch, ["nifc", str(entry), "--log-level", "info", "-q", "-o", str(out_file)])
    captured = capsys.readouterr()

    assert rc == 0
    assert "nifc: info: Resolving program graph" in captured.err
    assert "nifc: info: Wrote assembly to" not in captured.err
