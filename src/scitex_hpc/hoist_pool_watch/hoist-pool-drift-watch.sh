#!/bin/bash
# Watch for drift between WHAT THE HOIST POOL ROUTES TO and WHAT IS ACTUALLY
# SERVING. Both directions, because both have happened on this host.
#
#   POOLED but NOT SERVING  -> outage. Measured 2026-08-28: 18775 was in the
#       pool while not listening, and "roughly 1 request in 3 returned 502 …
#       which killed a working agent mid-task". A 3-member pool with one dead
#       member does not degrade to 2/3 throughput; it fails 1/3 of requests
#       outright, and a 502 mid-task is a dead agent, not a retry.
#   SERVING but NOT POOLED  -> silent lost capacity. 18775 was removed from the
#       drop-in on 2026-08-28 with the note "Restore it here the moment 18775
#       serves again". That restoration is currently held by whoever remembers.
#
# THE SECOND CASE IS WHY THIS EXISTS. A trigger held by a sentence in a config
# file is the same shape qwen-horizon.sh was built to replace — its header says
# "The deadline was being held by a sentence in a card. Nothing performed that
# check." Replica C (29722947) is predicted ~2026-09-02, days out, quite
# possibly in nobody's session.
#
# DETECTION ONLY. It never edits the drop-in. The hoist pool is what every agent
# reaches the models through, so changing its membership is a deliberate act,
# not something a timer does at 03:00. It reports and stops.
set -u

LOG=${HOIST_WATCH_LOG:-$HOME/.scitex/hpc/runtime/hoist-pool-drift.jsonl}
UNIT=${HOIST_WATCH_UNIT:-anthropic-system-hoist-proxy.service}
# Ports that MAY legitimately serve. 18776 is the A100, excluded from the pool
# by operator instruction 2026-08-16 — it may serve and must NOT be reported as
# missing capacity. Keep it out of CANDIDATES rather than special-casing later.
CANDIDATES=${HOIST_WATCH_CANDIDATES:-18773 18774 18775 18777}

mkdir -p "$(dirname "$LOG")" 2>/dev/null
now=$(date -u +%FT%TZ); host=$(hostname -s 2>/dev/null || echo unknown)

# --- alarm sink: ABSOLUTE PATH, resolved on EVERY run --------------------------
# Not `command -v`: a systemd --user unit gets a four-entry PATH carrying no
# scitex entry point, so a PATH lookup is false regardless of what is installed.
# Resolved every run, not only when alarming: a monitor that CANNOT report is
# broken now, and finding that out on the day it matters is too late.
_sink() {
  _c=""
  for _c in "${HOIST_WATCH_ALARM_CMD:-}" "$HOME/.local/bin/scitex-ci-alarm"; do
    [ -n "$_c" ] && [ -x "$_c" ] && { printf '%s\n' "$_c"; return 0; }
  done
  return 1
}
SINK=$(_sink) || SINK=""
if [ -z "$SINK" ]; then
  echo "[hoist-watch] ERROR no alarm sink resolved; drift cannot be reported, so this run is a FAILURE even if the pool is consistent." >&2
  exit 3
fi

# --- what does the pool ACTUALLY route to? -------------------------------------
# systemd's RESOLVED value, never the unit file. The main unit's own line 7 says
# "THIS LINE IS A FALLBACK, NOT THE LIVE VALUE" and a drop-in overrides it;
# reading the file instead of the resolution is the exact misread recorded in
# that unit on 2026-08-18 and repeated 2026-08-29.
POOL_RAW=$(systemctl --user show "$UNIT" -p Environment --value 2>/dev/null | tr ' ' '\n' | sed -n 's/^HOIST_UPSTREAM=//p')
if [ -z "$POOL_RAW" ]; then
  echo "[hoist-watch] ERROR: could not resolve HOIST_UPSTREAM from $UNIT. This is a FAILED LOOK, not an empty pool — an empty result here and a genuinely empty pool are different facts and must not both read as OK." >&2
  exit 2
fi
POOL=$(printf '%s' "$POOL_RAW" | tr ',' '\n' | sed -n 's#.*:\([0-9]\{4,5\}\).*#\1#p' | sort -u | tr '\n' ' ')

