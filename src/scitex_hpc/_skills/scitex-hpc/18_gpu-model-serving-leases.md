---
description: |
  [TOPIC] GPU model-serving leases
  [DETAILS] Hold scarce 80 GB GPU pairs persistently and run model replicas as
  srun --overlap steps without computing on the login node.
tags: [scitex-hpc-gpu-model-serving-leases, gpu, model-serving, slurm]
---

# GPU model-serving leases

`scitex-hpc` owns allocation and resubmission, not the inference engine. Let
`scitex-genai-serve launch` compose the held lease and one supervised
`srun --overlap --ntasks=1 --exact` step per tensor-parallel GPU group.

Never load weights, compile kernels, or benchmark on the Spartan login node.
Use it only to inspect/submit. The complete Qwen 1M+MTP profile requires two
verified H100 80 GB GPUs with TP=2; one H100 does not have safe usable
capacity, and L40S 48 GB is not suitable. Partition visibility does not imply
account eligibility or VRAM size.

Preserve queue position: replace the exact TP=2 step inside the running
allocation instead of cancelling the job. Identify the step and both rank
processes before `scancel JOB.STEP`. A second two-H100 lease is required to
keep another replica healthy during a roll. The lease alone owns walltime
resubmission. Use absolute Slurm binary paths on Spartan and verify that a
successor exists before expiry.

For commands, resource checks, handoff invariants, and the current recorded
job snapshot, read `docs/SETUP_LOCAL_LLM.md` in the source checkout.
