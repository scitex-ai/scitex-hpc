"""Tests for the injectable endpoint health-checker.

The default checker hits real network via ``urllib`` — these tests never
call it directly against a live URL; they either exercise
``check_endpoint``'s dispatch logic with a fake checker, or hit
``default_health_checker`` against a guaranteed-closed local port so the
call fails fast without any real network dependency.
"""

from __future__ import annotations

from scitex_hpc.tunnel_supervisor._health import (
    check_endpoint,
    default_health_checker,
)


def test_check_endpoint_returns_true_when_url_is_none():
    # Arrange
    # (no endpoint configured)
    # Act
    healthy = check_endpoint(None)
    # Assert — no endpoint configured means health-checking is a no-op
    assert healthy is True


def test_check_endpoint_uses_injected_checker():
    # Arrange
    calls = []

    def fake_checker(url: str, timeout: float) -> bool:
        calls.append((url, timeout))
        return True

    # Act
    check_endpoint("http://example.invalid/health", timeout=3.0, checker=fake_checker)
    # Assert
    assert calls == [("http://example.invalid/health", 3.0)]


def test_check_endpoint_returns_checker_result_true():
    # Arrange
    # Act
    healthy = check_endpoint("http://x/health", checker=lambda url, timeout: True)
    # Assert
    assert healthy is True


def test_check_endpoint_returns_checker_result_false():
    # Arrange
    always_false = lambda url, timeout: False
    # Act
    healthy = check_endpoint("http://x/health", checker=always_false)
    # Assert
    assert healthy is False


def test_default_health_checker_returns_false_on_connection_refused():
    # Arrange — a port nothing listens on locally fails fast, no real network
    url = "http://127.0.0.1:1/health"
    # Act
    healthy = default_health_checker(url, timeout=1.0)
    # Assert
    assert healthy is False
