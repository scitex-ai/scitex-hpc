#!/usr/bin/env bash
# Outer apptainer-exec wrapper for scitex-hpc's self-hosted CI.
#
# Runs ON THE RUNNER (outside the SIF). Resolves the apptainer binary + SIF
# image, then `apptainer exec`s the SIF and hands off to an INNER script (run
# inside the container). Keeps every workflow job's YAML down to one line —
# `bash .github/ci/exec-in-sif.sh <inner-script> [args...]` — and concentrates
# all the SIF plumbing (binary resolution, ~-expansion, scratch, binds) in one
# version-controlled place.
#
# HOST-INDEPENDENT BY CONSTRUCTION. This script used to assume Spartan in four
# places — a required apptainer path under ~/.env-3.11, a PATH prepend to that
# directory, an APPTAINER_TMPDIR under /data/gpfs/projects/punim0264, and an
# unconditional --bind of that same tree. On a runner without them it failed at
# the mkdir, before the apptainer path was even consulted. Each is now used
# WHEN PRESENT and skipped when absent, so the same script works on Spartan and
# on a plain Linux runner. Measured 2026-08-05: scitex-compute-01/02 carry
# apptainer at /usr/bin/apptainer and have no /data/gpfs and no ~/.env-3.11.
#
# Optional env (repo Actions Variables — overrides, not requirements):
#   SCITEX_CI_APPTAINER   path to a specific apptainer binary
#                         (Spartan: ~/.env-3.11/bin/apptainer)
#   SCITEX_CI_SIF         path to the CI SIF image
#                         (default: ~/.scitex/dev/containers/ci-cpu.sif)
#
# Usage:
#   bash .github/ci/exec-in-sif.sh run-in-sif.sh 3.12
#
# Fail-loud (operator directive): a missing apptainer or SIF is a HARD error —
# never a silent fallback to a bare-runner install. What changed is WHERE we
# look, not whether we fail when it is absent.
set -euo pipefail

INNER="${1:?inner script name required (relative to .github/ci/)}"
shift || true

# ~-expand the Actions-Variable paths: a quoted "~/…" is NOT tilde-expanded by
# the shell, so substitute a leading ~ with $HOME ourselves.
expand_tilde() { printf '%s' "${1/#\~/$HOME}"; }

# The runner's job shell is --noprofile --norc (no Lmod), so a shim directory
# has to be put on PATH explicitly — but only if it actually exists here.
[ -d "$HOME/.env-3.11/bin" ] && export PATH="$HOME/.env-3.11/bin:$PATH"

# apptainer: the configured path wins WHEN USABLE, otherwise resolve from PATH.
# A configured-but-missing path is reported rather than silently ignored — it
# means the variable describes a different machine, which is worth knowing.
APPTAINER=""
if [ -n "${SCITEX_CI_APPTAINER:-}" ]; then
    CONFIGURED="$(expand_tilde "$SCITEX_CI_APPTAINER")"
    if [ -x "$CONFIGURED" ]; then
        APPTAINER="$CONFIGURED"
    else
        echo "::warning::SCITEX_CI_APPTAINER=$CONFIGURED is not executable on $(hostname -s); falling back to PATH"
    fi
fi
[ -n "$APPTAINER" ] || APPTAINER="$(command -v apptainer || true)"
[ -n "$APPTAINER" ] && [ -x "$APPTAINER" ] || {
    echo "::error::no apptainer found — set SCITEX_CI_APPTAINER to a valid path or install apptainer on this runner"
    exit 1
}

SIF="$(expand_tilde "${SCITEX_CI_SIF:-$HOME/.scitex/dev/containers/ci-cpu.sif}")"
[ -f "$SIF" ] || {
    echo "::error::CI SIF missing at $SIF — rebuild it: scitex-container apptainer build ci-cpu"
    exit 1
}

# apptainer scratch. Prefer the shared project FS where it exists (keeps HOME
# clean on Spartan, whose HOME is inode-capped); otherwise node-local temp.
GPFS_ROOT="/data/gpfs/projects/punim0264"
if [ -d "$GPFS_ROOT" ]; then
    export APPTAINER_TMPDIR="$GPFS_ROOT/ywatanabe/ci/apptainer-tmp"
else
    export APPTAINER_TMPDIR="${TMPDIR:-/tmp}/apptainer-tmp"
fi
mkdir -p "$APPTAINER_TMPDIR"

# --bind the project tree only where it exists: on Spartan $HOME/.scitex is a
# symlink into punim0264 and the bind is what makes it resolve inside the
# container. Binding a nonexistent source is a hard apptainer error, so this
# must stay conditional. --pwd "$PWD" keeps the checkout as cwd.
BIND_ARGS=()
[ -d "$GPFS_ROOT" ] && BIND_ARGS=(--bind "$GPFS_ROOT")

exec "$APPTAINER" exec --pwd "$PWD" "${BIND_ARGS[@]+"${BIND_ARGS[@]}"}" \
    "$SIF" bash ".github/ci/$INNER" "$@"
