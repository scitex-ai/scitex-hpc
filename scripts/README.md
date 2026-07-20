# scripts/

Standalone host-side helper scripts for the Spartan integration (not part of the
`scitex_hpc` Python package).

## `ci-pooled-supervisor.sh`

The sbatch script holding the permanent allocation that hosts the pooled,
org-level GitHub Actions runners — including `spartan-pooled-cpu-01`, which
carries the `scitex-ci` label the shared CI template targets.

- **This file is the SOURCE OF TRUTH. Submit it from here.** It previously
  existed *only* as SLURM per-job spool copies: `_resubmit` runs
  `sbatch "$0"`, and inside a batch job `$0` is
  `/var/spool/slurm/job<N>/slurm_script`. Each hop resubmitted the copy SLURM
  made for it, so the script propagated hop to hop and lived nowhere else on
  disk. One `scancel` and it would have been unrecoverable — with no CI
  available to validate a rewrite. Recovered 2026-07-19
  (md5 `a4074b1a416340a5f6ca9b4b17ea685c`, byte-identical to the running copy).
- **Never patch the spool copy.** Editing it *would* propagate via
  `sbatch "$0"`, which is exactly why it is the wrong instinct — it perpetuates
  the no-durable-source condition. Patch here, then cut the chain over once.
- **Walltime is 24h deliberately, not by oversight.** A 64c/128GB request
  backfills within seconds at 24h and is genuinely Priority-blocked at 14 days
  on `sapphire` under current congestion. Permanence comes from the resubmit,
  not the walltime. Re-verify empirically before changing it.
- **Adding runners needs no edit to this file.** `_scan_and_spawn` globs
  `$CI/actions-runner-*/` and rescans every `RESCAN_INTERVAL` (300s), so a new
  runner directory is adopted within five minutes, with no restart.
- **Monitoring must not key on SLURM job State.** A healthy hop exits
  `FAILED / ExitCode 138:0` (`128+SIGUSR1`), so a State-keyed alarm fires on
  every *success*. Key on the outcome instead — online runners carrying the
  `scitex-ci` label, level-triggered on zero.

Background and the four resubmit-chain failure modes:
`src/scitex_hpc/_skills/scitex-hpc/14_permanent-allocation-doctrine.md`.

## `qwen_tunnel.sh`

Maintains a stable host-side endpoint for the Spartan-hosted **qwen** LLM,
auto-re-pointed when qwen reschedules to a new GPU node.

- **Problem it solves:** qwen serves behind a key-gated LiteLLM proxy on an
  *ephemeral* Spartan GPU node. The node changes on every walltime resubmit, so
  a fixed tunnel breaks. Agent containers also live on a different host than
  Spartan and can't reach the GPU node directly.
- **How:** the qwen holder publishes the current node to a discovery JSON on
  Spartan shared storage (`/data/scratch/.../qwen-endpoint.json`). This script
  polls it and keeps an `ssh -L 127.0.0.1:<port> -> <current node>:4000` forward
  alive, re-establishing on node change. Because agent containers share the host
  network namespace, every container reaches qwen at `http://127.0.0.1:<port>`.
- **Deployment:** runs as a host `systemd --user` unit on the agent host
  (`Restart=always`, after `network-online.target`). Requires a working
  key-based `ssh spartan` (BatchMode) in the operator account. The systemd unit
  + install commands are owned by scitex-agent-container.
- **Config:** `QWEN_LOCAL_PORT` (4000), `QWEN_SSH_HOST` (`spartan`),
  `QWEN_TUNNEL_POLL` (30s), `QWEN_DISCOVERY` (discovery json path).

Companion pieces: the serving side (`~/.scitex/hpc/scripts/spartan-gpu-h100-qwen.sh`,
which publishes the discovery file) and the client side (scitex-genai's
`base_url` support). Tracked on scitex-todo card `qwen-serving-reachable`.
