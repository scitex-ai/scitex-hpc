"""``scitex-hpc login-guard`` group — Spartan login-node compute guard.

Subcommands:

  * ``show`` — print the vendored guard script (the source of truth for
    the shell-function overrides), or the exact install script with
    ``--script``.
  * ``install`` — deploy the guard to a host over SSH: copy it to
    ``~/.scitex/hpc/login-guard.sh``, ``chmod +x``, back up ``~/.bashrc``,
    ``bash -n``-validate a candidate, and idempotently insert the source
    line above the interactive-return guard. Default ``--dry-run`` prints
    the install script; pass ``--confirm`` to actually run it over SSH.

The CLI only ever prints text (``show``/dry-run) or runs the explicit,
self-validating install — it never executes anything on import.
"""

from __future__ import annotations

import sys

import click

from ..login_guard import (
    REMOTE_GUARD_PATH,
    build_install_script,
    guard_text,
    install,
)


@click.group("login-guard")
def login_guard() -> None:
    """Spartan login-node heavy-compute guard (TeX toolchain).

    \b
    Versions the hand-deployed guard so it re-installs deterministically.
    Shell-function overrides refuse the TeX toolchain on spartan-login*
    hosts OUTSIDE a SLURM job; a no-op inside jobs and on compute nodes,
    so CI runners are unaffected. Incident: 2026-07-01.
    """


@login_guard.command("show")
@click.option(
    "--script",
    is_flag=True,
    help="Show the remote INSTALL script instead of the guard itself.",
)
def show_cmd(script: bool) -> None:
    """Print the vendored guard script (or the install script).

    \b
    Example:
      $ scitex-hpc login-guard show
      $ scitex-hpc login-guard show --script
    """
    click.echo(build_install_script() if script else guard_text(), nl=False)


@login_guard.command("install")
@click.option("--host", default="spartan", help="SSH host (default: spartan).")
@click.option(
    "--confirm",
    is_flag=True,
    help="Actually deploy over SSH (default is dry-run: print the script).",
)
def install_cmd(host: str, confirm: bool) -> None:
    """Deploy the guard to HOST over SSH (safe + idempotent).

    \b
    Copies the guard to ~/.scitex/hpc/login-guard.sh, backs up ~/.bashrc,
    bash -n-validates a candidate, and inserts the source line ABOVE the
    interactive-return guard (so non-interactive ``ssh host '<cmd>'`` is
    covered too). Default is DRY-RUN.

    \b
    Example:
      $ scitex-hpc login-guard install --host spartan          # dry-run
      $ scitex-hpc login-guard install --host spartan --confirm
    """
    if not confirm:
        click.echo(
            f"DRY RUN — would deploy guard to {host}:{REMOTE_GUARD_PATH}\n"
            "and insert an idempotent source line into ~/.bashrc.\n"
            "--- install script ---"
        )
        click.echo(build_install_script(), nl=False)
        click.echo("\nRe-run with --confirm to deploy over SSH.")
        return
    res = install(host=host)
    if getattr(res, "stdout", ""):
        click.echo(res.stdout)
    if getattr(res, "stderr", ""):
        click.echo(res.stderr, err=True)
    rc = getattr(res, "returncode", 0)
    if rc != 0:
        click.echo(f"login-guard install failed (rc={rc})", err=True)
        sys.exit(rc)
    click.echo(f"installed: login-node guard on {host} ({REMOTE_GUARD_PATH})")
