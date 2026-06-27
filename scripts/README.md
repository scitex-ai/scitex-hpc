# scripts/

Standalone host-side helper scripts for the Spartan integration (not part of the
`scitex_hpc` Python package).

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
