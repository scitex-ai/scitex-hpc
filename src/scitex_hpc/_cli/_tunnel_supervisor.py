"""``scitex-hpc tunnel-supervisor`` group — generic keepalive-supervisor primitive.

Subcommands:

  * ``show`` — print the rendered supervisor script for a profile.
  * ``install`` — write the rendered script to a target path (and
    ``chmod +x`` it). Default is ``--dry-run`` (prints what WOULD be
    written); pass ``--confirm`` to actually write it.

Profiles are supplied by the CALLER (via :func:`register_profile` or by
importing this package and constructing a
:class:`~scitex_hpc.tunnel_supervisor.TunnelProfile` directly) — no
cluster names, hostnames, or ports are baked into this CLI.
"""

from __future__ import annotations

import json as _json
import sys

import click

from ..tunnel_supervisor import (
    PROFILES,
    cron_line,
    get_profile,
    supervisor_text,
    systemd_unit_text,
    write_supervisor,
)


@click.group("tunnel-supervisor")
def tunnel_supervisor() -> None:
    """Generic per-node service/tunnel keepalive supervisor (profile-driven).

    \b
    Sentinel + keep-alive loop, flock single-instance semantics, a
    timestamped heartbeat log, and endpoint health-checking (not just
    PID liveness) — generalized out of scitex-hpc's ci_runners fleet
    supervisor so sibling projects can build their own supervisors on
    top of this primitive instead of hand-rolling flock scripts.
    """


@tunnel_supervisor.command("show")
@click.option(
    "--profile",
    default=None,
    help="Registered profile name (see PROFILES). Omit to use the example profile.",
)
@click.option("--json", "as_json", is_flag=True, help='Emit JSON ({"script": ...}).')
def show_cmd(profile: str | None, as_json: bool) -> None:
    """Print the rendered supervisor script for PROFILE.

    \b
    Example:
      $ scitex-hpc tunnel-supervisor show --profile clew-tunnel
      $ scitex-hpc tunnel-supervisor show --profile clew-tunnel --json
    """
    prof = get_profile(profile) if profile else get_profile()
    text = supervisor_text(prof)
    if as_json:
        click.echo(_json.dumps({"script": text}, indent=2))
        return
    click.echo(text, nl=False)


@tunnel_supervisor.command("install")
@click.argument("target_path")
@click.option(
    "--profile",
    default=None,
    help="Registered profile name (see PROFILES). Omit to use the example profile.",
)
@click.option("--dry-run", is_flag=True, help="Preview without writing (default).")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation; write TARGET_PATH.")
def install_cmd(
    target_path: str, profile: str | None, dry_run: bool, yes: bool
) -> None:
    """Write the rendered supervisor script to TARGET_PATH (chmod +x).

    \b
    Default is DRY-RUN (prints the script that would be written); pass
    -y/--yes to actually write it.

    \b
    Example:
      $ scitex-hpc tunnel-supervisor install /opt/acme/tunnel.sh --profile acme -y
    """
    prof = get_profile(profile) if profile else get_profile()
    if not yes or dry_run:
        click.echo(
            f"DRY RUN — would write {prof.name} supervisor to {target_path}\n"
            "--- script ---"
        )
        click.echo(supervisor_text(prof), nl=False)
        click.echo("\nRe-run with -y/--yes to actually write it.")
        return
    write_supervisor(prof, target_path)
    click.echo(f"installed: tunnel-supervisor ({prof.name}) -> {target_path}")
    click.echo("\nOptional registration artifacts:")
    click.echo(f"  cron:    {cron_line(prof, target_path)}")
    click.echo("  systemd (~/.config/systemd/user/<name>.service):")
    click.echo(systemd_unit_text(prof, target_path))
