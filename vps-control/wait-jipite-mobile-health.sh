#!/usr/bin/env bash
# Wait for the mobile API to bind its loopback port after systemd restart.
# Intentionally no public network access, Microsoft credentials or GPU calls.
set -euo pipefail

for attempt in $(seq 1 20); do
  # A successful systemd start does not guarantee the Python HTTP server is
  # listening yet. Retry a *connection error*, never accept invalid content.
  if health="$(curl --fail --silent --max-time 2 http://127.0.0.1:8895/health 2>/dev/null)"; then
    if python3 -c 'import json,sys; o=json.loads(sys.argv[1]); assert o.get("ok") is True and o.get("mode")=="device_signed"' "$health"; then
      echo "Local Android API health: OK"
      exit 0
    fi
    echo "ABORT: unexpected health response from 8895" >&2
    exit 5
  fi
  if (( attempt < 20 )); then sleep 0.5; fi
done

echo "Mobile API failed health check after 20 attempts; inspect systemd logs." >&2
echo "  sudo journalctl -u director-mobile-v06 -n 50 --no-pager" >&2
exit 5
