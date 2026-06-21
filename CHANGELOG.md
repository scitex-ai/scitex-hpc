# Changelog

All notable changes to `scitex-hpc` are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning
follows [SemVer](https://semver.org/).

## [Unreleased]

### Added
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
- **Renamed the `reservations` CLI command group to `lease`** (shorter,
  now the primary/documented name). All subcommands are unchanged:
  `book` / `list` / `get` / `exec` / `refresh` / `attach` / `cancel`.
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
