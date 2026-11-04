#!/usr/bin/env bash
# Executed as ONE command inside reactivecircus/android-emulator-runner.
# Runner's script property uses `sh -c <one line>`, not a multiline shell.
set -euo pipefail
adb install /tmp/jipite.apk
adb shell am force-stop cn.borealos.jipite || true
adb logcat -c
adb shell am start -W -n cn.borealos.jipite/.MainActivity > /tmp/jipite-launch.txt
sleep 8
adb logcat -d -b crash -v threadtime > /tmp/jipite-crash.log || true
if ! adb shell pidof cn.borealos.jipite > /tmp/jipite-pid.txt; then
  echo "Jipite process not alive after activity launch:"
  cat /tmp/jipite-crash.log
  exit 1
fi
if grep -qE 'FATAL EXCEPTION|Process: cn.borealos.jipite' /tmp/jipite-crash.log; then
  echo "Jipite Android startup crash detected:"
  cat /tmp/jipite-crash.log
  exit 1
fi
echo "Signed Jipite APK remained alive after 8s on Android 11 (API 30)."
