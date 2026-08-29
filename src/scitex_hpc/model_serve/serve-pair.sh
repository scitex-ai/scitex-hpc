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
#
# RESUBMIT AT MOST ONCE. Until 2026-08-29 this was implicit: the trap ended the
# job (the bare trailing `wait` fell through), so a second USR1 had nothing left
# to interrupt. Now that the script survives the signal and keeps serving to
# walltime, a repeated USR1 would call sbatch again and queue a SECOND successor
# for the same pair -- two jobs competing for GPUs on a queue where one already
# waits ~30h. The guard is the price of the fix and belongs with it.
_RESUBMITTED=0
_resubmit() {
  if [ "$_RESUBMITTED" -ne 0 ]; then
    echo "[pair] USR1 again; successor already submitted, ignoring" >&2
    return 0
  fi
  _RESUBMITTED=1
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

# RE-ENTER THE WAIT. A bare trailing `wait` ENDS THIS JOB THE MOMENT THE USR1
# TRAP FIRES, an hour before walltime.
#
# `wait` is interrupted by a delivered signal and does NOT resume by itself.
# With `wait` as the final statement the sequence was:
#   USR1 at T-3600 -> wait returns -> _resubmit runs (correctly, sbatch fires)
#   -> control falls off the end of the script -> ALLOCATION DIES AT T-3600
#
# Two costs, both measured on this fleet 2026-08-29:
#   1. ONE HOUR of serving thrown away every generation. The successor is
#      already queued by then, but it waits for a GPU -- observed 30h11m on
#      29644207 -- so the hour is pure additional outage, not a handover.
#   2. The script's exit status becomes wait's 128+10 = 138, so a job whose
#      handoff SUCCEEDED is recorded FAILED. Anyone auditing serve reliability
#      by sacct state -- the obvious way -- reads a working mechanism as a
#      failure. Four such jobs read that way before this was understood.
#
# Reproduced directly rather than inferred from the bash manual: background
# supervisors + bare trailing `wait` + `kill -USR1` prints
# "FELL THROUGH past wait -- script is ending".
#
# The loop below keeps both engines serving until SLURM's own walltime kill,
# which is the honest end for a job that served its full allocation. It is
# guarded on the supervisors being alive rather than being `while true`, so if
# both _spawn loops ever do exit this terminates instead of spinning on a
# `wait` that returns 0 immediately.
while kill -0 "$PID_A" 2>/dev/null || kill -0 "$PID_B" 2>/dev/null; do
  wait
done
