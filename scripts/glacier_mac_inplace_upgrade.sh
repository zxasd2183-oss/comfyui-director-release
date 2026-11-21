#!/usr/bin/env bash
# Only on isolated GitHub macOS runner; do not touch any real user device.
set -euo pipefail
root="$RUNNER_TEMP/glacier-official-upgrade"
mkdir -p "$root/old" "$root/new" "$HOME/Applications"
gh release download glacier-macos-v0.20.34 --repo "$GITHUB_REPOSITORY" \
  --pattern 'GlacierBrowser-v0.20.34-macOS-AppleSilicon.dmg' --dir "$root/old"
gh release download glacier-macos-v0.20.35 --repo "$GITHUB_REPOSITORY" \
  --pattern 'GlacierBrowser-v0.20.35-macOS-AppleSilicon.dmg' --dir "$root/new"
old="$root/old/GlacierBrowser-v0.20.34-macOS-AppleSilicon.dmg"
new="$root/new/GlacierBrowser-v0.20.35-macOS-AppleSilicon.dmg"
printf '%s  %s\n' 57c943bfabcbf0f4e726262bcb10079d49d97730a3206bd853e5a0730784a511 "$old" | shasum -a 256 -c -
printf '%s  %s\n' 181e8ca08295336eff5313675642f3d1407df198ecedc7284cf1d19fda61121c "$new" | shasum -a 256 -c -
test "$(stat -f%z "$old")" = 286117890
test "$(stat -f%z "$new")" = 290705713
hdiutil verify "$old"
hdiutil verify "$new"
app="$HOME/Applications/GlacierBrowser.app"
for version in 0.20.34 0.20.35; do
    mount="$root/mount-$version"
    mkdir -p "$mount"
    dmg="$old"
    if [[ "$version" == 0.20.35 ]]; then
        dmg="$new"
    fi
    hdiutil attach -readonly -nobrowse -quiet -mountpoint "$mount" "$dmg"
    test -d "$mount/GlacierBrowser.app"
    if [[ "$version" == 0.20.35 ]]; then
        data="$HOME/Library/Application Support/GlacierBrowser"
        mkdir -p "$data"
        printf 'synthetic-qa-data-preserve-2026' > "$data/.glacier-ci-upgrade-marker"
        mv "$app" "$root/previous-GlacierBrowser.app"
    fi
    ditto "$mount/GlacierBrowser.app" "$app"
    hdiutil detach -quiet "$mount"
    actual="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$app/Contents/Info.plist")"
    bundle_id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$app/Contents/Info.plist")"
    test "$actual" = "$version"
    test "$bundle_id" = cn.borealos.glacierbrowser
    codesign --verify --deep "$app"
done
test "$(cat "$HOME/Library/Application Support/GlacierBrowser/.glacier-ci-upgrade-marker")" = synthetic-qa-data-preserve-2026
icon_file="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIconFile' "$app/Contents/Info.plist")"
test -s "$app/Contents/Resources/$icon_file"
echo 'PASS official Apple Silicon 0.20.34 -> 0.20.35 app upgrade, Dock ICNS and synthetic profile retained'
