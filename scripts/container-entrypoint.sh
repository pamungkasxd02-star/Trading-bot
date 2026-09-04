#!/bin/sh
set -eu

config_path="${SPOTLAB_CONFIG:-config/paper-server.yaml}"
history_months="${SPOTLAB_HISTORY_MONTHS:-24}"
container_mode="${SPOTLAB_CONTAINER_MODE:-paper}"
command_name="${1:-paper}"

if [ "$container_mode" = "paper" ] && [ "$command_name" = "live" ]; then
    echo "LIVE BLOCKED: container ini dikunci untuk paper trading" >&2
    exit 64
fi

case "$command_name" in
    paper)
        spotlab --config "$config_path" fetch --months "$history_months"
        exec spotlab --config "$config_path" paper
        ;;
    health)
        exec spotlab --config "$config_path" health --mode paper
        ;;
    *)
        exec spotlab --config "$config_path" "$@"
        ;;
esac
