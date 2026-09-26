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
serve-model.sh     starts and supervises ONE engine
serve-pair.sh      holds a multi-GPU allocation, one serve-model.sh per GPU
models.d/*.conf    one small config per served engine
```

## `serve-pair.sh` — the pairing is a script, not a habit

`serve-model.sh` runs exactly one engine, and the operator's 2026-08-15 ruling
is one instance **per GPU** rather than one model spread across GPUs (TP=1). So
a 2-GPU allocation needs two engines:

```sh
sbatch --job-name=qwen38-27b-serve serve-pair.sh qwen38-27b qwen38-27b-b
```

Until now the second engine was added **by hand** with `srun --overlap` after
the job had started. That works, is invisible to anyone reading the job later,
and — crucially — is not reproduced when the job resubmits itself at walltime.
A step that only exists because someone typed it does not survive the thing it
was meant to survive.

Three things it deliberately does **not** do, each of which is how the obvious
implementation breaks:

- **It does not set `CUDA_VISIBLE_DEVICES`.** Each conf exports its own, and
  `serve-model.sh` *sources* the conf, so the export reaches the vLLM child.
  Setting it in the wrapper would silently override the confs and put both
  replicas on one card, where the second OOMs against the first. The conf is
  the load-bearing layer; the wrapper must not compete with it.
- **It does not let the steps resubmit themselves.** `--signal=B:USR1@3600` —
  the `B:` prefix delivers USR1 to the *batch shell only*, never to job steps,
  so `serve-model.sh`'s own trap cannot fire under the wrapper. Dropping `B:`
  would produce three resubmissions per walltime instead of one.
- **It does not run the engines in the foreground.** They are backgrounded with
  `wait`, because a foreground child blocks trap delivery until it exits — the
  trap would simply never run.

### A known asymmetry, documented rather than "fixed"

| key | pin |
|---|---|
| `qwen38-27b-b` | `CUDA_VISIBLE_DEVICES=1` |
| `qwen38-27b` | none — relies on vLLM defaulting to GPU 0 |
| `qwen38-27b-c`, `-d` | none — single-GPU nodes, correct as-is |

The pair works because B pins to card 1 and A takes card 0 by default. That is
correct today but *implicit*. It is recorded here rather than corrected,
because those confs are currently driving live engines and an unrequested
change to a load-bearing file — to make something already working more
explicit — is how a working system becomes a broken one.

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

## The engine publishes its own identity

Two defects were found on 2026-08-16 and are fixed. Both were cases of identity
being asserted once, by hand, and never revisited.

**1. The job now names itself.** `_resubmit` had always submitted as
`$KEY-serve`, so a job that resubmitted was named correctly. The drift came
from the other path: repointing a live allocation with `srun --overlap` — the
technique for swapping models *without releasing a node* — renames nothing, so
the allocation keeps whatever it was first called. On 2026-08-16 all three
serving jobs were named for models that had stopped days earlier
(`muse-serve-permanent` and `gptoss-serve-permanent` were both running
qwen38-27b). That naming led to a proposal to release a **live** allocation,
which is irreversible here, and to two false claims about a dependency on an
already-stopped model.

The name is `<served-name>-serve-<node>`, e.g. `qwen38-27b-serve-spartan-gpgpu178`.

**It is deliberately not built from `$KEY`,** even though `_resubmit` uses
`$KEY-serve` and that was the obvious thing to reuse. One allocation can hold
several engines: gpgpu178 runs keys `qwen38-27b` and `qwen38-27b-b` as two
`srun --overlap` steps sharing **one** job id. A `$KEY`-derived name would have
those two steps write *different* names to the same job — last-write-wins, and
the name flaps depending on which finished loading last.

Every engine in one allocation agrees on `SERVED_NAME` and on the node, so
every step computes the same string and the update is idempotent regardless of
how many replicas run or in what order they become ready. Choosing the name
from what the steps **share** rather than from what distinguishes them is what
makes concurrent writers safe here.

**2. The discovery entry is now withdrawn on exit.** It was written on ready
and never removed, so a stopped model left a record indistinguishable from a
live one. The directory held eight entries of which four described models that
had not run for days — a 50% false-positive rate for anyone following the
protocol this script's own header prescribes.

A trap cannot cover `SIGKILL` or a node failure, so removal is necessary and
not sufficient. The record therefore also carries `job_id`, letting a reader
confirm the owning allocation still exists instead of trusting the file's
presence. Absence of a record now means absent; presence still has to be
checked.

Both live at the READY block, which is where the model is proven up. An
identity published before `/health` answers would be a claim rather than an
observation.

## Why there is no port table here any more

The header used to carry one, listing each model's vllm/litellm/tunnel ports.
It is deliberately gone rather than corrected: on 2026-08-16 it still described
three models that had stopped and named none of the four engines actually
serving.

That table was one of **three** descriptive layers that had rotted together —
the SLURM job names and the discovery directory were the others — and each
looked authoritative on its own. The confs stayed correct throughout.

The confs stayed correct because `serve-model.sh` **reads** them. They are
load-bearing; a comment is not. So the fix is not to update the table but to
not keep one:

```
grep -H '^\(VLLM\|LITELLM\|TUNNEL\)_PORT=' $CONFD/*.conf
```

The one thing still written down is the reservation of port 18765 for the
`codex` provider — because that is **not** derivable from the confs. It is a
constraint imposed from outside this script, and the confs record only what we
did allocate, never what we must not.

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
