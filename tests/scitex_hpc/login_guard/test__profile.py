"""Tests for the login-guard site profile (config-driven values)."""

from __future__ import annotations

import pytest

from scitex_hpc.login_guard._profile import (
    PROFILES,
    SPARTAN_PROFILE,
    GuardProfile,
    get_profile,
)


def test_default_profile_is_spartan():
    # Arrange
    prof = GuardProfile()
    # Act
    name = prof.name
    # Assert
    assert name == "spartan"


def test_spartan_profile_protects_data_prefix():
    # Arrange
    prof = SPARTAN_PROFILE
    # Act
    prefixes = prof.protected_path_prefixes
    # Assert — the GPFS project tree the du/find walk-guard defends
    assert "/data/" in prefixes


def test_spartan_profile_guards_the_tex_toolchain():
    # Arrange
    prof = SPARTAN_PROFILE
    # Act
    heavy = prof.heavy_tools
    # Assert — pdflatex is the 2026-07-01 incident vector
    assert "pdflatex" in heavy


def test_spartan_profile_guards_du_and_find():
    # Arrange
    prof = SPARTAN_PROFILE
    # Act
    walkers = prof.fswalk_tools
    # Assert
    assert walkers == ["du", "find"]


def test_get_profile_returns_spartan_by_default():
    # Arrange
    expected = SPARTAN_PROFILE
    # Act
    prof = get_profile()
    # Assert
    assert prof is expected


def test_get_profile_unknown_name_raises_keyerror():
    # Arrange
    name = "no-such-site"
    # Act
    call = lambda: get_profile(name)
    # Assert
    with pytest.raises(KeyError):
        call()


def test_registry_contains_spartan():
    # Arrange
    registry = PROFILES
    # Act
    present = "spartan" in registry
    # Assert
    assert present is True


def test_replace_overrides_only_named_field():
    # Arrange
    prof = GuardProfile()
    # Act
    other = prof.replace(name="gadi")
    # Assert — name changed, defaults preserved
    assert other.name == "gadi" and other.protected_path_prefixes == ["/data/"]


def test_profile_is_frozen():
    # Arrange
    prof = GuardProfile()
    # Act
    def mutate() -> None:
        prof.name = "mutated"  # type: ignore[misc]
    # Assert — frozen dataclass rejects mutation
    with pytest.raises(Exception):
        mutate()
