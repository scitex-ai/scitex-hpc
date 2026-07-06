"""``scitex-hpc sentinel`` group — Spartan login-node compute guard.

Subcommands:

  * ``show`` — print the vendored guard script (the source of truth for
    the shell-function overrides), or the exact install script with
    ``--script``; ``--json`` wraps it as a machine-readable object.
  * ``install`` — deploy the guard to a host over SSH: copy it to
    ``~/.scitex/hpc/login-guard.sh``, ``chmod +x``, back up ``~/.bashrc``,
    ``bash -n``-validate a candidate, and idempotently insert the source
    line above the interactive-return guard. Default is a DRY-RUN that
    prints the install script; pass ``--yes`` to actually run it over SSH.

The CLI only ever prints text (``show``/dry-run) or runs the explicit,
self-validating install — it never executes anything on import.
"""

from __future__ import annotations

import json as _json
import sys

import click

from ..login_guard import (
    PROFILES,
    REMOTE_GUARD_PATH,
    build_install_script,
    get_profile,
    guard_text,
    install,
)

_PROFILE_CHOICE = click.Choice(sorted(PROFILES))


@click.group("sentinel")
def login_guard() -> None:
    """HPC login-node guardrail (heavy compute + protected-path du/find).

    \b
    Config-driven via profiles (default: spartan). Shell-function overrides
    refuse the TeX toolchain AND du/find walks over protected filesystem
    prefixes on login hosts OUTSIDE a SLURM job; a no-op inside jobs and on
    compute nodes, so CI runners are unaffected. Incidents: 2026-07-01.
    """


@login_guard.command("show")
@click.option(
    "--profile",
    default="spartan",
    type=_PROFILE_CHOICE,
    help="Site profile to render (default: spartan).",
)
@click.option(
    "--script",
    is_flag=True,
    help="Show the remote INSTALL script instead of the guard itself.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help='Emit JSON ({"profile","kind","content"}) for machine consumers.',
)
def show_cmd(profile: str, script: bool, as_json: bool) -> None:
    """Print the rendered guard script (or the install script).

    \b
    Example:
      $ scitex-hpc sentinel show
      $ scitex-hpc sentinel show --profile spartan --script
      $ scitex-hpc sentinel show --json
    """
    prof = get_profile(profile)
    content = build_install_script(profile=prof) if script else guard_text(prof)
    if as_json:
        click.echo(
            _json.dumps(
                {
                    "profile": prof.name,
                    "kind": "install-script" if script else "guard",
                    "content": content,
                }
            )
        )
        return
    click.echo(content, nl=False)


@login_guard.command("install")
@click.option(
    "--profile",
    default="spartan",
    type=_PROFILE_CHOICE,
    help="Site profile to render (default: spartan).",
)
@click.option("--host", default="spartan", help="SSH host (default: spartan).")
@click.option(
    "--dry-run/--no-dry-run",
    default=True,
    help="Print the install script instead of deploying (default: dry-run).",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Deploy for real over SSH (required; overrides the default dry-run).",
)
def install_cmd(profile: str, host: str, dry_run: bool, yes: bool) -> None:
    """Deploy the guard to HOST over SSH (safe + idempotent).

    \b
    Copies the guard to ~/.scitex/hpc/login-guard.sh, backs up ~/.bashrc,
    bash -n-validates a candidate, and inserts the source line ABOVE the
    interactive-return guard (so non-interactive ``ssh host '<cmd>'`` is
    covered too). Default is DRY-RUN; pass --yes to deploy.

    \b
    Example:
      $ scitex-hpc sentinel install --host spartan        # dry-run
      $ scitex-hpc sentinel install --host spartan --yes
    """
    prof = get_profile(profile)
    # Safe by default: only a bare ``--yes`` leaves dry-run and deploys.
    if dry_run and not yes:
        click.echo(
            f"DRY RUN — would deploy {prof.name} guard to "
            f"{host}:{REMOTE_GUARD_PATH}\n"
            "and insert an idempotent source line into ~/.bashrc.\n"
            "--- install script ---"
        )
        click.echo(build_install_script(profile=prof), nl=False)
        click.echo("\nRe-run with --yes to deploy over SSH.")
        return
    res = install(profile=prof, host=host)
    if getattr(res, "stdout", ""):
        click.echo(res.stdout)
    if getattr(res, "stderr", ""):
        click.echo(res.stderr, err=True)
    rc = getattr(res, "returncode", 0)
    if rc != 0:
        click.echo(f"sentinel install failed (rc={rc})", err=True)
        sys.exit(rc)
    click.echo(f"installed: login-node guard on {host} ({REMOTE_GUARD_PATH})")
