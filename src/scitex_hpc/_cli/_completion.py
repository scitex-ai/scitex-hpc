"""Shell-completion leaves: ``install-shell-completion`` + ``print-shell-completion``.

Inlined to avoid pulling ``scitex-dev`` into runtime deps. This is a minimal
copy of the install logic in ``scitex_dev._cli._completion`` (the reference
implementation, scitex-dev#1127); keep the two in step.

Install contract:

* It NEVER modifies a shell rc file (``~/.bashrc``, ``~/.zshrc``, ...). On many
  machines the rc file is a symlink into a version-controlled dotfiles
  checkout, so appending to it dirties a tracked file on every host. Earlier
  versions appended an ``eval "$(_SCITEX_HPC_COMPLETE=bash_source scitex-hpc)"``
  line.
* It writes one drop-in file at the location the shell's completion
  framework already scans::

    bash  ${BASH_COMPLETION_USER_DIR:-${XDG_DATA_HOME:-~/.local/share}/bash-completion}/completions/<prog>
    zsh   ${XDG_DATA_HOME:-~/.local/share}/zsh/site-functions/_<prog>
    fish  ${XDG_CONFIG_HOME:-~/.config}/fish/completions/<prog>.fish

* It is idempotent (an unchanged script is not rewritten) and atomic.
* It refuses to write when the target (or a directory on its way, resolved
  through symlinks) lies inside a git work tree.

The script is generated in-process with this interpreter's Click against the
registered group; no console program is executed from ``PATH``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

import click
from click.shell_completion import get_completion_class

SHELLS = ("bash", "zsh", "fish")


def _env_var(prog_name: str) -> str:
    """Click's autocompletion env var format: ``_<UPPER_PROG>_COMPLETE``."""
    return "_" + prog_name.upper().replace("-", "_") + "_COMPLETE"


def _legacy_marker(prog_name: str) -> str:
    """Trailing comment earlier versions appended to rc lines."""
    return f"# {prog_name} tab completion"


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def _xdg_data_home() -> Path:
    raw = os.environ.get("XDG_DATA_HOME")
    return Path(raw) if raw else _home() / ".local" / "share"


def _xdg_config_home() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME")
    return Path(raw) if raw else _home() / ".config"


def completion_dropin_path(shell: str, prog_name: str) -> Path:
    """Where ``install-shell-completion`` writes ``prog_name``'s script."""
    if shell == "bash":
        # bash-completion 2.x: BASH_COMPLETION_USER_DIR may list several
        # colon-separated roots; the first one is the user's primary.
        user_dirs = os.environ.get("BASH_COMPLETION_USER_DIR", "")
        first = user_dirs.split(":")[0] if user_dirs else ""
        root = Path(first) if first else _xdg_data_home() / "bash-completion"
        return root / "completions" / prog_name
    if shell == "zsh":
        return _xdg_data_home() / "zsh" / "site-functions" / f"_{prog_name}"
    if shell == "fish":
        return _xdg_config_home() / "fish" / "completions" / f"{prog_name}.fish"
    raise click.ClickException(f"Unsupported completion shell: {shell}.")


def generate_completion_script(
    shell: str, prog_name: str, command: click.Command
) -> str:
    """Generate with this interpreter's Click, without executing PATH entries."""
    completion_class = get_completion_class(shell)
    if completion_class is None:
        raise click.ClickException(f"Unsupported completion shell: {shell}.")
    script = (
        completion_class(command, {}, prog_name, _env_var(prog_name)).source().strip()
    )
    if not script:
        raise click.ClickException(
            f"Failed to generate {shell} completion script for {prog_name}."
        )
    return script + "\n"


def _enclosing_git_work_tree(path: Path) -> Optional[Path]:
    """The nearest ancestor of ``path`` (inclusive) holding a ``.git`` entry."""
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _refuse_if_versioned(target: Path) -> None:
    """Refuse to write a completion file into version-controlled territory."""
    places = [target.parent.resolve()]
    if target.is_symlink():
        places.append(target.resolve().parent)
    for place in places:
        repo = _enclosing_git_work_tree(place)
        if repo is not None:
            raise click.ClickException(
                f"refusing to write {target}: it resolves into the git work "
                f"tree {repo}. Writing there would modify a version-controlled "
                f"checkout. Point the shell at another directory (e.g. set "
                f"XDG_DATA_HOME / BASH_COMPLETION_USER_DIR), or save the "
                f"script yourself with `print-shell-completion`."
            )


