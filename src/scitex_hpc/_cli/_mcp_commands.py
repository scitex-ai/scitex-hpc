"""``scitex-hpc mcp`` group — start / doctor / list-tools / install (§3)."""

from __future__ import annotations

import json as _json

import click
from scitex_dev.ecosystem import CliHelp, Example, SpecCommand, SpecGroup


@click.group(
    "mcp",
    invoke_without_command=True,
    cls=SpecGroup,
    help_spec=CliHelp(
        summary="MCP (Model Context Protocol) server commands.",
    ),
)
@click.pass_context
def mcp_group(ctx):
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@mcp_group.command(
    "start",
    cls=SpecCommand,
    help_spec=CliHelp(
        summary="Start the scitex-hpc MCP server (stdio transport).",
        examples=(
            Example("{prog} mcp start", "Start the server."),
            Example(
                "{prog} mcp start --dry-run",
                "Print the launch plan without starting.",
            ),
        ),
    ),
)
@click.option("--dry-run", is_flag=True, help="Print launch plan without starting.")
@click.option("-y", "--yes", "yes", is_flag=True, help="Skip confirmation prompt.")
def mcp_start(dry_run: bool, yes: bool):
    del yes
    if dry_run:
        click.echo("DRY RUN — would start scitex-hpc MCP server (stdio transport)")
        return
    try:
        from .._mcp.server import mcp as mcp_server
    except ImportError as e:
        raise click.ClickException(
            f"MCP not available. Install: pip install scitex-hpc[mcp]\n{e}"
        ) from e
    click.echo("Starting scitex-hpc MCP server (stdio)...")
    mcp_server.run()


@mcp_group.command(
    "doctor",
    cls=SpecCommand,
    help_spec=CliHelp(
        summary="Check MCP server health and dependencies.",
        examples=(
            Example("{prog} mcp doctor", "Report fastmcp + server importability."),
        ),
    ),
)
def mcp_doctor():
    click.secho("scitex-hpc MCP Doctor", fg="cyan", bold=True)
    click.echo()
    all_ok = True
    try:
        import fastmcp

        click.echo(f"  [OK] fastmcp v{fastmcp.__version__}")
    except ImportError:
        click.echo("  [FAIL] fastmcp not installed (pip install scitex-hpc[mcp])")
        all_ok = False
    try:
        from .._mcp.server import mcp as _mcp  # noqa: F401

        click.echo("  [OK] MCP server importable")
    except ImportError as e:
        click.echo(f"  [FAIL] MCP server: {e}")
        all_ok = False
    click.echo()
    if all_ok:
        click.secho("All checks passed.", fg="green")
    else:
        click.secho("Some checks failed.", fg="red")


@mcp_group.command(
    "list-tools",
    cls=SpecCommand,
    help_spec=CliHelp(
        summary="List MCP tools exposed by scitex-hpc.",
        examples=(
            Example("{prog} mcp list-tools", "Tool names only."),
            Example("{prog} mcp list-tools -vv", "Names plus parameters."),
            Example("{prog} mcp list-tools --json", "Structured JSON output."),
        ),
    ),
)
@click.option("-v", "--verbose", count=True, help="-v names, -vv params, -vvv docs.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def mcp_list_tools(verbose, as_json):
    tools: list = []
    try:
        import asyncio

        from .._mcp.server import mcp as mcp_server

        tools = list(asyncio.run(mcp_server.list_tools()))
    except ImportError:
        tools = []

    if as_json:
        payload = {
            "total": len(tools),
            "tools": [
                {
                    "name": getattr(t, "name", str(t)),
                    "description": getattr(t, "description", "") or "",
                    "parameters": getattr(t, "parameters", {}) or {},
                }
                for t in tools
            ],
        }
        click.echo(_json.dumps(payload, indent=2))
        return

    if not tools:
        click.echo("(no MCP tools registered)")
        return

    for tool in tools:
        name = getattr(tool, "name", str(tool))
        desc = getattr(tool, "description", "") or ""
        first = desc.split("\n")[0] if desc else ""
        if verbose == 0:
            click.echo(f"  {name}")
        elif verbose == 1:
            click.echo(f"  {name:24s} {first}")
        else:
            click.echo(f"  {name}")
            for line in desc.split("\n")[:5]:
                click.echo(f"    {line}")
            click.echo()


@mcp_group.command(
    "install",
    cls=SpecCommand,
    help_spec=CliHelp(
        summary="Show MCP installation and configuration instructions.",
        examples=(
            Example("{prog} mcp install", "Human-readable instructions."),
            Example("{prog} mcp install --json", "Machine-readable config block."),
        ),
    ),
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--dry-run", is_flag=True, help="Preview without writing anything.")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation prompt.")
def mcp_install(as_json: bool, dry_run: bool, yes: bool):
    del dry_run, yes  # `install` only prints today; flags reserved for parity
    config = {
        "mcpServers": {
            "scitex-hpc": {
                "command": "scitex-hpc",
                "args": ["mcp", "start"],
            }
        }
    }
    if as_json:
        click.echo(
            _json.dumps(
                {
                    "install_command": "pip install scitex-hpc[mcp]",
                    "config": config,
                    "verify_commands": ["scitex-hpc mcp doctor"],
                },
                indent=2,
            )
        )
        return

    click.secho("scitex-hpc MCP Installation", fg="cyan", bold=True)
    click.echo()
    click.echo("Install scitex-hpc with MCP support:")
    click.echo()
    click.secho("  pip install scitex-hpc[mcp]", fg="green")
    click.echo()
    click.echo("Add to your MCP client config (e.g., claude_desktop_config.json):")
    click.echo()
    for line in _json.dumps(config, indent=2).split("\n"):
        click.secho(f"  {line}", dim=True)
    click.echo()
    click.echo("Verify with:")
    click.echo()
    click.secho("  scitex-hpc mcp doctor", fg="green")


@mcp_group.command(
    "show-installation",
    hidden=True,
    context_settings={"ignore_unknown_options": True},
)
@click.pass_context
def show_installation_deprecated(ctx):
    """(deprecated) Renamed to `install`."""
    click.echo(
        "error: `scitex-hpc mcp show-installation` was renamed to "
        "`scitex-hpc mcp install`.\n"
        "Re-run with: scitex-hpc mcp install",
        err=True,
    )
    ctx.exit(2)
