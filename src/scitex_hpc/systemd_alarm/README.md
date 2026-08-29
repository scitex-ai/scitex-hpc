# systemd_alarm — give a failed user unit a reader

A `Type=oneshot` unit driven by a `.timer` has **no supervision**. When it
fails, systemd records `Result=exit-code` and tells nobody. Measured on
spartan-login1, 2026-08-29:

| | |
|---|---|
| user services declaring `OnFailure=` | **0** |
| control: units containing `ExecStart=` | 12 |
| timer-driven oneshots | **10**, all `Type=oneshot` / `Restart=none` |

The control matters: a bare zero from a grep is indistinguishable from a grep
that matched nothing because it was pointed at the wrong place.

## Install

```sh
cp 'scitex-unit-failed@.service' ~/.config/systemd/user/
mkdir -p ~/.config/systemd/user/<unit>.service.d
cp onfailure.conf ~/.config/systemd/user/<unit>.service.d/
systemctl --user daemon-reload
```

Then confirm systemd **resolved** it, rather than that the file exists:

```sh
systemctl --user show <unit>.service -p OnFailure --value
```

## Three things the testing taught, each of which cost a wrong reading

**1. `%n` already includes `.service`.** `OnFailure=scitex-unit-failed@%n.service`
instantiates `scitex-unit-failed@<unit>.service.service` — a doubled suffix.
Querying the single-suffix name returns a unit that does not exist, and the
defaults of a nonexistent unit are:

```
Result=success
ExecMainStatus=0
ExecMainStartTimestamp=      <-- EMPTY: the only field that distinguishes it
```

which is otherwise indistinguishable from a clean run. **Always check
`ExecMainStartTimestamp`.** An empty one means it never ran.

**2. The sink is slow, not instant.** A real send walks the backend chain
(audio → emacs → …) and takes ~14–40s, returning `Notification sent` /
`{"success": true}`. `TimeoutStartSec=180` bounds it so a hung backend cannot
wedge the alarm, while leaving normal sends room.

**3. Verify the unit, do not trust that it loads.** `systemd-analyze --user
verify` catches a key placed in the wrong section, which systemd otherwise
reports as `Unknown key name ... ignoring` and silently drops. A unit can
"work" while carrying an inert directive.

## Testing it

Prove the rail before wiring anything real to it:

```sh
# a unit that deliberately fails
printf '[Unit]\nOnFailure=scitex-unit-failed@%%n.service\n\n[Service]\nType=oneshot\nExecStart=/bin/false\n' \
  > ~/.config/systemd/user/onfailure-selftest.service
systemctl --user daemon-reload
systemctl --user start onfailure-selftest.service    # returns non-zero by design
journalctl --user --since -2min | grep -i 'onfailure\|unit-failed'
```

The journal is the evidence, not the unit status:

```
Failed with result 'exit-code'
Triggering OnFailure= dependencies
Starting Alarm that onfailure-selftest.service failed...
Finished Alarm that onfailure-selftest.service failed
```

Remove the selftest unit afterwards.

## Scope

Wiring is **per unit and per owner**. Do not apply this across a shared host's
whole unit set: it routes another agent's failures to your notification rail,
and an alarm nobody owns is the alarm-fatigue this exists to avoid.

## Limit, stated plainly

If the notification backend chain is down, the alarm unit itself fails and
nothing watches the alarm. That regress terminates at `systemctl --user
--failed`, which is *pullable*, not pushed. This converts silent failure into
delivered notification; it does not make the rail self-verifying.
