#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
set -a
[ -f runner/runner.env ] && source runner/runner.env
set +a
export RUNNER_STATE_DIR="${RUNNER_STATE_DIR:-/tmp/openclaw-runner-state}"
mkdir -p "$RUNNER_STATE_DIR/plans"
echo "RUNNER_STATE_DIR=$RUNNER_STATE_DIR"
.venv-runner/bin/python -u runner/runner.py
