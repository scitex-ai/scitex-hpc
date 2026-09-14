from __future__ import annotations

from pathlib import Path

import pytest

from scitex_hpc.model_serve.experiments.capacity_report import (
    build_report,
    parse_startup_log,
    summarize_server_info,
)

ROOT = Path(__file__).parents[4]
EXPERIMENTS = ROOT / "src/scitex_hpc/model_serve/experiments"


def test_profiles_define_the_three_context_ceiling_choices():
    # Arrange
    observed = {}
    # Act
    for path in sorted((EXPERIMENTS / "profiles").glob("*.conf")):
        context_line = next(
            line
            for line in path.read_text().splitlines()
            if line.startswith("CONTEXT_LENGTH=")
        )
        observed[path.stem] = int(context_line.partition("=")[2])
    # Assert
    assert observed == {
        "qwen38-tp1-1m": 1_000_000,
        "qwen38-tp1-256k": 262_144,
        "qwen38-tp1-512k": 524_288,
    }


def test_launcher_exposes_cache_and_scheduler_measurement_controls():
    # Arrange
    required = (
        "--tp-size 1",
        "--kv-cache-dtype fp8_e4m3",
        "--schedule-policy lpm",
        "--enable-session-radix-cache",
        "--enable-cache-report",
        "--enable-metrics",
        "--chunked-prefill-size 8192",
        "--max-prefill-tokens 32768",
        "SLURM_JOB_ID",
        "refusing to run outside a Slurm allocation",
    )
    # Act
    launcher = (EXPERIMENTS / "qwen38-tp1-canary.sh").read_text()
    missing = [item for item in required if item not in launcher]
    # Assert
    assert missing == []


def test_measured_capacity_is_not_conflated_with_context_ceiling():
    # Arrange
    startup = parse_startup_log(
        "max_total_num_tokens=563215, chunked_prefill_size=32768, "
        "max_prefill_tokens=32768, max_running_requests=11, "
        "context_len=1000000, available_gpu_mem=13.64 GB"
    )
    # Act
    report = build_report(1_000_000, startup)
    selected = {
        key: report[key]
        for key in (
            "configured_context_tokens",
            "reported_context_tokens",
            "context_matches_configuration",
            "max_total_num_tokens",
            "capacity_fraction_of_one_max_context",
            "resolved_max_running_requests",
        )
    }
    # Assert
    assert selected == {
        "configured_context_tokens": 1_000_000,
        "reported_context_tokens": 1_000_000,
        "context_matches_configuration": True,
        "max_total_num_tokens": 563_215,
        "capacity_fraction_of_one_max_context": 0.563215,
        "resolved_max_running_requests": 11,
    }


def test_capacity_parser_fails_when_measurement_is_absent():
    # Arrange
    log = "server started without capacity evidence"
    # Act
    # Assert
    with pytest.raises(ValueError, match="no SGLang capacity line"):
        parse_startup_log(log)


def test_server_info_summary_keeps_runtime_identity_and_effective_limit():
    # Arrange
    server_info = {
        "served_model_name": "qwen38-27b",
        "version": "measured-version",
        "context_length": 1_000_000,
        "max_total_num_tokens": 563_215,
        "internal_states": [
            {"effective_max_running_requests_per_dp": 11, "large": "discard"}
        ],
        "unrelated_large_field": {"discard": True},
    }
    # Act
    summary = summarize_server_info(server_info)
    # Assert
    assert summary == {
        "model_path": None,
        "served_model_name": "qwen38-27b",
        "version": "measured-version",
        "context_length": 1_000_000,
        "kv_cache_dtype": None,
        "tp_size": None,
        "schedule_policy": None,
        "enable_session_radix_cache": None,
        "enable_cache_report": None,
        "enable_metrics": None,
        "chunked_prefill_size": None,
        "max_prefill_tokens": None,
        "max_total_num_tokens": 563_215,
        "effective_max_running_requests_per_dp": 11,
    }
