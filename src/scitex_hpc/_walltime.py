"""Empirically-verified SLURM walltime limits.

``sinfo``'s reported partition ``MaxTime`` is a ceiling, not a guarantee —
the actual achievable limit is the tightest of the partition ceiling, the
QOS's ``MaxWall``, and the user/account association's ``MaxWall``, and
``sinfo`` only ever shows the first of those three. Trusting it alone was
the exact mistake that produced conflicting walltime numbers during the
2026-07-13 CI-supervisor incident (see
``_skills/scitex-hpc/14_permanent-allocation-doctrine.md``).

This module queries all three sources and, optionally, submits a real
``sbatch --test-only`` probe — SLURM's own policy validation, without
actually queuing a job — as the decisive check.
"""

from __future__ import annotations

from dataclasses import dataclass

from scitex_ssh import exec_remote

from ._config import JobConfig
from ._dispatch import _quote, _wrap_in_login_shell


@dataclass
class WalltimeMax:
    """Result of an empirical walltime-ceiling query."""

    partition: str
    sinfo_ceiling: str | None
    qos_max_wall: str | None
    assoc_max_wall: str | None
    verified: bool
    verified_accepted: str | None
    verified_rejected: str | None
    note: str

    def achievable(self) -> str | None:
        """Best current estimate of the real achievable walltime.

        Association MaxWall (if set) overrides QOS MaxWall (if set)
        overrides the partition's sinfo ceiling — the same precedence
        SLURM itself applies.
        """
        return self.assoc_max_wall or self.qos_max_wall or self.sinfo_ceiling


def _run(config: JobConfig, remote_cmd: str, *, runner=None) -> str:
    host = config.resolve("host")
    run = runner if runner is not None else exec_remote
    result = run(host, _wrap_in_login_shell(remote_cmd))
    return result.stdout


def _parse_sinfo_ceiling(stdout: str, partition: str) -> str | None:
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        name, limit = parts
        if name.rstrip("*") == partition:
            return limit
    return None


def _parse_qos_max_wall(stdout: str, qos_names: list[str]) -> str | None:
    """First non-blank MaxWall among the QOS names attached to the account."""
    rows = {}
    for line in stdout.splitlines():
        if "|" not in line or line.startswith("Name|"):
            continue
        name, max_wall = line.split("|", 1)
        rows[name.strip()] = max_wall.strip()
    for qos in qos_names:
        val = rows.get(qos)
        if val:
            return val
    return None


def _parse_assoc_max_wall(stdout: str) -> tuple[str | None, list[str]]:
    """Returns (max_wall_if_set, qos_names_for_this_account)."""
    for line in stdout.splitlines():
        if "|" not in line or line.startswith("Account|"):
            continue
        _account, qos_field, max_wall = (line.split("|", 2) + ["", ""])[:3]
        qos_names = [q.strip() for q in qos_field.split(",") if q.strip()]
        if max_wall.strip():
            return max_wall.strip(), qos_names
        return None, qos_names
    return None, []


def _probe_test_only(
    config: JobConfig,
    partition: str,
    walltime: str,
    *,
    runner=None,
) -> bool:
    """Submit a throwaway script with ``sbatch --test-only``.

    Returns True if SLURM accepted the request (would schedule it),
    False if it was rejected as exceeding a limit. Never actually queues
    a job — ``--test-only`` is SLURM's own dry-run.
    """
    account = config.resolve("account")
    qos = config.resolve("qos")
    script_lines = [
        "#!/bin/bash",
        f"#SBATCH --partition={partition}",
        f"#SBATCH --time={walltime}",
    ]
    if account:
        script_lines.append(f"#SBATCH --account={account}")
    if qos:
        script_lines.append(f"#SBATCH --qos={qos}")
    script_lines.append("echo probe")
    script_body = "\n".join(script_lines) + "\n"

    # Same pattern as ``sbatch()`` in _dispatch.py: pipe the script body
    # through process substitution rather than writing/cleaning up a temp
    # file remotely — one round trip, no leftover state on failure.
    remote_cmd = f"sbatch --test-only <(printf %s {_quote(script_body)})"
    host = config.resolve("host")
    run = runner if runner is not None else exec_remote
    result = run(host, _wrap_in_login_shell(remote_cmd))
    return result.returncode == 0


def walltime_max(
    config: JobConfig,
    partition: str,
    *,
    verify: bool = False,
    runner=None,
) -> WalltimeMax:
    """Empirically determine the real achievable walltime for ``partition``.

    Always queries ``sinfo`` (ceiling), ``sacctmgr show qos`` and
    ``sacctmgr show assoc`` (overrides). With ``verify=True``, additionally
    submits a decisive ``sbatch --test-only`` probe at the resulting
    estimate and reports whether it was actually accepted or rejected —
    the only ground-truth signal, per the 2026-07-13 incident.
    """
    sinfo_out = _run(config, "sinfo -o '%P %l'", runner=runner)
    ceiling = _parse_sinfo_ceiling(sinfo_out, partition)

    assoc_out = _run(
        config,
        "sacctmgr show assoc user=$USER format=Account,QOS,MaxWall -P",
        runner=runner,
    )
    assoc_max_wall, qos_names = _parse_assoc_max_wall(assoc_out)

    qos_max_wall = None
    if qos_names:
        qos_out = _run(
            config, "sacctmgr show qos format=Name,MaxWall -P", runner=runner
        )
        qos_max_wall = _parse_qos_max_wall(qos_out, qos_names)

    verified_accepted: str | None = None
    verified_rejected: str | None = None
    note = (
        "Not empirically verified via --test-only. sinfo's MaxTime is a "
        "ceiling, not a guarantee -- pass verify=True / --verify to confirm "
        "with a real (non-queuing) sbatch --test-only probe."
    )
    if verify:
        candidate = assoc_max_wall or qos_max_wall or ceiling
        if candidate:
            accepted = _probe_test_only(config, partition, candidate, runner=runner)
            if accepted:
                verified_accepted = candidate
                note = f"Verified via sbatch --test-only: {candidate} accepted."
            else:
                verified_rejected = candidate
                note = (
                    f"Verified via sbatch --test-only: {candidate} REJECTED -- "
                    "the reported ceiling/override is not actually achievable; "
                    "investigate further (a stricter, unlisted limit may apply)."
                )

    return WalltimeMax(
        partition=partition,
        sinfo_ceiling=ceiling,
        qos_max_wall=qos_max_wall,
        assoc_max_wall=assoc_max_wall,
        verified=verify,
        verified_accepted=verified_accepted,
        verified_rejected=verified_rejected,
        note=note,
    )
