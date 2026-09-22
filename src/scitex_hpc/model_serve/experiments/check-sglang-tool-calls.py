#!/usr/bin/env python3
"""Repeatable OpenAI-compatible tool-call parser canary for SGLang."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

TOOL = {
    "type": "function",
    "function": {
        "name": "lookup_value",
        "description": "Look up a value by its exact key.",
        "parameters": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
            "additionalProperties": False,
        },
    },
}


def post(url: str, payload: dict) -> urllib.response.addinfourl:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(request, timeout=180)


def validate(name: str, arguments: str) -> None:
    if name != "lookup_value":
        raise ValueError(f"wrong function name: {name!r}")
    parsed = json.loads(arguments)
    if parsed != {"key": "alpha"}:
        raise ValueError(f"wrong arguments: {parsed!r}")


def nonstream(url: str, payload: dict) -> None:
    with post(url, {**payload, "stream": False}) as response:
        body = json.load(response)
    calls = body["choices"][0]["message"].get("tool_calls") or []
    if len(calls) != 1:
        raise ValueError(f"expected one tool call, got {calls!r}")
    function = calls[0]["function"]
    validate(function["name"], function["arguments"])


def stream(url: str, payload: dict) -> None:
    calls: dict[int, dict[str, str]] = {}
    with post(url, {**payload, "stream": True}) as response:
        for raw_line in response:
            line = raw_line.decode().strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            chunk = json.loads(line[6:])
            parts = chunk["choices"][0].get("delta", {}).get("tool_calls") or []
            for part in parts:
                call = calls.setdefault(part.get("index", 0), {"name": "", "arguments": ""})
                function = part.get("function", {})
                call["name"] += function.get("name") or ""
                call["arguments"] += function.get("arguments") or ""
    if len(calls) != 1:
        raise ValueError(f"expected one streamed tool call, got {calls!r}")
    validate(calls[0]["name"], calls[0]["arguments"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8775/v1")
    parser.add_argument("--model", default="qwen38-27b")
    parser.add_argument("--repetitions", type=int, default=10)
    args = parser.parse_args()
    payload = {
        "model": args.model,
        "messages": [
            {
                "role": "user",
                "content": "Call lookup_value with the exact key alpha. Do not answer directly.",
            }
        ],
        "tools": [TOOL],
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": 128,
    }
    url = f"{args.base_url.rstrip('/')}/chat/completions"
    failures: list[str] = []
    for mode, check in (("nonstream", nonstream), ("stream", stream)):
        for run in range(1, args.repetitions + 1):
            try:
                check(url, payload)
                print(f"PASS {mode} {run}/{args.repetitions}")
            except Exception as error:  # report every repetition, then fail once
                message = f"FAIL {mode} {run}/{args.repetitions}: {error}"
                print(message, file=sys.stderr)
                failures.append(message)
    print(f"SUMMARY passed={2 * args.repetitions - len(failures)} failed={len(failures)}")
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
