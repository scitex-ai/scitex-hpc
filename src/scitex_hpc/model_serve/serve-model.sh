#!/bin/bash
#SBATCH --partition=gpu-h100
#SBATCH --nodes=1
#SBATCH --cpus-per-task=16
#SBATCH --time=7-00:00:00
#SBATCH --mem=128G
#SBATCH --account=punim0264
#SBATCH --qos=publicgpu
#SBATCH --output=/data/scratch/projects/punim0264/ywatanabe/serve-logs/%x-%j.log
#SBATCH --signal=B:USR1@600
# ARMED 2026-08-15. Without this line SLURM never sends USR1, so the
# _resubmit trap below was installed-but-unreachable: every serve job
# ran its full 7 days, ended FAILED at walltime, and was restarted by
# hand (measured 9h gap between 28534846 ending and 28939737 starting).
# A trap with no signal is a recovery path that reads as present in
# the source and is absent in behaviour.
# ---------------------------------------------------------------------------
# ONE serve script for EVERY locally served model. Generalised from
# qwen-h100-cutover.sh rather than copied from it: three hand-copied scripts
# would be three places to fix every future bug, and they drift.
#
#   usage:  serve-model.sh <MODEL_KEY>
#   config: $CONFD/<MODEL_KEY>.conf   (one small file per model)
#
# GPU COUNT IS NOT IN THE HEADERS ON PURPOSE. It differs per model
# (qwen BF16 needs TP=2, gpt-oss MXFP4 needs 1), and an #SBATCH line cannot
# read the conf. Submit with the count on the command line, where it overrides
# the headers:
#   sbatch --job-name=gptoss-serve --gpus-per-node=1 serve-model.sh gpt-oss-120b
# or run inside an allocation you already hold:
#   srun --overlap --jobid <JOBID> bash serve-model.sh gpt-oss-120b
#
# EVERY MODEL WRITES ITS OWN DISCOVERY FILE, so a consumer enumerates
# $DISCD/*-endpoint.json to see what is being served instead of hardcoding a
# port. That is what makes "switch between models" real rather than manual.
#
# PORT ALLOCATIONS ARE CENTRAL, IN THE CONFS, AND MUST NOT COLLIDE.
# THE CONFS ARE THE ONLY RECORD OF THEM. There used to be a table here listing
# each model's vllm/litellm/tunnel ports. It is deliberately gone: on
# 2026-08-16 it still described qwen36-35b-a3b, gpt-oss-120b and
# muse-glimmer-30b -- three models that had stopped running -- and named none
# of the four engines actually serving. It was one of three descriptive layers
# that had rotted (job names and the discovery directory were the others),
# while the confs stayed correct throughout.
# The confs stayed correct because THIS SCRIPT READS THEM. They are
# load-bearing; a comment is not. A record nothing reads will rot, so the fix
# is not to update this table but to not keep one:
#   grep -H '^\(VLLM\|LITELLM\|TUNNEL\)_PORT=' $CONFD/*.conf
#
# RESERVED, DO NOT USE: 18765 -> the `codex` provider
# (src/scitex_agent_container/config/_provider_registry.py:43). Binding it
# would make any codex-configured agent silently reach a local model.
# This one stays written down because it is NOT derivable from the confs --
# it is a constraint imposed from outside this script, and the confs record
# only what we did allocate, never what we must not.
# ---------------------------------------------------------------------------
set -u

BASE=/data/scratch/projects/punim0264/ywatanabe
CONFD=$BASE/serve-models.d
LOGD=$BASE/serve-logs
DISCD=/data/gpfs/projects/punim0264/ywatanabe
BASTION=bastion-scitex-04.scitex.ai

KEY=${1:-}
if [ -z "$KEY" ]; then
  echo "usage: $0 <MODEL_KEY>   (available: $(ls "$CONFD" 2>/dev/null | sed 's/\.conf$//' | tr '\n' ' '))" >&2
  exit 2
fi
CONF=$CONFD/$KEY.conf
[ -r "$CONF" ] || { echo "no config: $CONF" >&2; exit 2; }

