#!/usr/bin/env bash
# qwen_tunnel.sh — maintain a stable host-side endpoint for the Spartan-hosted
# qwen LLM, re-pointed automatically when qwen reschedules to a new GPU node.
#
# WHY: qwen serves behind a key-gated LiteLLM proxy on an EPHEMERAL Spartan GPU
# node (the node changes on every walltime resubmit / reschedule). Agent
# containers on the host share the host network namespace, so a single host-side
# `ssh -L 127.0.0.1:<LOCAL_PORT>` gives every container a STABLE address
# (http://127.0.0.1:<LOCAL_PORT>) regardless of which node qwen is on.
#
# HOW: poll the discovery file that the qwen holder publishes to Spartan shared
# storage, and (re)establish the forward to the CURRENT node. Fail loud, log
# every transition. Intended to run as a host systemd --user unit
# (Restart=always); needs a working key-based `ssh <QWEN_SSH_HOST>` (BatchMode).
#
# Env knobs:
#   QWEN_LOCAL_PORT   local listen port (default 4000)
#   QWEN_SSH_HOST     ssh alias for the Spartan login node (default "spartan")
#   QWEN_TUNNEL_POLL  discovery poll interval seconds (default 30)
#   QWEN_DISCOVERY    discovery json path on Spartan (default below)
set -u

LOCAL_PORT="${QWEN_LOCAL_PORT:-4000}"
SSH_HOST="${QWEN_SSH_HOST:-spartan}"
POLL="${QWEN_TUNNEL_POLL:-30}"
DISC="${QWEN_DISCOVERY:-/data/scratch/projects/punim0264/ywatanabe/qwen-endpoint.json}"

cur_node=""
ssh_pid=""

log() { echo "[$(date -u +%FT%TZ)] qwen_tunnel: $*"; }
cleanup() { [ -n "$ssh_pid" ] && kill "$ssh_pid" 2>/dev/null; }
trap cleanup EXIT TERM INT

log "starting: local 127.0.0.1:${LOCAL_PORT} -> ${SSH_HOST} -> <discovery node>:4000 (poll ${POLL}s)"

while true; do
  # Read the current qwen node from the Spartan-side discovery file (no jq dep).
  node="$(ssh -o ConnectTimeout=15 -o BatchMode=yes "$SSH_HOST" "cat '$DISC' 2>/dev/null" \
            | sed -n 's/.*"node":"\([^"]*\)".*/\1/p')"

  if [ -z "$node" ]; then
    log "WARN: could not read discovery node from ${SSH_HOST}:${DISC} (qwen down / ssh failed); retry in ${POLL}s"
    sleep "$POLL"
    continue
  fi

  # (Re)establish if the node changed OR the existing forward died.
  if [ "$node" != "$cur_node" ] || ! kill -0 "$ssh_pid" 2>/dev/null; then
    if [ -n "$ssh_pid" ]; then
      log "tearing down forward to ${cur_node} (pid ${ssh_pid})"
      kill "$ssh_pid" 2>/dev/null
      wait "$ssh_pid" 2>/dev/null
    fi
    log "establishing forward 127.0.0.1:${LOCAL_PORT} -> ${node}:4000 via ${SSH_HOST}"
    ssh -o ConnectTimeout=15 -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
        -o ServerAliveCountMax=3 -o BatchMode=yes \
        -N -L "127.0.0.1:${LOCAL_PORT}:${node}:4000" "$SSH_HOST" &
    ssh_pid=$!
    cur_node="$node"
    sleep 3
    if kill -0 "$ssh_pid" 2>/dev/null; then
      log "forward up (pid ${ssh_pid}); qwen reachable at http://127.0.0.1:${LOCAL_PORT}"
    else
      log "ERROR: forward to ${node} failed to start; will retry next poll"
      ssh_pid=""
      cur_node=""
    fi
  fi

  sleep "$POLL"
done
