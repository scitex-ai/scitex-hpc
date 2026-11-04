---
description: |
  [TOPIC] Scheduler-neutral batch jobs
  [DETAILS] Plan, submit, query and cancel single-node batch workloads on
  Slurm or TSUBAME Grid Engine using configured profiles and the shared Python,
  CLI and MCP operations. Preserve uncertain outcomes and resource budgets.
tags: [scitex-hpc-scheduler-portability, slurm, grid-engine, batch]
---

# Scheduler-neutral batch jobs

Use `scitex_hpc.scheduler` when the same single-node workload must target Slurm
or the TSUBAME Grid Engine dialect. The existing `srun`, `sbatch`, `JobConfig`, and `Reservation`
interfaces retain their Slurm semantics. `BatchRequest` describes a workload;
it is distinct from Dev's `JobSpec`, which declares fleet services and timers.

This source adds batch planning, submission, status, and cancellation. It does
not establish site admission or live TSUBAME validation. Interactive allocation,
arrays, MPI, shared allocation reuse, renewal, result retrieval, and Web API
serving are not implemented by this new interface. Existing Slurm facilities
remain available separately; do not infer equivalent Grid Engine capabilities.

## Plan before submitting

```python
from scitex_hpc.scheduler import BatchRequest, ComputeClient, load_profile

client = ComputeClient(load_profile("my-cluster"))
request = BatchRequest(
    argv=("python3", "analysis.py"),
    working_directory="~/proj/my-project",
    cpus=4,
    memory_mib=4096,
    walltime_seconds=60,
)
plan = client.plan(request, name="my-project-check")  # No SSH or submission.
# Inspect plan.command, plan.requested, plan.planned, plan.billing_account,
# plan.resource_type and plan.warnings. allocation_observed remains False.
```

Submission can consume billed resources. Once the selected profile and budget
are appropriate, `client.submit(request, name=plan.name)` returns a `JobHandle`.
Use `client.status(handle)` and `client.cancel(handle)`. The functional Python
entry points `compute_plan`, `compute_submit`, `compute_status`, and `compute_cancel`
return the same domain models; MCP adapters delegate to these functions. Cancellation acknowledgment
does not establish terminal state; query it separately. Stage files using the
existing transport/staging facilities before submitting.

## Profiles

`load_profile(name)` reads `profiles.NAME` from an explicit `path=`, then
`SCITEX_HPC_CONFIG`, then the existing `~/.scitex/hpc/config.yaml` namespace
(relocated by `SCITEX_DIR`). It does not alter legacy `JobConfig` precedence.
Host values reference configured SSH aliases, not another host inventory.

These values are illustrative. Replace aliases, accounts, partitions, resource
types, capacities and limits with verified site settings; they are not validated
TSUBAME defaults. Keep credentials outside this file.

```yaml
profiles:
  my-cluster:
    host: my-slurm-alias
    scheduler: slurm
    account: my-project
    partition: my-cpu-partition
    max_walltime_seconds: 3600
  my-grid-cluster:
    host: my-grid-engine-alias
    scheduler: grid-engine
    dialect: tsubame
    account: my-billing-group
    max_walltime_seconds: 3600
    bundle:
      resource_type: verified_cpu_bundle
      cpus: 4
      memory_mib: 8192
      gpus: 0
```

The Grid Engine profile requires `dialect: tsubame`: billing uses TSUBAME’s
`qsub -g` extension, not the generic Grid Engine `-P` project option. Other
Grid Engine dialects are not implemented. The planner exposes the selected
dialect; it does not certify live site admission.

TSUBAME Grid Engine uses exactly one explicitly selected resource bundle, not an inferred
Slurm partition or GPU flag. Request sizes are minimum CPU, memory and whole-GPU
requirements. Requests exceeding the bundle are refused; excess bundle capacity
is displayed with a warning. Planned capacities come from the configured profile,
not an observed allocation or a verified charging rate.

For batch module setup, a profile may provide `module_init` (an absolute or
home-relative initialization-script path) and `modules` (a list of module names).
Initialization and module loading run in the batch script and must succeed before
the workload starts. Do not copy module names between clusters without checking.

## CLI and MCP

Write the request as JSON, using an array for `argv` and the same resource fields.
The standalone CLI is available without assuming a particular umbrella release:

```bash
scitex-hpc compute plan --profile my-cluster --spec job.json --name my-project-check
scitex-hpc compute submit --profile my-cluster --spec job.json --name my-project-check --yes > job-handle.json
scitex-hpc compute status --profile my-cluster --job-handle job-handle.json --json
scitex-hpc compute cancel --profile my-cluster --job-handle job-handle.json --yes
```

The package's existing FastMCP server registers `compute_plan`, `compute_submit`,
`compute_status`, and `compute_cancel`. The request schema comes from the same
`BatchRequest` dataclass; submit/cancel require `confirm=true`. Select a configured
profile by name. MCP startup diagnostics use scitex-logging on stderr, preserving
JSON-RPC stdout. Confirm an installed umbrella's `scitex hpc --help` routing before
substituting that prefix; no umbrella version is assumed here.

## Interpret uncertain outcomes conservatively

- Query/transport/parse failures, missing exit evidence, and delayed accounting
  produce `unknown`, never successful completion or proof an agent is dead.
- A lost submission response, signal-terminated SSH process, or unrecognized returned ID may mean the job was
  accepted. `SubmissionError` retains the correlation name and outcome. Reconcile
  with the scheduler before another submission; the client never auto-retries.
- Handles include host, scheduler, the native batch ID, and any returned Slurm
  cluster suffix. Pass the complete handle as `job` to MCP status/cancel. Another host/backend,
  array IDs, metadata control characters, path `..`, and option-like identifiers
  are refused. This does not replace host authentication, project authorization,
  filesystem permissions, or admitted Web API scope checks.
- Workload arguments are quoted as data; intentional shell scripts require an
  explicit shell in `argv`. Grid Engine embedded directives and user request-file
  defaults are disabled for the generated script. Slurm submissions clear inherited
  `SBATCH_*` variables so unmodeled environment options do not change the plan.
  This log layout rejects `$` or `%` in the working directory rather than
  accidentally expanding scheduler output placeholders. Grid Engine also rejects
  commas and colons in working directories because its log-path grammar treats
  them as lists and host separators, even when shell-quoted. Do not bypass site policy with
  workload scripts or claim application/container portability from submission alone.

The job runs on scheduler-allocated compute nodes. Do not start scientific
computation, agents, model servers, or synchronization daemons on login nodes.

Scheduler references: [Grid Engine qsub](https://gridscheduler.sourceforge.net/htmlman/htmlman1/qsub.html)
and [TSUBAME scheduler FAQ](https://www.t4.cii.isct.ac.jp/docs/faq.en/scheduler/).
