#!/usr/bin/env bash
# Only for an ephemeral rootable Android 15 CI emulator, never a user phone.
set -euo pipefail
cd "$GITHUB_WORKSPACE"
old=.upgrade-apks/old/GlacierAndroid-v0.2.10-ARM64-x86_64-release.apk
new=.upgrade-apks/new/GlacierAndroid-v0.2.11-ARM64-x86_64-release.apk
pkg=cn.borealos.glacier.geckopreview
tools="$ANDROID_HOME/build-tools/36.0.0"
test -s "$old"
test -s "$new"

verify_apk() {
    local apk="$1" code="$2"
    "$tools/apksigner" verify --verbose "$apk" >/dev/null
    local cert
    cert="$("$tools/apksigner" verify --print-certs "$apk" | sed -n -E 's/^Signer #1 certificate SHA-256 digest: ([a-fA-F0-9]{64})$/\1/p')"
    test "$cert" = 6d8fb8a4b3dd90427ff2f7959394df4b73f37c117a7d1d2e983bde0f10a1ff4e
    local badge
    badge="$("$tools/aapt" dump badging "$apk" | sed -n '1p')"
    [[ "$badge" == *"name='$pkg'"* ]]
    [[ "$badge" == *"versionCode='$code'"* ]]
}
verify_apk "$old" 19
verify_apk "$new" 20
adb wait-for-device
adb root
adb wait-for-device
root_uid="$(adb shell id -u | tr -d '\r')"
test "$root_uid" = 0 || { echo 'Emulator cannot verify app-private data; fail closed'; exit 2; }

adb install "$old"
adb shell pm path "$pkg" | grep -q 'package:'
installed_version() {
    adb shell dumpsys package "$pkg" | grep -oE 'versionCode=[0-9]+' | sed -n '1s/versionCode=//p' | tr -d '\r'
}
test "$(installed_version)" = 19
private_dir="/data/user/0/$pkg/no_backup"
adb shell "mkdir -p '$private_dir' && printf '%s' 'synthetic-qa-data-preserve-2026' > '$private_dir/.glacier-ci-upgrade-marker'"
test "$(adb shell "cat '$private_dir/.glacier-ci-upgrade-marker'" | tr -d '\r')" = synthetic-qa-data-preserve-2026

adb install -r "$new"
adb shell pm path "$pkg" | grep -q 'package:'
test "$(installed_version)" = 20
test "$(adb shell "cat '$private_dir/.glacier-ci-upgrade-marker'" | tr -d '\r')" = synthetic-qa-data-preserve-2026
echo 'PASS original permanent-signed Android 0.2.10 -> 0.2.11 overlay upgrade, app-private synthetic data retained'
