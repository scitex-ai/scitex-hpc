#!/bin/bash
#SBATCH --partition=gpu-h100
#SBATCH --nodes=1
#SBATCH --gpus-per-node=2
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=7-00:00:00
#SBATCH --account=punim0264
#SBATCH --qos=publicgpu
#SBATCH --signal=B:USR1@3600
#SBATCH --output=/data/scratch/projects/punim0264/ywatanabe/serve-logs/%x-%j.log
# ---------------------------------------------------------------------------
# Hold a MULTI-GPU allocation and run ONE serve-model.sh per GPU inside it.
#
#   usage:  sbatch --job-name=<name> serve-pair.sh KEY_A KEY_B
#   e.g.    sbatch --job-name=qwen38-27b-serve serve-pair.sh qwen38-27b qwen38-27b-b
#
# WHY THIS EXISTS. serve-model.sh runs exactly ONE engine, and the operator's
# 2026-08-15 ruling is one instance PER GPU rather than one model spread across
# GPUs (TP=1). So a 2-GPU allocation needs two engines, and `sbatch
# serve-model.sh <key>` would idle a card. Until now the second engine was
# added by hand with `srun --overlap` after the job started -- which works, and
# is invisible to anyone reading the job later, and is not reproduced when the
# job resubmits itself at walltime.
#
# GPU PINNING IS NOT DONE HERE. Each conf exports its own
# CUDA_VISIBLE_DEVICES, because serve-model.sh SOURCES the conf and the export
# reaches the vllm child. Setting it here as well would silently override the
# confs and put both replicas on one card, where the second OOMs against the
# first. The conf is the load-bearing place; this script must not compete with
# it.
#
# THE STEPS DO NOT RESUBMIT THEMSELVES. `--signal=B:USR1@3600` has the `B:`
# prefix, which delivers USR1 to the BATCH SHELL ONLY and not to job steps. So
# serve-model.sh's own USR1 trap never fires under this wrapper and cannot
# submit a duplicate chain. Removing the `B:` would produce three resubmissions
# per walltime instead of one.
# ---------------------------------------------------------------------------
set -uo pipefail

KEY_A=${1:-}
KEY_B=${2:-}
if [ -z "$KEY_A" ] || [ -z "$KEY_B" ]; then
  echo "usage: sbatch serve-pair.sh KEY_A KEY_B" >&2
  exit 2
fi

# Captured BEFORE anything redirects HOME, same reason as in serve-model.sh.
REAL_HOME=${HOME:-/home/ywatanabe}
SERVE=$REAL_HOME/serve-model.sh
SELF=$REAL_HOME/serve-pair.sh

[ -r "$SERVE" ] || { echo "FATAL: $SERVE unreadable" >&2; exit 2; }

# Resubmit from the CANONICAL path, never "$0" -- inside a batch job $0 is the
# node-local spool copy, so resubmitting it freezes the script forever. That
# defect left job 29265170 still serving Qwen3.6 on unreachable ports months
# after the qwen38 migration. See serve-model.sh's _resubmit for the full note.
_resubmit() {
  echo "[pair] walltime; resubmitting $KEY_A + $KEY_B" >&2
  if [ -r "$SELF" ]; then
    sbatch --job-name="${SLURM_JOB_NAME:-qwen-serve}" "$SELF" "$KEY_A" "$KEY_B"
  else
    echo "[pair] WARNING: $SELF unreadable; resubmitting the SPOOL COPY \"$0\"." \
         "The successor will run this job's frozen script. Restore $SELF." >&2
    sbatch --job-name="${SLURM_JOB_NAME:-qwen-serve}" "$0" "$KEY_A" "$KEY_B"
  fi
}
trap _resubmit USR1

echo "[pair] $(date -u +%FT%TZ) job=${SLURM_JOB_ID:-?} node=$(hostname -f) keys=$KEY_A,$KEY_B"

# One supervised step per engine. --overlap lets both share the allocation;
# without it the second step blocks waiting for resources the first holds.
# Each runs in BACKGROUND and we `wait`, so the USR1 trap can actually be
# delivered -- a foreground child would block trap delivery until it exits.
_spawn() {
  local key=$1
  while true; do
    echo "[pair] $(date -u +%FT%TZ) starting step for $key" >&2
    srun --overlap --ntasks=1 --exact bash "$SERVE" "$key"
    echo "[pair] $(date -u +%FT%TZ) step $key exited rc=$?; restart in 30s" >&2
    sleep 30
  done
}

_spawn "$KEY_A" &
PID_A=$!
_spawn "$KEY_B" &
PID_B=$!

echo "[pair] supervising pids $PID_A ($KEY_A) and $PID_B ($KEY_B); holding"
wait
