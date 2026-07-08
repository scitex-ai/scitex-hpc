#!/usr/bin/env bash
# ============================================================================
# HPC login-node guard  (scitex-hpc, profile: spartan)  [GENERATED]
# ----------------------------------------------------------------------------
# Blocks heavy compute (TeX toolchain) and recursive metadata walks (du/find
# over the protected filesystem) on a LOGIN node, where HPC policy prohibits
# them and the account gets sanctioned. Real work must go through SLURM
# (srun/sbatch) on a compute node.
#
# Mechanism: shell FUNCTION overrides (these beat both PATH lookups and
# `module load`, which a PATH-shim cannot). The guard is a no-op
#   - inside a SLURM allocation  ($SLURM_JOB_ID set)        -> real binary runs
#   - on a compute node          (hostname not a login pattern) -> real binary
# so the CI runner fleet and all legitimate compute are unaffected. It only
# refuses on login/gateway hosts OUTSIDE a job.
#
# Installed by sourcing from ~/.bashrc ABOVE the `[[ $- != *i* ]] && return`
# line, so it also applies to non-interactive `ssh spartan '<cmd>'` (bash
# sources ~/.bashrc for sshd-spawned non-interactive shells). Remove by
# deleting the source line in ~/.bashrc and this file.
# Incidents: 2026-07-01 (pdflatex/latexmk over ssh on a login node;
# recursive du/find over the GPFS project tree stressing the metadata disks).
#
# This file is GENERATED from a scitex_hpc.login_guard GuardProfile — edit the
# profile + renderer, not this artifact.
# ============================================================================

# Only meaningful on this site; cheap no-op elsewhere.
case "$(uname -n 2>/dev/null)" in
  spartan*) : ;;
  *) return 0 2>/dev/null || exit 0 ;;
esac

# Real texlive bin (the texlive module may add nothing to PATH).
_SPARTAN_TEXBIN="/apps/easybuild-2022/easybuild/software/Compiler/GCCcore/11.3.0/texlive/20230313/bin/x86_64-linux"

_spartan_login_guard() {
  local tool="$1"; shift
  # Inside a SLURM allocation => compute node => allow the real binary.
  if [ -n "${SLURM_JOB_ID:-}" ] || [ -n "${SLURM_JOBID:-}" ]; then
    command "$tool" "$@"; return $?
  fi
  case "$(uname -n 2>/dev/null)" in
    spartan-login*|spartan-gateway*|spartanlogin*)
      {
        printf '\n\033[1;31m[BLOCKED]\033[0m heavy compute on spartan login node \033[1m%s\033[0m: %s\n' "$(uname -n)" "$tool"
        printf '  HPC policy: login nodes are for EDIT + SUBMIT only. TeX compilation is heavy compute.\n'
        printf '  Run it on a COMPUTE node via SLURM instead:\n'
        printf '    srun --partition=cascade --qos=publiccpu --time=0:30:00 --cpus-per-task=2 --mem=4G \\\n'
        printf '         bash /path/to/build.sh        # build script on SHARED storage or $HOME, not per-node /tmp\n'
        printf '    spartan-tex <file.tex>             # canonical helper: auto-wraps the compile in srun\n\n'
      } >&2
      return 100 ;;
  esac
  # Compute node without a job env (unusual) — allow.
  command "$tool" "$@"
}

# Heavy toolchain — the incident vector; never legitimately needed on a login node.
for _stx_t in xelatex pdflatex lualatex luatex latex latexmk biber bibtex makeindex dvipdfmx xdvipdfmx dvips ps2pdf tex; do
  eval "${_stx_t}() { _spartan_login_guard ${_stx_t} \"\$@\"; }"
  export -f "${_stx_t}" 2>/dev/null || true
done
export -f _spartan_login_guard 2>/dev/null || true
unset _stx_t

# ----------------------------------------------------------------------------
# Filesystem-walk guard: block du/find that walk the protected tree
# (/data/) on a login node. Recursive du/find over the parallel
# filesystem stresses the metadata disks and reads as a DoS to the storage
# layer — the exact behavior that drew repeated admin complaints and fed the
# quota pressure. Scoped to protected prefixes so trivial local `find`/`du`
# in $HOME still works. No-op inside a SLURM job or on a compute node.
# To CHECK quota/usage, use the metadata-only query (no walk):
#   mmlsquota -j punim2354 punim2354
# To genuinely walk the tree, do it inside a SLURM job on a compute node.
_spartan_fswalk_guard() {
  local tool="$1"; shift
  if [ -n "${SLURM_JOB_ID:-}" ] || [ -n "${SLURM_JOBID:-}" ]; then
    command "$tool" "$@"; return $?
  fi
  case "$(uname -n 2>/dev/null)" in
    spartan-login*|spartan-gateway*|spartanlogin*) : ;;
    *) command "$tool" "$@"; return $? ;;
  esac
  # On a login node: block only when the walk targets the protected tree
  # (/data/), either via an explicit argument or the current directory.
  local _a _hits=0
  case "$PWD" in /data/*) _hits=1 ;; esac
  for _a in "$@"; do
    case "$_a" in /data/*) _hits=1 ;; esac
  done
  if [ "$_hits" -eq 1 ]; then
    {
      printf '\n\033[1;31m[BLOCKED]\033[0m filesystem walk on spartan login node \033[1m%s\033[0m: %s\n' "$(uname -n)" "$tool"
      printf '  Recursive %s over the protected filesystem (/data/) stresses the metadata disks and reads as a DoS —\n' "$tool"
      printf '  it is the behavior that drew admin complaints + the quota pressure.\n'
      printf '  \342\200\242 Check quota/usage WITHOUT walking:  mmlsquota -j punim2354 punim2354\n'
      printf '  \342\200\242 Need a real tree walk? Do it inside a SLURM job on a compute node:\n'
      printf '      srun --partition=cascade --qos=publiccpu --time=0:30:00 --cpus-per-task=2 --mem=4G %s %s\n\n' "$tool" "$*"
    } >&2
    return 100
  fi
  command "$tool" "$@"
}
for _stx_w in du find; do
  eval "${_stx_w}() { _spartan_fswalk_guard ${_stx_w} \"\$@\"; }"
  export -f "${_stx_w}" 2>/dev/null || true
done
export -f _spartan_fswalk_guard 2>/dev/null || true
unset _stx_w

# Canonical helper: compile a TeX file on a compute node via srun (dogfood this).
spartan-tex() {
  if [ -z "${1:-}" ]; then echo "usage: spartan-tex <file.tex> [latexmk args]" >&2; return 2; fi
  local f="$1"; shift
  srun --partition=cascade --qos=publiccpu --time=0:30:00 --cpus-per-task=2 --mem=4G \
       bash -c 'export PATH="'"$_SPARTAN_TEXBIN"':$PATH"; cd "$(dirname "$1")" && latexmk -pdf -interaction=nonstopmode "$@"' _ "$f" "$@"
}
export -f spartan-tex 2>/dev/null || true
