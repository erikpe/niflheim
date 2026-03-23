from __future__ import annotations

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