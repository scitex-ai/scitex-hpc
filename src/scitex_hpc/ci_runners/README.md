# scitex-hpc ci-runners — durable self-hosted CI runner fleet on SLURM

A deterministic replacement for the login-node band-aid that hosted ~72
GitHub Actions self-hosted runners on a shared Spartan login node.

## Root cause (2026-06-25)

All ~72 runners (one per SciTeX package + figrecipe / crossref-local /
openalex / etc.) lived under
`/data/gpfs/projects/punim0264/ywatanabe/ci/actions-runner-<name>/` and
were launched by ad-hoc `~ywatanabe/*.sh` scripts **on a shared login
node** — or borrowed onto unrelated holder jobs via `srun --overlap`.

A login node carrying 61 users at load 10–16 cannot sustain 72 long-poll
HTTPS connections. The fleet logged 4000–5000 `HTTP request timed out`
errors/day and mass-died at 05:23 when one runner took a
`Bus error (core dumped)`. The intended dedicated node job
(`spartan-ci-runner-permanent`, 26332626) was stuck `PENDING(Priority)`.

## Design

```
            ┌─────────────────────── workstation / laptop ───────────────────────┐
            │  cron: */5 * * * *  scitex-ci-monitor.sh   ── alarm ──> operator    │
            └───────────────┬─────────────────────────────────────────────────────┘
                            │ ssh (bastion-initiated, light squeue + 1 overlap srun)
            ┌───────────────▼──────────────── Spartan ────────────────────────────┐
            │  sbatch supervisor job  (dedicated CPU node, 7-day walltime,         │
            │  persistent=True → SIGUSR1 auto-resubmit before walltime)            │
            │                                                                      │
            │   for each runner:  while alive: ./run.sh; on exit sleep N; relaunch │
            │   ── runner-1 keep-alive ── runner-2 keep-alive ── … ── runner-N ──  │
            │   wait   (block as the job's main process)                           │
            └──────────────────────────────────────────────────────────────────────┘
```

Two pieces, both **generated** by this package (pure string generation —
no SSH on import, nothing runs implicitly):

1. **Supervisor** (`_supervisor.py`) — the sbatch *hold body*. Hosts the
   whole fleet on ONE dedicated CPU node. Each runner gets a keep-alive
   loop that re-runs `run.sh` whenever it exits, so a dead runner is back
   within the restart backoff (default 15 s) with no human involvement.
   Booked via the existing `scitex_hpc.Reservation` primitive with
   `persistent=True`, so the SIGUSR1 walltime-resubmit trap keeps the
   allocation alive past the cluster walltime cap indefinitely. It also
   runs a **`_diag` log pruner** (keeps the newest `diag_keep`, default 20,
   Worker/Runner logs per runner, hourly) so a long-lived session's per-job
   logs never grow the shared-fileset inode footprint unbounded.

2. **Health monitor** (`_monitor.py`) — a cron-driven script run from a
   workstation. Each tick it confirms the allocation is `RUNNING`, lists
   live `Runner.Listener` processes via one `srun --overlap` step, checks
   the runner install **fileset has inode headroom** (`df -i`), and
   **alarms the operator** (never fire-and-forget) when the allocation is
   gone, a runner stays down, or the fileset is out of inodes (Listeners
   can be alive while every job phantoms because a full-inode fileset stops
   Workers creating files — the 2026-07-06 outage). It never `scancel`s and
   never kills a process — relaunch is the supervisor's job.

## CLI

```bash
# 1. See what's there (light ls only — no recursive scans on login node)
scitex-hpc ci-runners discover

# 2. Review the plan + the exact supervisor body (DEFAULT is dry-run)
scitex-hpc ci-runners book-supervisor

# 3. Submit the dedicated allocation (explicit --confirm required)
scitex-hpc ci-runners book-supervisor --confirm

# 4. Generate the cron monitor
scitex-hpc ci-runners show-monitor --out ~/.scitex/ci/monitor.sh
chmod +x ~/.scitex/ci/monitor.sh

# 5. (post-cutover) generate the band-aid archival script
scitex-hpc ci-runners show-archive --out /tmp/archive-bandaids.sh

# Registering / re-installing a runner (bakes the scitex-ci label in)
scitex-hpc ci-runners show-register \
  --url https://github.com/ywatanabe1989/scitex-hpc --name scitex-hpc
```

Defaults target Spartan's `cascade` partition (32 cores / 128 GB / 7-day
walltime, account `punim2354`, QOS `publiccpu`) — all overridable via
flags. The `7-0` walltime is the cascade/sapphire cap; `persistent=True`
auto-resubmits before it expires.

