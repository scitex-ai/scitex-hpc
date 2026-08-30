#!/usr/bin/env python3
"""Tests for comparing a lease name against what SLURM granted."""

from __future__ import annotations

from scitex_hpc.lease_spec import Granted, parse_lease_name, verify


def _cpu(cores=32, ram=64):
    return Granted(job_id="1", cores=cores, ram_gb=ram)


def test_a_matching_grant_reports_match():
    # Arrange
    spec = parse_lease_name("spartan-cpu-32-cores-64-ram")
    # Act
    verdict = verify(spec, _cpu())
    # Assert
    assert verdict.state == "match"


def test_a_matching_grant_is_not_a_mismatch():
    # Arrange
    spec = parse_lease_name("spartan-cpu-32-cores-64-ram")
    # Act
    verdict = verify(spec, _cpu())
    # Assert
    assert verdict.is_mismatch is False


def test_fewer_cores_than_claimed_is_a_mismatch():
    # Arrange — booked as 64, granted 32: the name still says 64
    spec = parse_lease_name("spartan-cpu-64-cores-64-ram")
    # Act
    verdict = verify(spec, _cpu(cores=32))
    # Assert
    assert verdict.state == "mismatch"


def test_a_core_mismatch_names_the_field():
    # Arrange
    spec = parse_lease_name("spartan-cpu-64-cores-64-ram")
    # Act
    verdict = verify(spec, _cpu(cores=32))
    # Assert
    assert verdict.mismatches[0].field_name == "cores"


def test_a_mismatch_reports_both_numbers():
    # Arrange
    spec = parse_lease_name("spartan-cpu-64-cores-64-ram")
    # Act
    verdict = verify(spec, _cpu(cores=32))
    # Assert
    assert (verdict.mismatches[0].claimed, verdict.mismatches[0].granted) == (64, 32)


def test_a_mismatch_forbids_renaming_in_its_own_message():
    # Arrange — the guidance must travel WITH the finding, not live in a doc
    spec = parse_lease_name("spartan-cpu-64-cores-64-ram")
    # Act
    verdict = verify(spec, _cpu(cores=32))
    # Assert
    assert "do NOT rename" in verdict.detail


def test_a_ram_mismatch_is_detected():
    # Arrange
    spec = parse_lease_name("spartan-cpu-32-cores-256-ram")
    # Act
    verdict = verify(spec, _cpu(ram=64))
    # Assert
    assert verdict.state == "mismatch"


def test_a_name_with_no_spec_is_unknown():
    # Arrange
    spec = parse_lease_name("my-scratch-job")
    # Act
    verdict = verify(spec, _cpu())
    # Assert
    assert verdict.state == "unknown"


def test_a_name_with_no_spec_is_not_a_mismatch():
    # Arrange — a name that promised nothing cannot have broken a promise
    spec = parse_lease_name("my-scratch-job")
    # Act
    verdict = verify(spec, _cpu())
    # Assert
    assert verdict.is_mismatch is False


def test_an_unreadable_field_is_unknown_not_a_pass():
    # Arrange — SLURM stated no core count
    spec = parse_lease_name("spartan-cpu-32-cores-64-ram")
    # Act
    verdict = verify(spec, Granted(job_id="1", cores=None, ram_gb=64))
    # Assert
    assert verdict.state == "unknown"


def test_an_unreadable_field_is_named_in_the_detail():
    # Arrange
    spec = parse_lease_name("spartan-cpu-32-cores-64-ram")
    # Act
    verdict = verify(spec, Granted(job_id="1", cores=None, ram_gb=64))
    # Assert — say what was NOT checked rather than implying it passed
    assert "cores" in verdict.detail


def test_a_missing_gpu_is_a_mismatch():
    # Arrange — a GPU lease granted no GPU at all
    spec = parse_lease_name("spartan-gpu-16-cores-128-ram-80-vram-h100")
    # Act
    verdict = verify(spec, Granted(job_id="1", cores=16, ram_gb=128, gpu_count=0))
    # Assert
    assert verdict.state == "mismatch"


def test_the_wrong_gpu_model_is_a_mismatch():
    # Arrange — an a100 where the name claims h100
    spec = parse_lease_name("spartan-gpu-16-cores-128-ram-80-vram-h100")
    granted = Granted(
        job_id="1", cores=16, ram_gb=128, gpu_count=1, gpu_type="a100"
    )
    # Act
    verdict = verify(spec, granted)
    # Assert
    assert verdict.state == "mismatch"


def test_an_unnamed_gpu_model_does_not_contradict_the_name():
    # Arrange — the grant states a count but not a model
    spec = parse_lease_name("spartan-gpu-16-cores-128-ram-80-vram-h100")
    granted = Granted(
        job_id="1", cores=16, ram_gb=128, gpu_count=1, gpu_type=None
    )
    # Act
    verdict = verify(spec, granted)
    # Assert — cannot-see must not be reported as a fault
    assert verdict.is_mismatch is False


def test_several_disagreements_are_all_reported():
    # Arrange — cores AND ram both wrong; reporting one would hide the other
    spec = parse_lease_name("spartan-cpu-64-cores-256-ram")
    # Act
    verdict = verify(spec, _cpu(cores=32, ram=64))
    # Assert
    assert len(verdict.mismatches) == 2

# EOF
