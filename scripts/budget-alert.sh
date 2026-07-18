#!/bin/bash
# Budget alert: notify via ntfy.sh when monthly usage crosses thresholds.
#
# Runs from cron on the VM. Queries the admin status endpoint, computes
# percentage used, and posts to an ntfy topic when 50% or 80% is first
# crossed. Does NOT re-alert once a threshold has fired. Resets on month
# rollover.
#
# Required environment (set in crontab or source from a file):
#   CUSTOS_ADMIN_URL   - e.g. https://api.your-domain.com/api/admin/status
#   CUSTOS_ADMIN_TOKEN - bearer token for the admin endpoint
#   NTFY_TOPIC         - ntfy.sh topic (e.g. custos-alerts)
#
# State file: persists which thresholds have fired this month.
STATE_FILE="${HOME}/.custos-alert-state"

set -euo pipefail

# Fetch admin status
RESPONSE=$(curl -sf -H "Authorization: Bearer ${CUSTOS_ADMIN_TOKEN}" "${CUSTOS_ADMIN_URL}")
if [ $? -ne 0 ]; then
    echo "Failed to reach admin endpoint" >&2
    exit 1
fi

# Parse values
PCT=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['pct_monthly_used'])")
MONTH=$(date +%Y-%m)

# Load state (format: YYYY-MM:threshold1,threshold2,...)
FIRED=""
if [ -f "$STATE_FILE" ]; then
    STATE_MONTH=$(cut -d: -f1 "$STATE_FILE")
    if [ "$STATE_MONTH" = "$MONTH" ]; then
        FIRED=$(cut -d: -f2 "$STATE_FILE")
    fi
    # If month rolled over, state resets (FIRED stays empty)
fi

notify() {
    local level="$1"
    local msg="$2"
    curl -sf -d "$msg" "https://ntfy.sh/${NTFY_TOPIC}" \
        -H "Title: Custos budget alert" \
        -H "Priority: ${level}" > /dev/null 2>&1
}

UPDATED=false

# 80% threshold (check first, higher priority)
if echo "$PCT >= 80" | bc -l | grep -q 1; then
    if ! echo "$FIRED" | grep -q "80"; then
        notify "high" "Monthly usage at ${PCT}% (80% threshold). ${MONTH}."
        FIRED="${FIRED}80,"
        UPDATED=true
    fi
# 50% threshold
elif echo "$PCT >= 50" | bc -l | grep -q 1; then
    if ! echo "$FIRED" | grep -q "50"; then
        notify "default" "Monthly usage at ${PCT}% (50% threshold). ${MONTH}."
        FIRED="${FIRED}50,"
        UPDATED=true
    fi
fi

# Persist state
if [ "$UPDATED" = true ] || [ ! -f "$STATE_FILE" ]; then
    echo "${MONTH}:${FIRED}" > "$STATE_FILE"
fi
