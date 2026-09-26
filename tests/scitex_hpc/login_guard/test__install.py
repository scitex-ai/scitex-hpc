"""Tests for the config-driven HPC login-node guard.

Covers the Spartan-profile render (heavy-tool + du/find guards, the
cross-repo ``[BLOCKED]`` / rc-100 contract, the ``$SLURM_JOB_ID`` escape,
login-node host match, the ``/data/`` protected-prefix walk guard, and the
``mmlsquota`` hint), the ``~/.bashrc`` insertion transform, the remote
install script, AND a NON-Spartan custom profile (proving the guard is
truly generalized, not hardcoded).
"""

from __future__ import annotations

import pytest

from scitex_hpc.login_guard import (
    BLOCKED_RC,
    BLOCKED_TOKEN,
    REMOTE_GUARD_PATH,
    GuardProfile,
    build_bashrc,
    build_install_script,
    guard_text,
    render_guard,
)

# The TeX toolchain the Spartan guard must override (the incident vector).
TEX_TOOLS = (
    "xelatex",
    "pdflatex",
    "lualatex",
    "latex",
    "latexmk",
    "biber",
    "bibtex",
    "makeindex",
    "dvipdfmx",
    "xdvipdfmx",
    "dvips",
    "ps2pdf",
    "tex",
)

_INTERACTIVE_RETURN = "[[ $- != *i* ]] && return"
_ANCHOR = "000_spartan_noninteractive_libs.src"


# --------------------------------------------------------------------------
# Spartan-profile guard text — heavy-compute guard
# --------------------------------------------------------------------------
def test_guard_has_slurm_job_id_escape():
    # Arrange
    guard = guard_text()
    # Act
    has_escape = "SLURM_JOB_ID" in guard
    # Assert — inside a SLURM allocation the real binary must run (no-op).
    assert has_escape


def test_guard_matches_spartan_login_host():
    # Arrange
    guard = guard_text()
    # Act
    matches = "spartan-login*" in guard
    # Assert — refuses only on login/gateway hosts.
    assert matches


@pytest.mark.parametrize(
    "pat", ("spartan-login*", "spartan-gateway*", "spartanlogin*")
)
def test_guard_matches_each_spartan_login_pattern(pat):
    # Arrange
    guard = guard_text()
    # Act — every login-node pattern from the profile is templated in.
    present = pat in guard
    # Assert
    assert present


@pytest.mark.parametrize("tool", TEX_TOOLS)
def test_guard_defines_tex_tool(tool):
    # Arrange
    guard = guard_text()
    # Act
    present = tool in guard
    # Assert — each TeX tool is on the override loop list.
    assert present


def test_blocked_token_constant_is_contract_value():
    # Arrange
    expected = "[BLOCKED]"
    # Act
    actual = BLOCKED_TOKEN
    # Assert — scitex-writer keys off this exact stderr token.
    assert actual == expected


def test_blocked_rc_constant_is_contract_value():
    # Arrange
    expected = 100
    # Act
    actual = BLOCKED_RC
    # Assert — scitex-writer keys off this exact exit code.
    assert actual == expected


def test_guard_emits_blocked_token():
    # Arrange
    guard = guard_text()
    # Act
    present = BLOCKED_TOKEN in guard
    # Assert
    assert present


def test_guard_returns_blocked_rc():
    # Arrange
    guard = guard_text()
    # Act
    present = f"return {BLOCKED_RC}" in guard
    # Assert
    assert present


def test_guard_provides_tex_helper():
    # Arrange
    guard = guard_text()
    # Act
    has_helper = "spartan-tex()" in guard
    # Assert — the srun-wrapping convenience helper exists.
    assert has_helper


def test_guard_wraps_helper_in_srun():
    # Arrange
    guard = guard_text()
    # Act
    has_srun = "srun" in guard
    # Assert — the helper sends the compile to a compute node.
    assert has_srun


def test_guard_defines_login_guard_function():
    # Arrange
    guard = guard_text()
    # Act
    has_fn = "_spartan_login_guard()" in guard
    # Assert — functions beat both PATH and ``module load``.
    assert has_fn


def test_guard_exports_functions():
    # Arrange
    guard = guard_text()
    # Act
    exported = "export -f" in guard
    # Assert — exported so non-interactive subshells inherit the override.
    assert exported


# --------------------------------------------------------------------------
# Spartan-profile guard text — du/find filesystem-walk guard
# --------------------------------------------------------------------------
def test_guard_defines_fswalk_function():
    # Arrange
    guard = guard_text()
    # Act
    has_fn = "_spartan_fswalk_guard()" in guard
    # Assert — the du/find walk guard exists.
    assert has_fn


@pytest.mark.parametrize("tool", ("du", "find"))
def test_guard_overrides_fswalk_tool(tool):
    # Arrange
    guard = guard_text()
    # Act — the fswalk override loop lists du and find.
    has_loop = f"for _stx_w in {tool}" in guard or f" {tool} " in guard or (
        f"in du find" in guard
    )
    # Assert
    assert has_loop


