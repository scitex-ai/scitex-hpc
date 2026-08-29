"""Watch the dotfiles SSoT gitconfig for CI-runner safe.directory accumulation.

``~/.gitconfig`` on Spartan is a SYMLINK into the tracked dotfiles SSoT, so a
CI job's ``git config --global --add safe.directory`` writes into version
control. actions/checkout does that unconditionally per job and does not
deduplicate, so growth tracks CI RUNS rather than repositories.

Measured: 0 entries on 2026-08-17, 256 on 2026-08-29 — about 22/day, twelve
days after a fix that was believed structural and was not.

This package exists because the card recorded the right artefact ("a watch on
the file's line count") on 2026-08-17 and nobody built it; the regression was
then found by accident. Naming a gap does not close it.

READ-ONLY by design: the entries are the only evidence of WHICH runner is
writing, and clearing them destroys the diagnosis. See README.md.
"""
