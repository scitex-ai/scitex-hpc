---
description: |
  [TOPIC] Permanent Allocation Doctrine
  [DETAILS] When to hold a long-walltime SLURM allocation vs. dispatch
  one-shot jobs; how to make a held allocation durable (self-resubmit that
  verifies success and fails loud, not hopes silently); how to get freshness
  without re-queuing (container + overlay per unit of work, not a new
  allocation); the "zero failing steps" lost-runner detection rule. Grounded
  in the 2026-07-13 CI-supervisor incident (resubmit trap fired, `sbatch`
  wasn't on PATH after env hardening, ~74 runners died silently for 15-20min
  with no alarm) and verified Spartan partition limits.
tags: [scitex-hpc-permanent-allocation, scitex-hpc, scitex-package]
---

# When to hold a permanent allocation

SLURM is a scheduler, not an elastic cloud. A fresh allocation per unit of
work pays partition-contention queue latency on every run — sometimes
seconds, sometimes (on a busy partition) minutes. Whether that cost is
acceptable is the entire decision.

## Required: anything that must respond to external events with low latency

CI runners, long-lived daemons, agent hosts — anything where a queue wait
would be **visible to a human or would break a service's contract**. Hold
the allocation once; serve every subsequent event from inside it.

Examples live on Spartan today: `spartan-ci-runner-supervisor` (hosts ~76
self-hosted GitHub Actions runners, must pick up a queued CI job in
seconds, not after a scheduler round-trip) and the qwen LLM-serving job
(must answer inference requests immediately).

## Wrong: one-shot compute

A training run, a batch sweep, anything that can tolerate a queue wait —
use normal `sbatch`/`srun`, full stop. Do not squat a shared cluster's
nodes for work that queues fine on its own. The rule cuts both ways: a
permanent allocation idling most of the time is exactly the kind of
shared-resource pressure Spartan etiquette exists to prevent.

## How: verified real numbers, not folklore

`sinfo -o '%P %l'` (live-verified 2026-07-13):

| Partition | Max walltime |
|---|---|
| `sapphire` (default) | 30-00:00:00 |
| `cascade` | 30-00:00:00 |
| `gpu-h100` | 7-00:00:00 |
| `gpu-a100` | 7-00:00:00 |
| `long` | 90-00:00:00 |
| `bigmem` | 21-00:00:00 |
| `interactive` | 2-00:00:00 |

In production: the CI supervisor runs 14-day walltime on `sapphire`
(well inside its 30-day cap); qwen runs 7-day walltime on `gpu-h100`
(exactly at that partition's cap — 7 days is the practical ceiling for
GPU work, not a choice).

### The resubmit pattern — and its one real failure mode

```bash
#SBATCH --signal=B:USR1@3600   # SLURM signals 1h before the walltime boundary
trap _resubmit USR1
```

This is SLURM's documented signaling mechanism (see
[12_reservation-features.md](12_reservation-features.md) for the
`Reservation(persistent=True)` wrapper) — not a daemon, not a cron
@reboot, compatible with the no-daemon IT Security ruling
([13_compatibility-policies.md](13_compatibility-policies.md)).

**A permanent allocation WILL hit its walltime boundary. The only question
is whether the handoff to a successor job is verified, or merely hoped
for.** On 2026-07-13 the CI supervisor's trap fired exactly on schedule
and correctly, but the resubmit call itself —

```bash
_resubmit() { sbatch "$0"; }   # WRONG: assumes `sbatch` is still on PATH
```