# --- which candidates are actually SERVING? ------------------------------------
# /v1/models returning a model id is the ONLY proof. A TCP connect is not:
# a dead-but-listening forward accepts the connection and returns nothing, and
# renders identically to a refused one (both HTTP 000). 18770/18771 sat in that
# state for a day. connect==0 -> refused; connect>0 + empty -> zombie.
SERVING=""; ZOMBIE=""
for p in $CANDIDATES; do
  # NO `|| echo` FALLBACK HERE — it corrupts a measurement that is already
  # correct. curl -w ALWAYS writes the format string, including on connection
  # failure: a refused port gives "000 0.000000" and exit 7. Adding
  # `|| echo "000 0"` appends a SECOND record with no separator, so the field
  # reads "0.000000000" — which is != "0.000000" and classified every CLOSED
  # port as a ZOMBIE. Measured 2026-08-29: 18775/18777 reported zombie while
  # both were plainly refused.
  # (Second instance of this shape in one session; the gitconfig watch had
  # `grep -c … || echo 0`, where grep also already printed the right answer.
  # A defensive fallback on a command that cannot fail to produce output is
  # not defence, it is corruption.)
  raw=$(curl -s -o /dev/null -m 6 -w '%{http_code} %{time_connect}' \
        "http://127.0.0.1:$p/v1/models" 2>/dev/null)
  read -r code ctime <<<"$raw"
  # An EMPTY read means curl itself did not run (absent, or killed). That is a
  # FAILED LOOK and must not silently render as "this port is not serving".
  if [ -z "${code:-}" ]; then
    echo "[hoist-watch] ERROR: curl produced no output probing $p — cannot tell 'not serving' from 'could not look'." >&2
    exit 2
  fi
  if [ "$code" = "200" ]; then
    if curl -s -m 6 "http://127.0.0.1:$p/v1/models" 2>/dev/null | grep -q '"id"'; then
      SERVING="$SERVING $p"
    else
      ZOMBIE="$ZOMBIE $p"   # 200 with no model id — answering, serving nothing
    fi
  elif [ "$code" = "000" ] && [ "$ctime" != "0.000000" ] && [ -n "$ctime" ]; then
    ZOMBIE="$ZOMBIE $p"     # connected, returned nothing
  fi
done

_has() { case " $2 " in *" $1 "*) return 0;; *) return 1;; esac; }
POOLED_NOT_SERVING=""; SERVING_NOT_POOLED=""
for p in $POOL;      do _has "$p" "$SERVING" || POOLED_NOT_SERVING="$POOLED_NOT_SERVING $p"; done
for p in $SERVING;   do _has "$p" "$POOL"    || SERVING_NOT_POOLED="$SERVING_NOT_POOLED $p"; done

PREV="none"
[ -s "$LOG" ] && PREV=$(grep '"event":"hoist"' "$LOG" 2>/dev/null | tail -1 | sed -n 's/.*"drift":\([0-9]*\).*/\1/p')
PREV=${PREV:-none}
DRIFT=$(( $(printf '%s' "$POOLED_NOT_SERVING" | wc -w) + $(printf '%s' "$SERVING_NOT_POOLED" | wc -w) ))

printf '{"ts":%s,"host":"%s","event":"hoist","pool":"%s","serving":"%s","zombie":"%s","pooled_not_serving":"%s","serving_not_pooled":"%s","drift":%s,"prev":"%s"}\n' \
  "$(date -u +%s)" "$host" "${POOL# }" "${SERVING# }" "${ZOMBIE# }" \
  "${POOLED_NOT_SERVING# }" "${SERVING_NOT_POOLED# }" "$DRIFT" "$PREV" >> "$LOG"

echo "[hoist-watch] $now pool=[${POOL# }] serving=[${SERVING# }] zombie=[${ZOMBIE# }] drift=$DRIFT prev=$PREV"

# Alarm on the TRANSITION. Drift persists until a human edits the drop-in, and
# this fires on a timer, so alarming on state would re-send the same condition
# until it was fixed — which teaches everyone to ignore it, the exact failure
# the alarm exists to prevent.
if [ "$DRIFT" -gt 0 ] && { [ "$PREV" = "none" ] || [ "$PREV" -eq 0 ] 2>/dev/null; }; then
  _msg=$(printf 'HOIST POOL DRIFT on %s. Routed pool: [%s]. Actually serving: [%s].%s%s%s Drop-in: ~/.config/systemd/user/%s.d/upstream.conf — DETECTION ONLY, nothing was changed. Rotate to .old/ with a UTC timestamp before editing, and verify /v1/models returns a model id before adding any port. Evidence: %s' \
    "$host" "${POOL# }" "${SERVING# }" \
    "$([ -n "$POOLED_NOT_SERVING" ] && printf ' POOLED BUT NOT SERVING:[%s] — this returns 502s to callers (measured 2026-08-28: ~1 request in 3, killed an agent mid-task).' "${POOLED_NOT_SERVING# }")" \
    "$([ -n "$SERVING_NOT_POOLED" ] && printf ' SERVING BUT NOT POOLED:[%s] — capacity is live and unused; restore it to the drop-in.' "${SERVING_NOT_POOLED# }")" \
    "$([ -n "$ZOMBIE" ] && printf ' ZOMBIE (accepts a connection, serves nothing):[%s].' "${ZOMBIE# }")" \
    "$UNIT" "$LOG")
  if [ "${HOIST_WATCH_DRYRUN:-0}" = "1" ]; then
    echo "[hoist-watch] DRYRUN would alarm via $SINK: $_msg" >&2
  elif "$SINK" "$_msg" -t "hoist pool drift on $host" -l error; then
    echo "[hoist-watch] alarm sent via $SINK" >&2
  else
    echo "[hoist-watch] ERROR alarm SEND FAILED via $SINK — evidence is in $LOG" >&2
    exit 3
  fi
elif [ "$DRIFT" -gt 0 ]; then
  echo "[hoist-watch] drift persists (prev=$PREV); already alarmed, not re-sending" >&2
fi

# exit 1 == drift present: the monitor WORKING. The unit declares
# SuccessExitStatus=0 1 so a true positive is not rendered as a broken unit.
[ "$DRIFT" -eq 0 ] || exit 1
exit 0
