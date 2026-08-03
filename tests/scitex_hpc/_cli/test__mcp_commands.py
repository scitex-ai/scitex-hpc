"""Guards on the MCP install guidance and the extra-name contract.

PS-225 restricted extra NAMES to {all, dev, docs}, so the `mcp` extra was
removed and fastmcp folded into `all`.

The whole point of these tests is that pip does NOT fail on a removed extra.
Measured 2026-08-04 against this package:

    $ pip install '<checkout>[definitely-not-an-extra]'
    rc=0
    WARNING: scitex-hpc 0.9.0 does not provide the extra 'definitely-not-an-extra'
    ...package installed, extra silently absent

So installing the old extra now EXITS 0 and installs nothing. A user who runs it
believes it worked. The only thing between them and a silent broken install is
that our own messages tell the truth — which makes those strings load-bearing,
not cosmetic.

Deliberately NOT tested here: the `mcp doctor` FAILURE branch. Reaching it
requires fastmcp to be genuinely absent, and faking that with a patched import
would test the patch rather than production. The install commands below cover
the same guidance text on a path that runs for real.
"""

from __future__ import annotations

import pathlib
import tomllib

import pytest

from scitex_hpc._cli import main

#: Commands that print install guidance UNCONDITIONALLY.
#: `mcp doctor` is deliberately absent — it prints guidance only on its failure
#: branch, so including it would pass vacuously wherever fastmcp is installed
#: (as it is in CI).
INSTALL_COMMANDS = [
    ["mcp", "install"],
    ["mcp", "install", "--json"],
]

#: PS-225's permitted extra names.
ALLOWED_EXTRA_NAMES = {"all", "dev", "docs"}

PYPROJECT = pathlib.Path(__file__).parents[3] / "pyproject.toml"


def _extras() -> dict:
    return tomllib.loads(PYPROJECT.read_text())["project"]["optional-dependencies"]


def test_pyproject_is_where_this_test_thinks_it_is():
    # Arrange: guards every assertion below — a wrong path would make the
    # extras checks raise rather than pass, but say nothing useful.
    path = PYPROJECT
    # Act
    exists = path.is_file()
    # Assert
    assert exists, f"pyproject.toml not found at {path}"


def test_every_extra_name_is_permitted_by_ps225():
    # Arrange: the rule that removed `mcp`; re-adding any other name breaks it
    # again, and nothing else in this repo would notice.
    extras = _extras()
    # Act
    names = set(extras)
    # Assert
    assert names <= ALLOWED_EXTRA_NAMES


def test_fastmcp_is_still_reachable_through_an_extra():
    # Arrange: folding it away must not make it unreachable — nor core, since
    # it is imported lazily and a SLURM user need never carry it.
    extras = _extras()
    # Act
    all_deps = " ".join(extras["all"])
    # Assert
    assert "fastmcp" in all_deps


def test_fastmcp_is_not_a_core_dependency():
    # Arrange: it is optional BY DESIGN (lazy import, guarded call sites).
    data = tomllib.loads(PYPROJECT.read_text())
    # Act
    core = " ".join(data["project"]["dependencies"])
    # Assert
    assert "fastmcp" not in core


@pytest.mark.parametrize("argv", INSTALL_COMMANDS, ids=lambda a: " ".join(a))
def test_install_guidance_actually_produced_output(argv, capsys):
    # Arrange: guards the assertions below — a command printing nothing would
    # satisfy the negative one vacuously.
    main(list(argv))
    # Act
    out = capsys.readouterr().out
    # Assert
    assert len(out) > 100


@pytest.mark.parametrize("argv", INSTALL_COMMANDS, ids=lambda a: " ".join(a))
def test_install_guidance_names_the_all_extra(argv, capsys):
    # Arrange
    main(list(argv))
    # Act
    out = capsys.readouterr().out
    # Assert
    assert "scitex-hpc[all]" in out


@pytest.mark.parametrize("argv", INSTALL_COMMANDS, ids=lambda a: " ".join(a))
def test_install_guidance_warns_the_old_extra_fails_silently(argv, capsys):
    # Arrange: the danger is not that the old extra is gone — it is that pip
    # exits 0, so the user gets no signal unless we give them one.
    main(list(argv))
    # Act
    out = capsys.readouterr().out
    # Assert
    assert "installs nothing" in out
