#!/usr/bin/env bash
# ============================================================================
# Spartan login-node heavy-compute guard  (scitex-hpc)
# ----------------------------------------------------------------------------
# Blocks the TeX toolchain from running on a Spartan LOGIN node, where heavy
# compute is strictly prohibited by UniMelb HPC policy and gets the account
# sanctioned. Real builds must go through SLURM (srun/sbatch) on a compute node.
#
# Mechanism: shell FUNCTION overrides (these beat both PATH lookups and
# `module load`, which a PATH-shim cannot). The guard is a no-op
#   - inside a SLURM allocation  ($SLURM_JOB_ID set)        -> real binary runs
#   - on a compute node          (hostname not spartan-login*) -> real binary
# so the CI runner fleet and all legitimate compute are unaffected. It only
# refuses on spartan-login*/gateway hosts OUTSIDE a job.
#
# Installed by sourcing from ~/.bashrc ABOVE the `[[ $- != *i* ]] && return`
# line, so it also applies to non-interactive `ssh spartan '<cmd>'` (bash
# sources ~/.bashrc for sshd-spawned non-interactive shells). Remove by
# deleting the source line in ~/.bashrc and this file.
# Incident: 2026-07-01 (pdflatex/latexmk over ssh on a login node).
# ============================================================================

# Only meaningful on Spartan; cheap no-op elsewhere.
case "$(uname -n 2>/dev/null)" in
  spartan*) : ;;
  *) return 0 2>/dev/null || exit 0 ;;
esac

# Real texlive bin (the `texlive/20230313` module adds nothing to PATH).
_STX_TEXBIN="/apps/easybuild-2022/easybuild/software/Compiler/GCCcore/11.3.0/texlive/20230313/bin/x86_64-linux"

_spartan_login_guard() {
  local tool="$1"; shift
  # Inside a SLURM allocation => compute node => allow the real binary.
  if [ -n "${SLURM_JOB_ID:-}" ] || [ -n "${SLURM_JOBID:-}" ]; then
    command "$tool" "$@"; return $?
  fi
  case "$(uname -n 2>/dev/null)" in
    spartan-login*|spartan-gateway*|spartanlogin*)
      {
        printf '\n\033[1;31m[BLOCKED]\033[0m heavy compute on Spartan login node \033[1m%s\033[0m: %s\n' "$(uname -n)" "$tool"
        printf '  UniMelb HPC policy: login nodes are for EDIT + SUBMIT only. TeX compilation is heavy compute.\n'
        printf '  Run it on a COMPUTE node via SLURM instead:\n'
        printf '    srun --partition=cascade --qos=publiccpu --time=0:30:00 --cpus-per-task=2 --mem=4G \\\n'
        printf '         bash /path/to/build.sh        # build script on SHARED /data or $HOME, not per-node /tmp\n'
        printf '    spartan-tex <file.tex>             # canonical helper: auto-wraps the compile in srun\n\n'
      } >&2
      return 100 ;;
  esac
  # Compute node without a job env (unusual) — allow.
  command "$tool" "$@"
}

# TeX toolchain — the incident vector; never legitimately needed on a login node.
for _stx_t in xelatex pdflatex lualatex luatex latex latexmk biber bibtex \
              makeindex dvipdfmx xdvipdfmx dvips ps2pdf tex; do
  eval "${_stx_t}() { _spartan_login_guard ${_stx_t} \"\$@\"; }"
  export -f "${_stx_t}" 2>/dev/null || true
done
export -f _spartan_login_guard 2>/dev/null || true
unset _stx_t

# Canonical helper: compile a TeX file on a compute node via srun (dogfood this).
spartan-tex() {
  if [ -z "${1:-}" ]; then echo "usage: spartan-tex <file.tex> [latexmk args]" >&2; return 2; fi
  local f="$1"; shift
  srun --partition=cascade --qos=publiccpu --time=0:30:00 --cpus-per-task=2 --mem=4G \
       bash -c 'export PATH="'"$_STX_TEXBIN"':$PATH"; cd "$(dirname "$1")" && latexmk -pdf -interaction=nonstopmode "$@"' _ "$f" "$@"
}
export -f spartan-tex 2>/dev/null || true
