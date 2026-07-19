---
description: |
  [TOPIC] Permanent Allocation Doctrine
  [DETAILS] When to hold a SLURM allocation vs. dispatch one-shot jobs;
  permanence comes from a VERIFIED, fail-loud self-resubmit, not from the
  walltime requested (a tunable, weighed against queue contention); how
  to empirically verify the real achievable walltime (sacctmgr + sbatch
  --test-only, since sinfo's MaxTime is a ceiling, not a guarantee); how
  to get freshness without re-queuing (container + overlay per unit of
  work); the "zero failing steps" lost-runner detection rule. The resubmit
  chain's FOUR failure modes: it doesn't fire; it fires and the successor
  waits in the queue (16h measured outage — submit EARLY, not at death); a
  healthy SIGUSR1 hop records FAILED/138 so State-keyed monitoring is
  inverted (monitor the OUTCOME, level-triggered on zero); and
  `sbatch "$0"` resubmits the SPOOL COPY, so the script can exist nowhere
  else on disk. Grounded in the 2026-07-13 CI-supervisor incident (resubmit
  trap fired, `sbatch` wasn't on PATH after env hardening, ~74 runners died
  silently for 15-20min with no alarm) and the 2026-07-19 pooled-supervisor
  measurements.
tags: [scitex-hpc-permanent-allocation-doctrine, scitex-hpc, scitex-package]
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
nodes for work that queues fine on its own. A permanent allocation idling
most of the time is exactly the shared-resource pressure Spartan etiquette
exists to prevent.

## How: permanence comes from the verified resubmit, not the walltime

**The walltime you request is a tunable, not the source of durability.** A
14-day allocation with a proven, fail-loud resubmit is *more* permanent
than a 90-day one whose renewal silently fails — the renewal is what keeps
the allocation alive indefinitely, not the number. The 2026-07-13 incident
below is the proof: the resubmit trap fired on schedule, but the resubmit
*call* silently failed, and every dependent runner went dark regardless of
walltime. Get the resubmit right first. Then pick a walltime.
**Picking the walltime — two competing pulls, resolve empirically:**
- Longer walltime = fewer renewal cycles = fewer chances to hit the
  resubmit's one failure mode.
- Under partition contention, a *longer* request can sit queued while a
  *shorter* one schedules immediately — watch queue depth
  (`squeue -p <partition>`) and adjust downward when busy; there is no
  fixed "right" number, only what's schedulable right now.

**`sinfo`'s `MaxTime` is a partition ceiling, not a guarantee** — the real
limit is the tightest of partition MaxTime, QOS MaxWall, and your
account/user association's MaxWall, and `sinfo` only shows the first.
Verify empirically, not from a single read:

```bash
sacctmgr show qos format=Name,MaxWall -P                       # QOS ceiling
sacctmgr show assoc user=$USER format=Account,QOS,MaxWall -P   # your binding limit
sacct -u $USER -X -o JobID,Partition,QOS,Timelimit,State -S <date> -P  # actually granted, historically
sbatch --test-only <script-with-the-walltime-you-want>          # decisive: accepted or rejected
```

Live-verified 2026-07-13 for `punim0264`/`publiccpu` on `sapphire`: both
`sacctmgr` queries returned blank `MaxWall`; `sacct` history showed nothing
beyond the CI supervisor's own 14-day jobs; `sbatch --test-only`
**accepted** a 30-day request and **rejected** 35-day
(`allocation failure: Requested time limit is invalid`). `sinfo`'s 30-day
ceiling happened to be real for this account today — that agreement is a
fact about *this* account, not a property to assume elsewhere. Re-run the
empirical check, don't read the table from memory:

| Partition | `sinfo` MaxTime (ceiling, not a promise) | Empirically confirmed (this account, 2026-07-13) |
|---|---|---|
| `sapphire` (default) | 30-00:00:00 | 30-00:00:00 (`--test-only` accepted; 35d rejected) |
| `gpu-h100` | 7-00:00:00 | 7-00:00:00 (matches largest ever run: job 26987967) |
| `cascade` | 30-00:00:00 | not independently tested — likely matches `sapphire`, don't assume |
| `long` | 90-00:00:00 | not tested |

In production: the CI supervisor runs 14-day walltime on `sapphire` —
inside the confirmed 30-day ceiling, chosen for fewer renewals with
headroom against contention at submission time; qwen runs 7-day walltime
on `gpu-h100`, at that partition's confirmed ceiling (GPU has less slack).

### The resubmit pattern — and its four real failure modes

```bash
#SBATCH --signal=B:USR1@3600   # SLURM signals 1h before the walltime boundary
trap _resubmit USR1
```

SLURM's documented signaling mechanism (see
[12_reservation-features.md](12_reservation-features.md) for the
`Reservation(persistent=True)` wrapper) — not a daemon, not a cron
@reboot, compatible with the no-daemon IT Security ruling
([13_compatibility-policies.md](13_compatibility-policies.md)).
**A permanent allocation WILL hit its walltime boundary; the only question
is whether the handoff to a successor job is verified, or merely hoped
for.** On 2026-07-13 the CI supervisor's trap fired on schedule, but the
resubmit call itself —

