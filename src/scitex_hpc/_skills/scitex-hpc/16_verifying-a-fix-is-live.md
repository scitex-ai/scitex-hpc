# Verifying a fix is live — three ways a fix reads as applied and is not

All three shapes below were measured on this fleet on **2026-07-29**, in one
afternoon, by five different agents who each believed they were looking at a
local problem. They are distinct failure modes with distinct detection costs,
and conflating them is why the underlying bug survived twelve days.

| shape | example | what you observe |
|---|---|---|
| **declared-not-applied** | `RUNNER_TOOL_CACHE` | does nothing; the failure stays visible |
| **applied-in-wrong-place** | a per-workflow `GIT_CONFIG_GLOBAL` | works locally; **hides the curve globally** |
| **doctrine-as-description** | "fresh container + overlay per job" | never measured at all |

## 1. Declared-not-applied

The config carries the right value and the reader ignores it.

Measured instance: `RUNNER_TOOL_CACHE` held the correct per-runner `/tmp`
path while the tool-cache reader still resolved and PATH'd the old shared
`~/.runner-toolcache`. Declared and actual disagreed, and only the declared
one was visible from where the fix was made.

**Detection is cheap** — whoever hits the failure finds it, because the
failure never went away. This is the benign shape.

## 2. Applied-in-wrong-place — the dangerous one

The fix is real and works, but sits downstream of where the problem is
generated. It relieves the symptom *at that call site* while the cause keeps
compounding for everyone else.

Measured instance: redirecting one workflow's codecov step away from the
contended `~/.gitconfig`. That step went green. The file kept growing for
every other repo and every other step, and the step that went green was the
one everybody was watching.

**This shape requires a SECOND OBSERVER, because by construction the first
observer sees green.** The person who applies the fix is *structurally
incapable* of validating it — they are looking at the one place that now
works. Corollary for design: the check cannot live with the fixer. It has to
be a fleet-level observation, or an assertion that runs **where the fix
isn't**.

It is also the only shape that **destroys the signal**. Shape 1 leaves the
failure visible; shape 2 removes the last thing anyone was reading.

## 3. Doctrine-as-description

A design document describes the system in the present tense and nobody ever
measured it. Readers reason from the document as if it were the code.

Measured instance: the fresh-container-and-overlay design in
`14_permanent-allocation-doctrine.md` and the constitution. The CI runners
have no container at all. Three agents built arguments on it the same day.

**Detection cost is highest**, because every reader independently reaches the
same wrong conclusion and their agreement reads as corroboration.

## The general rule

> Local explicability and local greenness both defeat aggregation.

A failure every observer can explain locally never gets aggregated into the
one explanation that is true. Five agents filed six cards for the shared
`.gitconfig` lock race between 07-17 and 07-28, each believing they had found
a local flake, because each was the fixer for their own repo and structurally
could not see the other twenty-seven.

It also means **a flake rate is the wrong statistic for a curve**. The lock
race compounded — `git config --global --add` is a read-modify-write of the
whole file under lock, so hold time grew with the file. Reporting it as a
rate hid an accelerating failure behind a number that looked stable.

## Practical checks

- **Merged ≠ deployed ≠ effective-in-production.** Name which one you mean.
  Generated artifacts (a supervisor `sbatch` body, a cron `monitor.sh`) do not
  change when the generator merges — the running copy was baked earlier.
- **State the acceptance criterion as a production state, not a probe
  result.** "Measured effective" is a property of a probe. If what you care
  about is "the replacement is protecting people", say that.
- **Assert the mechanism; do not trust it.** Setting `GIT_CONFIG_GLOBAL`
  REPLACES the global config — without an `include.path` it silently strips
  `user.name`/`user.email` from every CI commit. That bug was caught only by
  running it, not by reading it.
- **Read the code, not the doc.** `rg` the actual job path, with a positive
  control so an empty result cannot masquerade as absence, then read the
  generated artifact directly.
- **Answering about the wrong artifact is the same error as answering about
  the wrong host.** "Does the base SIF have `fd`?" had no answer, because no
  SIF is in the job path. Name the artifact before measuring it.
