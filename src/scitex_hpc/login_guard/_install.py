"""Vendor + deploy the Spartan login-node heavy-compute guard.

Background (incident, 2026-07-01)
---------------------------------
An agent ran the TeX toolchain (``pdflatex``/``latexmk``) over SSH on a
Spartan **login node**. UniMelb HPC policy strictly prohibits heavy
compute on login nodes — admins kill it and can sanction the whole
account. The fix already lives, hand-deployed, on the fleet; this module
**versions** it so it can be re-installed deterministically and reviewed.

What the guard does
-------------------
``login-guard.sh`` (vendored verbatim next to this module) defines shell
**FUNCTION** overrides for the TeX toolchain
(``xelatex``/``pdflatex``/``lualatex``/``latex``/``latexmk``/``biber``/
``bibtex``/``makeindex``/``dvipdfmx``/``xdvipdfmx``/``dvips``/``ps2pdf``/
``tex``) that REFUSE to run on ``spartan-login*`` hosts UNLESS inside a
SLURM allocation (``$SLURM_JOB_ID`` set). Functions are used (not a PATH
shim) specifically because functions beat both PATH and ``module load``.
It is a **no-op inside jobs and on compute nodes**, so the CI runner
fleet and all legitimate compute are unaffected. A ``spartan-tex`` helper
wraps a compile in ``srun`` for convenience.

This module is pure string generation + a thin SSH call, exactly like
``ci_runners``: :func:`guard_text` returns the vendored script,
:func:`build_bashrc` performs the idempotent ``~/.bashrc`` transform
(unit-testable without SSH), and :func:`install` does the actual remote
deployment behind an explicit call (never on import).
"""

from __future__ import annotations

from importlib import resources

# Where the guard lands on the remote host (mirrors the live deployment).
REMOTE_GUARD_PATH = "~/.scitex/hpc/login-guard.sh"

# The line bash uses to bail out of ~/.bashrc for non-interactive shells.
# We must insert the guard source line ABOVE this so it ALSO applies to
# non-interactive ``ssh host '<cmd>'`` (which is exactly the incident
# vector: ``ssh spartan 'pdflatex ...'``).
_INTERACTIVE_RETURN = "[[ $- != *i* ]] && return"

# Live-deployment anchor: the guard source line is inserted right AFTER
# this Spartan non-interactive libs source line. If absent we fall back to
# prepending near the top (still before the interactive-return guard).
_ANCHOR_SUBSTR = "000_spartan_noninteractive_libs.src"

# Marker comment so the insertion is idempotent (re-running never dupes).
_MARKER = "# >>> scitex-hpc login-node guard >>>"
_MARKER_END = "# <<< scitex-hpc login-node guard <<<"


def guard_text() -> str:
    """Return the vendored guard script verbatim.

    Loaded from the packaged ``login-guard.sh`` via importlib.resources so
    it ships with the wheel and stays byte-identical to the hand-deployed
    source of truth.
    """
    return (
        resources.files(__package__)
        .joinpath("login-guard.sh")
        .read_text(encoding="utf-8")
    )


def _source_block(remote_path: str = REMOTE_GUARD_PATH) -> str:
    """The idempotent, marker-wrapped source block to splice into bashrc.

    The path is left UNQUOTED in the ``[ -f ... ] && . ...`` test so a
    leading ``~`` is tilde-expanded by bash at source time (a quoted
    ``"~/..."`` would be treated literally). ``REMOTE_GUARD_PATH`` has no
    whitespace, so leaving it unquoted is safe.
    """
    return (
        f"{_MARKER}\n"
        f"# Spartan login-node heavy-compute guard (scitex-hpc, incident 2026-07-01).\n"
        f"# Sourced ABOVE the interactive-return so it also applies to\n"
        f"# non-interactive ``ssh spartan '<cmd>'``. No-op inside SLURM jobs.\n"
        f"[ -f {remote_path} ] && . {remote_path}\n"
        f"{_MARKER_END}"
    )


def build_bashrc(
    bashrc: str,
    *,
    remote_path: str = REMOTE_GUARD_PATH,
) -> str:
    """Return ``bashrc`` with the guard source block idempotently inserted.

    Insertion rules (replicating the live deployment):

      1. If the marker block is already present, replace it in place
         (idempotent — re-running never duplicates the source line).
      2. Else, if the ``000_spartan_noninteractive_libs.src`` anchor line
         is present, insert the block right AFTER it.
      3. Else, prepend the block near the top, but ALWAYS before the
         ``[[ $- != *i* ]] && return`` interactive-return guard so it
         applies to non-interactive SSH commands too.

    Pure string transform — no SSH, no filesystem — so the placement
    logic is unit-testable on its own.
    """
    block = _source_block(remote_path)

    # (1) Idempotent replace of an existing marker block.
    if _MARKER in bashrc and _MARKER_END in bashrc:
        start = bashrc.index(_MARKER)
        end = bashrc.index(_MARKER_END) + len(_MARKER_END)
        return bashrc[:start] + block + bashrc[end:]

    lines = bashrc.splitlines(keepends=True)

    # (2) Anchor after the Spartan non-interactive libs source line.
    anchor_idx = next(
        (i for i, ln in enumerate(lines) if _ANCHOR_SUBSTR in ln), None
    )
    if anchor_idx is not None:
        insert_at = anchor_idx + 1
    else:
        # (3) Fall back to just before the interactive-return guard, else
        # the very top.
        ret_idx = next(
            (i for i, ln in enumerate(lines) if _INTERACTIVE_RETURN in ln),
            None,
        )
        insert_at = ret_idx if ret_idx is not None else 0

    insert_text = block + "\n"
    # Keep a clean blank line after the block if the next line isn't blank.
    if insert_at < len(lines) and lines[insert_at].strip():
        insert_text += "\n"
    lines.insert(insert_at, insert_text)
    return "".join(lines)


