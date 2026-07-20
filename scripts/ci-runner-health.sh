#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# ci-runner-health.sh — is each self-hosted runner ACTUALLY able to take work?
#
# A runner that advertises `online` to GitHub but cannot execute is the worst
# state this fleet produces: jobs are accepted, renewed once a minute, and burn
# their full workflow timeout having run ZERO steps. Nothing errors. From the
# outside it is indistinguishable from CI being slow.
#
# This checks the two conditions that have actually failed in production, and
# prints one line per runner so a sweep is auditable rather than summarised.
#
#   WORKDIR   `_work` resolves and is WRITABLE on the node the runner runs on.
#   LISTENERS exactly ONE Runner.Listener per runner directory.
#
# WHY "exactly one" IS A HEALTH CONDITION, not pedantry: on 2026-07-21 two
# keepalive loops ran for each of two runners. Each loop does
# `rm -rf "$wd/_temp"` on every iteration, so the second deleted the first
# listener's job temp directory out from under its worker — worker stalls,
# listener keeps renewing, run times out with steps:[]. Two listeners for one
# registration also produce SessionConflictException. Both runners reported
# `online` throughout.
#
# ===========================================================================
# RUN THIS INSIDE THE ALLOCATION. IT IS WRONG FROM A LOGIN NODE.
# ===========================================================================
#
#   JOBID=$(squeue --user="$USER" --name=spartan-ci-runner-supervisor \
#                  --states=RUNNING --noheader --format='%i' | head -1)
#   srun --jobid="$JOBID" --overlap -n1 scripts/ci-runner-health.sh
#
# `_work` points into node-local /tmp, and /tmp is PER-NODE. Run from
# spartan-login1 and every link reads as dangling because you are looking at a
# different filesystem than the runners use — a login node has its own /tmp
# with none of this in it. That error has been made three separate ways on this
# fleet (a `ls -d` that followed the link, a login-node read, and a login-node
# `mkdir -p` whose measured +2 "repair" only ever touched the login node). The
# command was correct every time; the NAMESPACE was wrong.
#
# Resolve the job id BY NAME, never store it: permanent allocations resubmit on
# walltime, so the id rolls while the name is stable.
#
# Exit 0 = all runners healthy. Exit 1 = at least one is not. Exit 2 = could not
# tell (refuses to report health it did not establish).
# ---------------------------------------------------------------------------
set -uo pipefail

CI="${CI_ROOT:-/data/gpfs/projects/punim0264/ywatanabe/ci}"

# Org every CI runner should be registered against after the 2026-07 migration.
EXPECTED_ORG="${EXPECTED_ORG:-scitex-ai}"
# Repos that legitimately remain under the personal account -- verified against
# the scitex-ai org listing 2026-07-21, not assumed.
PERSONAL_REPOS="${PERSONAL_REPOS:-.dotfiles neurovista scitex-audit scitex-core scitex-todo}"

[ -d "$CI" ] || { echo "FATAL: runner root not found: $CI" >&2; exit 2; }

# Refuse to run somewhere the answer would be meaningless. A login node has no
# runners, so "everything is broken" would be the confident wrong answer.
if ! pgrep -x Runner.Listener >/dev/null 2>&1; then
    echo "FATAL: no Runner.Listener process on $(hostname -s)." >&2
    echo "  This host runs no runners, so every check below would report a" >&2
    echo "  FALSE failure. Run inside the supervisor's allocation:" >&2
    echo "    srun --jobid=<supervisor-job> --overlap -n1 \$0" >&2
    exit 2
fi

rc=0
checked=0
warned=0

