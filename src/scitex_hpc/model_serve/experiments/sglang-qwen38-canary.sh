#!/bin/bash
# Reproducible Qwen3.8-27B SGLang canary for an existing Slurm allocation.
#
# Run this as an overlapping step, never on a login node:
#   /apps/slurm/latest/bin/srun --overlap --jobid=JOB_ID --ntasks=1 --exact \
#     bash sglang-qwen38-canary.sh baseline
#
# The image is pinned by OCI digest and converted once to the SIF named below.
# The baseline flags follow SGLang's maintained SM90 FP8 recipe. MTP and YaRN
# are independent profile axes so parser/engine, speculation, and long-context
# failures remain distinguishable.
set -euo pipefail

PROFILE=${1:-baseline}
BASE=${BASE:-/data/scratch/projects/punim0264/ywatanabe}
# OCI amd64 manifest:
# sha256:45e39d4c5bcfd89d171b3358ba78899354ab26a85bc746a17621ad818f8394aa
# SIF sha256: b742f112f8403417c781216e9d4cf9d7eff49f2d6127e682805c40225a74cab2
IMAGE=${SGLANG_IMAGE:-$BASE/containers/sglang-qwen38-cu12-amd64-45e39d4c5bcf.sif}
MODEL_PATH=${MODEL_PATH:-$BASE/hf/Qwen3.8-27B-FP8}
SERVED_NAME=${SERVED_NAME:-qwen38-27b}
GPU_INDEX=${GPU_INDEX:-1}
HOST=${SGLANG_HOST:-127.0.0.1}
PORT=${SGLANG_PORT:-8775}
# The maintained recipe uses 0.85, but on Spartan's 80 GB H100 the prefill
# CUDA-graph capture OOMs after weight/KV allocation. Keep measured headroom.
MEM_FRACTION=${SGLANG_MEM_FRACTION:-0.75}
FAST_DEEPGEMM_WARMUP=${SGLANG_FAST_DEEPGEMM_WARMUP:-1}
APPTAINER_BIN=${APPTAINER_BIN:-/apps/easybuild-2022/easybuild/software/Compiler/GCCcore/11.3.0/Apptainer/1.3.3/bin/apptainer}

MTP_ARGS=(
  --speculative-algorithm EAGLE
  --speculative-num-steps 3
  --speculative-eagle-topk 1
  --speculative-num-draft-tokens 4
)
YARN_ARGS=(
  --json-model-override-args '{"text_config":{"rope_parameters":{"mrope_interleaved":true,"mrope_section":[11,11,10],"rope_type":"yarn","rope_theta":10000000,"partial_rotary_factor":0.25,"factor":4.0,"original_max_position_embeddings":262144}}}'
  --context-length 1000000
)
CONTAINER_ENV_ARGS=()

case "$PROFILE" in
  baseline)
    PROFILE_ARGS=()
    ;;
  mtp)
    PROFILE_ARGS=("${MTP_ARGS[@]}")
    ;;
  yarn)
    CONTAINER_ENV_ARGS+=(--env SGLANG_ALLOW_OVERWRITE_LONGER_CONTEXT_LEN=1)
    PROFILE_ARGS=("${YARN_ARGS[@]}")
    ;;
  yarn-mtp)
    CONTAINER_ENV_ARGS+=(--env SGLANG_ALLOW_OVERWRITE_LONGER_CONTEXT_LEN=1)
    PROFILE_ARGS=("${YARN_ARGS[@]}" "${MTP_ARGS[@]}")
    ;;
  *)
    echo "usage: $0 {baseline|mtp|yarn|yarn-mtp}" >&2
    exit 2
    ;;
esac

[ -s "$IMAGE" ] || { echo "missing SGLang image: $IMAGE" >&2; exit 78; }
[ -d "$MODEL_PATH" ] || { echo "missing model weights: $MODEL_PATH" >&2; exit 78; }
[ -x "$APPTAINER_BIN" ] || { echo "apptainer is unavailable: $APPTAINER_BIN" >&2; exit 78; }

CACHE=${SGLANG_CACHE:-/tmp/sglang-qwen38-${SLURM_JOB_ID:-manual}-$PROFILE}
mkdir -p "$CACHE/xdg" "$CACHE/hf" "$CACHE/torch" "$CACHE/triton" "$CACHE/inductor" "$CACHE/jit"

echo "[sglang-canary] $(date -u +%FT%TZ) profile=$PROFILE node=$(hostname -f) gpu=$GPU_INDEX port=$PORT"
echo "[sglang-canary] image=$IMAGE model=$MODEL_PATH"

exec "$APPTAINER_BIN" exec --nv --cleanenv \
  --bind "$MODEL_PATH:$MODEL_PATH:ro" \
  --env "CUDA_VISIBLE_DEVICES=$GPU_INDEX" \
  --env "XDG_CACHE_HOME=$CACHE/xdg" \
  --env "SGLANG_CACHE_DIR=$CACHE" \
  --env "SGLANG_JIT_CACHE_DIR=$CACHE/jit" \
  --env "SGLANG_JIT_DEEPGEMM_FAST_WARMUP=$FAST_DEEPGEMM_WARMUP" \
  --env "FLASHINFER_WORKSPACE_BASE=$CACHE" \
  --env "HF_HOME=$CACHE/hf" \
  --env "TORCH_HOME=$CACHE/torch" \
  --env "TRITON_CACHE_DIR=$CACHE/triton" \
  --env "TORCHINDUCTOR_CACHE_DIR=$CACHE/inductor" \
  "${CONTAINER_ENV_ARGS[@]}" \
  "$IMAGE" \
  python3 -m sglang.launch_server \
    --trust-remote-code \
    --model-path "$MODEL_PATH" \
    --served-model-name "$SERVED_NAME" \
    --kv-cache-dtype fp8_e4m3 \
    --mem-fraction-static "$MEM_FRACTION" \
    --attention-backend flashinfer \
    --chunked-prefill-size 32768 \
    --max-prefill-tokens 32768 \
    --disable-prefill-cuda-graph \
    --reasoning-parser qwen3 \
    --tool-call-parser qwen3_coder \
    --host "$HOST" \
    --port "$PORT" \
    "${PROFILE_ARGS[@]}"
