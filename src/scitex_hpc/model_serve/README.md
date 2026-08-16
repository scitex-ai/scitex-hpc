# `model_serve` — the script that serves every local model

`serve-model.sh` starts one vLLM engine, a LiteLLM sidecar, and a reverse
tunnel, then supervises all three for the life of a SLURM allocation. Every
locally served model on Spartan runs through it.

Until 2026-08-16 it existed **only** at `~/serve-model.sh` on the Spartan login
node. One copy, on one host, with no author, no date, and no diff — while
carrying the reasoning behind several fixes that were expensive to find:

- the `#SBATCH --signal=B:USR1@600` line, without which the resubmit trap was
  installed-but-unreachable and every serve job died at walltime (a measured
  9-hour gap between one job ending and its replacement being started by hand);
- `ControlMaster=no` / `ControlPath=none` on the tunnel, without which `ssh -R`
  attaches to an existing mux master, exits 0 in two seconds, and leaves the
  forward's lifetime tied to something other than this job;
- node-local cache paths, because `/data/gpfs/projects/punim0264` sits at 99%
  of its 8,000,000-file inode quota and anything cache-shaped written there
  fails the job.

Each of those comments is a bug someone paid for. None of them was recoverable
from anywhere but that single file.

This package is the same treatment already given to the pooled CI supervisor
(#64) and the shared-tree monitor (#83/#84).

## Layout

```
serve-model.sh     the script, captured verbatim from Spartan
models.d/*.conf    one small config per served engine
```

`serve-model.sh <KEY>` reads `models.d/<KEY>.conf`. The conf is sourced **once**
at startup, so a conf change takes effect when the *script* restarts — not when
vLLM restarts. The supervision loop restarts only vLLM, so editing a conf under
a running job does nothing until the allocation is resubmitted.

## The four live engines

| key | vLLM | LiteLLM | tunnel | node |
|---|---|---|---|---|
| `qwen38-27b` | 8768 | 4003 | 18773 | gpgpu178 |
| `qwen38-27b-b` | 8769 | 4004 | 18774 | gpgpu178 |
| `qwen38-27b-c` | 8770 | 4005 | 18775 | gpgpu176 |
| `qwen38-27b-d` | 8771 | 4006 | 18776 | gpgpu119 (A100) |

All four serve the same model. One instance **per GPU** rather than one model
spread across GPUs — the operator's ruling, 2026-08-15.

Confs for `gpt-oss-120b`, `qwen36-35b-a3b` and `muse-glimmer-30b` were
deliberately **not** captured. Those models stopped running days ago, and
importing dead configuration into a fresh package would reproduce the exact
rot this package was created in response to. They remain on Spartan and in
`$DISCD/.old/` if ever needed.

## Known defects, not yet fixed here

This file is a **verbatim capture**. It is committed unchanged so that the
script has a history before it has edits, and so the next commit's diff is
exactly the behaviour change and nothing else. Two defects are known and
deliberately left for that commit:

1. **The job name is never set.** The script starts a model but does not name
   the allocation after it, so a job repointed at a new model keeps its old
   name. On 2026-08-16 all three serving jobs were named for models they no
   longer ran (`muse-serve-permanent` serving qwen38, and so on). That naming
   led an operator to propose releasing a live allocation, and led this agent
   to twice assert a dependency on a model that had already stopped. A name is
   the cheapest thing in the system to read, so it is the thing everyone reads
   first; when it lies it does not fail loudly, it produces confident and
   well-reasoned wrong plans.

2. **The discovery file is written on ready and never removed.** The header
   states that a consumer should enumerate `$DISCD/*-endpoint.json` rather than
   hardcode a port — so that directory is the sanctioned answer to "what is
   served where". On 2026-08-16 it held eight entries of which four described
   models that no longer existed: a 50% false-positive rate for anyone
   following the documented protocol. The four live entries were correct and
   current, so the mechanism works; nothing deletes an entry when a model
   stops, and write-on-start without remove-on-stop guarantees this outcome
   given time.

Both fixes belong at the READY block, which already publishes the discovery
file and is therefore where identity should be published.

## Why the confs are the only layer that stayed honest

Four places describe what is being served: the SLURM job name, the port table
in this script's header, the discovery directory, and these confs. On
2026-08-16 the first three all described a superseded world, and each looked
authoritative on its own. The confs were correct.

The confs are correct because `serve-model.sh` **reads** them. They are
load-bearing; the other three are descriptive. That is the rule worth taking
from this, and it is better than "keep the documentation updated": a record
that nothing reads will rot, so either make it load-bearing or delete it.
Descriptive copies of executable facts are debt with a due date.