for d in "$CI"/actions-runner-*/; do
    d="${d%/}"
    [ -x "$d/run.sh" ] || continue
    case "$d" in *.wrap.log) continue ;; esac
    tag="$(basename "$d")"; tag="${tag#actions-runner-}"
    checked=$((checked + 1))

    # --- WORKDIR ---------------------------------------------------------
    work_status="OK"
    if [ ! -e "$d/_work" ]; then
        # -e follows the symlink, so this is exactly the dangling-link case.
        work_status="DANGLING(-> $(readlink "$d/_work" 2>/dev/null || echo '?'))"
    elif ! probe="$(mktemp "$d/_work/.health-XXXXXX" 2>&1)"; then
        work_status="UNWRITABLE"
    else
        rm -f "$probe"
    fi

    # --- REGISTRATION URL ------------------------------------------------
    # A runner whose stored gitHubUrl points at a repo that has since been
    # TRANSFERRED keeps working indefinitely -- GitHub binds it by stored
    # credentials, not by the URL string. The URL only matters when the runner
    # has to RE-REGISTER. So this is a recovery hazard, not an outage, and it
    # is invisible until the day it matters:
    #
    #   runner drops offline long enough for GitHub to delete its registration
    #     -> config.sh posts the stale URL to /actions/runner-registration
    #     -> 404, and that repo's CI stays dead until someone works out why
    #
    # Measured 2026-07-21: 64 of 69 runners on ywatanabe1989/ URLs pointed at
    # repos already transferred to scitex-ai/. scitex-config had already died
    # this exact way.
    #
    # The trap when diagnosing it: `gh api repos/<old-owner>/<repo>` SUCCEEDS,
    # because the API silently follows the transfer redirect. Every read
    # reinforces the wrong URL. config.sh does NOT follow it.
    #
    # Checked locally against an expected org so this needs no API access
    # (it runs on a compute node). EXPECTED_ORG / PERSONAL_REPOS are
    # overridable; the defaults encode the 2026-07 migration.
    url_status="OK"
    if [ -f "$d/.runner" ]; then
        # .runner is UTF-8 with a BOM; plain json parsers choke on it, so match
        # textually rather than decoding.
        url="$(tr -d '\000' < "$d/.runner" | grep -o 'https://github\.com/[^"]*' | head -1)"
        owner="$(echo "$url" | awk -F/ '{print $4}')"
        repo="$(echo "$url" | awk -F/ '{print $5}')"
        if [ -n "$owner" ] && [ "$owner" != "$EXPECTED_ORG" ]; then
            case " $PERSONAL_REPOS " in
                *" $repo "*) : ;;   # genuinely still a personal repo
                *) url_status="STALE-ORG($owner/$repo)" ;;
            esac
        fi
    fi

    # --- LISTENERS -------------------------------------------------------
    # Match the RESOLVED path: an adopted runner directory can be a symlink
    # into this tree, and the listener advertises its resolved path in argv.
    # Matching the nominal path finds nothing and this check fails OPEN.
    real="$(readlink -f "$d" 2>/dev/null)" || real=""
    [ -n "$real" ] || real="$d"
    # Count with `wc -l`, NOT `pgrep -c ... || echo 0`. `pgrep -c` prints "0"
    # AND exits 1 when nothing matches, so the `||` fallback appends a SECOND
    # value: n_listeners becomes "0\n0", matches neither the 0 nor the 1 case,
    # and falls through to the duplicate branch. A runner with NO listener then
    # reports DUPLICATE — the exact opposite of its actual fault. `wc -l`
    # always emits one clean integer and never fails.
    n_listeners="$(pgrep -f "^$real/bin/Runner.Listener" 2>/dev/null | wc -l)"

    case "$n_listeners" in
        1) listener_status="OK" ;;
        0) listener_status="NONE" ;;
        *) listener_status="DUPLICATE($n_listeners)" ;;
    esac

    # A stale registration URL is a WARN, deliberately NOT a failure. Those
    # runners are serving jobs right now; only their future RE-registration is
    # broken. Failing on them would turn this detector red for ~64 of 80
    # runners and bury the two or three that genuinely cannot take work --
    # which is how a check gets ignored, and then gets ignored on the day it
    # matters. Exit status answers "can these runners take work NOW"; WARN
    # carries the latent hazard without competing with it.
    if [ "$work_status" = "OK" ] && [ "$listener_status" = "OK" ]; then
        if [ "$url_status" = "OK" ]; then
            printf 'OK      %-45s work=OK listeners=1\n' "$tag"
        else
            printf 'WARN    %-45s work=OK listeners=1 url=%s\n' "$tag" "$url_status"
            warned=$((warned + 1))
        fi
    else
        printf 'UNHEALTHY %-43s work=%s listeners=%s url=%s\n' \
               "$tag" "$work_status" "$listener_status" "$url_status"
        rc=1
    fi
done

if [ "$checked" -eq 0 ]; then
    echo "FATAL: no runner directories matched under $CI" >&2
    exit 2
fi

echo "--- checked $checked runner(s) on $(hostname -s); $warned with stale registration URL (WARN, still serving); exit $rc"
exit "$rc"
