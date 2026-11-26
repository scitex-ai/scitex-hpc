"""Named scheduler profiles within the existing HPC configuration namespace."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import yaml
from scitex_config._ecosystem import local_state

from ._models import HostProfile, ResourceBundle, identifier


def load_profile(name: str, *, path: str | Path | None = None) -> HostProfile:
    """Load profiles.NAME; explicit path > SCITEX_HPC_CONFIG > user HPC config.

    This extends the existing HPC file with a profiles mapping, without
    changing legacy JobConfig resolution. Host values reference SSH aliases;
    this is not another host inventory or a credentials store.
    """
    identifier(name, "profile name")
    source = Path(
        path
        or os.environ.get("SCITEX_HPC_CONFIG")
        or local_state.path("hpc", "config.yaml")
    )
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    profiles = data.get("profiles") if isinstance(data, Mapping) else None
    if not isinstance(profiles, Mapping) or not isinstance(profiles.get(name), Mapping):
        raise ValueError(f"No scheduler profile named {name!r} in {source}")
    values = dict(profiles[name])
    if "modules" in values:
        if not isinstance(values["modules"], list):
            raise ValueError("modules must be a list of module names")
        values["modules"] = tuple(values["modules"])
    if "bundle" in values:
        if not isinstance(values["bundle"], Mapping):
            raise ValueError("bundle must be a resource mapping")
        values["bundle"] = ResourceBundle(**values["bundle"])
    return HostProfile(**values)
