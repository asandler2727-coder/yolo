#!/bin/sh
set -eu

requested_strategy="$1"
shift

if [ "${YOLO_APPROVED_STRATEGY:-}" != "$requested_strategy" ]; then
    echo "No approved strategy: paper launcher is blocked for $requested_strategy." >&2
    exit 78
fi

exec "$@"