def test_guard_checks_protected_prefix_in_args():
    # Arrange
    guard = guard_text()
    # Act — each argument is matched against the /data/ prefix.
    checks_args = 'for _a in "$@"' in guard and "/data/*)" in guard
    # Assert
    assert checks_args


def test_guard_checks_protected_prefix_in_pwd():
    # Arrange
    guard = guard_text()
    # Act — the current directory is matched against the /data/ prefix too.
    checks_pwd = 'case "$PWD" in /data/*)' in guard
    # Assert
    assert checks_pwd


def test_guard_includes_quota_hint():
    # Arrange
    guard = guard_text()
    # Act
    has_hint = "mmlsquota -j punim2354 punim2354" in guard
    # Assert — points users at the metadata-only query instead of a walk.
    assert has_hint


def test_guard_fswalk_emits_blocked_token():
    # Arrange
    guard = guard_text()
    body = guard[guard.index("_spartan_fswalk_guard()"):]
    # Act
    present = BLOCKED_TOKEN in body
    # Assert — the fswalk guard refuses with the same token as heavy tools.
    assert present


def test_guard_fswalk_returns_blocked_rc():
    # Arrange
    guard = guard_text()
    body = guard[guard.index("_spartan_fswalk_guard()"):]
    # Act
    present = f"return {BLOCKED_RC}" in body
    # Assert — the fswalk guard refuses with the same rc as heavy tools.
    assert present


# --------------------------------------------------------------------------
# Generalization — a NON-Spartan custom profile renders custom values
# --------------------------------------------------------------------------
def _gadi_profile() -> GuardProfile:
    """A wholly different site to prove the guard is not Spartan-hardcoded."""
    return GuardProfile(
        name="gadi",
        login_node_patterns=["gadi-login*"],
        protected_path_prefixes=["/g/data/", "/scratch/"],
        heavy_tools=["pdflatex", "Rscript"],
        fswalk_tools=["du", "find", "ncdu"],
        quota_hint_cmd="lquota -u $USER",
        srun_template="srun --partition=normal --time=0:30:00",
        texbin="/apps/texlive/2023/bin/x86_64-linux",
    )


@pytest.fixture
def gadi_guard() -> str:
    return render_guard(_gadi_profile())


def _bash_n_rc(guard: str) -> int:
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
        fh.write(guard)
        path = fh.name
    return subprocess.run(
        ["bash", "-n", path], capture_output=True, text=True
    ).returncode


def test_custom_profile_renders_custom_login_pattern(gadi_guard):
    # Arrange
    guard = gadi_guard
    # Act
    present = "gadi-login*" in guard
    # Assert — the custom host pattern is templated in.
    assert present


def test_custom_profile_omits_spartan_login_pattern(gadi_guard):
    # Arrange
    guard = gadi_guard
    # Act
    leaked = "spartan-login*" in guard
    # Assert — proves the render is not Spartan-hardcoded.
    assert not leaked


def test_custom_profile_renders_first_protected_prefix(gadi_guard):
    # Arrange
    guard = gadi_guard
    # Act — both prefixes share one |-joined case arm: /g/data/*|/scratch/*.
    present = "/g/data/*" in guard
    # Assert
    assert present


def test_custom_profile_renders_second_protected_prefix(gadi_guard):
    # Arrange
    guard = gadi_guard
    # Act
    present = "/scratch/*" in guard
    # Assert
    assert present


def test_custom_profile_joins_protected_prefixes_into_one_case_arm(gadi_guard):
    # Arrange
    guard = gadi_guard
    # Act — the $PWD guard matches against the |-joined prefixes.
    present = 'case "$PWD" in /g/data/*|/scratch/*)' in guard
    # Assert
    assert present


def test_custom_profile_omits_spartan_protected_prefix(gadi_guard):
    # Arrange
    guard = gadi_guard
    # Act
    leaked = 'in /data/*)' in guard
    # Assert — the Spartan-only prefix must not appear.
    assert not leaked


def test_custom_profile_renders_custom_heavy_tool(gadi_guard):
    # Arrange
    guard = gadi_guard
    # Act
    present = "Rscript" in guard
    # Assert
    assert present


def test_custom_profile_renders_custom_fswalk_tool(gadi_guard):
    # Arrange
    guard = gadi_guard
    # Act
    present = "ncdu" in guard
    # Assert
    assert present


def test_custom_profile_renders_custom_quota_hint(gadi_guard):
    # Arrange
    guard = gadi_guard
    # Act
    present = "lquota -u $USER" in guard
    # Assert
    assert present


def test_custom_profile_renders_custom_srun_template(gadi_guard):
    # Arrange
    guard = gadi_guard
    # Act
    present = "srun --partition=normal" in guard
    # Assert
    assert present


def test_custom_profile_renders_named_tex_helper(gadi_guard):
    # Arrange
    guard = gadi_guard
    # Act
    present = "gadi-tex()" in guard
    # Assert — the helper is named after the profile.
    assert present


def test_custom_profile_emits_blocked_token(gadi_guard):
    # Arrange
    guard = gadi_guard
    # Act
    present = BLOCKED_TOKEN in guard
    # Assert — the cross-repo contract holds for ANY profile.
    assert present


