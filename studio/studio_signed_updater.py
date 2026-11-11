"""Root-owned, pull-only, pinned signed Director Studio application updates.

One-time VPS bootstrap required. Never runs caller-supplied commands, grants
MCP shell access, touches GPU power or writes Studio content, sessions or DB.
Only fixed /opt/director-studio code/UI files are within its update boundary.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
import re
import socket
import stat
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

REPO = "zxasd2183-oss/comfyui-director-release"
CHANNEL_URL = f"https://raw.githubusercontent.com/{REPO}/studio-updates/channel.json"
RELEASE_URL = f"https://github.com/{REPO}/releases/download/"
ALLOWED_HOSTS = {"github.com", "raw.githubusercontent.com",
                 "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
FORMAT = "director-studio-code-signed-v1"
FILES = (
    "gpu_return.py",
    "gpu_power_bridge.py",
    "studio_server.py",
    "studio_identity.py",
    "session_store.py",
    "studio_brain.py",
    "studio_backend.py",
    "studio_core.py",
    "production_core.py",
    "production_web.py",
    "production_manage.py",
    "visual_library.py",
    "character_library.py",
    "character_library_v2.py",
    "shot_character_bindings.py",
    "scene_library.py",
    "production_workflows.py",
    "video_results.py",
    "picture_cuts.py",
    "picture_cut_jobs.py",
    "audio_stems.py",
    "audio_master.py",
    "audio_master_jobs.py",
    "subtitle_tracks.py",
    "release_candidates.py",
    "release_jobs.py",
    "assemble_approved_cut.py",
    "manage.py",
    "index.html",
    "login.html",
    "login.css",
    "studio.css",
    "studio.js",
    "glacier-peaks.svg",
    "glacier-banner.svg",
)
STUDIO_DIR = Path("/opt/director-studio")
STATE = Path("/var/lib/director-studio-signed-updater")
PUBLIC = Path("/etc/director-ue-hub-update.pub")

STATUS_FILE = STUDIO_DIR / "signed-update-status.json"
HEX = re.compile(r"[0-9a-f]{64}\Z")
VER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
MAX_MANIFEST, MAX_PACKAGE, MAX_FILE = 4096, 12 * 1024 * 1024, 2 * 1024 * 1024

class UpdateError(RuntimeError):
    pass

def canon(item):
    return json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")

def unique(pairs):
    result = {}
    for k,v in pairs:
        if k in result: raise UpdateError("duplicate_field")
        result[k] = v
    return result

def version(value):
    if type(value) is not str or not VER.fullmatch(value):
        raise UpdateError("invalid_version")
    parts = tuple(map(int, value.split(".")))
    if max(parts) > 99999: raise UpdateError("unbounded_version")
    return parts

def verify_manifest(data, public):
    if len(data) > MAX_MANIFEST: raise UpdateError("manifest_too_large")
    try:
        obj = json.loads(data, object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise UpdateError("invalid_manifest") from exc
    keys = {"format", "version", "archive_sha256", "archive_size", "signature"}
    if type(obj) is not dict or set(obj) != keys or obj["format"] != FORMAT:
        raise UpdateError("manifest_contract_mismatch")
    version(obj["version"])
    if (type(obj["archive_sha256"]) is not str or not HEX.fullmatch(obj["archive_sha256"])
            or type(obj["archive_size"]) is not int
            or not 0 < obj["archive_size"] <= MAX_PACKAGE):
        raise UpdateError("manifest_archive_invalid")
    if (type(public) is not str or not HEX.fullmatch(public)
            or type(obj["signature"]) is not str
            or not re.fullmatch(r"[a-f0-9]{128}", obj["signature"])):
        raise UpdateError("manifest_signature_invalid")
    payload = {key: obj[key] for key in keys if key != "signature"}
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public)).verify(
            bytes.fromhex(obj["signature"]), canon(payload))
    except (ValueError, InvalidSignature) as exc:
        raise UpdateError("signature_failed") from exc
    return payload

def files_from_archive(blob, manifest):
    if (len(blob) != manifest["archive_size"]
            or hashlib.sha256(blob).hexdigest() != manifest["archive_sha256"]):
        raise UpdateError("archive_integrity_failed")
    result = {}
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            infos = archive.infolist()
            if len(infos) != len(FILES) or {x.filename for x in infos} != set(FILES):
                raise UpdateError("archive_file_allowlist")
            for info in infos:
                mode = (info.external_attr >> 16) & 0xF000
                if (info.is_dir() or mode == 0xA000 or info.flag_bits & 1
                        or not 0 < info.file_size <= MAX_FILE):
                    raise UpdateError("unsafe_archive_entry")
                binary = archive.read(info)
                if len(binary) != info.file_size:
                    raise UpdateError("archive_file_length")
                if info.filename.endswith(".py"):
                    compile(binary, info.filename, "exec", dont_inherit=True)
                elif b"\x00" in binary:
                    raise UpdateError("unsafe_noncode_asset")
                result[info.filename] = binary
    except (zipfile.BadZipFile, RuntimeError, SyntaxError, UnicodeError, OSError) as exc:
        if isinstance(exc, UpdateError): raise
        raise UpdateError("archive_bad_zip") from exc
    if result["studio_server.py"].decode("utf-8").count(
        'STUDIO_CODE_VERSION = "' + manifest["version"] + '"') != 1:
        raise UpdateError("studio_version_drift")
    return result

class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        p = urllib.parse.urlparse(newurl)
        if (p.scheme != "https" or p.hostname not in ALLOWED_HOSTS
                or p.username or p.password or p.port not in (None,443)):
            raise UpdateError("untrusted_redirect")
        return super().redirect_request(request,fp,code,msg,headers,newurl)

# HTTPS release fetches may use ONLY this local CONNECT proxy. Never honor
# HTTP(S)_PROXY from the root service environment: those may name remote hosts.
# The Ed25519 signature, HTTPS allowlist, and archive SHA-256 remain enforced.
LOCAL_RELEASE_PROXY = "http://127.0.0.1:1081"


def release_opener():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": LOCAL_RELEASE_PROXY}), Redirect()
    )


OPENER = release_opener()

def fetch(url, maximum):
    p = urllib.parse.urlparse(url)
    if p.scheme != "https" or p.hostname not in ALLOWED_HOSTS:
        raise UpdateError("untrusted_download_origin")
    with OPENER.open(urllib.request.Request(url, headers={
        "User-Agent": "DirectorStudio-SignedUpdate/1", "Accept-Encoding": "identity",
    }), timeout=25) as response:
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != "https" or final.hostname not in ALLOWED_HOSTS:
            raise UpdateError("untrusted_final_origin")
        data = response.read(maximum + 1)
    if len(data) > maximum: raise UpdateError("download_too_large")
    return data

def check_studio(expected_version=None):
    """Check the local Studio process and audit-verified project counts."""
    systemctl("is-active", "--quiet", "director-studio.service")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Redirect())
    req = urllib.request.Request(
        "http://127.0.0.1:8900/api/v1/production",
        headers={"Host": "127.0.0.1:8900", "Accept": "application/json"}
    )
    with opener.open(req, timeout=8) as response:
        if response.status != 200 or response.geturl() != req.full_url:
            raise UpdateError("studio_health_invalid")
        raw=response.read(65537)
        if len(raw) > 65536: raise UpdateError("studio_health_oversized")
        info=json.loads(raw)
    counts=info.get("counts") if isinstance(info,dict) else None
    if (not isinstance(info,dict) or
            info.get("mode") != "read_only_production_summary" or
            type(info.get("version")) is not str or
            not VER.fullmatch(info["version"]) or
            info.get("audit_chain_verified") is not True or
            not isinstance(counts,dict) or
            not all(type(v) is int and v>=0 for v in counts.values()) or
            "production_shots" not in counts or "projects" not in counts):
        raise UpdateError("studio_audit_or_health_invalid")
    if expected_version is not None and info.get("studio_code_version") != expected_version:
        raise UpdateError("studio_running_version_mismatch")
    return counts

def systemctl(*args):
    proc = subprocess.run(["/bin/systemctl", *args], stdin=subprocess.DEVNULL,
                          capture_output=True, timeout=20, check=False)
    if proc.returncode != 0:
        raise UpdateError("studio_service_operation_failed")

def check_studio_health(expected_version=None):
    return check_studio(expected_version)

def atomic(path, content):
    if path.is_symlink(): raise UpdateError("unsafe_path")
    # Code is non-secret and must remain readable by the unprivileged
    # directorpower systemd service after a root-owned atomic replace.
    # State files remain root-only, even under a 0077 service umask.
    public_app_file = path.parent == STUDIO_DIR
    mode = (stat.S_IMODE(path.stat().st_mode) if path.exists()
            else (0o644 if public_app_file else 0o600))
    if public_app_file:
        mode |= 0o444
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".pending")
    with temp.open("xb") as f:
        os.fchmod(f.fileno(), mode)
        f.write(content)
    os.replace(temp, path)

def ensure_safe_directory(folder):
    if folder.is_symlink() or not folder.is_dir():
        raise UpdateError("unsafe_directory")
    return folder

def apply_update(manifest, files):
    ensure_safe_directory(STUDIO_DIR)
    ensure_safe_directory(STATE)
    current = STATE / "installed-version.txt"
    if current.is_symlink() or not current.is_file():
        raise UpdateError("installed_version_missing")
    old = current.read_text("ascii").strip()
    if version(manifest["version"]) <= version(old):
        return {"status":"already_current", "version":old}
    baseline = check_studio_health()
    # Existing files must be safe ordinary files. A missing target is a
    # legitimate file ADDED by this signed release; dangling symlinks are not.
    original, created = {}, []
    for name in FILES:
        file = STUDIO_DIR / name
        if file.is_symlink():
            raise UpdateError("unsafe_existing_studio_file")
        if not file.exists():
            created.append(name)
            continue
        if not file.is_file() or file.stat().st_size > MAX_FILE:
            raise UpdateError("unsafe_existing_studio_file")
        original[name] = file.read_bytes()
    backup = STATE / ("backup-" + uuid.uuid4().hex)
    backup.mkdir(mode=0o700)
    for name, data in original.items():
        (backup / name).write_bytes(data)
    journal = STATE / "pending.json"
    atomic(journal, canon({"backup":backup.name, "from_version":old,
                           "created_files":created}))
    try:
        for name in FILES:
            target = STUDIO_DIR / name
            if name in created and (target.is_symlink() or target.exists()):
                raise UpdateError("unsafe_new_studio_file")
            atomic(target, files[name])
        systemctl("restart", "director-studio.service")
        time.sleep(2)
        if check_studio_health(manifest["version"])!=baseline:
            raise UpdateError("studio_ledger_changed_during_upgrade")
        atomic(current, manifest["version"].encode("ascii"))
        journal.unlink()
        return {"status":"upgraded", "version": manifest["version"]}
    except BaseException:
        # Roll back BOTH replaced files and newly introduced files. Retain
        # the journal if recovery fails so the next poll can retry recovery.
        _restore_files(original, created)
        systemctl("restart", "director-studio.service")
        check_studio_health()
        journal.unlink()
        raise
    finally:
        # Backups retained for operator audit and recovery; no recursive deletion.
        pass

def _restore_files(original, created):
    """Restore original application bytes and delete only signed newly added paths."""
    for name in FILES:
        file = STUDIO_DIR / name
        if name in created:
            if file.is_symlink() or (file.exists() and not file.is_file()):
                raise UpdateError("unsafe_created_studio_file")
            if file.exists():
                file.unlink()
        else:
            atomic(file, original[name])


def recover():
    journal = STATE / "pending.json"
    if not journal.exists(): return False
    if journal.is_symlink() or journal.stat().st_size > 1024:
        raise UpdateError("bad_recovery_journal")
    try:
        info = json.loads(journal.read_text("ascii"), object_pairs_hook=unique)
    except (ValueError,UnicodeError,OSError) as exc:
        raise UpdateError("bad_recovery_journal") from exc
    if (type(info) is not dict or set(info) != {
            "backup", "from_version", "created_files"}
            or type(info["backup"]) is not str
            or not re.fullmatch(r"backup-[a-f0-9]{32}", info["backup"])
            or type(info["created_files"]) is not list
            or len(info["created_files"]) > len(FILES)
            or any(type(name) is not str or name not in FILES
                   for name in info["created_files"])
            or len(set(info["created_files"])) != len(info["created_files"])):
        raise UpdateError("bad_recovery_journal")
    version(info["from_version"])
    backup = ensure_safe_directory(STATE / info["backup"])
    created = set(info["created_files"])
    originals = {}
    for name in FILES:
        if name in created:
            # A newly added file has no backup; it must be removed on rollback.
            if (backup / name).exists() or (backup / name).is_symlink():
                raise UpdateError("bad_recovery_backup")
            continue
        file = backup / name
        if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_FILE:
            raise UpdateError("bad_recovery_backup")
        originals[name] = file.read_bytes()
    _restore_files(originals, created)
    systemctl("restart", "director-studio.service")
    check_studio_health()
    atomic(STATE / "installed-version.txt", info["from_version"].encode("ascii"))
    journal.unlink()
    return True

def run_once(*, channel=None, download=None, public=None):
    recover()
    if public is None:
        if PUBLIC.is_symlink() or not PUBLIC.is_file() or PUBLIC.stat().st_size != 64:
            raise UpdateError("studio_trust_key_unconfigured")
        public = PUBLIC.read_text("ascii")
    try:
        raw = channel() if channel else fetch(CHANNEL_URL, MAX_MANIFEST)
    except urllib.error.HTTPError as exc:
        if exc.code == 404: return {"status":"no_signed_channel"}
        raise
    payload = verify_manifest(raw, public)
    installed = (STATE / "installed-version.txt").read_text("ascii").strip()
    if version(payload["version"]) <= version(installed):
        return {"status":"already_current", "version":installed}
    asset = "director-studio-v" + payload["version"] + ".zip"
    path = RELEASE_URL + "director-studio-v" + payload["version"] + "/" + asset
    data = download(payload["version"]) if download else fetch(path, MAX_PACKAGE)
    return apply_update(payload, files_from_archive(data, payload))

def main():
    if os.geteuid() != 0: raise SystemExit("VPS root needed")
    if not STATE.is_dir() or STATE.is_symlink():
        raise SystemExit("updater state unavailable")
    try:
        result = run_once()
        atomic(STATE / "last-result.json", canon(result))
        atomic(STATUS_FILE, canon(result))
    except Exception as exc:
        data = {"status":"failed",
                "reason":str(exc)[:100] if isinstance(exc, UpdateError)
                         else "unexpected_updater_failure"}
        atomic(STATE / "last-result.json", canon(data))
        atomic(STATUS_FILE, canon(data))
        raise SystemExit(1) from None

if __name__ == "__main__":
    main()
