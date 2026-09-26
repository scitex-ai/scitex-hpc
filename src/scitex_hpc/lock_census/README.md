# `lock_census` — catch the next batch of stale `index.lock` with its evidence intact

On 2026-08-15, **59 of 108** git repos on Spartan were found write-locked by
0-byte `.git/index.lock` files. Some had been locked for up to two months. They
were laid in batches — 24 repos on one night, 14 on another — clustered at
02:00–03:59 local, by a recurring process that has still not been identified.

They were cleared. **Clearing them destroyed the mtimes**, which were the only
evidence capable of naming the cause. The card puts it plainly: *remediating
destroyed the diagnostic*, and capturing `stat` first would have cost one
command.

This monitor exists so that does not happen twice. **It removes nothing.** It
records, and whoever clears the locks does so afterwards as a separate,
deliberate act.

## Why nobody noticed for two months

A stale `index.lock` blocks every **write** and no **read**. `git log`,
`rev-parse`, `rev-list --count`, `grep` over the worktree — all succeed
normally. A locked repo is indistinguishable from a healthy one by inspection
and reports itself as fine.

Measured on one repo before the fix:

```
git rev-list --count HEAD..origin/develop   ->  0      ("up to date")
truth                                       ->  57 behind, unwritable 18 days
```

The `0` came from comparing against a remote-tracking ref last fetched 51 days
earlier. Both readings were reassuring and both were worthless.

## What it emits

Append-only JSONL at `~/.scitex/hpc/runtime/index-lock-census.jsonl`:

```json
{"ts":…,"host":"…","event":"lock","repo":"…","mtime_epoch":…,"size":…}
{"ts":…,"host":"…","event":"census","scanned":108,"locked":0}
```

`mtime_epoch` is the load-bearing field. The test this evidence feeds is a
correlation against `sacct --format=End` in **epoch seconds** — never local
time, because this host has already produced one phantom anomaly from a
JST/AEST mix-up between two agents.

> **Run the correlation on Spartan, not by reading epochs back.** A bare
> 10-digit epoch is secret-shaped, and an agent's secret-scanning hook will
> redact it in transit — observed while testing this script, and previously
> when a `usage.prompt_tokens` value came back unreadable for the same reason.
> The log on disk is correct; the *transcript* is not. So compute the
> correlation where the data lives and return the derived verdict, exactly as
> one would for any other value that cannot survive the trip.

## Three design choices that are not incidental

**It dedupes by `realpath`.** `$HOME/proj/<pkg>` is a symlink to
`/data/gpfs/projects/punim0264/ywatanabe/<pkg>`, so globbing both arms counts
many repos twice. That is exactly how 59 distinct locked repos were first
reported as **85**, and how "61% of the estate" became arithmetic on two
inflated numbers.

**It fails loudly when it scans zero repos.** If the globs match nothing —
wrong host, moved tree, unmounted GPFS — a naive census reports `0 locked` and
reads as a clean estate. That is the absence-indistinguishable-from-failure
shape this estate keeps producing, so `scanned == 0` exits 2 and says so. The
service unit deliberately excludes 2 from `SuccessExitStatus`: a failed look
*should* render as a failure, while a true detection (exit 1) should not.

**It runs on an interval, not a calendar.** The obvious design is a daily run
just after the 02:00–03:59 window. But the timezone here is precisely what
cannot be trusted — a `systemctl --user list-timers` reading came back in JST
while every other record asserts AEST. A wall-clock schedule built on the wrong
timezone fails silently: the monitor runs faithfully, forever, at the wrong
hour. Every 6 hours cannot miss a nightly event under any timezone assumption,
and 108 `stat` calls four times a day is free.

## Install

```sh
install -m755 index-lock-census.sh  ~/.scitex/hpc/scripts/
install -m644 index-lock-census.*   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now index-lock-census.timer
```

Override the scanned parents with `LOCK_CENSUS_PARENTS`, or the log path with
`LOCK_CENSUS_LOG`, if this is ever pointed at another estate.

## What it does *not* answer

Whether the cause is still running. The lock pattern is **episodic**, not
nightly — most nights in the eight-week window produced no locks at all — so a
single clean census is exactly what the mechanism produced most of the time
while it was active. Only repeated sampling distinguishes "stopped" from "did
not fire tonight," which is the whole reason this is a timer rather than a note
in a calendar.