```bash
_resubmit() { sbatch "$0"; }   # WRONG: assumes `sbatch` is still on PATH
```

— failed with `sbatch: command not found`: the script's own env-hardening
(`module purge` + a PATH scrub for secret/easybuild isolation) ran *after*
the trap was registered but had already stripped `/apps/slurm/latest/bin`
off PATH by the time USR1 fired. No successor job was ever submitted.
SLURM recorded the exit as `FAILED/138` (`128+SIGUSR1`) — a code that
reads as "killed by a signal", not "resubmit silently no-op'd". All ~76
dependent runners died with zero alarm, caught only by a human/agent
noticing the job had vanished from `squeue` 15-20 minutes later.
**The durable pattern, not just the one-off fix:**

```bash
# Resolve the resubmit binary's ABSOLUTE PATH before any env hardening runs.
SBATCH_BIN="$(command -v sbatch 2>/dev/null)"
[ -x "$SBATCH_BIN" ] || SBATCH_BIN="/apps/slurm/latest/bin/sbatch"

_resubmit() {
  if [ -x "$SBATCH_BIN" ] && "$SBATCH_BIN" "$0"; then
    rm -f "$FAIL_MARKER" 2>/dev/null
  else
    # FAIL LOUD: a silent no-op resubmit is worse than a visible crash —
    # nothing else in the system knows to page anyone.
    echo "$(date -u +%FT%TZ) resubmit failed; SBATCH_BIN='$SBATCH_BIN'" \
      > "$FAIL_MARKER"
  fi
}
trap _resubmit USR1
# ... only THEN do module purge / PATH scrubbing / secret hardening ...
```

Any script that hardens its own environment and *also* self-resubmits must
resolve the resubmit binary before the hardening step — hardening can
silently break a mechanism defined earlier in the same script. A sentinel
file alone is necessary but not sufficient: something must actually watch
it and alert (a genuinely independent check, not the script policing
itself — the single point of failure that failed here).

That was failure mode 1: **the resubmit does not fire.** It is the loudest
of the four and the only one the pattern above defends against. The other
three were measured on 2026-07-19 on the pooled CI supervisor
(`spartan-ci-runner-pooled-supervisor`), whose chain was working correctly
by every check anyone had thought to run. All three share a shape: the
mechanism is healthy, and its health is indistinguishable from the thing
you actually care about being broken.

#### 2. The resubmit fires, and the successor waits in the queue

`_resubmit` calls `sbatch` and the incumbent then exits. The successor is
now a normal PENDING job competing for the partition — so the handoff is
only instant if the scheduler happens to be generous at that moment.
Measured across five renewals of a 24h chain on `sapphire`:

```
job        submitted             started               queue wait
27225547   2026-07-14T12:21:16   2026-07-14T12:22:20   64s
27281296   2026-07-15T11:21:52   2026-07-15T13:24:27   2h 02m
27331011   2026-07-16T12:24:26   2026-07-17T04:27:04   16h 03m   <-- service down
27481243   2026-07-18T03:26:57   2026-07-18T03:27:24   27s
27544359   2026-07-19T02:27:08   2026-07-19T02:27:28   20s
```

**Those timestamps are cluster-local (Spartan is UTC+10), as everything
`squeue`/`sacct` prints is.** The queue waits are differences and so are
timezone-independent, but do not plan a maintenance window off a raw SLURM
timestamp without converting it — reading one as UTC on this cluster
overstates your remaining runway by ten hours, in the direction that has
you arrive after the event you meant to precede. `squeue --format=%L`
(time *remaining*) sidesteps the conversion entirely and is the safer
thing to key on.

Every successor was submitted ~1 second *before* its predecessor's end, so
the entire gap is unserved queue wait. ~18h of downtime across six days,
on the fleet's only `scitex-ci` runner path. Nothing failed. No marker was
written. CI simply stopped draining, in a state indistinguishable from
ordinary slowness.

**Submit the successor EARLY, not at death.** Let it start and idle until
the incumbent exits: the queue wait is then served while the service is
still up, and the gap closes by construction rather than by getting lucky.
The cost is one briefly-idle allocation per handover.

Note what does *not* fix this: a longer walltime. It reduces how often you
run the lottery without changing the odds of any single draw, and on a
contended partition a longer walltime is itself harder to schedule — see
the walltime section above. Reducing the frequency of an unbounded outage
is not the same as bounding it.

#### 3. `State` is inverted, so State-keyed monitoring is worse than none

