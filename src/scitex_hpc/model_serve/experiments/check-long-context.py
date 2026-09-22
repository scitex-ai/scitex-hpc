#!/usr/bin/env python3
"""Verify an OpenAI-compatible server can process a target context length."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8775/v1")
    parser.add_argument("--model", default="qwen38-27b")
    parser.add_argument("--repetitions", type=int, default=270_000)
    parser.add_argument("--minimum-prompt-tokens", type=int, default=262_144)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    payload = {
        "model": args.model,
        "messages": [
            {
                "role": "user",
                "content": ("x " * args.repetitions)
                + "\nReply with the single character K.",
            }
        ],
        "temperature": 0,
        "max_tokens": 1,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        f"{args.base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=args.timeout) as response:
        body = json.load(response)
    elapsed = time.monotonic() - started
    prompt_tokens = body["usage"]["prompt_tokens"]
    content = body["choices"][0]["message"].get("content")
    passed = prompt_tokens > args.minimum_prompt_tokens and bool(content)
    print(
        f"SUMMARY passed={passed} prompt_tokens={prompt_tokens} "
        f"minimum_exclusive={args.minimum_prompt_tokens} elapsed={elapsed:.2f}s "
        f"content={content!r}"
    )
    return not passed


if __name__ == "__main__":
    raise SystemExit(main())
