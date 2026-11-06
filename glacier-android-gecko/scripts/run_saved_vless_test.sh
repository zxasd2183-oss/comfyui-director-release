#!/usr/bin/env bash
# Android 15 Keystore regression using a fake test-only VLESS link.
# No real VLESS traffic, account, credentials, or GPU provider access.
set -euo pipefail
OUT="$GITHUB_WORKSPACE/emulator-storage-evidence"
mkdir -p "$OUT"
trap 'adb logcat -d -t 2500 > "$OUT/logcat.txt" 2>/dev/null || true' EXIT

APK="$GITHUB_WORKSPACE/.glacier-test-apk/GlacierAndroid-v0.2.0-Mobile-M01-ARM64-x86_64-debug.apk"
TEST_APK="$GITHUB_WORKSPACE/.glacier-test-app/app-debug-androidTest.apk"
test -s "$APK"
test -s "$TEST_APK"
adb wait-for-device
adb install -r "$APK"
adb install -r "$TEST_APK"
adb shell am instrument -w -r \
  cn.borealos.glacier.geckopreview.test/androidx.test.runner.AndroidJUnitRunner \
  | tee "$OUT/instrumentation.txt"
grep -q 'OK (1 test)' "$OUT/instrumentation.txt"
echo 'M01_STORAGE_TEST_PASS: Keystore encrypted-save/read, auto-connect flag and delete'