A healthy SIGUSR1 renewal exits `FAILED / ExitCode 138:0` — `128+10`,
killed by its own signal. Every successful hop in the table above is
recorded `FAILED`. A monitor keyed on job State therefore alarms on every
*success*, gets muted inside a week, and is then silent for the real
failure — while still reading, to anyone glancing at the dashboard, as
coverage.

**Do not monitor the mechanism; monitor the outcome.** For a CI supervisor
the availability SLI is "is a runner registered and online for this label
right now", which is observable without touching SLURM at all, goes red for
the 16h gap above, and stays green across all five `FAILED/138` exits. It
also survives a redesign of the supervisor, because it asks about the
service rather than the implementation.

Make it **level-triggered on zero**, evaluated fresh each run with no
memory of prior state. A drop-detector only fires if it observed the
transition, so an outage beginning while the monitor is down stays
invisible forever — precisely the case it exists to catch. And a monitor
that cannot reach its data source must report UNKNOWN distinctly, never
"fine".

#### 4. `sbatch "$0"` means the script may exist nowhere but the spool

```bash
_resubmit() { "$SBATCH_BIN" "$0"; }   # $0 is /var/spool/slurm/job<N>/slurm_script
```

Inside a running batch job, `$0` is **SLURM's per-job spool copy**, not the
file you submitted. Each hop therefore resubmits the copy SLURM made for
it, and SLURM makes a fresh copy for the successor. The script propagates
itself hop to hop and can exist nowhere else on disk — as was the case for
the pooled CI supervisor, which had no copy in `$HOME`, none beside the
runners, and none in any repo.

A chain in that state works perfectly right up until it doesn't. One
`scancel`, one node failure at the wrong moment, or failure mode 1, and the
script is not merely stopped — it is **gone**, with nothing to resubmit
from and no CI available to validate a rewrite.

**Keep the script in version control and submit it from there.** `$0` may
be a spool copy; a path you chose is not. This also changes how you patch a
running chain: editing the spool copy in place *would* propagate to the
next hop, which is exactly why it is the wrong instinct — it perpetuates
the condition. Patch the version-controlled script and cut the chain over
once, deliberately.

The recovery, if you inherit a chain with no source, is one command and
costs nothing:

```bash
srun --jobid=<held-allocation-id> --overlap -n1 \
    cp /var/spool/slurm/job<N>/slurm_script /path/in/version/control/supervisor.sh
```

### Concurrency inside the held allocation: `srun --overlap`

Do not re-allocate per unit of work — run units of work as **steps inside
the held allocation**:

```bash
srun --jobid=<held-allocation-id> --overlap <cmd>
```

`--overlap` lets multiple steps share the allocation's resources
concurrently instead of serializing on it. Verified live (see
[13_compatibility-policies.md](13_compatibility-policies.md)) and used in
production for the CI runner fleet's stuck-busy reaper (a background
`srun --overlap` step against the supervisor's own job).

### Freshness without re-queuing: discard the environment, not the allocation

The temptation, once state has rotted (a corrupted local config, leaked
`/tmp` scratch, a stale credential), is to re-provision the whole
allocation. Don't — that reintroduces the queue-latency cost the
permanent allocation exists to avoid. Instead, discard the *environment*
each unit of work runs in:

- A shared, read-only Apptainer base SIF.
- A **fresh overlay per unit of work**, created at start, destroyed at end
  (`ACTIONS_RUNNER_HOOK_JOB_STARTED` / `_JOB_COMPLETED` are the supported
  integration points for GitHub Actions runners; `JOB_COMPLETED` is
  already live in production, clearing `$RUNNER_TEMP` on every job).
- The allocation persists; only the overlay is new. Start cost is seconds
  (Apptainer exec), not a scheduler round-trip.

This kills per-machine state rot **by construction**, not by remembering
to clean up. It was the direct fix for the 2026-07-12 incident class: a
corrupted `~/.config/gh/config.yml` on one long-lived runner silently
broke that repo's releases for hours, because nothing ever discarded its
`$HOME`-adjacent state between jobs. N long-lived machines each holding
mutable state is N places for it to rot; a shared base image + a
disposable overlay per job removes the "N places" entirely.

## Detection rule: zero failing steps means a lost runner, not a flaky test

A CI run that reports **failed with zero failing steps** is not a test
flake — it is the signature of the runner itself dying mid-job (crashed,
OOM-killed, walltime-killed, network-partitioned) before it could report
which step it was on. **Do not blindly re-run it as "just flaky."** Check
first: is the runner that picked it up still online, and does its
`keepalive.log` show a completion for that job or just stop? This exact
signature once produced a release that reported "queued and on track" on
GitHub while the runner that owned it was already dead — caught only
because someone checked the actual step list, not the run's red/green
status.
