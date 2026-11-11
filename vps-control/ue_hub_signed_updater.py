"""Root-owned, pull-only signed update for exactly two Director Hub UE files.

Bootstrapped once by a VPS administrator. Never listens on a port, takes
caller-supplied commands, or touches GPU power, Worker, SSH or Nginx.
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
CHANNEL_URL = f"https://raw.githubusercontent.com/{REPO}/ue-hub-updates/channel.json"
RELEASE_URL = f"https://github.com/{REPO}/releases/download/"
ALLOWED_HOSTS = {"github.com", "raw.githubusercontent.com",
                 "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
FORMAT = "director-ue-hub-signed-v1"
FILES = ("hub_app.py", "ue_worker_rpc.py")
HUB_DIR = Path("/opt/comfyui-director-hub")
STATE = Path("/var/lib/director-ue-hub-updater")
PUBLIC = Path("/etc/director-ue-hub-update.pub")
WORKER_TOKEN = Path("/etc/director-ue-worker.token")
STATUS_FILE = HUB_DIR / "ue_hub_signed_update_status.json"
HEX = re.compile(r"[0-9a-f]{64}\Z")
VER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
MAX_MANIFEST, MAX_PACKAGE, MAX_FILE = 4096, 1024 * 1024, 400 * 1024

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
                compile(binary, info.filename, "exec", dont_inherit=True)
                result[info.filename] = binary
    except (zipfile.BadZipFile, RuntimeError, SyntaxError, UnicodeError, OSError) as exc:
        if isinstance(exc, UpdateError): raise
        raise UpdateError("archive_bad_zip") from exc
    if result["hub_app.py"].decode("utf-8").count(
        'UE_HUB_API_VERSION = "' + manifest["version"] + '"') != 1:
        raise UpdateError("hub_version_drift")
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
        "User-Agent": "DirectorUEHub-SignedUpdate/1", "Accept-Encoding": "identity",
    }), timeout=25) as response:
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != "https" or final.hostname not in ALLOWED_HOSTS:
            raise UpdateError("untrusted_final_origin")
        data = response.read(maximum + 1)
    if len(data) > maximum: raise UpdateError("download_too_large")
    return data

def get_worker_state(required_version=None):
    if (WORKER_TOKEN.is_symlink() or not WORKER_TOKEN.is_file()
            or WORKER_TOKEN.stat().st_size > 128):
        raise UpdateError("worker_token_missing")
    token = WORKER_TOKEN.read_text("ascii").strip()
    if not HEX.fullmatch(token): raise UpdateError("worker_token_invalid")
    request = urllib.request.Request("http://127.0.0.1:18910/v1/status",
               headers={"Authorization": "Bearer " + token})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
        request, timeout=3
    ) as response:
        info = json.load(response)
    # Only post-V0.7 Workers report active_job_id. Fail closed otherwise.
    if (type(info) is not dict or info.get("ok") is not True
            or "active_job_id" not in info or info["active_job_id"] is not None):
        raise UpdateError("worker_busy_or_activity_unknown")
    if required_version is not None:
        try:
            if version(info.get("worker_version")) < version(required_version):
                raise UpdateError("worker_version_not_ready_for_hub")
        except (TypeError, ValueError) as exc:
            raise UpdateError("worker_version_unverifiable") from exc
    return info

def systemctl(*args):
    proc = subprocess.run(["/bin/systemctl", *args], stdin=subprocess.DEVNULL,
                          capture_output=True, timeout=20, check=False)
    if proc.returncode != 0:
        raise UpdateError("hub_service_operation_failed")

def check_hub():
    systemctl("is-active", "--quiet", "director-hub-mcp.service")
    systemctl("is-active", "--quiet", "director-hub-bridge.service")
    with socket.create_connection(("127.0.0.1", 8898), timeout=2):
        return True

def atomic(path, content):
    if path.is_symlink(): raise UpdateError("unsafe_path")
    # Code is non-secret and must remain readable by the unprivileged
    # directorpower systemd service after a root-owned atomic replace.
    # State files remain root-only, even under a 0077 service umask.
    public_app_file = path.parent == HUB_DIR
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
    ensure_safe_directory(HUB_DIR)
    ensure_safe_directory(STATE)
    current = STATE / "installed-version.txt"
    if current.is_symlink() or not current.is_file():
        raise UpdateError("installed_version_missing")
    old = current.read_text("ascii").strip()
    if version(manifest["version"]) <= version(old):
        return {"status":"already_current", "version":old}
    # A new Hub API must never arrive before its matching signed Worker:
    # installing Hub 0.7 with a 0.5.x Worker would expose unsupported tools.
    get_worker_state(manifest["version"])
    check_hub()
    # Existing Hub files are root owned; never blindly follow symlinks.
    original = {}
    for name in FILES:
        file = HUB_DIR / name
        if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_FILE:
            raise UpdateError("unsafe_existing_hub_file")
        original[name] = file.read_bytes()
    backup = STATE / ("backup-" + uuid.uuid4().hex)
    backup.mkdir(mode=0o700)
    for name, data in original.items():
        (backup / name).write_bytes(data)
    journal = STATE / "pending.json"
    atomic(journal, canon({"backup":backup.name, "from_version":old}))
    try:
        for name in FILES:
            atomic(HUB_DIR / name, files[name])
        systemctl("restart", "director-hub-mcp.service")
        time.sleep(2)
        check_hub()
        atomic(current, manifest["version"].encode("ascii"))
        journal.unlink()
        return {"status":"upgraded", "version": manifest["version"]}
    except BaseException:
        # Restore before allowing future updates. Retain journal if recovery fails.
        for name in FILES: atomic(HUB_DIR / name, original[name])
        systemctl("restart", "director-hub-mcp.service")
        check_hub()
        journal.unlink()
        raise
    finally:
        # Backups retained for operator audit and recovery; no recursive deletion.
        pass

def recover():
    journal = STATE / "pending.json"
    if not journal.exists(): return False
    if journal.is_symlink() or journal.stat().st_size > 1024:
        raise UpdateError("bad_recovery_journal")
    info = json.loads(journal.read_text("ascii"))
    if (type(info) is not dict or set(info) != {"backup", "from_version"}
            or type(info["backup"]) is not str
            or not re.fullmatch(r"backup-[a-f0-9]{32}", info["backup"])):
        raise UpdateError("bad_recovery_journal")
    backup = ensure_safe_directory(STATE / info["backup"])
    get_worker_state()
    for name in FILES:
        file = backup / name
        if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_FILE:
            raise UpdateError("bad_recovery_backup")
        atomic(HUB_DIR / name, file.read_bytes())
    systemctl("restart", "director-hub-mcp.service")
    check_hub()
    atomic(STATE / "installed-version.txt", info["from_version"].encode("ascii"))
    journal.unlink()
    return True

def run_once(*, channel=None, download=None, public=None):
    recover()
    if public is None:
        if PUBLIC.is_symlink() or not PUBLIC.is_file() or PUBLIC.stat().st_size != 64:
            raise UpdateError("hub_trust_key_unconfigured")
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
    asset = "ue-hub-v" + payload["version"] + ".zip"
    path = RELEASE_URL + "ue-hub-v" + payload["version"] + "/" + asset
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