## Deploy runbook

1. **Do NOT touch the live runners yet.** They are currently borrowed
   onto holder jobs 26437532 (bm027) / 26136176 (bm079) via the `~`
   band-aids. Leave them running until the new fleet is verified.
2. `scitex-hpc ci-runners book-supervisor` (dry-run) — eyeball the body
   and runner list.
3. `scitex-hpc ci-runners book-supervisor --confirm` — books the
   dedicated node. Wait for `node=` to populate (it polls squeue).
4. The runners are registered to GitHub by `(host, repo)` — once the new
   supervisor's `run.sh` connects each runner, GitHub routes jobs to it.
   Because the runner identity is the install dir (not the host), the new
   node simply takes over.
5. Drain / cancel the old borrowed-holder runners **only after** the new
   node shows all runners `Connected to GitHub` in their `keepalive.log`.
6. `scitex-hpc ci-runners show-monitor --out ~/.scitex/ci/monitor.sh`,
   then add to crontab:
   ```
   */5 * * * * ~/.scitex/ci/monitor.sh >> ~/.scitex/ci/monitor.log 2>&1
   ```
7. Wire the alarm: either set `SCITEX_CI_ALARM_CMD` in the crontab env
   (it receives `"<subject>\n<body>"` on stdin — e.g. a telegram-send
   one-liner), or rely on the default fleet
   `~/.dotfiles/src/.bin/utils/notify.sh` fallback, or let `cron` mail
   the stderr.
8. `scitex-hpc ci-runners show-archive` and **hand-run** the result on
   Spartan to move the `~` band-aids to `~/.old/<timestamp>/` — only
   after cutover, since the live runners depend on them until then.

## Recovery behavior

| failure                         | who recovers       | how                                        |
| ------------------------------- | ------------------ | ------------------------------------------ |
| a runner's `run.sh` exits/crashes | supervisor       | keep-alive loop re-runs it after backoff   |
| walltime approaching            | Reservation trap   | SIGUSR1 → `sbatch "$0"` resubmits in place |
| whole allocation gone           | operator (alarmed) | monitor exits 11 + alarm; rebook explicitly |
| a keep-alive loop wedged        | operator (alarmed) | monitor exits 10 + alarm + `.needs-restart` |
| supervisor never registered     | operator (alarmed) | monitor exits 12 + alarm; re-exec supervisor |
| runner fileset out of inodes    | operator (alarmed) | monitor exits 13 + alarm; free inodes        |

## Monitor exit-code / alarm contract

Domain verdicts start at **10**, never at 1 or 2.

- `exit 0` — fleet healthy (one-line `OK` to stdout, incl. current inode %)
- `exit 10` — degraded: some runners down — alarm fired, names listed
- `exit 11` — allocation gone / unreachable — alarm fired
- `exit 12` — supervisor UNREGISTERED (no holder-jobid file; the
  `ci-runners watch` / `overlap_jobid_file` deploy) — alarm fired
- `exit 13` — runner install fileset at/above the inode threshold
  (default 90 %); Listeners may be up but Workers can't create files, so
  jobs phantom `in_progress` — alarm fired, free inodes
- Alarm command: `$SCITEX_CI_ALARM_CMD` (stdin = `subject\nbody`), else
  the fleet `notify.sh` helper, else stderr (cron mails it).

### Why 10+ (renumbered 2026-07-29)

These verdicts were `1/2/3/4`. `1` and `2` already mean "generic failure"
and "usage error" in every shell and CLI framework, so anything that killed
the monitor **before it measured anything** — an ImportError, a renamed
module, a bad interpreter path — exited `1` and was read as the verdict
*"degraded: some runners down"*.

That is worse than a crash, because it is **actionable-looking**: the
operator goes hunting for downed runners that were never down, and a
monitor that never ran reports a plausible fleet state. Reserving the low
range keeps "did not run" distinguishable from "ran and found trouble".

**Teach the supervisor the non-failure codes**, or this is undone one layer
up. Under `cron`, any non-zero mails — which is what we want. Under
systemd, the wrapping unit needs:

```ini
SuccessExitStatus=10 11 12 13
```

Otherwise a correct multi-state answer is collapsed back to two-state by
the supervisor reporting every verdict as a unit FAILURE.

## Why not the old `~` scripts?

They started compute on the login node (admin-flagged), borrowed
unrelated holder jobs, had no auto-restart, no walltime survival, and no
alarm. This package makes every one of those a first-class, tested
property. The band-aids are archived (not deleted) post-cutover.
