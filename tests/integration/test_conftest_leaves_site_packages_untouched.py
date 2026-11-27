"""Conftest must not touch site-packages or caller coverage env vars."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

CONFTEST_PATH = Path(__file__).resolve().parents[1] / "conftest.py"


def test_conftest_leaves_site_packages_untouched() -> None:
    # Arrange
    child = textwrap.dedent(
        """\
        import os
        import runpy
        import site
        from pathlib import Path

        os.environ["COVERAGE_PROCESS_START"] = "SENTINEL_PROCESS_START"
        os.environ["COVERAGE_FILE"] = "SENTINEL_FILE"


        def _snapshot():
            names = {}
            try:
                dirs = list(site.getsitepackages())
            except Exception:
                dirs = []
            try:
                dirs.append(site.getusersitepackages())
            except Exception:
                pass
            for d in dirs:
                try:
                    names[str(d)] = sorted(p.name for p in Path(d).iterdir())
                except OSError:
                    names[str(d)] = None
            return names


        _before = _snapshot()
        runpy.run_path(%r, run_name="__conftest__")
        _after = _snapshot()
        assert _before == _after, "conftest.py changed site-packages contents"
        assert os.environ["COVERAGE_PROCESS_START"] == "SENTINEL_PROCESS_START"
        assert os.environ["COVERAGE_FILE"] == "SENTINEL_FILE"
        """
        % (str(CONFTEST_PATH),)
    )

    # Act
    proc = subprocess.run(
        [sys.executable, "-c", child], capture_output=True, text=True
    )

    # Assert
    assert proc.returncode == 0, proc.stderr + proc.stdout