— failed with `sbatch: command not found`, because the script's own
env-hardening (`module purge` + a PATH scrub for secret/easybuild
isolation) ran *after* the trap was registered but had *already stripped
`/apps/slurm/latest/bin`* off PATH by the time USR1 fired. No successor
job was ever submitted. SLURM recorded the exit as `FAILED/138`
(`128+SIGUSR1`, since `wait` returning early on the trapped signal was
the script's last statement) — a code that reads as "killed by a signal",
not "resubmit silently no-op'd". All ~76 dependent runners died with
zero alarm, caught only by a human/agent noticing the job had vanished
from `squeue` roughly 15-20 minutes later.

**The durable pattern, not just the one-off fix:**

```bash
# Resolve the resubmit binary's ABSOLUTE PATH before any env hardening runs.
SBATCH_BIN="$(command -v sbatch 2>/dev/null)"
[ -x "$SBATCH_BIN" ] || SBATCH_BIN="/apps/slurm/latest/bin/sbatch"

_resubmit() {
  if [ -x "$SBATCH_BIN" ] && "$SBATCH_BIN" "$0"; then
    rm -f "$FAIL_MARKER" 2>/dev/null
  else
    # FAIL LOUD. A resubmit that silently no-ops is worse than one that
    # crashes visibly — nothing else in the system knows to page anyone.
    echo "$(date -u +%FT%TZ) resubmit failed; SBATCH_BIN='$SBATCH_BIN'" \
      > "$FAIL_MARKER"
  fi
}
trap _resubmit USR1
# ... only THEN do module purge / PATH scrubbing / secret hardening ...
```

Any script that hardens its own environment (secret-var scrubbing, PATH
sanitization, `module purge`) and *also* self-resubmits must resolve the
resubmit binary before the hardening step, not after — hardening is
exactly the kind of change that can silently break a mechanism defined
earlier in the same script. A sentinel file alone is necessary but not
sufficient: something has to actually watch it and alert (a separate,
genuinely independent check — not the same script policing itself, which
is the single point of failure that failed here).

### Concurrency inside the held allocation: `srun --overlap`

Do not re-allocate per unit of work — run units of work as **steps
inside the held allocation**:

```bash
srun --jobid=<held-allocation-id> --overlap <cmd>
```

`--overlap` lets multiple steps share the allocation's resources
concurrently instead of serializing on it. Verified live (see
[13_compatibility-policies.md](13_compatibility-policies.md)'s empirical
guarantees) and used in production for the CI runner fleet's
stuck-busy reaper (a background `srun --overlap` step against the
supervisor's own job).

### Freshness without re-queuing: discard the environment, not the allocation

The temptation, once state has rotted (a corrupted local config, leaked
`/tmp` scratch, a stale credential), is to re-provision the whole
allocation. Don't — that reintroduces the queue-latency cost the
permanent allocation exists to avoid. Instead, discard the *environment*
each unit of work runs in:

- A shared, read-only Apptainer base SIF.
- A **fresh overlay per unit of work**, created at start, destroyed at
  end (`ACTIONS_RUNNER_HOOK_JOB_STARTED` / `_JOB_COMPLETED` are the
  supported integration points for GitHub Actions runners specifically —
  `JOB_COMPLETED` is already live in production, clearing `$RUNNER_TEMP`
  on every job).
- The allocation persists; only the overlay is new. Start cost is
  seconds (Apptainer exec), not a scheduler round-trip.

This kills per-machine state rot **by construction**, not by remembering
to clean up after yourself. It was the direct fix proposed for the
2026-07-12 incident class below: a corrupted `~/.config/gh/config.yml`
on one long-lived runner silently broke that repo's releases for hours,
because nothing ever discarded that runner's local `$HOME`-adjacent
state between jobs. N long-lived machines each holding their own
mutable state is N independent places for that state to rot; a shared
base image + a disposable overlay per job removes the "N places" entirely.

## Detection rule: zero failing steps means a lost runner, not a flaky test

A CI run that reports **failed with zero failing steps** is not a test
flake — it is the signature of the runner itself dying mid-job (crashed,
OOM-killed, walltime-killed, network-partitioned) before it could report
which step it was on. GitHub is left holding a run it can no longer get
status updates for. **Do not blindly re-run it as "just flaky."** Check
first: is the runner that picked it up still online? Does its
`keepalive.log` show a completion for that job, or does the log simply
stop? This exact signature produced a release that reported as "queued
and on track" on GitHub while the runner that owned it was already dead
— caught only because someone checked the actual step list, not just the
run's overall red/green status.
