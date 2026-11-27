"""Pytest fixtures and rootdir marker for this package.

An empty conftest.py at tests/ is the canonical SciTeX
convention (audit-project PS208) — it pins the pytest
rootdir and gives downstream fixtures a home.

subprocess coverage is configured in pyproject.toml via coverage.py's subprocess patch; test collection must not install .pth files or overwrite caller-owned coverage environment variables.
"""
