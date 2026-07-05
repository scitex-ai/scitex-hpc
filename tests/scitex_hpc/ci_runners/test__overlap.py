"""Tests for the overlap (exec-on-existing-allocation) script generator.

Pure string assertions — no SSH, no SLURM. These pin the exact srun
invocation and the body-write mechanics ``exec-supervisor`` relies on.
"""

from __future__ import annotations

from scitex_hpc.ci_runners import (
    FleetSpec,
    RunnerSpec,
    build_exec_supervisor_script,
    build_overlap_srun_command,
    build_supervisor_hold_body,
    build_write_body_command,
)
from scitex_hpc.ci_runners._overlap import (
    DEFAULT_BODY_PATH,
    DEFAULT_LOG_PATH,
    SRUN_BIN,
)

CI_BASE = "/data/gpfs/projects/punim0264/ywatanabe/ci"


def _fleet(*names: str) -> FleetSpec:
    runners = [
        RunnerSpec(name=n, dir=f"{CI_BASE}/actions-runner-{n}") for n in names
    ]
    return FleetSpec(ci_base=CI_BASE, runners=runners)


# --------------------------------------------------------------------------
# srun command
# --------------------------------------------------------------------------


def test_srun_targets_the_holder_jobid():
    # Arrange
    jobid = "26437532"
    # Act
    cmd = build_overlap_srun_command(jobid)
    # Assert
    assert "--jobid=26437532" in cmd


def test_srun_uses_overlap_flag():
    # Arrange
    jobid = "26437532"
    # Act
    cmd = build_overlap_srun_command(jobid)
    # Assert — --overlap shares the holder's allocation
    assert "--overlap" in cmd


def test_srun_uses_absolute_srun_binary():
    # Arrange
    jobid = "1"
    # Act
    cmd = build_overlap_srun_command(jobid)
    # Assert — holder env may have a scrubbed PATH, so srun is absolute
    assert SRUN_BIN in cmd and SRUN_BIN.startswith("/")


def test_srun_is_detached_with_setsid_nohup():
    # Arrange
    jobid = "1"
    # Act
    cmd = build_overlap_srun_command(jobid)
    # Assert — survives the launching SSH shell exiting
    assert cmd.startswith("setsid nohup")


def test_srun_backgrounds_so_ssh_returns_immediately():
    # Arrange
    jobid = "1"
    # Act
    cmd = build_overlap_srun_command(jobid)
    # Assert — trailing ` &` so the long-lived step doesn't block SSH
    assert cmd.rstrip().endswith("&")


def test_srun_bashes_the_body_path():
    # Arrange
    jobid = "1"
    # Act
    cmd = build_overlap_srun_command(jobid, body_path="/x/body.sh")
    # Assert
    assert "bash /x/body.sh" in cmd


def test_srun_redirects_both_streams_to_log():
    # Arrange
    jobid = "1"
    # Act
    cmd = build_overlap_srun_command(jobid, log_path="/tmp/sup.log")
    # Assert
    assert ">/tmp/sup.log 2>&1" in cmd


# --------------------------------------------------------------------------
# body-write command
# --------------------------------------------------------------------------


def test_write_body_uses_quoted_heredoc_to_avoid_expansion():
    # Arrange
    body = build_supervisor_hold_body(_fleet("a"))
    # Act
    cmd = build_write_body_command(body)
    # Assert — quoted delimiter keeps $HOME / $(...) literal until run time
    assert "<<'SCITEX_CI_BODY'" in cmd


def test_write_body_writes_to_the_default_stable_path():
    # Arrange
    body = build_supervisor_hold_body(_fleet("a"))
    # Act
    cmd = build_write_body_command(body)
    # Assert
    assert f"> {DEFAULT_BODY_PATH}" in cmd


def test_write_body_embeds_the_full_supervisor_body():
    # Arrange
    body = build_supervisor_hold_body(_fleet("a", "b"))
    # Act
    cmd = build_write_body_command(body)
    # Assert — the verbatim keep-alive body is between the heredoc markers
    assert "./run.sh" in cmd and cmd.count("./run.sh") == 2


# --------------------------------------------------------------------------
# full exec script
# --------------------------------------------------------------------------


def test_exec_script_writes_then_launches():
    # Arrange
    body = build_supervisor_hold_body(_fleet("a"))
    # Act
    script = build_exec_supervisor_script(body, "26437532")
    # Assert — body write precedes the srun launch
    assert script.index("SCITEX_CI_BODY") < script.index("setsid nohup")


def test_exec_script_carries_the_holder_jobid_into_srun():
    # Arrange
    body = build_supervisor_hold_body(_fleet("a"))
    # Act
    script = build_exec_supervisor_script(body, "999")
    # Assert
    assert "--jobid=999 --overlap" in script


def test_exec_script_mentions_the_log_path_for_the_operator():
    # Arrange
    body = build_supervisor_hold_body(_fleet("a"))
    # Act
    script = build_exec_supervisor_script(body, "1")
    # Assert
    assert DEFAULT_LOG_PATH in script


def test_exec_script_reuses_the_exact_supervisor_body():
    # Arrange — the body the SAME generator book-supervisor uses produces
    fleet = _fleet("a", "b", "c")
    body = build_supervisor_hold_body(fleet)
    # Act
    script = build_exec_supervisor_script(body, "1")
    # Assert — no duplicated keep-alive logic: the verbatim body is present
    assert body.rstrip() in script
