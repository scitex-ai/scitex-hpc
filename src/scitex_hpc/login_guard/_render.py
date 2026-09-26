"""Render the login-node guard shell from a :class:`GuardProfile`.

Like ``ci_runners`` (which generates its supervisor shell from Python),
the guard is GENERATED from the profile rather than shipped as a static
``.sh``. :func:`render_guard` templates the site-specific values — login
host patterns, protected FS prefixes, tool lists, quota hint, srun prefix,
texlive bin — into a single, self-contained guard script.

The Spartan profile renders a script that is behaviorally identical to the
hand-deployed source of truth: same shell-FUNCTION overrides, same exit
code ``100`` + literal ``[BLOCKED]`` stderr token (the cross-repo contract
scitex-writer keys off), same ``$SLURM_JOB_ID`` escape, same login-node
host match, same ``/data/`` protected-prefix walk guard.
"""

from __future__ import annotations

import re

from ._profile import SPARTAN_PROFILE, GuardProfile

# Cross-repo contract — DO NOT CHANGE (scitex-writer keys off these).
BLOCKED_TOKEN = "[BLOCKED]"
BLOCKED_RC = 100


def _safe_ident(name: str) -> str:
    """Sanitise a profile name into a shell-identifier-safe stem."""
    ident = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not ident or ident[0].isdigit():
        ident = f"_{ident}"
    return ident


def _toplevel_glob(login_node_patterns: list[str]) -> str:
    """Cheap top-level ``case`` gate (``spartan*``) from the first pattern.

    Derives a coarse ``<stem>*`` glob from the first login pattern so the
    whole guard is a fast no-op on unrelated hosts. For ``spartan-login*``
    this yields ``spartan*``.
    """
    if not login_node_patterns:
        return "*"
    first = login_node_patterns[0]
    stem = re.split(r"[-*]", first, maxsplit=1)[0]
    return f"{stem}*" if stem else "*"


