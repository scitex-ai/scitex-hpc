#!/bin/bash
set -euo pipefail

PROFILE=${1:-}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CONF="$HERE/profiles/qwen38-tp1-${PROFILE}.conf"

if [ -z "$PROFILE" ] || [ ! -r "$CONF" ]; then
  echo "usage: $0 {1m|512k|256k}" >&2
  exit 2
fi

# shellcheck disable=SC1090
. "$CONF"

if [ -z "${SLURM_JOB_ID:-}" ]; then
  echo "refusing to run outside a Slurm allocation; use srun --overlap" >&2
  exit 78
fi

BASE=${SGLANG_BASE:-/data/scratch/projects/punim0264/ywatanabe}
# OCI amd64 manifest sha256:45e39d4c5bcfd89d171b3358ba78899354ab26a85bc746a17621ad818f8394aa
# SIF sha256: b742f112f8403417c781216e9d4cf9d7eff49f2d6127e682805c40225a74cab2
IMAGE=${SGLANG_IMAGE:-$BASE/containers/sglang-qwen38-cu12-amd64-45e39d4c5bcf.sif}
MODEL_PATH=${MODEL_PATH:-$BASE/hf/Qwen3.8-27B-FP8}
SERVED_NAME=${SERVED_NAME:-qwen38-27b}
HOST=${SGLANG_HOST:-127.0.0.1}
PORT=${SGLANG_PORT:-8775}
GPU_INDEX=${GPU_INDEX:-0}
MEM_FRACTION=${SGLANG_MEM_FRACTION:-0.85}
APPTAINER_BIN=${APPTAINER_BIN:-/apps/easybuild-2022/easybuild/software/Compiler/GCCcore/11.3.0/Apptainer/1.3.3/bin/apptainer}

[ -s "$IMAGE" ] || { echo "missing SGLang image: $IMAGE" >&2; exit 78; }
[ -d "$MODEL_PATH" ] || { echo "missing model weights: $MODEL_PATH" >&2; exit 78; }
[ -x "$APPTAINER_BIN" ] || { echo "apptainer is unavailable: $APPTAINER_BIN" >&2; exit 78; }

CACHE=${SGLANG_CACHE:-/tmp/sglang-qwen38-${SLURM_JOB_ID}-${PROFILE}}
mkdir -p "$CACHE/xdg" "$CACHE/hf" "$CACHE/torch" "$CACHE/triton" \
  "$CACHE/inductor" "$CACHE/jit"

echo "[qwen38-tp1] profile=$PROFILE_LABEL configured_context_tokens=$CONTEXT_LENGTH"
echo "[qwen38-tp1] runtime_capacity_is_not_the_configured_context; inspect startup max_total_num_tokens"
echo "[qwen38-tp1] node=$(hostname -f) gpu=$GPU_INDEX port=$PORT image=$IMAGE"

MTP_ARGS=(
  --speculative-algorithm EAGLE
  --speculative-num-steps 3
  --speculative-eagle-topk 1
  --speculative-num-draft-tokens 4
)

exec "$APPTAINER_BIN" exec --nv --cleanenv \
  --bind "$MODEL_PATH:$MODEL_PATH:ro" \
  --env "CUDA_VISIBLE_DEVICES=$GPU_INDEX" \
  --env "SGLANG_ALLOW_OVERWRITE_LONGER_CONTEXT_LEN=1" \
  --env "XDG_CACHE_HOME=$CACHE/xdg" \
  --env "SGLANG_CACHE_DIR=$CACHE" \
  --env "SGLANG_JIT_CACHE_DIR=$CACHE/jit" \
  --env "SGLANG_JIT_DEEPGEMM_FAST_WARMUP=1" \
  --env "FLASHINFER_WORKSPACE_BASE=$CACHE" \
  --env "HF_HOME=$CACHE/hf" \
  --env "TORCH_HOME=$CACHE/torch" \
  --env "TRITON_CACHE_DIR=$CACHE/triton" \
  --env "TORCHINDUCTOR_CACHE_DIR=$CACHE/inductor" \
  "$IMAGE" \
  python3 -m sglang.launch_server \
    --trust-remote-code \
    --model-path "$MODEL_PATH" \
    --served-model-name "$SERVED_NAME" \
    --context-length "$CONTEXT_LENGTH" \
    --json-model-override-args '{"text_config":{"rope_parameters":{"mrope_interleaved":true,"mrope_section":[11,11,10],"rope_type":"yarn","rope_theta":10000000,"partial_rotary_factor":0.25,"factor":4.0,"original_max_position_embeddings":262144}}}' \
    --tp-size 1 \
    --kv-cache-dtype fp8_e4m3 \
    --mem-fraction-static "$MEM_FRACTION" \
    --attention-backend flashinfer \
    --schedule-policy lpm \
    --enable-session-radix-cache \
    --enable-cache-report \
    --enable-metrics \
    --chunked-prefill-size 8192 \
    --max-prefill-tokens 32768 \
    --disable-prefill-cuda-graph \
    --reasoning-parser qwen3 \
    --tool-call-parser qwen3_coder \
    --host "$HOST" \
    --port "$PORT" \
    "${MTP_ARGS[@]}"
