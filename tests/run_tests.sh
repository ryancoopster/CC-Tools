#!/bin/sh
# Run every CC Tools suite. Exits non-zero if any fail.
cd "$(dirname "$0")" || exit 1
status=0
for t in t*.py; do
    printf '%-20s ' "$t"
    if out=$(python3 "$t" 2>&1); then
        echo "$out" | tail -1
    else
        echo "$out" | tail -1
        status=1
    fi
done
exit $status
