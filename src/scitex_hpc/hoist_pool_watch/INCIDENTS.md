# Hoist pool — what went wrong, and what each guard is for

Four incidents on scitex-compute-04 between 2026-08-15 and 2026-08-28. Until
2026-09-03 the only written account of them was a block of comments in
`~/.config/systemd/user/anthropic-system-hoist-proxy.service.d/upstream.conf`:
one file, on one host, outside version control, readable only by someone who
already knew to look there.

Every agent on the fleet reaches the local models through this proxy, so its
pool membership is load-bearing. The measurements below are why
[`_policy.py`](_policy.py) exists and why each exclusion in it is worded the way
it is.

## 2026-08-15 — the pool pointed at a dead port

The proxy's built-in default upstream was 18771, which had served gpt-oss-120b.
That model was stopped when the GPU fleet was converted to Qwen3.8. The port
still **listened** with nothing behind it, so the proxy forwarded every request
into it and returned an empty reply — HTTP 000 to the caller — while systemd
reported the service `active (running)`.

**What it teaches:** a TCP connect is not proof of service. A dead-but-listening
forward and a refused connection are the same observation at the socket layer.
Probe `/v1/models` and require a model id back.

## 2026-08-15 — one upstream made four GPUs behave as one

The pool held a single member. Measured on both sides of the wire:
18773 at `num_requests_running=3` while three identical H100s sat at
`running=0` and `waiting=0` everywhere — so never saturation, only routing. A
direct 64-token request to the loaded card took **106.8 s**.

**What it teaches:** `waiting=0` on the idle members is the discriminator. It
rules out load and leaves routing as the only explanation.

## 2026-08-16 — the A100 was removed, and reachability could not have found it

The operator's instruction was 「A100はさしあたりQwenに使うのはやめましょう」.
Two agents reported it done on the strength of grepping agent specs for 18776
and finding zero references. The grep was accurate and answered the wrong
question: agents reach the models through **this proxy's pool**, not through the
direct path a spec names. Measured the same day, 18776 was carrying 19 requests
and 1.60M prompt tokens — more than any H100 — with no spec naming it anywhere.

**The reason is simpler than the analysis around it.** Asked directly on
2026-09-03, the operator gave it in one line: 「ただ、A100だと遅いからって言うだけ
です」「H100でも遅いのに、A100で使ってられるかってことです」 — the card is slow;
even an H100 is slower than we would like for this model, so an A100 is not worth
a slot. He also called the exclusion 「たまたま私たちの趣味趣向」, our taste, which
is why it belongs in a config file and not in this package.

Two measurements sit alongside that preference and should not be mistaken for
it. The A100 was about 8.7x slower on time-to-first-token (73.1 s against 8.4 s),
and because a slower card drains its queue faster than work arrives it can keep
*looking* least-loaded to a selection policy that assumes members are
interchangeable. That is a real effect and it is not the reason for the ruling.

**What it teaches:** admissibility is a **second axis**, independent of liveness.
A healthy, reachable endpoint can be one we simply do not want, and no probe will
ever say so.

## 2026-08-28 — a dead member cost one request in three

18775 stopped listening and stayed in the pool. Roughly one request in three
came back `502 anthropic_system_hoist_proxy could not reach
http://127.0.0.1:18775`, which killed a working agent mid-task and produced
intermittent failures that led to a wrong repair elsewhere.

**What it teaches:** a three-member pool with one dead member does not degrade
to two-thirds throughput. It fails a third of requests outright, and a 502
mid-task is a dead agent rather than a retry.

## The shape common to all four

Each was a disagreement between what the pool **routed to** and what was
**actually serving** — and in the A100's case, between what was serving and what
was **allowed to serve**. Three separate facts:

| fact | who knows it | where it lives |
|---|---|---|
| is it in the pool | systemd's resolved `HOIST_UPSTREAM` | the running unit |
| is it serving | an HTTP probe of `/v1/models` | the endpoint |
| may it serve | an operator decision | `_policy.py`, from 2026-09-03 |

Read the pool from `systemctl --user show -p Environment`, never from the unit
file. The unit's own line 7 says *"THIS LINE IS A FALLBACK, NOT THE LIVE VALUE"*,
a drop-in overrides it, and reading the file instead of the resolution is a
misread this fleet has now made twice — recorded in that unit on 2026-08-18 and
repeated on 2026-08-29.
