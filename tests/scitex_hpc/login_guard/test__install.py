"""Tests for the Spartan login-node guard text + bashrc-insertion logic."""

from __future__ import annotations

import pytest

from scitex_hpc.login_guard import (
    REMOTE_GUARD_PATH,
    build_bashrc,
    build_install_script,
    guard_text,
)

# The TeX toolchain the guard must override (the incident vector).
TEX_TOOLS = (
    "xelatex",
    "pdflatex",
    "lualatex",
    "latex",
    "latexmk",
    "biber",
    "bibtex",
    "makeindex",
    "dvipdfmx",
    "xdvipdfmx",
    "dvips",
    "ps2pdf",
    "tex",
)

_INTERACTIVE_RETURN = "[[ $- != *i* ]] && return"
_ANCHOR = "000_spartan_noninteractive_libs.src"


# --------------------------------------------------------------------------
# Guard text
# --------------------------------------------------------------------------
def test_guard_has_slurm_job_id_escape():
    # Arrange
    guard = guard_text()
    # Act
    has_escape = "SLURM_JOB_ID" in guard
    # Assert — inside a SLURM allocation the real binary must run (no-op).
    assert has_escape


def test_guard_matches_spartan_login_host():
    # Arrange
    guard = guard_text()
    # Act
    matches = "spartan-login*" in guard
    # Assert — refuses only on login/gateway hosts.
    assert matches


@pytest.mark.parametrize("tool", TEX_TOOLS)
def test_guard_defines_tex_tool(tool):
    # Arrange
    guard = guard_text()
    # Act
    present = tool in guard
    # Assert — each TeX tool is on the override loop list.
    assert present


def test_guard_provides_spartan_tex_helper():
    # Arrange
    guard = guard_text()
    # Act
    has_helper = "spartan-tex()" in guard
    # Assert — the srun-wrapping convenience helper exists.
    assert has_helper


def test_guard_wraps_helper_in_srun():
    # Arrange
    guard = guard_text()
    # Act
    has_srun = "srun" in guard
    # Assert — the helper sends the compile to a compute node.
    assert has_srun


def test_guard_defines_guard_function():
    # Arrange
    guard = guard_text()
    # Act
    has_fn = "_spartan_login_guard()" in guard
    # Assert — functions beat both PATH and ``module load``.
    assert has_fn


def test_guard_exports_functions():
    # Arrange
    guard = guard_text()
    # Act
    exported = "export -f" in guard
    # Assert — exported so non-interactive subshells inherit the override.
    assert exported


# --------------------------------------------------------------------------
# ~/.bashrc insertion transform
# --------------------------------------------------------------------------
def test_bashrc_insert_before_interactive_return_when_no_anchor():
    # Arrange — a bashrc with the interactive-return guard but no anchor.
    bashrc = "export FOO=1\n" f"{_INTERACTIVE_RETURN}\n" "alias ll='ls -l'\n"
    # Act
    out = build_bashrc(bashrc)
    # Assert — the source line lands BEFORE the interactive-return marker
    # so non-interactive ``ssh host '<cmd>'`` is covered too.
    assert out.index(REMOTE_GUARD_PATH) < out.index(_INTERACTIVE_RETURN)


def test_bashrc_insert_after_spartan_anchor_when_present():
    # Arrange — replicate the live deployment anchor.
    bashrc = (
        "export FOO=1\n"
        f"source ~/.config/{_ANCHOR}\n"
        f"{_INTERACTIVE_RETURN}\n"
    )
    # Act
    out = build_bashrc(bashrc)
    # Assert — block sits right AFTER the anchor line, still before return.
    assert out.index(_ANCHOR) < out.index(REMOTE_GUARD_PATH) < out.index(
        _INTERACTIVE_RETURN
    )


def test_bashrc_insert_at_top_when_no_anchor_and_no_return():
    # Arrange — a bare bashrc.
    bashrc = "export FOO=1\nexport BAR=2\n"
    # Act
    out = build_bashrc(bashrc)
    # Assert — block is prepended above the original first line.
    assert out.index(REMOTE_GUARD_PATH) < out.index("export FOO=1")


def test_bashrc_insertion_is_idempotent():
    # Arrange
    bashrc = "export FOO=1\n" f"{_INTERACTIVE_RETURN}\n"
    once = build_bashrc(bashrc)
    # Act — apply a second time.
    twice = build_bashrc(once)
    # Assert — re-running never duplicates the source line.
    assert once == twice


def test_bashrc_insertion_inserts_single_guard_block():
    # Arrange
    bashrc = "export FOO=1\n" f"{_INTERACTIVE_RETURN}\n"
    # Act
    out = build_bashrc(build_bashrc(bashrc))
    # Assert — exactly one guard block even after re-applying.
    assert out.count("# >>> scitex-hpc login-node guard >>>") == 1


def test_bashrc_insertion_preserves_existing_lines():
    # Arrange
    bashrc = "export FOO=1\n" f"{_INTERACTIVE_RETURN}\n" "alias g=git\n"
    # Act
    out = build_bashrc(bashrc)
    # Assert — original content is not dropped.
    assert "alias g=git" in out


# --------------------------------------------------------------------------
# Remote install script
# --------------------------------------------------------------------------
def test_install_script_targets_remote_guard_path():
    # Arrange
    script = build_install_script()
    # Act
    present = REMOTE_GUARD_PATH in script
    # Assert
    assert present


def test_install_script_makes_guard_executable():
    # Arrange
    script = build_install_script()
    # Act
    present = "chmod +x" in script
    # Assert
    assert present


def test_install_script_backs_up_bashrc():
    # Arrange
    script = build_install_script()
    # Act
    present = "cp -p" in script
    # Assert — ~/.bashrc is backed up before any edit.
    assert present


def test_install_script_validates_before_replacing():
    # Arrange
    script = build_install_script()
    # Act
    present = "bash -n" in script
    # Assert — never install a syntactically broken ~/.bashrc.
    assert present


def test_install_script_embeds_guard_verbatim():
    # Arrange
    script = build_install_script()
    # Act
    present = "_spartan_login_guard()" in script
    # Assert — the vendored guard body is spliced in.
    assert present
