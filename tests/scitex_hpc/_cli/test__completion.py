"""Shell-completion install: drop-in file only, never an rc edit (scitex-dev#1127).

Every test runs the real CLI against a real temporary HOME; git work trees
are created with the real ``git`` binary.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from scitex_hpc._cli import cli

_RC_TEXT = "# user rc\nexport KEEP=1\n"


def _env(home: Path, **extra) -> dict:
    """An isolated environment: only HOME decides where files go."""
    env = {
        "HOME": str(home),
        "XDG_DATA_HOME": None,
        "XDG_CONFIG_HOME": None,
        "BASH_COMPLETION_USER_DIR": None,
    }
    env.update(extra)
    return env


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".bashrc").write_text(_RC_TEXT)
    (home / ".zshrc").write_text(_RC_TEXT)
    return home


def _install(home: Path, *args, **extra_env):
    return CliRunner().invoke(
        cli,
        ["install-shell-completion", "--yes", *args],
        env=_env(home, **extra_env),
    )


def _bash_dropin(home: Path) -> Path:
    return home / ".local/share/bash-completion/completions/scitex-hpc"


def _git_init(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_print_uses_current_click_without_running_path_executable(tmp_path, shell):
    # Arrange
    marker = tmp_path / "foreign-executable-ran"
    foreign = tmp_path / "scitex-hpc"
    foreign.write_text(
        f"#!/bin/sh\nprintf foreign > '{marker}'\nprintf FOREIGN_SCRIPT\n"
    )
    foreign.chmod(0o700)
    # Act
    result = CliRunner().invoke(
        cli, ["print-shell-completion", "--shell", shell], env={"PATH": str(tmp_path)}
    )
    # Assert
    assert (
        result.exit_code,
        "_SCITEX_HPC_COMPLETE" in result.stdout,
        "FOREIGN_SCRIPT" in result.stdout,
        marker.exists(),
    ) == (0, True, False, False)


def test_bash_install_writes_dropin_and_leaves_rc_untouched(tmp_path):
    # Arrange
    home = _home(tmp_path)
    # Act
    result = _install(home)
    # Assert
    assert (
        result.exit_code,
        "_SCITEX_HPC_COMPLETE=bash_complete" in _bash_dropin(home).read_text(),
        (home / ".bashrc").read_bytes(),
        sorted(p.name for p in home.iterdir()),
    ) == (0, True, _RC_TEXT.encode(), [".bashrc", ".local", ".zshrc"])


def test_second_install_is_a_no_op(tmp_path):
    # Arrange
    home = _home(tmp_path)
    _install(home)
    before = _bash_dropin(home).stat()
    # Act
    result = _install(home)
    after = _bash_dropin(home).stat()
    # Assert
    assert (
        result.exit_code,
        "Up to date" in result.stdout,
        (before.st_ino, before.st_mtime_ns),
    ) == (0, True, (after.st_ino, after.st_mtime_ns))


def test_dry_run_writes_nothing(tmp_path):
    # Arrange
    home = _home(tmp_path)
    # Act
    result = _install(home, "--dry-run")
    # Assert
    assert (
        result.exit_code,
        str(_bash_dropin(home)) in result.stdout,
        (home / ".local").exists(),
    ) == (0, True, False)


def test_zsh_and_fish_dropins_honour_xdg_dirs(tmp_path):
    # Arrange
    home = _home(tmp_path)
    data, config = tmp_path / "data", tmp_path / "config"
    xdg = {"XDG_DATA_HOME": str(data), "XDG_CONFIG_HOME": str(config)}
    # Act
    zsh = _install(home, "--shell", "zsh", **xdg)
    fish = _install(home, "--shell", "fish", **xdg)
    # Assert
    assert (
        zsh.exit_code,
        fish.exit_code,
        (data / "zsh/site-functions/_scitex-hpc").read_text().startswith("#compdef"),
        (config / "fish/completions/scitex-hpc.fish").is_file(),
        (home / ".zshrc").read_text(),
    ) == (0, 0, True, True, _RC_TEXT)


def test_bash_completion_user_dir_is_honoured(tmp_path):
    # Arrange
    home = _home(tmp_path)
    user_dir = tmp_path / "bc-user"
    # Act
    result = _install(home, BASH_COMPLETION_USER_DIR=f"{user_dir}:/elsewhere")
    # Assert
    assert (result.exit_code, (user_dir / "completions/scitex-hpc").is_file()) == (
        0,
        True,
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="requires real git")
def test_refuses_when_completion_dir_links_into_a_git_work_tree(tmp_path):
    # Arrange — a dotfiles checkout manages ~/.local/share/bash-completion
    home = _home(tmp_path)
    dotfiles = tmp_path / "dotfiles"
    _git_init(dotfiles)
    (dotfiles / "bash-completion").mkdir()
    (home / ".local/share").mkdir(parents=True)
    (home / ".local/share/bash-completion").symlink_to(dotfiles / "bash-completion")
    # Act
    result = _install(home)
    status = subprocess.run(
        ["git", "-C", str(dotfiles), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=True,
    )
    # Assert
    assert (
        result.exit_code,
        "git work tree" in result.output,
        status.stdout,
    ) == (1, True, "")


@pytest.mark.skipif(shutil.which("git") is None, reason="requires real git")
def test_refuses_to_replace_a_symlink_into_a_git_work_tree(tmp_path):
    # Arrange — the drop-in slot itself is a dotfiles-managed symlink
    home = _home(tmp_path)
    dotfiles = tmp_path / "dotfiles"
    _git_init(dotfiles)
    managed = dotfiles / "scitex-hpc.bash"
    managed.write_text("# managed by dotfiles\n")
    _bash_dropin(home).parent.mkdir(parents=True)
    _bash_dropin(home).symlink_to(managed)
    # Act
    result = _install(home)
    # Assert
    assert (
        result.exit_code,
        _bash_dropin(home).is_symlink(),
        managed.read_text(),
    ) == (1, True, "# managed by dotfiles\n")


def test_legacy_rc_line_is_reported_but_not_edited(tmp_path):
    # Arrange — the exact line the pre-fix installer appended
    home = _home(tmp_path)
    legacy = (
        'eval "$(_SCITEX_HPC_COMPLETE=bash_source scitex-hpc)"  '
        "# scitex-hpc tab completion"
    )
    rc_text = _RC_TEXT + "\n" + legacy + "\n"
    (home / ".bashrc").write_text(rc_text)
    # Act
    result = _install(home)
    # Assert
    assert (
        result.exit_code,
        legacy in result.output,
        (home / ".bashrc").read_text(),
    ) == (0, True, rc_text)


@pytest.mark.skipif(shutil.which("bash") is None, reason="requires real Bash")
def test_installed_dropin_can_be_sourced_by_bash(tmp_path):
    # Arrange
    home = tmp_path / "owned home's dir"
    home.mkdir()
    # Act
    install = _install(home)
    loaded = subprocess.run(
        [
            shutil.which("bash"),
            "--noprofile",
            "--norc",
            "-c",
            'source "$1" && declare -F _scitex_hpc_completion',
            "owned-check",
            str(_bash_dropin(home)),
        ],
        env={"PATH": "/usr/bin:/bin", "HOME": str(home)},
        check=False,
        capture_output=True,
        text=True,
    )
    # Assert
    assert (install.exit_code, loaded.returncode, loaded.stdout.strip()) == (
        0,
        0,
        "_scitex_hpc_completion",
    )
