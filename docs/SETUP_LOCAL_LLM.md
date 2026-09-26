# Allocating Spartan GPUs for local LLM serving

`scitex-hpc` owns the allocation lifecycle only. `scitex-genai` owns the
SGLang process, model profile, sidecars, tunnels, and gateway;
`scitex-agent-container` consumes the gateway.

## Non-negotiable boundary

The Spartan login node is for SSH, scheduler inspection, file transfer, and
submission. Never load a model, compile CUDA kernels, benchmark inference, or
run another computationally heavy task there. Run those inside an allocation
with `srun --overlap`.

## Discover capacity without assuming access

```bash
ssh spartan '/apps/slurm/latest/bin/sinfo -o "%P %a %l %D %t %G"'
ssh spartan '/apps/slurm/latest/bin/squeue -u "$USER" \
  -o "%.18i %.12P %.30j %.10T %.10M %.10l %.20R"'
```

Qwen3.8-27B with the proven 1M+MTP profile requires a pair of 80 GB GPUs.
H100 80 GB with TP=2 is known-good. An A100 partition name alone does not prove
its VRAM or that the account can allocate it; validate the allocated pair with
`nvidia-smi --query-gpu=name,memory.total --format=csv` inside the job. L40S
48 GB cannot host this 1M profile.

## Preferred lease pattern

Book a persistent pseudo-long-running job, then put the real model servers in
overlapping job steps. The canonical cross-package command is:

```bash
scitex-genai-serve launch qwen38-27b-sglang \
  --lease qwen38-27b-serve --host spartan --gpus h100:2 \
  --partition gpu-h100 --time 7-00:00:00
```

This creates one `srun --overlap --ntasks=1 --exact` engine step and waits in
the batch body. The Qwen profile uses TP=2 across both GPUs. The lease, not the
engine step, owns walltime resubmission. A second cache-balanced replica needs
a second two-H100 lease; never launch two TP=2 profiles in one two-GPU job.

For an already-held allocation:

```bash
ssh spartan '/apps/slurm/latest/bin/srun --overlap --jobid=JOB_ID \
  --ntasks=1 --exact COMMAND ...'
```

Never start the long-running engine as a plain login-node process.

## Inspect and roll safely

```bash
ssh spartan '/apps/slurm/latest/bin/scontrol show job JOB_ID'
ssh spartan '/apps/slurm/latest/bin/squeue -s -u "$USER"'
ssh spartan '/apps/slurm/latest/bin/scontrol show step JOB_ID.STEP_ID'
```

Map a step using its command line, port, CUDA visibility, and GPU processes
before cancellation. Cancel only its exact step, wait for both rank processes
and its tunnel to disappear, then start the replacement with `srun --overlap`.
Zero-downtime rolling requires another two-GPU lease; restarting within one
pair has a short outage. Never cancel the allocation merely to change engine
code; scarce GPU queue position is the resource the lease preserves.

## Walltime handoff

A durable lease submits its successor before expiry and continues serving to
the actual walltime. Use absolute Slurm binary paths because non-interactive
batch PATHs on Spartan may omit `srun` and `sbatch`. The resubmit logic belongs
to one layer only; engine steps must not submit successors independently.

After a handoff, verify outcome rather than trusting job name or state:

- a successor job exists and eventually becomes RUNNING;
- the new node has one TP=2 engine spanning both GPUs;
- its reverse tunnel answers from `scitex-compute-04`;
- the single gateway port reports the upstream healthy;
- the running command comes from `scitex-genai`, not `~/serve-model.sh`.

`sbatch "$0"` from a running batch script can resubmit Slurm's frozen spool
copy. The canonical launcher must be a stable package path so fixes reach the
next generation.

## Snapshot on 2026-09-09 UTC

- active: job `29965837`, `spartan-gpgpu179`, two H100s, ends
  `2026-09-11T12:34:52`;
- SGLang TP=2: step `29965837.982` using `--overlap`, with 2,180,158 usable
  KV slots and a configured 1M request ceiling;
- queued successor: `30024585`, pending priority;
- other visible GPU partitions included H100, A100, and L40S variants, but
  visibility is not proof of account eligibility or 80 GB capacity.

See `scitex-genai/docs/SETUP_LOCAL_LLM.md` for engine and gateway operations.