# ---- per-model settings (see $CONFD/<key>.conf) --------------------------
MODEL_PATH=""; SERVED_NAME=""; VLLM_PORT=""; LITELLM_PORT=""; TUNNEL_PORT=""
TP=1; GPU_MEM_UTIL=0.92; MAX_MODEL_LEN=""; MAX_NUM_SEQS=8; EXTRA_VLLM_ARGS=""
# shellcheck disable=SC1090
. "$CONF"
for v in MODEL_PATH SERVED_NAME VLLM_PORT LITELLM_PORT TUNNEL_PORT MAX_MODEL_LEN; do
  [ -n "${!v}" ] || { echo "$CONF: $v is unset" >&2; exit 2; }
done
[ -d "$MODEL_PATH" ] || { echo "weights missing: $MODEL_PATH" >&2; exit 2; }

mkdir -p "$LOGD"
VLOG=$LOGD/vllm-$KEY.log
LLOG=$LOGD/litellm-$KEY.log
TLOG=$LOGD/tunnel-$KEY.log
DISC=$DISCD/$KEY-endpoint.json
LITELLM_CFG=$BASE/litellm-$KEY.yaml

# REAL_HOME must be captured BEFORE HOME is redirected to the node-local cache.
# The tunnel needs the true home for BOTH ~/bin/cloudflared AND ~/.ssh (key +
# known_hosts); pointing it at the cache home breaks it silently.
REAL_HOME=${HOME:-/home/ywatanabe}

_resubmit() { echo "[serve] walltime; resubmitting $KEY" >&2; sbatch --job-name="$KEY-serve" "$0" "$KEY"; }
trap _resubmit USR1

# ---- Withdraw the discovery entry when this engine stops.
# The header above tells consumers to enumerate $DISCD/*-endpoint.json rather
# than hardcode a port, which makes that directory the sanctioned answer to
# "what is served where". It was written on ready and never removed, so a
# stopped model left a record indistinguishable from a live one.
# Measured 2026-08-16: 8 entries, 4 of them describing models that had not run
# for days -- a 50% false-positive rate for anyone following the documented
# protocol. The four live entries were correct, so the mechanism worked;
# nothing withdrew an entry, and write-on-start without remove-on-stop
# guarantees that outcome given time.
# A trap cannot cover SIGKILL or a node failure, so this is necessary and not
# sufficient: the record also carries job_id, letting a reader confirm the
# owning allocation still exists rather than trusting the file's presence.
_withdraw_discovery() {
  [ -n "${DISC:-}" ] && [ -f "$DISC" ] || return 0
  rm -f "$DISC" && echo "[serve] withdrew $DISC" >&2
}
trap _withdraw_discovery EXIT

# ---- CUDA / venv. Absolute paths captured BEFORE any cd: a cd after a module
# ---- load silently wipes the module PATH on this cluster.
export CUDA_HOME=/apps/easybuild-2022/easybuild/software/Core/CUDA/12.8.0
export PATH="$CUDA_HOME/bin:$BASE/vllm-venv/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
VLLM_BIN=$BASE/vllm-venv/bin/vllm
LITELLM_BIN=$BASE/vllm-venv/bin/litellm
export VLLM_ALLOW_LONG_MAX_MODEL_LEN=1
# hf_transfer is NOT installed in this venv; enabling it would raise.
unset HF_HUB_ENABLE_HF_TRANSFER

# ---- Node-local caches (the flashinfer/EDQUOT fix). /data/gpfs/projects/
# ---- punim0264 sits at 99% of its 8,000,000-file inode quota, so nothing
# ---- cache-shaped may be written there.
CACHE=/tmp/$KEY-cache-${SLURM_JOB_ID:-0}
export HOME="$CACHE/home"
export XDG_CACHE_HOME="$CACHE/xdg"
export HF_HOME="$CACHE/hf"
export TRITON_CACHE_DIR="$CACHE/triton"
export TORCHINDUCTOR_CACHE_DIR="$CACHE/inductor"
export VLLM_CACHE_ROOT="$CACHE/vllm"
export FLASHINFER_WORKSPACE_BASE="$CACHE/flashinfer"
mkdir -p "$HOME/.cache/flashinfer" "$XDG_CACHE_HOME" "$HF_HOME" "$TRITON_CACHE_DIR" \
  "$TORCHINDUCTOR_CACHE_DIR" "$VLLM_CACHE_ROOT" "$FLASHINFER_WORKSPACE_BASE"

