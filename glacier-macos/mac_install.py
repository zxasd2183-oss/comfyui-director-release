"""User-confirmed Glacier macOS DMG install handoff, with rollback.

The user must approve an already Ed25519-verified, SHA256-checked DMG.
Only replace the currently running GlacierBrowser.app in writable
/Applications or ~/Applications. No sudo, Gatekeeper bypass or shell input.
"""
from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from mac_update_core import CURRENT_VERSION, UpdateError, newer_than, verify_local_dmg

VERSION = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")

# This script runs under the OS-provided bash AFTER the old browser exits.
# It needs no Python interpreter inside the app bundle being replaced.
INSTALL_HELPER = r"""#!/bin/bash
set -Eeuo pipefail
umask 077
[[ "$#" -eq 6 ]] || exit 2
dmg="$1"; digest="$2"; size="$3"; version="$4"; dest="$5"; oldpid="$6"
[[ "$digest" =~ ^[a-f0-9]{64}$ && "$size" =~ ^[0-9]+$ ]] || exit 2
[[ "$version" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] || exit 2
[[ "$oldpid" =~ ^[1-9][0-9]*$ ]] || exit 2
[[ "$dmg" == */GlacierBrowser-v"$version"-macOS-AppleSilicon.dmg ]] || exit 2
[[ "$dest" == "/Applications/GlacierBrowser.app" ||
   "$dest" == "$HOME/Applications/GlacierBrowser.app" ]] || exit 2
[[ -f "$dmg" && ! -L "$dmg" && -d "$dest" && ! -L "$dest" ]] || exit 2
parent="$(/usr/bin/dirname "$dest")"
[[ -d "$parent" && ! -L "$parent" && -w "$parent" ]] || exit 2

for ((i=0;i<120;i++)); do
  if ! /bin/kill -0 "$oldpid" 2>/dev/null; then break; fi
  /bin/sleep 1
done
if /bin/kill -0 "$oldpid" 2>/dev/null; then
  echo "Browser did not exit; no files changed"; exit 1
fi
[[ "$(/usr/bin/stat -f '%z' "$dmg")" == "$size" ]] || {
  echo "DMG size changed; refusing install"; exit 1;
}
actual="$(/usr/bin/shasum -a 256 "$dmg" | /usr/bin/awk '{print $1}')"
[[ "$actual" == "$digest" ]] || {
  echo "DMG SHA256 changed; refusing install"; exit 1;
}

work="$(/usr/bin/mktemp -d "$parent/.glacier-update.XXXXXXXX")"
mounted=0
cleanup() {
  result=$?
  if [[ "$mounted" == 1 ]]; then
    /usr/bin/hdiutil detach "$work/mount" >/dev/null 2>&1 || true
  fi
  if [[ -d "$work/previous.app" && ! -e "$dest" ]]; then
    /bin/mv "$work/previous.app" "$dest" || {
      echo "Manual recovery: $work/previous.app"; exit 1;
    }
  fi
  if [[ ! -d "$work/previous.app" || "$result" == 0 ]]; then
    /bin/rm -rf "$work"
  else
    echo "Backup preserved at $work/previous.app"
  fi
  exit "$result"
}
trap cleanup EXIT
/bin/mkdir "$work/mount"
/usr/bin/hdiutil attach -readonly -nobrowse -mountpoint "$work/mount" "$dmg" >/dev/null
mounted=1
source="$work/mount/GlacierBrowser.app"
[[ -d "$source" && ! -L "$source" ]] || {
  echo "Expected app bundle missing"; exit 1;
}
/usr/bin/ditto "$source" "$work/new.app"
plist="$work/new.app/Contents/Info.plist"
[[ -f "$plist" && ! -L "$plist" ]] || exit 1
bundle_id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$plist")"
bundle_exe="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$plist")"
bundle_ver="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$plist")"
[[ "$bundle_id" == "cn.borealos.glacierbrowser" &&
   "$bundle_exe" == "GlacierBrowser" &&
   "$bundle_ver" == "$version" &&
   -x "$work/new.app/Contents/MacOS/GlacierBrowser" ]] || {
  echo "App bundle identity/version invalid"; exit 1;
}
/usr/bin/codesign --verify --deep "$work/new.app" || {
  echo "App bundle integrity check failed"; exit 1;
}
[[ -d "$dest" && ! -L "$dest" ]] || exit 1
/bin/mv "$dest" "$work/previous.app"
/bin/mv "$work/new.app" "$dest" || {
  /bin/mv "$work/previous.app" "$dest" || true
  echo "Unable to replace browser"; exit 1;
}
if ! /usr/bin/open -a "$dest"; then
  /bin/mv "$dest" "$work/failed.app" || true
  /bin/mv "$work/previous.app" "$dest" || true
  echo "Relaunch failed; attempted rollback"
  exit 1
fi
echo "Glacier v$version installed and launched"
"""


