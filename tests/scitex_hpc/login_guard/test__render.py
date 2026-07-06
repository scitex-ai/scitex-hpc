"""Tests for the login-guard shell renderer (profile -> guard script)."""

from __future__ import annotations

from scitex_hpc.login_guard._profile import GuardProfile
from scitex_hpc.login_guard._render import (
    BLOCKED_RC,
    BLOCKED_TOKEN,
    _safe_ident,
    _toplevel_glob,
    render_guard,
)


def test_render_emits_bash_shebang():
    # Arrange
    prof = GuardProfile()
    # Act
    script = render_guard(prof)
    # Assert
    assert script.startswith("#!/usr/bin/env bash")


def test_render_includes_blocked_token_contract():
    # Arrange
    prof = GuardProfile()
    # Act
    script = render_guard(prof)
    # Assert — cross-repo contract scitex-writer keys off
    assert BLOCKED_TOKEN in script


def test_render_uses_blocked_return_code():
    # Arrange
    prof = GuardProfile()
    # Act
    script = render_guard(prof)
    # Assert
    assert f"return {BLOCKED_RC}" in script


def test_render_escapes_inside_slurm_job():
    # Arrange
    prof = GuardProfile()
    # Act
    script = render_guard(prof)
    # Assert — a job env means a compute node, so the real binary runs
    assert "SLURM_JOB_ID" in script


def test_render_templates_login_node_patterns():
    # Arrange
    prof = GuardProfile()
    # Act
    script = render_guard(prof)
    # Assert
    assert "spartan-login*" in script


def test_render_templates_protected_prefix():
    # Arrange
    prof = GuardProfile()
    # Act
    script = render_guard(prof)
    # Assert — the du/find walk-guard's protected-prefix case arm
    assert "/data/*" in script


def test_render_overrides_a_heavy_tool():
    # Arrange
    prof = GuardProfile()
    # Act
    script = render_guard(prof)
    # Assert — pdflatex is wrapped as a guarded shell function
    assert "pdflatex" in script


def test_render_templates_custom_profile_values():
    # Arrange — a non-Spartan site should template its own values in
    prof = GuardProfile(name="gadi", protected_path_prefixes=["/g/data/"])
    # Act
    script = render_guard(prof)
    # Assert
    assert "/g/data/*" in script


def test_render_names_functions_from_profile_name():
    # Arrange
    prof = GuardProfile(name="gadi")
    # Act
    script = render_guard(prof)
    # Assert — the guard functions are namespaced by the site ident
    assert "_gadi_login_guard" in script


def test_safe_ident_sanitises_non_identifier_chars():
    # Arrange
    name = "my-site.1"
    # Act
    ident = _safe_ident(name)
    # Assert
    assert ident == "my_site_1"


def test_safe_ident_prefixes_leading_digit():
    # Arrange
    name = "3site"
    # Act
    ident = _safe_ident(name)
    # Assert — a shell ident cannot start with a digit
    assert ident.startswith("_")


def test_toplevel_glob_derives_stem_from_first_pattern():
    # Arrange
    patterns = ["spartan-login*", "spartan-gateway*"]
    # Act
    glob = _toplevel_glob(patterns)
    # Assert
    assert glob == "spartan*"


def test_toplevel_glob_falls_back_to_wildcard_when_empty():
    # Arrange
    patterns: list[str] = []
    # Act
    glob = _toplevel_glob(patterns)
    # Assert
    assert glob == "*"