NODE=$(hostname -f)
echo "[serve] $(date -u +%FT%TZ) key=$KEY node=$NODE model=$MODEL_PATH tp=$TP"
echo "[serve] ports vllm=$VLLM_PORT litellm=$LITELLM_PORT tunnel=$TUNNEL_PORT"
echo "[serve] nvcc=$(command -v nvcc) real_home=$REAL_HOME"

# ---- LiteLLM sidecar (restart loop), bound on all interfaces.
( while true; do
    "$LITELLM_BIN" --config "$LITELLM_CFG" --host 0.0.0.0 --port "$LITELLM_PORT" >> "$LLOG" 2>&1
    echo "[$(date -u +%FT%TZ)] litellm exited; restart 10s" >> "$LLOG"
    sleep 10
  done ) &

# ---- Reverse tunnel supervisor, started ONLY after vLLM answers, so the
# ---- published port never fronts a still-loading engine. It belongs to the
# ---- JOB: a tunnel started by hand is tied to whichever node held the job at
# ---- the time and vanishes silently when the job is resubmitted elsewhere.
# ---- DIRECTION IS DELIBERATE: initiated FROM Spartan, outbound, cloudflared
# ---- as a CLIENT. Nothing is hosted on Spartan; no standing forward INTO the
# ---- cluster. Operator 2026-08-12: cloudflare は怒られそう / ssh reverse ならOK
_tunnel_supervisor() {
  export HOME="$REAL_HOME"   # cloudflared + ssh key live under the real home
  while true; do
    echo "[$(date -u +%FT%TZ)] establishing -R $TUNNEL_PORT -> 127.0.0.1:$VLLM_PORT from $NODE" >> "$TLOG"
    # ControlMaster=no + ControlPath=none are LOAD-BEARING, not boilerplate.
    # ~/.ssh/config enables connection multiplexing (auto-mux). With it, this
    # `ssh -N -R` does NOT open its own connection: it attaches to the existing
    # master, asks it to register the forward, and EXITS rc=0 in ~2 seconds
    # (observed: "auto-mux: Trying existing master ... mux_client_request_session
    # ... exit 0"). The forward then lives and dies with that master rather than
    # with this job -- which is precisely the fragility this supervisor exists to
    # remove, and it makes the retry loop spin re-registering a forward forever.
    # Forcing a dedicated connection ties the tunnel's lifetime to THIS process.
    ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes \
      -o ControlMaster=no -o ControlPath=none \
      -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
      -o StrictHostKeyChecking=accept-new \
      -o ProxyCommand="$REAL_HOME/bin/cloudflared access ssh --hostname $BASTION" \
      -R "$TUNNEL_PORT:127.0.0.1:$VLLM_PORT" "ywatanabe@$BASTION" >> "$TLOG" 2>&1
    rc=$?
    # ExitOnForwardFailure turns a stale remote LISTEN into a fast, loud
    # failure instead of a tunnel fronting nothing. ServerAlive* makes this
    # client die promptly so the far sshd releases the port.
    # A near-instant rc=0 here means multiplexing slipped back in -- treat it
    # as a fault, not a success, or the loop will hammer the bastion.
    if [ "$rc" = 0 ]; then
      echo "[$(date -u +%FT%TZ)] WARNING: ssh -N returned 0 immediately; multiplexing may be active (expect a held connection)" >> "$TLOG"
    fi
    echo "[$(date -u +%FT%TZ)] tunnel exited rc=$rc; retry in 20s" >> "$TLOG"
    sleep 20
  done
}

