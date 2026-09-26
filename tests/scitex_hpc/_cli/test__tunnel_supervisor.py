"""CLI tests for ``scitex-hpc tunnel-supervisor`` (show + dry-run install)."""

from __future__ import annotations

from scitex_hpc._cli import main
from scitex_hpc.tunnel_supervisor import TunnelProfile, register_profile


def test_show_prints_rendered_script(capsys):
    # Arrange
    register_profile(TunnelProfile(name="cli-test-tunnel", command="echo hi"))
    # Act
    rc = main(["tunnel-supervisor", "show", "--profile", "cli-test-tunnel"])
    # Assert
    out = capsys.readouterr().out
    assert rc == 0 and "echo hi" in out


def test_install_dry_run_does_not_write_target(tmp_path, capsys):
    # Arrange
    register_profile(TunnelProfile(name="cli-test-tunnel-2", command="echo hi"))
    target = tmp_path / "supervisor.sh"
    # Act
    main(["tunnel-supervisor", "install", str(target), "--profile", "cli-test-tunnel-2"])
    # Assert
    assert not target.exists()


def test_install_dry_run_prints_dry_run_marker(tmp_path, capsys):
    # Arrange
    register_profile(TunnelProfile(name="cli-test-tunnel-3", command="echo hi"))
    target = tmp_path / "supervisor.sh"
    # Act
    main(["tunnel-supervisor", "install", str(target), "--profile", "cli-test-tunnel-3"])
    # Assert
    out = capsys.readouterr().out
    assert "DRY RUN" in out


def test_install_confirm_writes_target(tmp_path):
    # Arrange
    register_profile(TunnelProfile(name="cli-test-tunnel-4", command="echo hi"))
    target = tmp_path / "supervisor.sh"
    # Act
    rc = main(
        [
            "tunnel-supervisor",
            "install",
            str(target),
            "--profile",
            "cli-test-tunnel-4",
            "--yes",
        ]
    )
    # Assert
    assert rc == 0 and target.exists()