def test_custom_profile_returns_blocked_rc(gadi_guard):
    # Arrange
    guard = gadi_guard
    # Act
    present = f"return {BLOCKED_RC}" in guard
    # Assert
    assert present


def test_custom_profile_has_slurm_escape(gadi_guard):
    # Arrange
    guard = gadi_guard
    # Act
    present = "SLURM_JOB_ID" in guard
    # Assert
    assert present


def test_custom_profile_guard_is_valid_bash(gadi_guard):
    # Arrange
    guard = gadi_guard
    # Act
    rc = _bash_n_rc(guard)
    # Assert — bash -n accepts the generated script.
    assert rc == 0


def test_spartan_profile_guard_is_valid_bash():
    # Arrange
    guard = guard_text()
    # Act
    rc = _bash_n_rc(guard)
    # Assert
    assert rc == 0


# --------------------------------------------------------------------------
# ~/.bashrc insertion transform
# --------------------------------------------------------------------------
def test_bashrc_insert_before_interactive_return_when_no_anchor():
    # Arrange — a bashrc with the interactive-return guard but no anchor.
    bashrc = "export FOO=1\n" f"{_INTERACTIVE_RETURN}\n" "alias ll='ls -l'\n"
    # Act
    out = build_bashrc(bashrc)
    # Assert — the source line lands BEFORE the interactive-return marker
    # so non-interactive ``ssh host '<cmd>'`` is covered too.
    assert out.index(REMOTE_GUARD_PATH) < out.index(_INTERACTIVE_RETURN)


def test_bashrc_insert_after_spartan_anchor_when_present():
    # Arrange — replicate the live deployment anchor.
    bashrc = (
        "export FOO=1\n"
        f"source ~/.config/{_ANCHOR}\n"
        f"{_INTERACTIVE_RETURN}\n"
    )
    # Act
    out = build_bashrc(bashrc)
    # Assert — block sits right AFTER the anchor line, still before return.
    assert out.index(_ANCHOR) < out.index(REMOTE_GUARD_PATH) < out.index(
        _INTERACTIVE_RETURN
    )


def test_bashrc_insert_at_top_when_no_anchor_and_no_return():
    # Arrange — a bare bashrc.
    bashrc = "export FOO=1\nexport BAR=2\n"
    # Act
    out = build_bashrc(bashrc)
    # Assert — block is prepended above the original first line.
    assert out.index(REMOTE_GUARD_PATH) < out.index("export FOO=1")


def test_bashrc_insertion_is_idempotent():
    # Arrange
    bashrc = "export FOO=1\n" f"{_INTERACTIVE_RETURN}\n"
    once = build_bashrc(bashrc)
    # Act — apply a second time.
    twice = build_bashrc(once)
    # Assert — re-running never duplicates the source line.
    assert once == twice


def test_bashrc_insertion_inserts_single_guard_block():
    # Arrange
    bashrc = "export FOO=1\n" f"{_INTERACTIVE_RETURN}\n"
    # Act
    out = build_bashrc(build_bashrc(bashrc))
    # Assert — exactly one guard block even after re-applying.
    assert out.count("# >>> scitex-hpc login-node guard >>>") == 1


def test_bashrc_insertion_preserves_existing_lines():
    # Arrange
    bashrc = "export FOO=1\n" f"{_INTERACTIVE_RETURN}\n" "alias g=git\n"
    # Act
    out = build_bashrc(bashrc)
    # Assert — original content is not dropped.
    assert "alias g=git" in out


# --------------------------------------------------------------------------
# Remote install script
# --------------------------------------------------------------------------
def test_install_script_targets_remote_guard_path():
    # Arrange
    script = build_install_script()
    # Act
    present = REMOTE_GUARD_PATH in script
    # Assert
    assert present


def test_install_script_makes_guard_executable():
    # Arrange
    script = build_install_script()
    # Act
    present = "chmod +x" in script
    # Assert
    assert present


def test_install_script_backs_up_bashrc():
    # Arrange
    script = build_install_script()
    # Act
    present = "cp -p" in script
    # Assert — ~/.bashrc is backed up before any edit.
    assert present


def test_install_script_validates_before_replacing():
    # Arrange
    script = build_install_script()
    # Act
    present = "bash -n" in script
    # Assert — never install a syntactically broken ~/.bashrc.
    assert present


def test_install_script_embeds_guard_verbatim():
    # Arrange
    script = build_install_script()
    # Act
    present = "_spartan_login_guard()" in script
    # Assert — the rendered guard body is spliced in.
    assert present


def test_install_script_embeds_custom_profile_host_pattern():
    # Arrange — install script respects a non-default profile.
    script = build_install_script(profile=_gadi_profile())
    # Act
    present = "gadi-login*" in script
    # Assert — the custom guard body is spliced into the install script.
    assert present


def test_install_script_embeds_custom_profile_guard_function():
    # Arrange
    script = build_install_script(profile=_gadi_profile())
    # Act
    present = "_gadi_login_guard()" in script
    # Assert — the per-profile function name is used.
    assert present