def render_guard(profile: GuardProfile = SPARTAN_PROFILE) -> str:
    """Return the guard shell text generated from ``profile``.

    Templates every site-specific value from the profile. The generated
    script is self-contained and safe to source from ``~/.bashrc``.
    """
    name = profile.name
    ident = _safe_ident(name)
    login_fn = f"_{ident}_login_guard"
    fswalk_fn = f"_{ident}_fswalk_guard"
    tex_helper = f"{name}-tex"
    texbin_var = f"_{ident.upper()}_TEXBIN"

    toplevel = _toplevel_glob(profile.login_node_patterns)
    login_cases = "|".join(profile.login_node_patterns)
    heavy_tools = " ".join(profile.heavy_tools)
    fswalk_tools = " ".join(profile.fswalk_tools)
    srun = profile.srun_template
    quota_hint = profile.quota_hint_cmd
    texbin = profile.texbin

    # Protected-prefix case arms for the fswalk guard (one per prefix).
    prefix_cases = "|".join(f"{p}*" for p in profile.protected_path_prefixes)
    # Human-readable list of protected prefixes for the message.
    prefix_disp = ", ".join(profile.protected_path_prefixes)

    return f"""#!/usr/bin/env bash
# ============================================================================
# HPC login-node guard  (scitex-hpc, profile: {name})  [GENERATED]
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
# line, so it also applies to non-interactive `ssh {name} '<cmd>'` (bash
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
  {toplevel}) : ;;
  *) return 0 2>/dev/null || exit 0 ;;
esac

# Real texlive bin (the texlive module may add nothing to PATH).
{texbin_var}="{texbin}"

{login_fn}() {{
  local tool="$1"; shift
  # Inside a SLURM allocation => compute node => allow the real binary.
  if [ -n "${{SLURM_JOB_ID:-}}" ] || [ -n "${{SLURM_JOBID:-}}" ]; then
    command "$tool" "$@"; return $?
  fi
  case "$(uname -n 2>/dev/null)" in
    {login_cases})
      {{
        printf '\\n\\033[1;31m{BLOCKED_TOKEN}\\033[0m heavy compute on {name} login node \\033[1m%s\\033[0m: %s\\n' "$(uname -n)" "$tool"
        printf '  HPC policy: login nodes are for EDIT + SUBMIT only. TeX compilation is heavy compute.\\n'
        printf '  Run it on a COMPUTE node via SLURM instead:\\n'
        printf '    {srun} \\\\\\n'
        printf '         bash /path/to/build.sh        # build script on SHARED storage or $HOME, not per-node /tmp\\n'
        printf '    {tex_helper} <file.tex>             # canonical helper: auto-wraps the compile in srun\\n\\n'
      }} >&2
      return {BLOCKED_RC} ;;
  esac
  # Compute node without a job env (unusual) — allow.
  command "$tool" "$@"
}}

# Heavy toolchain — the incident vector; never legitimately needed on a login node.
for _stx_t in {heavy_tools}; do
  eval "${{_stx_t}}() {{ {login_fn} ${{_stx_t}} \\"\\$@\\"; }}"
  export -f "${{_stx_t}}" 2>/dev/null || true
done
export -f {login_fn} 2>/dev/null || true
unset _stx_t

# ----------------------------------------------------------------------------
# Filesystem-walk guard: block du/find that walk the protected tree
# ({prefix_disp}) on a login node. Recursive du/find over the parallel
# filesystem stresses the metadata disks and reads as a DoS to the storage
# layer — the exact behavior that drew repeated admin complaints and fed the
# quota pressure. Scoped to protected prefixes so trivial local `find`/`du`
# in $HOME still works. No-op inside a SLURM job or on a compute node.
# To CHECK quota/usage, use the metadata-only query (no walk):
#   {quota_hint}
# To genuinely walk the tree, do it inside a SLURM job on a compute node.
{fswalk_fn}() {{
  local tool="$1"; shift
  if [ -n "${{SLURM_JOB_ID:-}}" ] || [ -n "${{SLURM_JOBID:-}}" ]; then
    command "$tool" "$@"; return $?
  fi
  case "$(uname -n 2>/dev/null)" in
    {login_cases}) : ;;
    *) command "$tool" "$@"; return $? ;;
  esac
  # On a login node: block only when the walk targets the protected tree
  # ({prefix_disp}), either via an explicit argument or the current directory.
  local _a _hits=0
  case "$PWD" in {prefix_cases}) _hits=1 ;; esac
  for _a in "$@"; do
    case "$_a" in {prefix_cases}) _hits=1 ;; esac
  done
  if [ "$_hits" -eq 1 ]; then
    {{
      printf '\\n\\033[1;31m{BLOCKED_TOKEN}\\033[0m filesystem walk on {name} login node \\033[1m%s\\033[0m: %s\\n' "$(uname -n)" "$tool"
      printf '  Recursive %s over the protected filesystem ({prefix_disp}) stresses the metadata disks and reads as a DoS —\\n' "$tool"
      printf '  it is the behavior that drew admin complaints + the quota pressure.\\n'
      printf '  \\342\\200\\242 Check quota/usage WITHOUT walking:  {quota_hint}\\n'
      printf '  \\342\\200\\242 Need a real tree walk? Do it inside a SLURM job on a compute node:\\n'
      printf '      {srun} %s %s\\n\\n' "$tool" "$*"
    }} >&2
    return {BLOCKED_RC}
  fi
  command "$tool" "$@"
}}
for _stx_w in {fswalk_tools}; do
  eval "${{_stx_w}}() {{ {fswalk_fn} ${{_stx_w}} \\"\\$@\\"; }}"
  export -f "${{_stx_w}}" 2>/dev/null || true
done
export -f {fswalk_fn} 2>/dev/null || true
unset _stx_w

# Canonical helper: compile a TeX file on a compute node via srun (dogfood this).
{tex_helper}() {{
  if [ -z "${{1:-}}" ]; then echo "usage: {tex_helper} <file.tex> [latexmk args]" >&2; return 2; fi
  local f="$1"; shift
  {srun} \\
       bash -c 'export PATH="'"${texbin_var}"':$PATH"; cd "$(dirname "$1")" && latexmk -pdf -interaction=nonstopmode "$@"' _ "$f" "$@"
}}
export -f {tex_helper} 2>/dev/null || true
"""
