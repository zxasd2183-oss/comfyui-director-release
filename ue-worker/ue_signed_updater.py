"""Director UE privileged *pull-only* signed release updater.

Designed to run as SYSTEM via a dedicated five-minute Windows scheduled task.
No listener, no command arguments, no remote PowerShell, no private signing key
on Windows. The only writable application files are a fixed set of UE Worker
Python scripts under the known ProgramData directory.

Requires a separately provisioned, administrator-pinned Ed25519 public key.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
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
CHANNEL_URL = (
    "https://raw.githubusercontent.com/" + REPO + "/ue-worker-updates/channel.json"
)
RELEASE_BASE = "https://github.com/" + REPO + "/releases/download/"
FORMAT = "director-ue-signed-update-v1"
FILES = (
    "agent.py", "ue_jobs.py", "ue_previs.py", "ue_process.py",
    "ue_logs.py", "unreal_build_episode.py", "unreal_build_stage.py",
    "unreal_create_previs_preset.py",
)
MAX_ARCHIVE = 2 * 1024 * 1024
MAX_MEMBER = 400 * 1024
MAX_MANIFEST = 4096
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
ALLOWED_HOSTS = frozenset((
    "github.com", "release-assets.githubusercontent.com",
    "objects.githubusercontent.com", "raw.githubusercontent.com",
))
MANIFEST_KEYS = {"format", "version", "archive_sha256", "archive_size"}


class UpdateError(RuntimeError):
    pass


def canonical(obj):
    return json.dumps(
        obj, separators=(",", ":"), sort_keys=True, ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise UpdateError("duplicate_manifest_key")
        result[key] = value
    return result


def version_tuple(text):
    if type(text) is not str or not SEMVER.fullmatch(text):
        raise UpdateError("invalid_release_version")
    parts = tuple(int(segment) for segment in text.split("."))
    if max(parts) > 99999:
        raise UpdateError("unbounded_release_version")
    return parts


def verify_manifest(raw, public_key_hex):
    if len(raw) > MAX_MANIFEST:
        raise UpdateError("manifest_too_large")
    try:
        doc = json.loads(raw, object_pairs_hook=unique_object)
    except (UnicodeError, ValueError) as exc:
        raise UpdateError("invalid_release_manifest") from exc
    if type(doc) is not dict or set(doc) != MANIFEST_KEYS | {"signature"}:
        raise UpdateError("unexpected_release_manifest_fields")
    payload = {k: doc[k] for k in MANIFEST_KEYS}
    if doc["format"] != FORMAT:
        raise UpdateError("unexpected_release_format")
    version_tuple(doc["version"])
    if type(doc["archive_sha256"]) is not str or not HEX64.fullmatch(doc["archive_sha256"]):
        raise UpdateError("invalid_archive_digest")
    if type(doc["archive_size"]) is not int or not 0 < doc["archive_size"] <= MAX_ARCHIVE:
        raise UpdateError("invalid_archive_size")
    if (type(public_key_hex) is not str or not HEX64.fullmatch(public_key_hex) or
            type(doc["signature"]) is not str or
            not re.fullmatch(r"[0-9a-f]{128}", doc["signature"])):
        raise UpdateError("invalid_release_signature_format")
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        key.verify(bytes.fromhex(doc["signature"]), canonical(payload))
    except (ValueError, InvalidSignature) as exc:
        raise UpdateError("release_signature_verification_failed") from exc
    return payload


def archive_url(version):
    version_tuple(version)
    name = "ue-worker-v" + version + ".zip"
    return RELEASE_BASE + "ue-worker-v" + version + "/" + name


class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise UpdateError("untrusted_release_redirect")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), RestrictedRedirect()
)


def fetch_bytes(url, maximum=MAX_ARCHIVE):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise UpdateError("untrusted_release_origin")
    request = urllib.request.Request(url, headers={
        "User-Agent": "DirectorUE-SignedUpdater/1",
        "Accept-Encoding": "identity",
    })
    with OPENER.open(request, timeout=25) as response:
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != "https" or final.hostname not in ALLOWED_HOSTS:
            raise UpdateError("untrusted_final_release_origin")
        raw = response.read(maximum + 1)
    if len(raw) > maximum:
        raise UpdateError("release_size_limit_exceeded")
    return raw


def verified_files(blob, manifest):
    if len(blob) != manifest["archive_size"]:
        raise UpdateError("release_archive_length_mismatch")
    if hashlib.sha256(blob).hexdigest() != manifest["archive_sha256"]:
        raise UpdateError("release_archive_hash_mismatch")
    result = {}
    try:
        with zipfile.ZipFile(io.BytesIO(blob), "r") as archive:
            listed = archive.infolist()
            if {entry.filename for entry in listed} != set(FILES) or len(listed) != len(FILES):
                raise UpdateError("release_archive_allowlist_mismatch")
            for entry in listed:
                mode = (entry.external_attr >> 16) & 0xF000
                if (entry.is_dir() or entry.file_size > MAX_MEMBER or
                        mode == 0xA000 or entry.flag_bits & 0x1):
                    raise UpdateError("unsafe_release_archive_entry")
                data = archive.read(entry)
                if len(data) != entry.file_size:
                    raise UpdateError("release_member_size_mismatch")
                compile(data, entry.filename, "exec", dont_inherit=True)
                result[entry.filename] = data
    except UpdateError:
        raise
    except (zipfile.BadZipFile, RuntimeError, SyntaxError, UnicodeError, OSError) as exc:
        raise UpdateError("release_archive_invalid") from exc
    agent = result["agent.py"].decode("utf-8")
    expected = '"worker_version": "' + manifest["version"] + '"'
    if agent.count(expected) != 1:
        raise UpdateError("release_worker_version_mismatch")
    return result


def check_no_running_ue_commandlet():
    """Fail closed before changing any code; static trusted PS query only."""
    script = (
        "$ErrorActionPreference='Stop'; try { "
        "$p=@(Get-CimInstance -ClassName Win32_Process | Where-Object { "
        "$_.Name -eq 'UnrealEditor-Cmd.exe' }); "
        "if($p.Count -gt 0){exit 23}; exit 0 "
        "} catch {exit 24}"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-Command", script],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=20, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdateError("ue_process_safety_check_failed") from exc
    if result.returncode == 23:
        raise UpdateError("ue_render_in_progress")
    if result.returncode != 0:
        raise UpdateError("ue_process_safety_check_failed")


def atomic_write(path, content):
    if path.is_symlink():
        raise UpdateError("updater_state_symlink")
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".pending")
    with tmp.open("xb") as stream:
        stream.write(content)
    os.replace(tmp, path)


def owned_replace(code_dir, name, content):
    """New files inherit the existing worker-readable ACL from code_dir."""
    target = code_dir / name
    if target.is_symlink():
        raise UpdateError("worker_code_symlink")
    temp = code_dir / ("." + name + "." + uuid.uuid4().hex + ".pending")
    with temp.open("xb") as stream:
        stream.write(content)
    os.replace(temp, target)


def invoke_task(verb):
    task = "Director-UE-Worker-V02"
    try:
        process = subprocess.run(
            ["schtasks.exe", verb, "/TN", task],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=20, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdateError("worker_task_control_failed") from exc
    if process.returncode != 0:
        raise UpdateError("worker_task_control_failed")


def worker_status(root):
    token_file = root / "worker.token"
    if token_file.is_symlink() or not token_file.is_file():
        raise UpdateError("worker_token_missing")
    token = token_file.read_text("ascii").strip()
    if not HEX64.fullmatch(token):
        raise UpdateError("worker_token_invalid")
    request = urllib.request.Request(
        "http://127.0.0.1:19010/v1/status",
        headers={"Authorization": "Bearer " + token},
    )
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
        request, timeout=3
    ) as response:
        data = json.load(response)
    if not isinstance(data, dict) or not data.get("ok"):
        raise UpdateError("worker_status_invalid")
    return data


def worker_reaches_version(root, version, attempts=20):
    for _ in range(attempts):
        try:
            if worker_status(root).get("worker_version") == version:
                return True
        except (OSError, ValueError, urllib.error.URLError):
            pass
        time.sleep(2)
    return False


def recover_interrupted_update(root, state):
    journal = state / "pending.json"
    if not journal.exists():
        return False
    info = json.loads(journal.read_text("utf-8"))
    if type(info) is not dict or set(info) != {"backup", "from_version"}:
        raise UpdateError("invalid_updater_recovery_journal")
    backup = state / info["backup"]
    if (not re.fullmatch(r"backup-[0-9a-f]{32}", info["backup"]) or
            backup.is_symlink() or not backup.is_dir()):
        raise UpdateError("updater_backup_missing")
    check_no_running_ue_commandlet()
    invoke_task("/End")
    for filename in FILES:
        src = backup / filename
        if not src.is_file() or src.is_symlink():
            raise UpdateError("updater_backup_incomplete")
        owned_replace(root, filename, src.read_bytes())
    invoke_task("/Run")
    if not worker_reaches_version(root, info["from_version"]):
        raise UpdateError("updater_recovery_health_failed")
    atomic_write(state / "installed-version.txt", info["from_version"].encode("ascii"))
    journal.unlink()
    shutil.rmtree(backup)
    return True


def apply_update(code_dir, state, payload, files):
    """Fail-closed upgrade with durable rollback journal and health assertion."""
    current_file = state / "installed-version.txt"
    if not current_file.is_file() or current_file.is_symlink():
        raise UpdateError("installed_version_not_initialized")
    current = current_file.read_text("ascii").strip()
    target = payload["version"]
    if version_tuple(target) <= version_tuple(current):
        return {"status": "already_current", "version": current}
    status = worker_status(code_dir)
    if status.get("worker_version") != current:
        raise UpdateError("worker_version_drift")
    if status.get("active_job_id") is not None:
        raise UpdateError("ue_worker_job_in_progress")
    check_no_running_ue_commandlet()
    if (state / "pending.json").exists():
        raise UpdateError("unrecovered_previous_update")
    backup_name = "backup-" + uuid.uuid4().hex
    backup = state / backup_name
    backup.mkdir()
    for filename in FILES:
        src = code_dir / filename
        if not src.is_file() or src.is_symlink() or src.stat().st_size > MAX_MEMBER:
            raise UpdateError("existing_worker_files_invalid")
        (backup / filename).write_bytes(src.read_bytes())
    atomic_write(
        state / "pending.json",
        canonical({"backup": backup_name, "from_version": current}),
    )
    try:
        # The dedicated Worker task is the only task affected.
        invoke_task("/End")
        for filename in FILES:
            owned_replace(code_dir, filename, files[filename])
        invoke_task("/Run")
        if not worker_reaches_version(code_dir, target):
            raise UpdateError("new_worker_health_failed")
        atomic_write(current_file, target.encode("ascii"))
        (state / "pending.json").unlink()
        shutil.rmtree(backup)
        return {"status": "upgraded", "version": target}
    except BaseException:
        # If rollback cannot verify health, retain the journal for next run.
        recover_interrupted_update(code_dir, state)
        raise


def run_once(code_dir, state, public_key_hex, *, channel=None, download=None):
    channel = channel or (lambda: fetch_bytes(CHANNEL_URL, MAX_MANIFEST))
    download = download or (lambda version: fetch_bytes(archive_url(version)))
    recovered = recover_interrupted_update(code_dir, state)
    try:
        raw = channel()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"status": "no_signed_channel", "recovered": recovered}
        raise
    manifest = verify_manifest(raw, public_key_hex)
    current = (state / "installed-version.txt").read_text("ascii").strip()
    if version_tuple(manifest["version"]) <= version_tuple(current):
        return {"status": "already_current", "version": current,
                "recovered": recovered}
    files = verified_files(download(manifest["version"]), manifest)
    result = apply_update(code_dir, state, manifest, files)
    result["recovered"] = recovered
    return result


def main():
    if os.name != "nt":
        raise SystemExit("Windows only")
    import ctypes
    if not ctypes.windll.shell32.IsUserAnAdmin():
        raise SystemExit("Administrator or SYSTEM context required")
    program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    state = program_data / "DirectorUEUpdater"
    code = program_data / "DirectorUEWorker"
    public_file = state / "trusted-public-key.hex"
    if not public_file.is_file() or public_file.is_symlink():
        raise SystemExit("Updater public key not provisioned")
    public = public_file.read_text("ascii").strip()
    try:
        result = run_once(code, state, public)
        # No secrets or token are present in the status record.
        atomic_write(state / "last-result.json", canonical(result))
        atomic_write(code / "signed-update-status.json", canonical(result))
    except Exception as exc:
        summary = {
            "status": "failed", "reason": type(exc).__name__,
            "code": str(exc)[:100] if isinstance(exc, UpdateError)
                    else "unexpected_updater_failure",
        }
        atomic_write(state / "last-result.json", canonical(summary))
        atomic_write(code / "signed-update-status.json", canonical(summary))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
