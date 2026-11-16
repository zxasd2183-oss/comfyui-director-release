"""Fail-closed source consistency check for Glacier-only installable RC versions.

Verifies public version identities across desktop applications, installers,
Android app, smoke scripts and candidate artifacts. Does not publish a release.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _expect_single(pattern: str, content: str, path: str) -> str:
    matches = re.findall(pattern, content, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError(f"{path}: expected one version, found {matches!r}")
    return matches[0]


def inspect(root=ROOT):
    root = Path(root)
    sources = {
        "windows_core": "glacier-windows/secure_update.py",
        "windows_main": "glacier-windows/main.py",
        "mac_core": "glacier-macos/mac_update_core.py",
        "mac_main": "glacier-macos/main.py",
        "android_gradle": "glacier-android-gecko/app/build.gradle",
        "win_ci": ".github/workflows/glacier-rc-windows.yml",
        "mac_ci": ".github/workflows/glacier-rc-macos.yml",
        "android_ci": ".github/workflows/glacier-rc-android.yml",
        "android_vless": "glacier-android-gecko/scripts/run_saved_vless_test.sh",
        "android_smoke": "glacier-android-gecko/scripts/run_emulator_smoke.sh",
    }
    data = {key: (root / value).read_text(encoding="utf-8")
            for key, value in sources.items()}
    win = _expect_single(r"^CURRENT_VERSION = '([0-9]+\.[0-9]+\.[0-9]+)'$", data["windows_core"], "Windows")
    mac = _expect_single(r'^CURRENT_VERSION = "([0-9]+\.[0-9]+\.[0-9]+)"$', data["mac_core"], "macOS")
    android = _expect_single(r"^\s*versionName '([0-9]+\.[0-9]+\.[0-9]+)'$", data["android_gradle"], "Android")
    code = int(_expect_single(r"^\s*versionCode ([0-9]+)$", data["android_gradle"], "Android versionCode"))
    if win != "0.20.29" or mac != win or android != "0.2.4" or code != 13:
        raise ValueError("Glacier versions are not the approved monotonic RC upgrade")
    # The Ed25519 trust-root preparation deliberately refuses any unapproved
    # version. Match its allowlist before scheduling expensive native builds.
    safety = (root / "scripts/glacier_prepare_rotated_update.py").read_text(encoding="utf-8")
    accepted = 'PLATFORM_VERSIONS = {"windows": "0.20.29", "macos": "0.20.29"}'
    if safety.count(accepted) != 1:
        raise ValueError("Pinned Ed25519 build preparation rejects current clients")
    for key, version in (("windows_main", win), ("mac_main", mac)):
        if f"v{version}" not in data[key]:
            raise ValueError(key + ": displayed version does not match updater")
    if (root / "glacier-windows/glacier_accounts22.py").read_bytes() != (
            root / "glacier-macos/glacier_accounts22.py").read_bytes():
        raise ValueError("macOS website account and Cookie implementation is stale")
    for key, version, filename in (
        ("win_ci", win, f"GlacierBrowser-v{win}-Windows-Setup-x64.exe"),
        ("mac_ci", mac, f"GlacierBrowser-v{mac}-macOS-AppleSilicon.dmg"),
        ("android_ci", android, f"GlacierAndroid-v{android}-ARM64-x86_64-release.apk"),
    ):
        if f"v{version}" not in data[key]:
            raise ValueError(key + ": lacks updated version")
        if filename not in data[key]:
            raise ValueError(key + ": lacks corresponding installer name")
    for key in ("android_ci", "android_vless", "android_smoke"):
        if f"GlacierAndroid-v{android}-Mobile-M05-ARM64_x86_64-debug.apk" not in data[key].replace(
                "ARM64-x86_64", "ARM64_x86_64"):
            raise ValueError(key + ": stale Android APK name")
    if "versionCode='13'" not in data["android_ci"] or "versionName='0.2.4'" not in data["android_ci"]:
        raise ValueError("Android release signing guard is still pinned to old APK")
    if "0.20.28" in data["win_ci"] or "0.20.27" in data["mac_ci"]:
        raise ValueError("Installer workflow still refers to an old release version")
    if "0.2.3" in data["android_ci"]:
        raise ValueError("Android RC still refers to previous release")
    # Functional smoke suites must target the version just packaged. Earlier
    # harnesses looked for the old title and failed valid new installers.
    checks = (
        ("glacier-windows/test_windows_desktop15.py", f"v{win}"),
        ("glacier-macos/test_mac_desktop15.py", f"v{mac}"),
        ("glacier-macos/test_mac_gui_start.py", f"v{mac}"),
        ("glacier-android-gecko/scripts/emulator_smoke_v012.py", f"更新与版本 {android}"),
        ("glacier-android-gecko/scripts/test_rc_signed_release_guard.py",
         f"versionName='{android}'"),
    )
    for rel, expected in checks:
        if expected not in (root / rel).read_text(encoding="utf-8"):
            raise ValueError(rel + ": smoke check expects an obsolete client version")
    return {"windows": win, "macos": mac, "android": android, "android_code": code}


if __name__ == "__main__":
    print("PASS Glacier candidate version consistency:", inspect())
