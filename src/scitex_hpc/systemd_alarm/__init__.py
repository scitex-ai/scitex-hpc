"""OnFailure alarm rail for timer-driven systemd user units.

A ``Type=oneshot`` unit under a ``.timer`` has no supervision: it fails,
systemd records ``Result=exit-code``, and nobody is told. Measured on
spartan-login1 2026-08-29, ZERO of that host's user services declared
``OnFailure=`` while TEN timer-driven oneshots were running — including the
index.lock census, whose own alarm had been unable to fire for two weeks with
the warning about it going to a journal holding zero lines.

This package ships the target unit and the drop-in that wires it, plus the
three traps found while testing it, all of which produced a wrong reading
before they produced a working rail:

* ``%n`` already includes ``.service``, so the live instance carries a DOUBLED
  suffix. Querying the single-suffix name returns a nonexistent unit whose
  defaults (``Result=success``, ``ExecMainStatus=0``) are indistinguishable
  from a clean run. ``ExecMainStartTimestamp`` is the only discriminator.
* the notification sink is SLOW (~14-40s), not instant and not blocking —
  hence a bound rather than a workaround.
* ``systemd-analyze --user verify`` catches a directive placed in the wrong
  section, which systemd otherwise drops with "Unknown key name ... ignoring".
  A unit can work while carrying an inert line.

Wiring is per-unit and per-owner. Applying it across a shared host's whole
unit set routes another agent's failures to your rail, which is the alarm
fatigue the rail exists to avoid.

See README.md for install, test and the stated limit.
"""
