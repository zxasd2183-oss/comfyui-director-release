#!/usr/bin/env bash
# Android 15 Keystore regression using a fake test-only VLESS link.
# No real VLESS traffic, account, credentials, or GPU provider access.
set -euo pipefail
OUT="$GITHUB_WORKSPACE/emulator-storage-evidence"
mkdir -p "$OUT"
trap 'adb logcat -d -t 2500 > "$OUT/logcat.txt" 2>/dev/null || true' EXIT

APK="$GITHUB_WORKSPACE/.glacier-test-apk/GlacierAndroid-v0.2.3-Mobile-M05-ARM64-x86_64-debug.apk"
TEST_APK="$GITHUB_WORKSPACE/.glacier-test-app/app-debug-androidTest.apk"
test -s "$APK"
test -s "$TEST_APK"
adb wait-for-device
adb install -r "$APK"
adb install -r "$TEST_APK"
adb shell am instrument -w -r \
  cn.borealos.glacier.geckopreview.test/androidx.test.runner.AndroidJUnitRunner \
  | tee "$OUT/instrumentation.txt"
grep -Eq '^OK \(([9]|[1-9][0-9]+) tests?\)' "$OUT/instrumentation.txt"
echo 'M05_STORAGE_TEST_PASS: VLESS, tab and library encryption; stable-only updater release validation and SOCKS5 remote-host handshake'
