# Qwen3.8-27B TP=1 capacity profiles

These profiles measure one Qwen3.8-27B-FP8 SGLang engine on one H100. They
must run as an overlapping step inside an existing HPC allocation; the
launcher refuses to run on a login node.

The default SGLang image is the locally materialized SIF for OCI amd64
manifest `sha256:45e39d4c5bcfd89d171b3358ba78899354ab26a85bc746a17621ad818f8394aa`;
its measured SIF SHA-256 is
`b742f112f8403417c781216e9d4cf9d7eff49f2d6127e682805c40225a74cab2`.

```bash
srun --overlap --jobid="$JOB_ID" --gpus-per-task=1 --ntasks=1 --exact \
  qwen38-tp1-canary.sh 1m
```

The accepted profile names are `1m`, `512k`, and `256k`. They change only the
configured request-context ceiling. Every profile keeps the serving variables
that matter to the multi-agent experiment explicit: TP=1, FP8 KV, YaRN, EAGLE
MTP, LPM scheduling, session-aware radix caching, cache reporting, metrics,
8,192-token prefill chunks, and a 32,768-token prefill batch ceiling.

## What the 1M measurement established

Observed on 2026-09-14 with one H100 and the pinned image/model used by this
launcher:

| Measurement | Observed value |
|---|---:|
| Configured context length | 1,000,000 tokens |
| SGLang `max_total_num_tokens` | 563,215 tokens |
| Resolved maximum running requests | 11 |
| Available GPU memory after static allocation | 13.64 GiB |
| HBM used by the ready, idle process | 68,150 MiB |
| Repeated 73-token request, second prefill | 64 cached + 9 new |

The first two rows are different limits. A one-million-token configured
context means the server accepts a request up to that ceiling. It does not
mean the HBM KV pool can retain one million tokens, nor that several such
requests can be resident together. The measured `max_total_num_tokens` is the
aggregate device KV-token pool for that boot.

After each boot, capture the distinction from the startup log rather than
copying the table:

```bash
python -m scitex_hpc.model_serve.experiments.capacity_report \
  --configured-context-tokens 1000000 \
  --startup-log "$LOG" \
  --server-url http://127.0.0.1:8775
```

The report includes the live `/get_server_info` response when a server URL is
provided. Retain that JSON with benchmark results so a throughput number is
never detached from the configuration that produced it.

## Measurement order

Start with `1m`; record startup success or failure, server info, the capacity
line, idle HBM, and repeated-prefix cache behavior. Then repeat the same load
at `512k` and `256k`. Compare concurrency, TTFT, throughput, queue depth, and
cache hits under identical prompts. Do not infer concurrency from the context
ceiling or from `max_running_requests`: HBM KV capacity and prompt-length mix
remain the binding measurements.