def writable_installed_app(executable=None, home=None, platform=None, roots=None):
    """Find a writable application installed in a supported Applications folder."""
    if (sys.platform if platform is None else platform) != "darwin":
        return None
    exe = Path(sys.executable if executable is None else executable).absolute()
    h = Path.home() if home is None else Path(home)
    allowed = tuple(roots) if roots is not None else (Path("/Applications"), h / "Applications")
    app = exe.parent.parent.parent
    if (app.name != "GlacierBrowser.app" or app.parent not in allowed or
            exe != app / "Contents" / "MacOS" / "GlacierBrowser" or
            app.is_symlink() or not app.is_dir() or exe.is_symlink() or
            not exe.is_file() or not (app / "Contents" / "Info.plist").is_file()):
        return None
    try:
        if app.resolve(strict=True) != app or not os.access(app.parent, os.W_OK | os.X_OK):
            return None
    except OSError:
        return None
    return app


def launch_user_confirmed_install(manifest, dmg_file, updates_dir):
    """Start the verified install helper; the browser closes only on success."""
    if sys.platform != "darwin":
        raise UpdateError("仅支持 macOS 原生安装")
    target = writable_installed_app()
    if target is None:
        raise UpdateError("当前应用不在可写的 Applications 目录")
    if not newer_than(CURRENT_VERSION, manifest["version"]):
        raise UpdateError("仅允许升级到更新版本")
    version = manifest["version"]
    if not VERSION.fullmatch(version):
        raise UpdateError("更新版本号无效")
    folder, dmg = Path(updates_dir), Path(dmg_file)
    if (folder.is_symlink() or not folder.is_dir() or dmg.is_symlink() or
            dmg.parent.resolve(strict=True) != folder.resolve(strict=True)):
        raise UpdateError("DMG 不在专用更新目录")
    verify_local_dmg(manifest, dmg)
    helper = folder / ("glacier-install-" + version + "-" + secrets.token_hex(8) + ".sh")
    descriptor = None
    logfd = None
    launched = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(helper, flags, 0o700)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            descriptor = None
            output.write(INSTALL_HELPER)
            output.flush()
            os.fsync(output.fileno())
        log = folder / "mac-install-last.log"
        if log.is_symlink():
            raise UpdateError("安装日志路径异常")
        logfd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND |
                        getattr(os, "O_NOFOLLOW", 0), 0o600)
        subprocess.Popen(
            ["/bin/bash", str(helper), str(dmg.resolve(strict=True)),
             manifest["sha256"], str(manifest["size"]), version,
             str(target), str(os.getpid())],
            stdin=subprocess.DEVNULL, stdout=logfd, stderr=subprocess.STDOUT,
            close_fds=True, start_new_session=True,
        )
        launched = True
        return True
    except (OSError, ValueError) as exc:
        raise UpdateError("无法启动 Mac 更新安装助手") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if logfd is not None:
            os.close(logfd)
        if not launched:
            helper.unlink(missing_ok=True)
