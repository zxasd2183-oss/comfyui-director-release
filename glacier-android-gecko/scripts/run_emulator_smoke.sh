#!/usr/bin/env bash
# Executed as a single command by reactivecircus/android-emulator-runner.
set -euo pipefail
export GLACIER_APK="${GLACIER_APK:-$GITHUB_WORKSPACE/.glacier-test-apk/GlacierAndroid-v0.2.3-Mobile-M05-ARM64-x86_64-debug.apk}"
export GLACIER_SMOKE_OUT="$GITHUB_WORKSPACE/emulator-evidence"
mkdir -p "$GLACIER_SMOKE_OUT"

python3 "$GITHUB_WORKSPACE/glacier-android-gecko/scripts/isolation_fixture.py" \
  > "$GLACIER_SMOKE_OUT/fixture-server.log" 2>&1 &
fixture_pid=$!
cleanup() { kill "$fixture_pid" 2>/dev/null || true; wait "$fixture_pid" 2>/dev/null || true; }
trap cleanup EXIT

python3 - <<'PY'
import socket,time
for i in range(30):
    try:
        with socket.create_connection(("127.0.0.1",18765),timeout=1):
            break
    except OSError:
        time.sleep(.2)
else:
    raise SystemExit("Loopback isolation fixture did not start")
PY
python3 "$GITHUB_WORKSPACE/glacier-android-gecko/scripts/emulator_smoke_v012.py"
