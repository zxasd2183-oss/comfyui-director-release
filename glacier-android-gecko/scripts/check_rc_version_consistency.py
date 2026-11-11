#!/usr/bin/env python3
"""Fail closed when Android RC version differs across APK consumers.

Check static artifact identities BEFORE emulator boot. This intentionally does
not scan unit tests containing older versions as comparison fixtures.
"""
from pathlib import Path
import re


def inspect(root: Path) -> str:
    root = Path(root)
    gradle = (root / "glacier-android-gecko/app/build.gradle").read_text(encoding="utf-8")
    match = re.search(r"(?m)^\s*versionName\s+['\"]([0-9]+\.[0-9]+\.[0-9]+)['\"]\s*$", gradle)
    if not match:
        raise ValueError("Android Gradle versionName missing or invalid")
    version = match.group(1)
    expected = f"GlacierAndroid-v{version}-Mobile-M05-ARM64-x86_64-debug.apk"
    consumers = (
        root / "glacier-android-gecko/scripts/run_saved_vless_test.sh",
        root / "glacier-android-gecko/scripts/run_emulator_smoke.sh",
        root / ".github/workflows/glacier-rc-android.yml",
    )
    for path in consumers:
        data = path.read_text(encoding="utf-8")
        if expected not in data:
            raise ValueError(f"{path.name} does not reference expected candidate APK {expected}")
        observed = re.findall(r"GlacierAndroid-v([0-9]+\.[0-9]+\.[0-9]+)-[^\s\"']+\.apk", data)
        if observed and set(observed) != {version}:
            raise ValueError(f"{path.name} contains stale APK version references: {sorted(set(observed))}")
    if "versionCode 12" not in gradle:
        raise ValueError("Android versionCode unexpected; candidate upgrade may not install")
    return version


if __name__ == "__main__":
    try:
        version = inspect(Path(__file__).resolve().parents[2])
    except (ValueError, OSError) as error:
        raise SystemExit("Android RC artifact identity check FAILED: " + str(error))
    print(f"PASS: Android {version} Gradle, CI APK, instrumentation and UI test runners agree")