def build_install_script(
    *,
    remote_path: str = REMOTE_GUARD_PATH,
) -> str:
    """Return the remote bash script that deploys the guard safely.

    The generated script (run on the remote host over SSH):

      * writes the vendored guard to ``remote_path`` (mkdir -p its dir)
        and ``chmod +x`` it,
      * backs up ``~/.bashrc`` to ``~/.bashrc.scitex-hpc.bak.<ts>``,
      * computes the new ``~/.bashrc`` via the SAME insertion rules as
        :func:`build_bashrc` (delegated to an embedded python3 one-shot so
        the transform logic is not re-implemented in shell), and
      * ``bash -n``-validates the candidate BEFORE replacing the live
        ``~/.bashrc`` — never installs a syntactically broken profile.

    Pure string generation; :func:`install` feeds it to ``exec_remote``.
    """
    guard = guard_text()
    block = _source_block(remote_path)
    # For the script's filesystem ops a quoted ``"~/..."`` would NOT
    # tilde-expand, so map a leading ``~/`` to ``$HOME/`` for the real
    # write target (the bashrc source line keeps the unquoted ``~`` form).
    script_path = (
        f"$HOME/{remote_path[2:]}"
        if remote_path.startswith("~/")
        else remote_path
    )
    # Heredocs (quoted sentinels) so the guard body and the python helper
    # are passed verbatim, never re-expanded by the outer shell.
    return f"""#!/usr/bin/env bash
# scitex-hpc login-node guard installer (generated). Safe + idempotent.
set -euo pipefail

GUARD_PATH="{script_path}"
GUARD_DIR="$(dirname "$GUARD_PATH")"
mkdir -p "$GUARD_DIR"

cat > "$GUARD_PATH" <<'__SCITEX_GUARD_EOF__'
{guard}__SCITEX_GUARD_EOF__
chmod +x "$GUARD_PATH"
echo "wrote guard -> $GUARD_PATH"

BASHRC="$HOME/.bashrc"
[ -f "$BASHRC" ] || touch "$BASHRC"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BAK="$BASHRC.scitex-hpc.bak.$TS"
cp -p "$BASHRC" "$BAK"
echo "backed up ~/.bashrc -> $BAK"

CANDIDATE="$(mktemp)"
python3 - "$BASHRC" "$GUARD_PATH" > "$CANDIDATE" <<'__SCITEX_PY_EOF__'
import sys

MARKER = {_MARKER!r}
MARKER_END = {_MARKER_END!r}
ANCHOR = {_ANCHOR_SUBSTR!r}
RET = {_INTERACTIVE_RETURN!r}

bashrc_path, remote_path = sys.argv[1], sys.argv[2]
with open(bashrc_path, encoding="utf-8") as fh:
    bashrc = fh.read()

block = (
{block!r}
)

if MARKER in bashrc and MARKER_END in bashrc:
    start = bashrc.index(MARKER)
    end = bashrc.index(MARKER_END) + len(MARKER_END)
    sys.stdout.write(bashrc[:start] + block + bashrc[end:])
    raise SystemExit

lines = bashrc.splitlines(keepends=True)
anchor_idx = next((i for i, ln in enumerate(lines) if ANCHOR in ln), None)
if anchor_idx is not None:
    insert_at = anchor_idx + 1
else:
    ret_idx = next((i for i, ln in enumerate(lines) if RET in ln), None)
    insert_at = ret_idx if ret_idx is not None else 0

insert_text = block + "\\n"
if insert_at < len(lines) and lines[insert_at].strip():
    insert_text += "\\n"
lines.insert(insert_at, insert_text)
sys.stdout.write("".join(lines))
__SCITEX_PY_EOF__

# Validate BEFORE replacing the live profile — never install a broken ~/.bashrc.
if ! bash -n "$CANDIDATE"; then
  echo "candidate ~/.bashrc failed bash -n; aborting (live profile untouched, backup at $BAK)" >&2
  rm -f "$CANDIDATE"
  exit 1
fi

cp "$CANDIDATE" "$BASHRC"
rm -f "$CANDIDATE"
echo "installed guard source line into ~/.bashrc (idempotent; backup $BAK)"
"""


def install(*, host: str = "spartan") -> "object":
    """Deploy the guard to ``host`` over SSH (explicit call, never on import).

    Copies the vendored guard to ``~/.scitex/hpc/login-guard.sh``, makes
    it executable, backs up ``~/.bashrc``, ``bash -n``-validates a
    candidate, and idempotently inserts the source line ABOVE the
    interactive-return guard (after the Spartan non-interactive libs
    anchor when present). Returns the ``scitex_ssh`` result object.
    """
    from scitex_ssh import exec_remote

    import shlex

    script = build_install_script()
    # shlex.quote (not json.dumps): the script carries the multi-line guard
    # body inside a quoted heredoc; literal-\n escaping would collapse it.
    return exec_remote(host, f"bash -lc {shlex.quote(script)}")
