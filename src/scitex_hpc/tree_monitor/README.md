# tree_monitor — catch-it-live monitor for shared-tree deletions

## Why this exists

`~/.scitex/hpc/`, `~/.scitex/dev/containers/` and the clew `for_solver` roots
have vanished from the shared punim0264 tree before. Every attempt to identify
the deleter failed, because every investigation began *after* the tree was
already gone: crontab disabled, `systemd --user` swept twice, own SLURM history
clean, four concrete leads closed with hard evidence and no culprit.

Post-hoc forensics are exhausted. This catches the **next** one while it is
happening.

## What it does

`check_shared_tree.sh` stats a manifest of critical paths, diffs against the
last-known state persisted between runs, and on a path that *was* present and is
now missing:

1. captures cheap in-the-moment forensics — parent listing, `squeue` snapshot,
   active sessions, host and uid — to a timestamped file, and
2. alarms onto the **shared card board**, not merely a local log. A local log is
   exactly what a deleter could also remove; the card is the rail that survives
   the host.

## The design decision that matters: it is three-valued

Every path is `PRESENT`, `MISSING`, or **`UNKNOWN`**, and it alarms only on a
`PRESENT -> MISSING` **transition**.

A `stat` failure (GPFS hiccup, EIO, unreadable parent) yields `UNKNOWN`. That
never alarms **and never overwrites the baseline**, so a real deletion during an
unreadable window is still caught on the next good run.

Collapsing `UNKNOWN` into `MISSING` would page on every filesystem stutter and
train everyone to ignore the alarm. Collapsing it into `PRESENT` would lose the
event. Both are worse than carrying the third state.

## Rehearsing the alarm

    SCITEX_TREE_MONITOR_DRYRUN=1 ./check_shared_tree.sh

Without it, exercising the deletion branch writes a **real P1 card** to the
shared fleet board — measured 2026-08-05, when testing created
`spartan-shared-tree-vanish-20260805T163310Z` against a temp path that then had
to be hunted down and deleted. An alarm path that cannot be rehearsed safely
either goes untested or teaches everyone to ignore its cards.

## Deployment (currently by hand)

    scp check_shared_tree.sh  spartan:~/.scitex/hpc/scripts/
    scp shared-tree-monitor.{service,timer}  spartan:~/.config/systemd/user/
    ssh spartan 'systemctl --user daemon-reload &&
                 systemctl --user enable --now shared-tree-monitor.timer'

**Verify by observation, not by the enable command.** `is-enabled` and
`is-active` tell you the *timer unit* loaded; they say nothing about whether the
service ever runs. The proof is a second log line appearing one interval later:

    ssh spartan 'tail -3 ~/.scitex/hpc/runtime/shared-tree-monitor.log'

The `--now` activation produces a log line immediately, so a run right after
install shows **two** lines that are both yours. Wait for the third.

## Why these files are version-controlled

The monitor guards a tree, and until 2026-08-05 it lived **only inside that
tree** — if `~/.scitex/hpc/scripts/` vanished, the monitor vanished with it, and
the one tool that could explain the disappearance would disappear in the same
event. That is the hazard it exists to detect, applied to itself.

## Known limits

- **The manifest is partial.** It covers paths owned and verified here. The clew
  `for_solver` roots are deliberately absent: their current locations could not
  be confirmed, and a wrong path in a deletion monitor is worse than a missing
  one — it would alarm forever on something that never existed. Add lines as
  owners confirm.
- **One host.** A deletion performed elsewhere is caught only if it removes a
  path this host can see.
- **Five-minute granularity.** Forensics are contemporaneous, not instantaneous.
- **Deployed by hand.** No CLI verb or install command yet — see the follow-up
  card for packaging this the way `tunnel_supervisor` is packaged.
