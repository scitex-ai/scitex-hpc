"""Tests for scitex_hpc._quota (inode-quota parsing).

Pure-parser tests over REAL ``df -i`` output (Spartan punim0264 at the wall)
plus a healthy fixture. The network wrapper ``check_inode_quota`` is thin.
"""

from __future__ import annotations

from scitex_hpc._quota import parse_df_inodes

# Real Spartan output: punim0264 fileset AT the inode wall (2026-07-06).
_DF_AT_WALL = (
    "Filesystem      Inodes   IUsed IFree IUse% Mounted on\n"
    "project        7000000 6966926 33074  100% /data/gpfs\n"
)

# A healthy fileset (well under threshold).
_DF_HEALTHY = (
    "Filesystem      Inodes   IUsed   IFree IUse% Mounted on\n"
    "gpfs           7000000 3150000 3850000   45% /data/gpfs/projects/punim0264\n"
)


def test_parse_df_inodes_extracts_used():
    # Arrange
    stdout = _DF_AT_WALL
    # Act
    parsed = parse_df_inodes(stdout)
    # Assert
    assert parsed["used"] == 6966926


def test_parse_df_inodes_extracts_total():
    # Arrange
    stdout = _DF_AT_WALL
    # Act
    parsed = parse_df_inodes(stdout)
    # Assert
    assert parsed["total"] == 7000000


def test_parse_df_inodes_extracts_free():
    # Arrange
    stdout = _DF_AT_WALL
    # Act
    parsed = parse_df_inodes(stdout)
    # Assert
    assert parsed["free"] == 33074


def test_parse_df_inodes_extracts_pct_at_wall():
    # Arrange
    stdout = _DF_AT_WALL
    # Act
    parsed = parse_df_inodes(stdout)
    # Assert
    assert parsed["pct"] == 100


def test_parse_df_inodes_parses_healthy_fileset():
    # Arrange
    stdout = _DF_HEALTHY
    # Act
    parsed = parse_df_inodes(stdout)
    # Assert
    assert parsed["pct"] == 45


def test_parse_df_inodes_skips_header_row():
    # Arrange — only the header, no data row
    stdout = "Filesystem Inodes IUsed IFree IUse% Mounted on\n"
    # Act
    parsed = parse_df_inodes(stdout)
    # Assert
    assert parsed is None


def test_parse_df_inodes_returns_none_on_garbage():
    # Arrange
    stdout = "df: /nope: No such file or directory\n"
    # Act
    parsed = parse_df_inodes(stdout)
    # Assert
    assert parsed is None
