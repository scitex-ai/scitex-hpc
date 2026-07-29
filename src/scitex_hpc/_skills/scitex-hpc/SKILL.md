---
name: scitex-hpc
description: |
  [WHAT] Generic SLURM dispatch + persistent reservations for the SciTeX
  ecosystem — one-shot `srun`/`sbatch`/`sync`/`poll`/`fetch_result` plus a
  `Reservation` primitive that books a node once and runs many short commands
  inside the allocation via `srun --jobid --overlap`, cutting queue wait from
  minutes to one ssh round-trip per command.
  [WHEN] Dispatching jobs to an HPC cluster from a laptop or login node —
  especially when iterating in tight loops, running multi-agent fleets, or
  doing jupyter-on-HPC where queue wait dominates wall time.
  [HOW] `from scitex_hpc import srun, sbatch, Reservation`, or
  `scitex-hpc <verb> ...`. Bastion-initiated SSH only; no persistent daemons.
primary_interface: python
interfaces:
  python: 3
  cli: 2
  mcp: 0
  skills: 1
  hook: 0
  http: 0
tags: [scitex-hpc]
---

# scitex-hpc

Generic SLURM dispatch + persistent reservations. Login nodes never run
compute — every command is wrapped in `srun`/`sbatch` via a login-shell SSH.

## Two patterns

| Pattern | Use when | Module |
|---|---|---|
| **One-shot dispatch** (`srun`/`sbatch`) | Run a script once, fetch results | `scitex_hpc.{srun,sbatch,sync,poll_job,fetch_result}` |
| **Reservations** (book once, exec many) | Iteration loops; multi-agent fleets; jupyter-on-HPC | `scitex_hpc.Reservation` |

## Sub-skills

### Core (01–09)
- [01_installation.md](01_installation.md) — install + import sanity check
- [02_quick-start.md](02_quick-start.md) — 30-second tour
- [03_python-api.md](03_python-api.md) — Python API surface
- [04_cli-reference.md](04_cli-reference.md) — CLI subcommands

### Workflows (10–19)
- [11_reservations-api.md](11_reservations-api.md) — full `Reservation` API + CLI
- [12_reservation-features.md](12_reservation-features.md) — walltime auto-resubmit, tmux bootstrap, adopt-existing-jobid
- [13_compatibility-policies.md](13_compatibility-policies.md) — no-daemon policy, login-shell wrapping, state files, empirical guarantees, source layout
- [14_permanent-allocation-doctrine.md](14_permanent-allocation-doctrine.md) — when to hold a permanent allocation vs. dispatch one-shot; durable self-resubmit (verify + fail loud); `srun --overlap` concurrency; freshness via container+overlay, not re-queuing; the zero-failing-steps lost-runner signature
- [16_resubmit-chain-failure-modes.md](16_resubmit-chain-failure-modes.md) — the four ways a SIGUSR1 self-resubmit chain fails, three of them silently: it doesn't fire; it fires and the successor waits in the queue (16h measured outage — submit EARLY and serve out the full walltime); a healthy hop records `FAILED/138` so State-keyed monitoring is INVERTED (monitor the outcome, level-triggered on zero); and `sbatch "$0"` resubmits the SPOOL COPY, so the script can exist nowhere else on disk
- [15_spartan-identity-access-traps.md](15_spartan-identity-access-traps.md) — why a multiplexed ssh session reads the PAST and makes a group revocation look like a "flap"; probing authoritatively (`ControlPath=none`, `getent group` over cached `id`); why losing a project group breaks shell init when `$HOME` dotdirs symlink into it; SLURM Account ≠ POSIX group
- [16_verifying-a-fix-is-live.md](16_verifying-a-fix-is-live.md) — four ways a fix reads as applied and is not (declared-not-applied / applied-in-wrong-place / layers-disagree / doctrine-as-description); why applied-in-wrong-place needs a SECOND observer and destroys the signal; why a job log cannot testify about the launcher; merged ≠ deployed ≠ effective; why a flake rate is the wrong statistic for a compounding failure. **NOTE: the CI runners have NO container/overlay — 14's freshness section is the target design, not the deployment**

### Meta (20+)
- [20_env-vars.md](20_env-vars.md) — Environment variables (`SCITEX_HPC_*`)
