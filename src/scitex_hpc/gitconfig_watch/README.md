# gitconfig_watch — the watch that was named twice and never built

`~/.gitconfig` on Spartan is a **symlink into the tracked dotfiles SSoT**. The
watch confirms that itself at runtime:

```
path=/home/ywatanabe/.dotfiles/src/.gitconfig
```

So a CI job running `git config --global --add safe.directory <path>` writes into
a **version-controlled file**. `actions/checkout` does that unconditionally at
job start and does not deduplicate, so growth is proportional to **CI runs**, not
to repositories.

## Why it exists

| date | state |
|---|---|
| 2026-08-17 | reset to **0** entries / 92 lines |
| 2026-08-29 | **256** entries / 349 lines, one runner (`spartan-cpu-org-03`) |

≈22 entries/day, twelve days after a fix that was believed structural and was
not.

On 2026-08-17 the card recorded that the right artefact was *"a watch on the
file's line count"*, and that *"nobody has ever pointed one at it — the growth
was invisible for months not because it was subtle but because nothing looked."*
Twelve days later nothing was looking and the regression was found by accident
while measuring an unrelated card. Naming a gap is not closing it. This is the
watch.

## Exit codes

| code | meaning | unit sees |
|---|---|---|
| 0 | at or below threshold | success |
| 1 | **drift present** — the monitor *working* | success (`SuccessExitStatus=0 1`) |
| 2 | target unreadable — a **failed look**, not a clean config | failure |
| 3 | **no alarm sink** — the monitor cannot report, so it is broken *now* | failure |

Exit 3 is checked on **every** run, not only when alarming. A monitor that
cannot report is broken today; deferring that discovery to the day it matters
means finding out too late. This is the defect that left `index-lock-census`
unable to fire its alarm for two weeks.

## Alarming on the transition, not the state

The file stays polluted until someone clears it, and the timer fires every 6h.
Alarming on *state* would re-send the same condition every run until it was
fixed — which teaches everyone to ignore the alarm, the exact failure the alarm
exists to prevent. Copied deliberately from `index-lock-census`, which learned
it the same way.

## It is READ-ONLY, deliberately

It never edits, reverts or commits the file. Two reasons, and the second is the
important one:

1. The dotfiles SSoT is not this repo's to modify.
2. **The entries are the only evidence of which runner is writing.** Clearing
   them destroys the diagnosis — the same mistake the 2026-08-15 index.lock
   remediation made when it cleared 59 locks and with them the mtimes that were
   the only data identifying the cause.

## Install

```sh
cp gitconfig-drift-watch.sh              ~/.scitex/hpc/scripts/
cp gitconfig-drift-watch.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gitconfig-drift-watch.timer
```

Confirm systemd **resolved** the OnFailure wiring rather than that the file
exists:

```sh
systemctl --user show gitconfig-drift-watch.service -p OnFailure --value
```

## Testing

`GITCONFIG_WATCH_DRYRUN=1` suppresses the send but **not** the sink resolution,
so a broken alarm rail is still caught in rehearsal.
`GITCONFIG_WATCH_SELFTEST=1` exercises real delivery end to end.

All four exit paths were tested before deployment. The **clean-file** case is the
one that matters: `grep -c` prints `0` *and* exits 1 when nothing matches, so an
`|| echo 0` fallback appends a second zero and every later integer test dies.
That bug appears **only on a clean file** — the good case — and would have
reported drift on a config that had none. Testing only the interesting case would
have shipped it.
