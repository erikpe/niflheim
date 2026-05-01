from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.compiler.integration.helpers import repo_root, write


def test_build_script_forwards_compiler_cli_args(tmp_path: Path) -> None:
    if shutil.which("gcc") is None:
        pytest.skip("gcc not available")

    source = repo_root() / "samples" / "arithmetic_loop.nif"
    output = tmp_path / "main_program"

    proc = subprocess.run(
        [
            str(repo_root() / "scripts" / "build.sh"),
            str(source),
            str(output),
            "--log-level",
            "info",
        ],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert output.exists()
    assert output.with_suffix(".s").exists()
    assert "nifc: info: Resolving program graph" in proc.stderr


def test_build_script_rejects_missing_prebuilt_runtime_archive(tmp_path: Path) -> None:
    if shutil.which("gcc") is None:
        pytest.skip("gcc not available")

    source = repo_root() / "samples" / "arithmetic_loop.nif"
    output = tmp_path / "main_program"
    env = os.environ.copy()
    env["NIF_PREBUILT_RUNTIME"] = str(tmp_path / "missing_runtime.a")

    proc = subprocess.run(
        [
            str(repo_root() / "scripts" / "build.sh"),
            str(source),
            str(output),
        ],
        cwd=repo_root(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    assert "build.sh: prebuilt runtime archive not found" in proc.stderr


def test_run_script_supports_absolute_output_paths(tmp_path: Path) -> None:
    if shutil.which("gcc") is None:
        pytest.skip("gcc not available")

    source = repo_root() / "samples" / "arithmetic_loop.nif"
    output = tmp_path / "main_program"

    proc = subprocess.run(
        [
            str(repo_root() / "scripts" / "run.sh"),
            str(source),
            str(output),
        ],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 15, proc.stderr or proc.stdout
    assert output.exists()
    assert output.with_suffix(".s").exists()
    assert "RUN_EXIT:15" in proc.stdout


def test_build_runtime_script_writes_requested_archive_path(tmp_path: Path) -> None:
    if shutil.which("make") is None:
        pytest.skip("make not available")

    output_archive = tmp_path / "custom_runtime" / "libruntime.a"

    proc = subprocess.run(
        [
            str(repo_root() / "scripts" / "build_runtime.sh"),
            str(output_archive),
        ],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert output_archive.exists()
    assert f"Built runtime archive: {output_archive}" in proc.stdout