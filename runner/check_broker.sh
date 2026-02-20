#!/usr/bin/env bash
# Quick connectivity check from WSL (or any worker host).
# Usage: BROKER_URL=http://YOUR_VPS_IP:8000 ./runner/check_broker.sh

set -e
url="${BROKER_URL:-http://127.0.0.1:8000}"
url="${url%/}"
echo "Checking $url/health ..."
if curl -sf --connect-timeout 5 "$url/health" > /dev/null; then
  echo "OK: broker reachable."
  curl -s "$url/health"
  echo ""
else
  echo "FAIL: cannot reach broker. Open TCP 8000 in the VPS cloud firewall (see docs/VPS_FIREWALL.md)."
  exit 1
fi
