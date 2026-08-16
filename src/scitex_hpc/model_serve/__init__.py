"""The script that serves every locally hosted model on Spartan.

`serve-model.sh` starts one vLLM engine plus a LiteLLM sidecar and a reverse
tunnel, then supervises all three for the life of a SLURM allocation. Until
2026-08-16 it existed only as `~/serve-model.sh` on the Spartan login node —
one copy, on one host, with no author and no diff, while carrying the
reasoning behind several expensively-found fixes in its comments.

This module is the verbatim capture. There is deliberately no Python API yet:
the script is committed unchanged so it has a history BEFORE it has edits, so
that the next commit's diff is exactly the behaviour change. A `_profile` /
`_render` / `_install` / `_health` package in the shape of
:mod:`scitex_hpc.tunnel_supervisor` and :mod:`scitex_hpc.tree_monitor` is the
intended destination, and `models.d/` is the data that renderer will consume —
the four confs are near-identical, differing only in three ports.

See README.md for the two known defects left for that commit, and for why the
confs were the only one of four descriptive layers that stayed truthful.
"""

from __future__ import annotations

from pathlib import Path

#: Directory holding the captured script and its per-engine configs.
PACKAGE_DIR = Path(__file__).resolve().parent

#: The captured script. Callers should read this rather than reaching for a
#: path under someone's home directory.
SERVE_SCRIPT = PACKAGE_DIR / "serve-model.sh"

#: One conf per served engine. `serve-model.sh <KEY>` reads `<KEY>.conf`.
MODELS_DIR = PACKAGE_DIR / "models.d"

__all__ = ["PACKAGE_DIR", "SERVE_SCRIPT", "MODELS_DIR"]
