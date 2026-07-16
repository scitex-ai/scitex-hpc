---
description: |
  [TOPIC] Identity & Access Traps on a Shared Cluster
  [DETAILS] Why a multiplexed ssh session reports a group you no longer have
  (it reads the PAST), making a hard revocation look like an intermittent
  "flap"; how to probe authoritatively (`ssh -o ControlPath=none`, and trust
  `getent group` over a cached `id`); why losing a project group breaks the
  SHELL ENV itself when $HOME dotdirs symlink into that project; and why a
  SLURM Account is not a POSIX group. Grounded in the 2026-07-16 punim0264
  revocation (fresh sessions denied, one multiplexed session still "fine",
  ~7TB/6.6M files at stake).
tags: [scitex-hpc-spartan-identity-access-traps, scitex-hpc, scitex-package]
---

# Identity & access traps on a shared cluster

Permission bugs on a shared cluster are usually diagnosed wrong, because the
tool you reach for first (`ssh host id`) can silently answer from a connection
opened before the thing you are debugging happened.

## The trap: a multiplexed ssh session reads the PAST

An ssh **ControlMaster** (connection multiplexing — `ControlPath`/`ControlPersist`,
on by default in many configs) reuses one TCP connection for later `ssh` calls.
The user's group vector is fixed when that master session **authenticates**. If
a group is revoked afterwards, every command riding the existing master keeps
the **old** vector: `id -Gn` still lists the group, and file access still
succeeds — because the kernel is enforcing credentials granted at login, not
re-resolving LDAP per command.

A **fresh** connection gets the current truth. So the same command, on the same
host, minutes apart, gives opposite answers depending only on whether it reused
the master.

**The tell:** *"but it worked an hour ago"* / *"it works on login1 but not
login2"* / *"it's intermittent"*. That is not a flap — that is one cached
session outliving a revocation.

**Why this is worse than a flap:** a flap self-heals; a revocation masked by
stale sessions only **degrades**, as long-lived sessions close one by one.
Reading it as "transient, will pass" is exactly backwards — the blast radius
grows with time.

## Probe authoritatively

```bash
# 1. Bypass the master — re-probe on a genuinely fresh connection.
ssh -o ControlPath=none host 'id; getent passwd $USER; getent group <grp>'

# 2. Compare against a node you have NOT touched this session.
ssh -o ControlPath=none other-login 'id -Gn; ls -d /path/in/<grp> && echo OK'
```

Rules of evidence, strongest first:

1. **`getent group <grp>`** — the directory's member list. This is truth. If the
   user is not listed here **and** their `getent passwd` primary GID is a
   different group, they have **no membership at all** — neither primary nor
   secondary — regardless of what any `id` says.
2. **`getent passwd <user>`** — field 4 is the primary GID. Primary membership
   does not appear in the group's member list, so you must check both to rule
   membership in or out.
3. **`id` on a fresh session** — current, but still a snapshot of login.
4. **`id` on a multiplexed session** — evidence about the past. Not usable.

A corollary worth internalising: *an interactive session that predates the
change can never disagree with you.* If your evidence is "the operator's shell
can still `ls` it", you have proven nothing.

## Worked example — the 2026-07-16 punim0264 revocation

Reported as "login1 intermittently loses the punim0264 group; sssd/LDAP cache
flap". The authoritative probe said otherwise:

```
getent group punim0264   → punim0264:*:10278:karolyp,stirlingr,pokhims,jieying1   # no ywatanabe
getent passwd ywatanabe  → ywatanabe:*:17107:12453:...                            # primary GID = punim2354
getent group punim2354   → punim2354:*:12453:ywatanabe                            # his only membership
login1 (ControlPath=none) → uid=17107 gid=12453(punim2354) groups=12453(punim2354)
login2 / login3          → id -Gn = punim2354 ;  /data/gpfs/projects/punim0264 → DENIED
```

Not primary, not secondary, absent from the member list: membership was
**revoked**, not flapping. The only probe that showed it healthy was one over an
existing ControlMaster on login1. Fix was account-side (re-add to gid 10278) —
there was nothing to repair in sssd, and nothing to wait out.

## Why losing a project group breaks the SHELL, not just data

On Spartan, `$HOME` dotdirs commonly symlink into a project filesystem
(`~/.cache`, `~/.local`, and venvs like `~/.env-3.11` → `/data/gpfs/projects/<proj>/...`).
Lose the group and **shell init itself** fails, on login *and* compute nodes:

```
error: Unable to create TMPDIR [/home/<u>/.cache/tmp]: Permission denied
mkdir: cannot create directory '/home/<u>/.cache': Permission denied
~/.bash_profile: line NN: /home/<u>/.local/bin/env: Permission denied
```

So the symptom presents as "my environment is broken / my venv vanished", far
from the actual cause. When a project group is in doubt, check the **symlink
targets of `$HOME` dotdirs** before believing an env-corruption theory. (See
[13_compatibility-policies.md](13_compatibility-policies.md) for the login-shell
wrapping this interacts with.)

## A SLURM Account is not a POSIX group

`#SBATCH --account=<proj>` (billing) and the POSIX group `<proj>` (file access)
are **independent**. A revoked group still leaves jobs schedulable under that
account — they queue, start, and then fail on file access. The result reads as
bizarre partial breakage: SLURM says RUNNING, the job says Permission denied.
Do not infer group health from a job that scheduled.

## Rule

Before concluding *cache flap*, *sssd lag*, *transport flakiness*, or *env
corruption* for any permission symptom: **re-probe with
`ssh -o ControlPath=none` and read `getent group`.** If a fresh session and the
directory disagree with a live session, the live session is the liar — and the
clock is against you, because it is the last thing still working.
