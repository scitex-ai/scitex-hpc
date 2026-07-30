"""CLI tests for the ``ci-runners show-register`` command.

Pure text generation: ``show-register`` prints the registration command a
human pastes on the runner host, so these tests need neither SSH nor SLURM.
The label assertion is the load-bearing one — ``scitex-ci`` is what the
reusable ci-template's ``runs-on`` selects on, so dropping it would strand
every workflow in the org while the command still looked fine.
"""

from __future__ import annotations

from scitex_hpc._cli import main


def test_show_register_bakes_scitex_ci_label(capsys):
    # Arrange
    argv = [
        "ci-runners",
        "show-register",
        "--url",
        "https://github.com/ywatanabe1989/scitex-hpc",
        "--name",
        "scitex-hpc",
    ]
    # Act
    rc = main(argv)
    # Assert — the label the ci-template selects on is always emitted
    out = capsys.readouterr().out
    assert rc == 0 and "--labels spartan-cpu,scitex-ci" in out


def test_show_register_requires_url(capsys):
    # Arrange — --url is a required option
    argv = ["ci-runners", "show-register", "--name", "scitex-hpc"]
    # Act
    rc = main(argv)
    # Assert
    assert rc != 0


def test_show_register_json_emits_command_key(capsys):
    # Arrange
    argv = [
        "ci-runners",
        "show-register",
        "--url",
        "https://github.com/ywatanabe1989/scitex-hpc",
        "--name",
        "x",
        "--json",
    ]
    # Act
    main(argv)
    # Assert
    out = capsys.readouterr().out
    assert '"command"' in out
