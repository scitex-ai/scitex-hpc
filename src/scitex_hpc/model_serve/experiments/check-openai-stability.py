#!/usr/bin/env python3
"""Concurrent streaming/non-streaming HTTP stability canary."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import time
import urllib.request


def request_once(url: str, model: str, run: int) -> tuple[int, str, float]:
    stream = run % 2 == 0
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": f"Reply with exactly the decimal integer {run} and nothing else.",
            }
        ],
        "temperature": 0,
        "max_tokens": 32,
        "stream": stream,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    text = ""
    with urllib.request.urlopen(request, timeout=180) as response:
        if stream:
            for raw_line in response:
                line = raw_line.decode().strip()
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                chunk = json.loads(line[6:])
                text += chunk["choices"][0].get("delta", {}).get("content") or ""
        else:
            body = json.load(response)
            text = body["choices"][0]["message"].get("content") or ""
    elapsed = time.monotonic() - started
    return run, text.strip(), elapsed


def percentile(values: list[float], fraction: float) -> float:
    return sorted(values)[round((len(values) - 1) * fraction)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8775/v1")
    parser.add_argument("--model", default="qwen38-27b")
    parser.add_argument("--requests", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    url = f"{args.base_url.rstrip('/')}/chat/completions"
    failures: list[str] = []
    latencies: list[float] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(request_once, url, args.model, run) for run in range(args.requests)]
        for future in concurrent.futures.as_completed(futures):
            try:
                run, result, elapsed = future.result()
                latencies.append(elapsed)
                if result != str(run):
                    failures.append(f"run={run} expected={run!r} got={result!r}")
            except Exception as error:
                failures.append(repr(error))
    for failure in failures:
        print(f"FAIL {failure}")
    latency_summary = "latency=unavailable"
    if latencies:
        latency_summary = (
            f"latency_mean={statistics.mean(latencies):.3f}s "
            f"latency_p50={percentile(latencies, 0.50):.3f}s "
            f"latency_p95={percentile(latencies, 0.95):.3f}s"
        )
    print(
        f"SUMMARY passed={args.requests - len(failures)} failed={len(failures)} "
        f"{latency_summary}"
    )
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