def _atomic_write(path: Path, content: str) -> None:
    """Write ``content`` via a same-directory temp file and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def install_completion(
    command: click.Command, shell: str, prog_name: str, *, dry_run: bool = False
) -> Tuple[Path, str]:
    """Write the drop-in; return ``(path, status)``. Never touches an rc file.

    ``status`` is ``"written"``, ``"unchanged"`` or ``"would-write"``. Raises
    ``click.ClickException`` (before any write) for a git-tracked target.
    """
    target = completion_dropin_path(shell, prog_name)
    _refuse_if_versioned(target)
    if dry_run:
        return target, "would-write"
    script = generate_completion_script(shell, prog_name, command)
    current = (
        target.read_text(encoding="utf-8")
        if target.is_file() and not target.is_symlink()
        else None
    )
    if current == script:
        return target, "unchanged"
    _atomic_write(target, script)
    return target, "written"


def legacy_rc_lines(shell: str, prog_name: str) -> List[Tuple[Path, str]]:
    """Lines an earlier version appended to the rc file (read-only)."""
    rc_name = {"bash": ".bashrc", "zsh": ".zshrc"}.get(shell)
    if rc_name is None:
        return []
    rc = _home() / rc_name
    try:
        text = rc.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    marker = _legacy_marker(prog_name)
    return [(rc, line) for line in text.splitlines() if line.rstrip().endswith(marker)]


def _activation_hint(shell: str, path: Path) -> str:
    if shell == "bash":
        return (
            "bash-completion (>= 2) loads it on the first <TAB> in a new "
            "shell; no rc edit needed."
        )
    if shell == "zsh":
        directory = path.parent
        return (
            f"zsh loads it from fpath: if {directory} is not on your fpath "
            f"yet, add `fpath=({directory} $fpath)` before `compinit` in "
            f"your zsh config (this command never edits it)."
        )
    return "fish loads it automatically in a new shell."


def attach_shell_completion(main_group, *, prog_name: str) -> None:
    """Register the canonical 4 shell-completion leaves on ``main_group``."""

    @main_group.command("print-shell-completion")
    @click.option(
        "--shell",
        type=click.Choice(list(SHELLS)),
        default="bash",
        help="Target shell. Default: bash.",
    )
    def print_shell_completion(shell):
        """Print the click-generated completion script to stdout.

        \b
        Example:
          $ scitex-hpc print-shell-completion --shell bash
          $ eval "$(scitex-hpc print-shell-completion --shell bash)"
        """
        click.echo(generate_completion_script(shell, prog_name, main_group), nl=False)

    @main_group.command("install-shell-completion")
    @click.option(
        "--shell",
        type=click.Choice(list(SHELLS)),
        default="bash",
        help="Target shell. Default: bash.",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Print the target drop-in path without writing.",
    )
    @click.option("-y", "--yes", is_flag=True, help="Skip confirmation prompt.")
    def install_shell_completion(shell, dry_run, yes):
        """Write a TAB-completion drop-in file; never edits shell rc files.

        Writes into the per-user directory the shell's completion framework
        scans. Idempotent; refuses to write into a git work tree.

        \b
        Examples:
          scitex-hpc install-shell-completion              # bash drop-in
          scitex-hpc install-shell-completion --shell zsh  # zsh site-functions
          scitex-hpc install-shell-completion --dry-run    # preview only

        \b
        Targets:
          bash  ~/.local/share/bash-completion/completions/scitex-hpc
          zsh   ~/.local/share/zsh/site-functions/_scitex-hpc
          fish  ~/.config/fish/completions/scitex-hpc.fish
        """
        del yes  # accepted for §2 compliance; install never prompts
        path, status = install_completion(main_group, shell, prog_name, dry_run=dry_run)
        label = {
            "would-write": "Would write",
            "written": "Wrote",
            "unchanged": "Up to date",
        }[status]
        click.echo(f"{label}: {path}")
        for rc, line in legacy_rc_lines(shell, prog_name):
            click.echo(
                f"note: {rc} still carries a line an older installer "
                f"appended; it is no longer needed and can be deleted:\n"
                f"  {line}",
                err=True,
            )
        if not dry_run:
            click.echo(_activation_hint(shell, path))

    @main_group.command(
        "install-tab-completion",
        hidden=True,
        context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
    )
    @click.pass_context
    def install_tab_completion_deprecated(ctx):
        """(deprecated) Renamed to ``install-shell-completion``."""
        click.echo(
            f"error: `{prog_name} install-tab-completion` was renamed to "
            f"`{prog_name} install-shell-completion`.",
            err=True,
        )
        ctx.exit(2)

    @main_group.command(
        "completion",
        hidden=True,
        context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
    )
    @click.pass_context
    def completion_deprecated(ctx):
        """(deprecated) Renamed to ``install-shell-completion``."""
        click.echo(
            f"error: `{prog_name} completion` was renamed to "
            f"`{prog_name} install-shell-completion`.",
            err=True,
        )
        ctx.exit(2)
