#!/usr/bin/env python3
"""Report configured context separately from measured SGLang KV capacity."""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

CAPACITY_LINE = re.compile(
    r"max_total_num_tokens=(?P<capacity>\d+).*?"
    r"max_running_requests=(?P<running>\d+).*?"
    r"context_len=(?P<context>\d+).*?"
    r"available_gpu_mem=(?P<memory>[0-9.]+) GB"
)


def parse_startup_log(text: str) -> dict[str, int | float]:
    """Return the last complete capacity record in an SGLang startup log."""
    matches = list(CAPACITY_LINE.finditer(text))
    if not matches:
        raise ValueError("startup log has no SGLang capacity line")
    values = matches[-1].groupdict()
    return {
        "max_total_num_tokens": int(values["capacity"]),
        "resolved_max_running_requests": int(values["running"]),
        "reported_context_length": int(values["context"]),
        "available_gpu_memory_gib": float(values["memory"]),
    }


def build_report(
    configured_context_tokens: int,
    startup: dict[str, int | float],
    server_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an explicit configuration-versus-capacity report."""
    capacity = int(startup["max_total_num_tokens"])
    reported_context = int(startup["reported_context_length"])
    return {
        "configured_context_tokens": configured_context_tokens,
        "reported_context_tokens": reported_context,
        "context_matches_configuration": reported_context == configured_context_tokens,
        "max_total_num_tokens": capacity,
        "capacity_fraction_of_one_max_context": round(
            capacity / configured_context_tokens, 6
        ),
        "resolved_max_running_requests": startup["resolved_max_running_requests"],
        "available_gpu_memory_gib": startup["available_gpu_memory_gib"],
        "interpretation": (
            "configured_context_tokens is the per-request acceptance limit; "
            "max_total_num_tokens is the measured aggregate device KV-token pool"
        ),
        "server_info": summarize_server_info(server_info) if server_info else None,
    }


def summarize_server_info(server_info: dict[str, Any]) -> dict[str, Any]:
    """Keep the live identity/capacity fields needed to interpret a run."""
    internal = (server_info.get("internal_states") or [{}])[0]
    return {
        key: server_info.get(key)
        for key in (
            "model_path",
            "served_model_name",
            "version",
            "context_length",
            "kv_cache_dtype",
            "tp_size",
            "schedule_policy",
            "enable_session_radix_cache",
            "enable_cache_report",
            "enable_metrics",
            "chunked_prefill_size",
            "max_prefill_tokens",
            "max_total_num_tokens",
        )
    } | {
        "effective_max_running_requests_per_dp": internal.get(
            "effective_max_running_requests_per_dp"
        )
    }


def fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--configured-context-tokens", type=int, required=True)
    parser.add_argument("--startup-log", type=Path, required=True)
    parser.add_argument("--server-url")
    args = parser.parse_args()

    startup = parse_startup_log(args.startup_log.read_text(errors="replace"))
    server_info = None
    if args.server_url:
        server_info = fetch_json(args.server_url.rstrip("/") + "/get_server_info")
    print(
        json.dumps(
            build_report(args.configured_context_tokens, startup, server_info),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
