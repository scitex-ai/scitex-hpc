#!/usr/bin/env python3
"""Tests for parsing a lease name into the spec it claims."""

from __future__ import annotations

from scitex_hpc.lease_spec import parse_lease_name


def test_cpu_name_yields_a_spec():
    # Arrange
    name = "spartan-cpu-64-cores-256-ram"
    # Act
    spec = parse_lease_name(name)
    # Assert
    assert spec is not None


def test_cpu_name_reads_the_core_count():
    # Arrange
    name = "spartan-cpu-64-cores-256-ram"
    # Act
    spec = parse_lease_name(name)
    # Assert
    assert spec.cores == 64


def test_cpu_name_reads_the_ram():
    # Arrange
    name = "spartan-cpu-64-cores-256-ram"
    # Act
    spec = parse_lease_name(name)
    # Assert
    assert spec.ram_gb == 256


def test_the_live_spartan_lease_name_parses():
    # Arrange — the name job 29677925 actually carries
    name = "spartan-cpu-32-cores-64-ram"
    # Act
    spec = parse_lease_name(name)
    # Assert
    assert (spec.cores, spec.ram_gb) == (32, 64)


def test_gpu_name_reads_the_vram():
    # Arrange
    name = "spartan-gpu-16-cores-128-ram-80-vram-h100"
    # Act
    spec = parse_lease_name(name)
    # Assert
    assert spec.vram_gb == 80


def test_gpu_name_reads_the_model():
    # Arrange
    name = "spartan-gpu-16-cores-128-ram-80-vram-h100"
    # Act
    spec = parse_lease_name(name)
    # Assert
    assert spec.gpu_type == "h100"


def test_a_bare_model_means_one_gpu():
    # Arrange
    name = "spartan-gpu-16-cores-128-ram-80-vram-h100"
    # Act
    spec = parse_lease_name(name)
    # Assert
    assert spec.gpu_count == 1


def test_a_multiplier_means_that_many_gpus():
    # Arrange
    name = "spartan-gpu-64-cores-1024-ram-80-vram-4xh100"
    # Act
    spec = parse_lease_name(name)
    # Assert
    assert spec.gpu_count == 4


def test_a_multiplier_still_reads_the_model():
    # Arrange
    name = "spartan-gpu-64-cores-1024-ram-80-vram-4xh100"
    # Act
    spec = parse_lease_name(name)
    # Assert
    assert spec.gpu_type == "h100"


def test_a_trailing_purpose_is_captured():
    # Arrange
    name = "spartan-cpu-32-cores-64-ram-ci"
    # Act
    spec = parse_lease_name(name)
    # Assert
    assert spec.purpose == "ci"


def test_a_trailing_purpose_does_not_disturb_the_spec():
    # Arrange
    name = "spartan-cpu-32-cores-64-ram-ci"
    # Act
    spec = parse_lease_name(name)
    # Assert
    assert (spec.cores, spec.ram_gb) == (32, 64)


def test_a_hand_written_name_states_no_spec():
    # Arrange — a name that never promised anything
    name = "my-scratch-job"
    # Act
    spec = parse_lease_name(name)
    # Assert — None, so it can never be reported as a mismatch
    assert spec is None


def test_an_almost_matching_name_is_rejected():
    # Arrange — missing the -ram suffix; half-parsing it would invent a spec
    name = "spartan-cpu-64-cores-256"
    # Act
    spec = parse_lease_name(name)
    # Assert
    assert spec is None


def test_an_empty_name_states_no_spec():
    # Arrange
    name = "   "
    # Act
    spec = parse_lease_name(name)
    # Assert
    assert spec is None

# EOF
