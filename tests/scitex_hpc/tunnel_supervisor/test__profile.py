"""Tests for the TunnelProfile dataclass + registry."""

from __future__ import annotations

import pytest

from scitex_hpc.tunnel_supervisor import (
    PROFILES,
    TunnelProfile,
    get_profile,
    register_profile,
)


def test_default_profile_has_a_name():
    # Arrange
    # (no fixture needed)
    # Act
    profile = TunnelProfile()
    # Assert
    assert profile.name == "example-tunnel"


def test_replace_returns_new_profile_with_override():
    # Arrange
    profile = TunnelProfile(name="a")
    # Act
    updated = profile.replace(name="b")
    # Assert
    assert updated.name == "b"


def test_replace_does_not_mutate_original():
    # Arrange
    profile = TunnelProfile(name="a")
    # Act
    profile.replace(name="b")
    # Assert
    assert profile.name == "a"


def test_get_profile_returns_registered_profile():
    # Arrange
    custom = TunnelProfile(name="my-svc")
    register_profile(custom)
    # Act
    fetched = get_profile("my-svc")
    # Assert
    assert fetched is custom


def test_get_profile_unknown_name_raises_key_error():
    # Arrange
    unknown_name = "does-not-exist-xyz"
    # Act
    def act():
        return get_profile(unknown_name)

    # Assert
    with pytest.raises(KeyError):
        act()


def test_register_profile_adds_to_registry():
    # Arrange
    custom = TunnelProfile(name="registry-probe")
    # Act
    register_profile(custom)
    # Assert
    assert "registry-probe" in PROFILES
