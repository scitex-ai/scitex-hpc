#!/usr/bin/env python3
"""Tests for reading what SLURM granted.

The sample is REAL `scontrol show job` output captured from spartan job
29677925 on 2026-08-30, not an invented string: the format is the thing under
test, so inventing it would test my idea of scontrol rather than scontrol.
"""

from __future__ import annotations

from scitex_hpc.lease_spec import parse_scontrol

REAL = """JobId=29677925 JobName=spartan-cpu-32-cores-64-ram
   UserId=ywatanabe(17107) GroupId=punim2354(12453) MCS_label=N/A
   Priority=3104 Nice=0 Account=punim2354 QOS=publiccpu
   JobState=RUNNING Reason=None Dependency=(null)
   Requeue=1 Restarts=0 BatchFlag=1 Reboot=0 ExitCode=0:0
   RunTime=2-09:14:45 TimeLimit=7-00:00:00 TimeMin=N/A
   NumNodes=1 NumCPUs=32 NumTasks=1 CPUs/Task=1 ReqB:S:C:T=0:0:*:*
   TRES=cpu=32,mem=64G,node=1,billing=32
   mem=64G MinCpusNode=1 MinMemoryNode=64G MinTmpDiskNode=0
"""

GPU = """JobId=29644207 JobName=spartan-gpu-16-cores-128-ram-80-vram-h100
   JobState=RUNNING NumCPUs=16
   TresPerNode=gres:gpu:h100:1
   mem=128G
"""


def test_job_id_is_read():
    # Arrange
    text = REAL
    # Act
    granted = parse_scontrol(text)
    # Assert
    assert granted.job_id == "29677925"


def test_job_name_is_read():
    # Arrange
    text = REAL
    # Act
    granted = parse_scontrol(text)
    # Assert
    assert granted.job_name == "spartan-cpu-32-cores-64-ram"


def test_core_count_is_read():
    # Arrange
    text = REAL
    # Act
    granted = parse_scontrol(text)
    # Assert
    assert granted.cores == 32


def test_memory_is_converted_to_gb():
    # Arrange
    text = REAL
    # Act
    granted = parse_scontrol(text)
    # Assert
    assert granted.ram_gb == 64


def test_a_cpu_job_grants_no_gpus():
    # Arrange
    text = REAL
    # Act
    granted = parse_scontrol(text)
    # Assert
    assert granted.gpu_count == 0


def test_gpu_count_is_read_from_tres():
    # Arrange
    text = GPU
    # Act
    granted = parse_scontrol(text)
    # Assert
    assert granted.gpu_count == 1


def test_gpu_model_is_read_from_tres():
    # Arrange
    text = GPU
    # Act
    granted = parse_scontrol(text)
    # Assert
    assert granted.gpu_type == "h100"


def test_megabyte_memory_converts_to_gb():
    # Arrange — SLURM reports plain numbers as MB
    text = "JobId=1 NumCPUs=4 mem=8192M"
    # Act
    granted = parse_scontrol(text)
    # Assert
    assert granted.ram_gb == 8


def test_an_unreadable_core_count_stays_none():
    # Arrange — a zero here would be indistinguishable from "none granted"
    text = "JobId=1 JobState=PENDING"
    # Act
    granted = parse_scontrol(text)
    # Assert
    assert granted.cores is None


def test_empty_output_does_not_raise():
    # Arrange — scontrol prints nothing for an unknown job
    text = ""
    # Act
    granted = parse_scontrol(text)
    # Assert
    assert granted.job_id is None

# EOF
