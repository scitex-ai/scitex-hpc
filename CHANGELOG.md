# Changelog

All notable changes to `scitex-hpc` are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning
follows [SemVer](https://semver.org/).

## [Unreleased]

### Removed
- **BREAKING — the `mcp` extra is gone.** Install MCP support with
  `pip install 'scitex-hpc[all]'`. PS-225 restricts extra *names* to
  `{all, dev, docs}`, and `fastmcp` is neither tooling nor documentation, so
  `all` is the only permitted home for it. It stays an *optional* dependency —
  it is imported lazily and a SLURM user who never runs an MCP server should
  not carry it — which is why it is not folded into core.

  **Installing the old extra does NOT fail. It exits 0.** Measured against this
  package with an undeclared extra name (name redacted here, because a literal
  one in prose is itself flagged as a broken install remedy by PS-215 §3):

  ```
  rc=0
  WARNING: scitex-hpc 0.9.0 does not provide the extra '<undeclared>'
  ```

  pip warns, installs the base package, and silently omits the extra. So the old
  command now *looks* like it worked and leaves `fastmcp` missing. Packaging
  offers no alias for a removed extra, so there is no warn-forward phase
  available — the only place a migration signal can live is our own output, and
  every message that mentions installation now says `[all]` and states plainly
  that the old form installs nothing.

  The cost, stated because it is a deliberate trade and not an oversight: there
  is no longer any way to get MCP support without also installing `dev`
  (pytest, ruff) and `docs` (six sphinx packages).

### Added
- **`scitex-hpc liveness check-heartbeat`** — the same instrument shape for the
  *other* class of thing we run: a bare loop on a node, holding a lockfile
  and appending to a log on a fixed cadence. `liveness check` cannot see
  these at all, because they live inside somebody else's allocation.
  Answers ALIVE / **STALLED** / **STOPPED** / UNKNOWN with its evidence.

  Two distinctions carry the design. **STALLED** (a holder exists but the
  cadence was missed) is never folded into ALIVE — a process that is
  present and not doing its job is the failure that a moving log disguises.
  And **STOPPED must be earned from a node-local observation**: `/proc` is
  node-local and `flock` is not guaranteed cluster-coherent on shared
  storage, so a probe run from the login node can acquire a lock a compute
  node genuinely holds. A false STOPPED authorises starting a replacement,
  and two copies read-modify-writing shared state is worse than none —
  both logs keep moving, so it presents as healthy. Any negative holder
  reading taken from the wrong node is therefore UNKNOWN, never STOPPED.

  A tick that is simply *not due yet* is ALIVE, not UNKNOWN: "no tick yet,
  within interval" is a healthy reading and collapsing it into either pole
  is the bug. Ages are computed from the remote clock against the
  component's own UTC stamps, so no local timezone enters the arithmetic.
- **`scitex-hpc liveness`** — a SLURM job-liveness instrument that answers
  ALIVE / DEAD / **UNKNOWN** with the evidence it used. `UNKNOWN` is a
  first-class answer, not an error: a probe that timed out or found no
  witness must not be reported as either "running" or "gone", because
  collapsing it into a pole is how a dead allocation gets treated as
  healthy (and vice versa).
- **`lease sync-state NAME --dry-run`** — perform the same `squeue` query
  the real run performs and print the lease record it *would* have
  written, without saving. Fields that would change are starred, so what
  catches the eye is the edge rather than the middle:

  ```
  DRY RUN — would sync lease state for spartan-foo, not saved:
    * job_id: '42' -> '200'
    * node: '' -> 'bm175'
      walltime_end: None -> None
  ```
- `lease adopt NAME --job-id <id> --host <host> [--persistent]` (also via
  the deprecated `reservations adopt` alias) — register an EXISTING
  running SLURM job as a lease WITHOUT submitting any sbatch. Writes the
  same lease state `book` writes (wraps `Reservation.from_jobid`), so
  post-adopt `lease get` / `lease refresh` work and `refresh`
  re-discovers the job_id by name. Honors "never request a new node":
  brings an ad-hoc / externally-submitted hold-job under lease management
  for the solver to refresh-track. `--persistent` only MARKS the lease
  persistent — it cannot retro-fit a SIGUSR1 walltime auto-resubmit trap
  onto an already-running job (that trap is installed only by `book
  --persistent` at sbatch time); at walltime the job ends and the solver
  re-books one fresh node.
- `reservations book --nodelist NODE` — pin a hold-job to a specific
  compute node (useful for landing on a node the operator already
  needs ssh access to via `pam_slurm_adopt`, or one with a specific
  hardware feature).
- `reservations book --account` / `--qos` — surface SLURM account /
  QOS as first-class flags. Routed through the standard
  `JobConfig.resolve()` cascade so `~/.scitex/hpc/config.yaml`
  defaults propagate.
- `mcp start | doctor | install` — convention §3 MCP CLI compliance.
- `install-shell-completion` / `print-shell-completion` — §1a CLI
  surface.

### Changed
- **Three CLI verbs moved to their canonical spellings.** Every old
  spelling still works and prints a one-line notice to stderr naming its
  replacement — nothing is removed in this release:

  | old | new |
  |---|---|
  | `lease refresh` | `lease sync-state` |
  | `lease cancel` | `lease close` |
  | `lease release` | `lease close` |
  | `quota check` | `quota validate` |

  `lease release` was already a hidden alias but **never warned**; it does
  now. `sync-state` names its object deliberately: in this package `sync`
  already means "rsync files to the cluster" (`scitex_hpc.sync`), and this
  verb moves no bytes — it reconciles the local lease record from
  `squeue`. The Python API names (`Reservation.refresh()`, `.release()`)
  are **unchanged**; this moved CLI verbs only.
- **Renamed the `reservations` CLI command group to `lease`** (shorter,
  now the primary/documented name). Subcommands are
  `book` / `adopt` / `list` / `get` / `exec` / `sync-state` / `attach` /
  `close`.
  `reservations` is kept as a **deprecated alias** that forwards to the
  exact same command objects (no duplicated logic) and prints a one-line
  deprecation notice to stderr — so existing `scitex-hpc reservations …`
  callers keep working with identical behavior and exit codes. Migrate
  to `scitex-hpc lease …` at your convenience.
- `reservations book --host` is no longer `required=True` at the
  Click layer. The package's `JobConfig.resolve("host")` cascade
  (env `SCITEX_HPC_HOST` → `~/.scitex/hpc/config.yaml`) now fills
  the value when omitted, matching the rest of the SciTeX
  convention. Operators with a single cluster never type `--host`
  again. The Python API still raises a clear `ValueError` when the
  cascade comes up empty.