# ---- vLLM supervision loop.
TUNNEL_PID=""
while true; do
  echo "[serve] $(date -u +%FT%TZ) starting vLLM tp=$TP len=$MAX_MODEL_LEN on $NODE" >> "$VLOG"
  # shellcheck disable=SC2086
  "$VLLM_BIN" serve "$MODEL_PATH" --served-model-name "$SERVED_NAME" \
    --tensor-parallel-size "$TP" --gpu-memory-utilization "$GPU_MEM_UTIL" \
    --max-model-len "$MAX_MODEL_LEN" --max-num-seqs "$MAX_NUM_SEQS" \
    $EXTRA_VLLM_ARGS \
    --host 127.0.0.1 --port "$VLLM_PORT" >> "$VLOG" 2>&1 &
  VPID=$!

  ready=no
  for _ in $(seq 1 240); do
    kill -0 "$VPID" 2>/dev/null || break
    if curl -s -m 5 "http://127.0.0.1:$VLLM_PORT/health" >/dev/null 2>&1; then ready=yes; break; fi
    sleep 15
  done

  if [ "$ready" = yes ]; then
    # THE JOB NAMES ITSELF AFTER WHAT IT IS ACTUALLY SERVING.
    # _resubmit already submits as "$KEY-serve", so a job that resubmits is
    # named correctly. The drift comes from the OTHER path: repointing a live
    # allocation with `srun --overlap` (the technique for swapping models
    # without releasing a node) renames nothing, so the allocation keeps the
    # name of whatever it served first.
    # Measured 2026-08-16: all three serving jobs were named for models that
    # had stopped days earlier -- "muse-serve-permanent" and
    # "gptoss-serve-permanent" were both serving qwen38-27b. That naming led to
    # a proposal to release a LIVE allocation (irreversible here) and to two
    # false claims about a dependency on an already-stopped model.
    # Naming happens HERE, next to the discovery write, because this is the
    # point where the model is proven up: an identity published before /health
    # answers would be a claim rather than an observation.
    #
    # THE NAME IS BUILT FROM SERVED_NAME AND THE NODE, NOT FROM $KEY, AND THAT
    # IS LOAD-BEARING. One allocation can hold SEVERAL engines: gpgpu178 runs
    # keys qwen38-27b and qwen38-27b-b as two `srun --overlap` steps sharing
    # ONE job id. A $KEY-derived name would make those two steps write
    # different names to the same job -- last-write-wins, and the name flaps
    # between them. Every engine in one allocation agrees on SERVED_NAME and on
    # the node, so every step computes the SAME string and the update is
    # idempotent no matter how many replicas run or what order they finish in.
    JOB_NAME="$SERVED_NAME-serve-${NODE%%.*}"
    if [ -n "${SLURM_JOB_ID:-}" ] && command -v scontrol >/dev/null 2>&1; then
      if ! scontrol update JobId="$SLURM_JOB_ID" JobName="$JOB_NAME" >/dev/null 2>&1; then
        echo "[serve] WARNING: could not rename job $SLURM_JOB_ID to $JOB_NAME;" \
             "its name may not describe what it serves" >&2
      fi
    fi
    printf '{"node":"%s","litellm_port":%s,"vllm_port":%s,"tunnel_port":%s,"bind":"0.0.0.0","model":"%s","key":"sk-clew-local","tp":%s,"max_model_len":%s,"job_id":"%s","updated":"%s"}\n' \
      "$NODE" "$LITELLM_PORT" "$VLLM_PORT" "$TUNNEL_PORT" "$SERVED_NAME" "$TP" "$MAX_MODEL_LEN" \
      "${SLURM_JOB_ID:-unknown}" "$(date -u +%FT%TZ)" > "$DISC"
    if [ -z "$TUNNEL_PID" ] || ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
      _tunnel_supervisor & TUNNEL_PID=$!
      echo "[serve] tunnel supervisor pid=$TUNNEL_PID (remote 127.0.0.1:$TUNNEL_PORT on compute-04)"
    fi
    echo "[serve] === READY: $SERVED_NAME vLLM 127.0.0.1:$VLLM_PORT + LiteLLM 0.0.0.0:$LITELLM_PORT + tunnel $TUNNEL_PORT on $NODE — holding ==="
    echo "[serve] === READY ===" >> "$VLOG"
  else
    echo "[serve] vLLM did not become ready; see $VLOG" >&2
  fi

  wait "$VPID"
  echo "[$(date -u +%FT%TZ)] vllm exited; restart 15s" >> "$VLOG"
  sleep 15
done
