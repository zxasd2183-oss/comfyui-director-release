"""Director UE Windows worker: loopback-only, token-authenticated and allowlisted.

No general shell, Python execution, package installation or file upload endpoint.
The SSH -R tunnel is the only intended path from VPS to this process.
"""
from __future__ import annotations

import csv
import hashlib
import time
import urllib.error
import urllib.request
import hmac
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ue_jobs import JobManager, JobError, inspect_episode_inputs
from ue_logs import log_tail
from ue_preview_images import get_preview_png, get_cast_review_png

HOST = "127.0.0.1"
PORT = 19010
MAX_BODY = 24576
ACTION_LOCK = threading.Lock()
NODE_ID = "ue-worker-01"
JOB_MANAGER = None


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def read_secret(path=None):
    raw_path = (path or os.getenv("DIRECTOR_UE_TOKEN_FILE") or
                str(Path(os.getenv("PROGRAMDATA", r"C:\\ProgramData")) /
                    "DirectorUEWorker" / "worker.token"))
    f = Path(raw_path)
    if f.is_symlink() or not f.is_file() or f.stat().st_size > 128:
        raise RuntimeError("invalid token file")
    token = f.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        raise RuntimeError("token must be 64 lowercase hex characters")
    return token


def workspace_root():
    raw = os.environ.get("DIRECTOR_UE_WORKSPACE", r"C:\DirectorVirtualStudio")
    root = Path(raw)
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("workspace must be an absolute, normalized path")
    return root


def find_ue_installations():
    """Discover editor binaries; never download, install, or run UE."""
    candidates = []
    for env in ("UE_EDITOR_PATH",):
        path = os.environ.get(env)
        if path:
            candidates.append(Path(path))
    for base in (os.environ.get("PROGRAMFILES", r"C:\Program Files"),):
        epic = Path(base) / "Epic Games"
        if epic.is_dir():
            for entry in sorted(epic.iterdir()):
                if entry.is_dir() and entry.name.startswith("UE_"):
                    candidates.append(entry / "Engine" / "Binaries" / "Win64" /
                                      "UnrealEditor.exe")
    found = []
    for candidate in candidates:
        try:
            if candidate.is_file():
                found.append({"editor_path": str(candidate.resolve())})
        except (OSError, ValueError):
            continue
    return found[:16]



def hero_project_manifest():
    """A fixed, separate UE 5.8 project; never alter the episode project."""
    return {
        "FileVersion": 3,
        "EngineAssociation": "5.8",
        "Category": "Film & Television",
        "Description": "WaitingOffice EP01 CHAR_GPT MetaHuman candidate only",
        "Plugins": [
            {"Name": "PythonScriptPlugin", "Enabled": True},
            {"Name": "EditorScriptingUtilities", "Enabled": True},
            {"Name": "MetaHumanCharacter", "Enabled": True},
        ],
    }


def hero_project_file():
    return (workspace_root() / "HeroProjects" / "CHAR_GPT" /
            "DirectorHeroGPT.uproject")


def hero_project_state():
    candidate = hero_project_file()
    try:
        if candidate.is_symlink() or getattr(candidate, "is_junction", lambda:False)():
            return "unsafe_project_link"
        if not candidate.exists():
            return "missing"
        if not candidate.is_file() or candidate.stat().st_size > 65536:
            return "unsupported_project_file"
        content = json.loads(candidate.read_text(encoding="utf-8"))
        return "prepared" if content == hero_project_manifest() else "foreign_project"
    except (OSError, ValueError, TypeError, UnicodeError):
        return "unreadable"


def prepare_hero_metahuman_project():
    """Create EXACTLY one isolated project with MetaHuman enabled, no UE launch.

    This is a project *configuration* receipt, not evidence of Core Data,
    Epic authorization, generated facial rigs, or director-approved models.
    """
    if JOB_MANAGER is not None:
        with JOB_MANAGER.lock:
            if JOB_MANAGER.active is not None:
                raise ValueError("hero_project_busy")
    found = False
    for item in find_ue_installations()[:16]:
        try:
            exe = Path(item["editor_path"])
            descriptor = (exe.parents[2] / "Plugins" / "MetaHuman" /
                          "MetaHumanCharacter" / "MetaHumanCharacter.uplugin")
            if (exe.name.lower() == "unrealeditor.exe"
                    and descriptor.is_file() and not descriptor.is_symlink()):
                found = True
                break
        except (OSError, IndexError, KeyError, TypeError, ValueError):
            continue
    if not found:
        raise ValueError("metahuman_plugin_not_installed")
    root = workspace_root()
    target = hero_project_file()
    for folder in (root, root / "HeroProjects", target.parent):
        if folder.is_symlink() or getattr(folder, "is_junction", lambda:False)():
            raise ValueError("unsafe_hero_project_directory")
        if folder.exists() and not folder.is_dir():
            raise ValueError("unsafe_hero_project_directory")
    existing = hero_project_state()
    if existing not in ("missing", "prepared"):
        raise ValueError("hero_project_collision_" + existing)
    if existing == "prepared":
        return {"ok":True,"created":False,"state":"prepared",
                "relative_project":"HeroProjects/CHAR_GPT/DirectorHeroGPT.uproject",
                "source_episode_untouched":True,"rendered_character":False}
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as output:
        json.dump(hero_project_manifest(), output, ensure_ascii=False, indent=2)
        output.write("\n")
    for leaf in ("Content", "Config"):
        folder = target.parent / leaf
        if folder.is_symlink() or getattr(folder, "is_junction", lambda:False)():
            raise ValueError("unsafe_hero_project_directory")
        folder.mkdir(exist_ok=True)
    return {"ok":True,"created":True,"state":hero_project_state(),
            "relative_project":"HeroProjects/CHAR_GPT/DirectorHeroGPT.uproject",
            "source_episode_untouched":True,"rendered_character":False}


def hero_character_readiness():
    """Bounded local preflight for ONE EP01 hero; no installs or mutations.

    Presence of a plugin descriptor is NOT proof of MetaHuman Core Data,
    Epic login, cloud auto-rig service availability, or a finished model.
    """
    installations = find_ue_installations()
    plugin_detected = False
    examples_detected = False
    for item in installations[:16]:
        try:
            exe = Path(item["editor_path"])
            if exe.name.lower() != "unrealeditor.exe":
                continue
            engine = exe.parents[2]
            descriptor = (engine / "Plugins" / "MetaHuman" /
                          "MetaHumanCharacter" / "MetaHumanCharacter.uplugin")
            examples = (engine / "Plugins" / "MetaHuman" /
                        "MetaHumanCharacter" / "Content" / "Python" /
                        "examples" / "example_create_asset.py")
            if descriptor.is_file() and not descriptor.is_symlink():
                plugin_detected = True
            if examples.is_file() and not examples.is_symlink():
                examples_detected = True
        except (IndexError, KeyError, TypeError, OSError, ValueError):
            continue

    project_state = "missing"
    enabled = False
    try:
        project = workspace_root() / "DirectorVirtualStudio.uproject"
        if project.is_symlink():
            project_state = "unsafe_project_symlink"
        elif project.is_file() and project.stat().st_size <= 65536:
            data = json.loads(project.read_text(encoding="utf-8"))
            if type(data) is dict and type(data.get("Plugins")) is list:
                enabled = any(
                    type(p) is dict and
                    p.get("Name") in ("MetaHumanCharacter", "MetaHumanCreator") and
                    p.get("Enabled") is True for p in data["Plugins"]
                )
                project_state = "valid"
            else:
                project_state = "invalid_project_manifest"
        elif project.exists():
            project_state = "unsupported_project_manifest"
    except (OSError, UnicodeError, ValueError, TypeError):
        project_state = "unreadable_project_manifest"

    return {
        "target": "WaitingOffice/EP01/CHAR_GPT",
        "engine_detected": bool(installations),
        "metahuman_character_plugin_descriptor_found": plugin_detected,
        "metahuman_python_examples_found": examples_detected,
        "project_state": project_state,
        "metahuman_project_plugin_enabled": enabled,
        "isolated_hero_project_state": hero_project_state(),
        "isolated_hero_project_enabled": hero_project_state() == "prepared",
        "creator_core_data": "not_verified_by_read_only_preflight",
        "epic_cloud_auth": "not_verified_by_read_only_preflight",
        "full_rig_and_groom": "not_created",
        "cinematic_character_master": "not_approved",
        "character_production_ready": False,
        "mutations_performed": False,
    }


def gpu_summary():
    executable = shutil.which("nvidia-smi")
    if not executable:
        return {"available": False}
    try:
        p = subprocess.run(
            [executable, "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if p.returncode != 0:
            return {"available": False}
        # Status data only. Do not return arbitrary command output.
        records = []
        for line in p.stdout.splitlines()[:8]:
            fields = [item.strip()[:120] for item in line.split(",")]
            if len(fields) == 3:
                records.append(dict(zip(("name", "vram_mib", "driver"), fields)))
        return {"available": bool(records), "devices": records}
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False}


def signed_update_status():
    """Read only the SYSTEM updater's small non-secret status receipt."""
    source = Path(__file__).resolve().parent / "signed-update-status.json"
    try:
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 2048:
            return {"status": "not_configured"}
        item = json.loads(source.read_text(encoding="utf-8"))
        if type(item) is not dict:
            return {"status": "invalid_receipt"}
        # Never forward arbitrary strings or raw updater logs through MCP.
        allowed = ("status", "version", "reason", "code", "recovered",
                   "request_id", "checked_at")
        return {name: item[name] for name in allowed
                if name in item and type(item[name]) in (str, bool)}
    except (OSError, UnicodeError, ValueError, TypeError):
        return {"status": "invalid_receipt"}


# Only a poll trigger for the separately installed SYSTEM signed updater.
# This code never executes scripts or elevates its own access.
UPDATE_REQUEST_NAME = "signed_update_check_requested.json"


def update_request_path():
    root = workspace_root()
    folder = root / "JobStatus"
    if folder.is_symlink() or getattr(folder, "is_junction", lambda:False)():
        raise RuntimeError("update_queue_invalid")
    return folder / UPDATE_REQUEST_NAME


def pending_update_request():
    file = update_request_path()
    if not file.exists():
        return None
    if (file.is_symlink() or getattr(file, "is_junction", lambda:False)()
            or not file.is_file() or file.stat().st_size > 512):
        raise RuntimeError("update_request_invalid")
    try:
        item = json.loads(file.read_text(encoding="ascii"))
        if (type(item) is not dict or set(item) != {"request_id", "requested_at"}
                or type(item["request_id"]) is not str
                or not re.fullmatch(r"[a-f0-9]{32}", item["request_id"])
                or type(item["requested_at"]) is not str
                or len(item["requested_at"]) > 50):
            raise ValueError("invalid update request")
    except (OSError, ValueError, UnicodeError) as exc:
        raise RuntimeError("update_request_invalid") from exc
    return item


def update_status():
    status = signed_update_status()
    try:
        pending = pending_update_request()
    except (OSError, RuntimeError):
        return {"ok": False, "reason": "update_request_unavailable",
                "signed_update": status}
    return {"ok": True, "signed_update": status,
            "pending_request": pending,
            "poll_interval_seconds": 300}


def request_signed_update_check():
    # No request can start an elevated command or supply an executable.
    status = signed_update_status()
    if status.get("status") in ("not_configured", "invalid_receipt"):
        return {"ok": False, "reason": "signed_updater_not_ready"}
    folder = update_request_path().parent
    folder.mkdir(parents=True, exist_ok=True)
    # A single durable request per node, including after Worker restarts.
    with ACTION_LOCK:
        previous = pending_update_request()
        if previous is not None:
            return {"ok": True, "request_id": previous["request_id"],
                    "state": "pending_next_signed_poll", "duplicate": True}
        request = {"request_id": uuid.uuid4().hex, "requested_at": utcnow()}
        file = folder / UPDATE_REQUEST_NAME
        with file.open("x", encoding="ascii") as handle:
            json.dump(request, handle, separators=(",", ":"))
        return {"ok": True, "request_id": request["request_id"],
                "state": "pending_next_signed_poll", "duplicate": False}



# The GUI companion runs only when the human launches DesktopShare.ps1
# inside their own logged-in RDP session. Never capture Session 0.
DESKTOP_PIN = None
DESKTOP_PIN_EXPIRES = 0.0
DESKTOP_LOCK = threading.RLock()
DESKTOP_ORIGIN = "http://127.0.0.1:19017"
DESKTOP_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _desktop_http(path, code, max_bytes=1024):
    if path not in ("/v1/status", "/v1/frame"):
        raise ValueError("desktop_route_not_allowed")
    request = urllib.request.Request(
        DESKTOP_ORIGIN + path, method="GET",
        headers={"X-Director-Desktop-Code":code,"Accept":"image/jpeg,application/json"})
    try:
        with DESKTOP_HTTP.open(request, timeout=6) as response:
            if response.geturl()!=DESKTOP_ORIGIN+path:
                raise ValueError("desktop_redirect_denied")
            data=response.read(max_bytes+1)
            if len(data)>max_bytes:
                raise ValueError("desktop_response_too_large")
            return response.headers.get("Content-Type",""),data
    except (OSError, urllib.error.URLError) as exc:
        raise ValueError("desktop_companion_unavailable") from exc


def pair_desktop(code):
    global DESKTOP_PIN,DESKTOP_PIN_EXPIRES
    if type(code) is not str or not re.fullmatch(r"[0-9a-f]{32}",code):
        return {"ok":False,"reason":"desktop_pair_code_invalid"}
    try:
        kind,raw=_desktop_http("/v1/status",code)
        if not kind.startswith("application/json"):
            raise ValueError("desktop_pair_protocol_invalid")
        body=json.loads(raw)
        if (type(body) is not dict or body.get("ok") is not True or
                body.get("sharing") is not True):
            raise ValueError("desktop_not_sharing")
        with DESKTOP_LOCK:
            DESKTOP_PIN=code
            DESKTOP_PIN_EXPIRES=time.monotonic()+590
        return {"ok":True,"paired":True,"sharing":True,
                "seconds_remaining_max":590,"control_enabled":False}
    except (ValueError,TypeError,UnicodeError):
        return {"ok":False,"reason":"desktop_pair_unavailable_or_not_sharing"}


def _desktop_pair_code():
    with DESKTOP_LOCK:
        if DESKTOP_PIN is None or time.monotonic()>=DESKTOP_PIN_EXPIRES:
            return None
        return DESKTOP_PIN


def desktop_status():
    code=_desktop_pair_code()
    if code is None:
        return {"ok":True,"paired":False,"sharing":False,"control_enabled":False}
    try:
        kind,raw=_desktop_http("/v1/status",code)
        body=json.loads(raw)
        if not kind.startswith("application/json") or type(body) is not dict:
            raise ValueError("desktop_status_invalid")
        return {"ok":True,"paired":True,"sharing":body.get("ok") is True and
                body.get("sharing") is True,"control_enabled":False}
    except (OSError,ValueError,UnicodeError,TypeError):
        return {"ok":True,"paired":True,"sharing":False,"control_enabled":False}


def unpair_desktop():
    global DESKTOP_PIN,DESKTOP_PIN_EXPIRES
    with DESKTOP_LOCK:
        DESKTOP_PIN=None
        DESKTOP_PIN_EXPIRES=0.0
    return {"ok":True,"paired":False,"sharing":False,"control_enabled":False}


def desktop_frame():
    code=_desktop_pair_code()
    if code is None:
        raise ValueError("desktop_not_paired")
    try:
        kind,data=_desktop_http("/v1/frame",code,max_bytes=400000)
        if (not kind.startswith("image/jpeg") or len(data)<200 or
                not data.startswith(bytes((255,216))) or
                not data.endswith(bytes((255,217)))):
            raise ValueError("desktop_jpeg_invalid")
        return data,hashlib.sha256(data).hexdigest()
    except (OSError,ValueError,UnicodeError,TypeError) as exc:
        raise ValueError("desktop_frame_unavailable") from exc


def status():
    active_job_id = None
    if JOB_MANAGER is not None:
        with JOB_MANAGER.lock:
            active_job_id = JOB_MANAGER.active
    return {
        "active_job_id": active_job_id,
        "signed_update": signed_update_status(),
        "desktop_sharing": desktop_status(),
        "ok": True, "node_id": NODE_ID, "platform": platform.system(),
        "hostname": platform.node()[:128], "timestamp": utcnow(),
        "python": platform.python_version(),
        "gpu": gpu_summary(), "ue": {"installations": find_ue_installations()},
        "workspace_exists": workspace_root().is_dir(),
        "hero_character_readiness": hero_character_readiness(),
        "control_mode": "allowlisted_only",
        "worker_version": "2.1.0",
    }



# An explicit allowlist of process names that can modify or compile UE assets.
# This inventory must be authoritative for the *entire* Windows host, not
# limited to jobs owned by this Worker. It is used only to deny unsafe stops.
UE_POWER_BUSY_IMAGES = frozenset({
    "unrealeditor.exe", "unrealeditor-cmd.exe", "unrealbuildtool.exe",
    "shadercompileworker.exe", "unreallightmass.exe",
})


def count_windows_ue_processes():
    """Read Windows tasklist via fixed system executable, no injected commands.

    Failure to enumerate *all* host processes is a stop blocker. The result
    is only a count; no process command lines or PIDs leave the Worker.
    """
    executable = Path(r"C:\Windows\System32\tasklist.exe")
    try:
        result = subprocess.run(
            [str(executable), "/FO", "CSV", "/NH"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            errors="replace", timeout=15, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if (result.returncode != 0 or not result.stdout
                or len(result.stdout) > 2 * 1024 * 1024):
            raise RuntimeError("ue_process_inventory_unavailable")
        rows = csv.reader(io.StringIO(result.stdout))
        count, total = 0, 0
        for row in rows:
            total += 1
            if (len(row) != 5 or not row[0].strip()
                    or not row[1].strip().isdigit()):
                raise RuntimeError("ue_process_inventory_invalid")
            if row[0].strip().casefold() in UE_POWER_BUSY_IMAGES:
                count += 1
        if total == 0:
            raise RuntimeError("ue_process_inventory_empty")
        return count
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired,
            csv.Error) as exc:
        raise RuntimeError("ue_process_inventory_unavailable") from exc


def ue_power_readiness():
    """Authenticated, read-only shutdown guard for the one RTX4090 UE node.

    Never starts/stops power, never inspects ComfyUI, and never treats an
    unreachable or incomplete process inventory as permission to stop.
    """
    base = {
        "kind": "director_ue_windows_power_readiness_v1",
        "node_id": NODE_ID, "platform": platform.system(),
        "checked_at": utcnow(),
        "ok": False, "verified": False, "safe_to_stop": False,
        "active_job_id": None, "unreal_process_count": None,
        "process_inventory_verified": False,
    }
    if platform.system() != "Windows" or JOB_MANAGER is None:
        return {**base, "reason": "ue_power_worker_not_ready"}
    try:
        processes = count_windows_ue_processes()
        with JOB_MANAGER.lock:
            active = JOB_MANAGER.active
        if active is not None and (
                type(active) is not str or
                not re.fullmatch(r"[a-f0-9]{32}", active)):
            return {**base, "reason": "ue_job_state_invalid"}
        safe = processes == 0 and active is None
        return {**base, "ok": True, "verified": True,
                "process_inventory_verified": True,
                "unreal_process_count": processes,
                "active_job_id": active, "safe_to_stop": safe}
    except (OSError, RuntimeError, ValueError, TypeError):
        return {**base, "reason": "ue_process_inventory_unavailable"}


def capabilities():
    return {
        "ok": True, "node_id": NODE_ID,
        "actions": ["prepare_workspace", "prepare_hero_metahuman_project"],
        "jobs": ["build_episode_timeline", "build_stage_cameras",
                 "render_previs_stills", "audit_ep01_assets",
                 "build_ep01_scene_candidates", "build_ep01_cast_blueprints",
                 "render_cast_review_stills","build_ep01_hero_metahuman_seed",
                 "audit_ep01_hero_metahuman_runtime",
                 "build_ep01_hero_amber_eyes",
                 "build_ep01_hero_face_contour",
                 "build_ep01_hero_cloud_rig"],
        "job_status_route": "/v2/jobs/<job_id>",
        "job_logs_route": "/v3/jobs/<job_id>/logs/<kind>",
        "job_cancel_route": "/v3/jobs/<job_id>/cancel",
        "preview_image_route": "/v5/jobs/<job_id>/previews/<shot_id>",
        "supports_preview_image_read": True,
        "supports_episode_assembly_inventory": True,
        "supports_ep01_native_asset_audit": True,
        "supports_ep01_scene_candidates": True,
        "supports_ep01_cast_blueprints": True,
        "supports_ep01_cast_review_stills": True,
        "supports_hero_metahuman_seed": True,
        "supports_hero_runtime_audit": True,
        "supports_hero_amber_eyes_candidate": True,
        "supports_hero_face_contour_candidate": True,
        "supports_hero_cloud_rig_candidate": True,
        "supports_ue_power_readiness": True,
        "power_readiness_route": "/v7/power/readiness",
        "cast_review_image_route": "/v11/jobs/<job_id>/cast-review/<view>",
        "signed_update_status_route": "/v4/update/status",
        "signed_update_request_route": "/v4/update/request",
        "supports_signed_update_request": True,
        "supports_job_cancel": True,
        "supports_desktop_view_only": True,
        "supports_desktop_keyboard_or_mouse": False,
        "supports_arbitrary_commands": False,
        "supports_unreal_install": False,
        "supports_rendering": False,
        "supports_previs_stills": True,
    }


def prepare_workspace():
    """Only create a fixed directory structure under configured workspace root."""
    root = workspace_root()
    subdirs = ("Characters", "Environments", "Animations", "Audio",
               "Sequences", "Cameras", "Python", "Render", "Outputs")
    root.mkdir(parents=True, exist_ok=True)
    for part in subdirs:
        (root / part).mkdir(exist_ok=True)
    return {"ok": True, "action": "prepare_workspace",
            "workspace": str(root), "directories": list(subdirs),
            "timestamp": utcnow()}


class Handler(BaseHTTPRequestHandler):
    server_version = "DirectorUEWorker/2.1.0"
    sys_version = ""

    def log_message(self, fmt, *args):
        # Never log Authorization headers or request bodies.
        sys.stderr.write(f"[{utcnow()}] {self.client_address[0]} {fmt % args}\n")

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorize(self):
        supplied = self.headers.get("Authorization", "")
        expected = "Bearer " + self.server.token
        return hmac.compare_digest(supplied.encode("utf-8", "ignore"),
                                   expected.encode("ascii"))

    def do_GET(self):
        if not self.authorize():
            self.send_json(401, {"ok": False, "reason": "unauthorized"})
        elif self.path == "/v1/status":
            self.send_json(200, status())
        elif self.path == "/v1/capabilities":
            self.send_json(200, capabilities())
        elif self.path == "/v7/power/readiness":
            readiness = ue_power_readiness()
            self.send_json(200 if readiness["ok"] else 503, readiness)
        elif self.path == "/v14/desktop/status":
            self.send_json(200,desktop_status())
        elif self.path == "/v14/desktop/frame":
            try:
                data,digest=desktop_frame()
                self.send_response(200)
                self.send_header("Content-Type","image/jpeg")
                self.send_header("X-Content-Type-Options","nosniff")
                self.send_header("Cache-Control","no-store")
                self.send_header("Content-Length",str(len(data)))
                self.send_header("X-Director-JPEG-SHA256",digest)
                self.end_headers()
                self.wfile.write(data)
            except ValueError:
                self.send_json(403,{"ok":False,"reason":"desktop_frame_unavailable"})
        elif self.path == "/v4/update/status":
            self.send_json(200, update_status())
        elif self.path == "/v6/episode/assembly-readiness":
            try:
                self.send_json(200, inspect_episode_inputs(workspace_root()))
            except (OSError, ValueError):
                self.send_json(503, {"ok": False, "reason": "episode_readiness_unavailable"})
        elif re.fullmatch(r"/v5/jobs/[a-f0-9]{32}/previews/(?:01|13|26|31)", self.path):
            parts = self.path.split("/")
            try:
                data, digest = get_preview_png(JOB_MANAGER, parts[3], parts[5])
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Disposition", "attachment")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Director-PNG-SHA256", digest)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except JobError as exc:
                self.send_json(404, {"ok": False, "reason": str(exc)})
            except OSError:
                self.send_json(500, {"ok": False, "reason": "preview_image_unavailable"})
        elif re.fullmatch(
            r"/v11/jobs/[a-f0-9]{32}/cast-review/(?:LINEUP|GPT|GEM|DS|CLA|ZERO)",
            self.path
        ):
            parts = self.path.split("/")
            try:
                data, digest = get_cast_review_png(
                    JOB_MANAGER, parts[3], parts[5])
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Disposition", "attachment")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Director-PNG-SHA256", digest)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except JobError as exc:
                self.send_json(404, {"ok": False, "reason": str(exc)})
            except OSError:
                self.send_json(500, {"ok": False,
                                     "reason": "cast_review_png_unavailable"})
        elif re.fullmatch(r"/v2/jobs/[a-f0-9]{32}", self.path):
            try:
                self.send_json(200, JOB_MANAGER.lookup(self.path.rsplit("/", 1)[-1]))
            except JobError as exc:
                self.send_json(404, {"ok": False, "reason": str(exc)})
        elif re.fullmatch(r"/v3/jobs/[a-f0-9]{32}/logs/[a-z0-9_]{1,20}", self.path):
            parts = self.path.split("/")
            try:
                self.send_json(200, log_tail(JOB_MANAGER, parts[3], parts[5]))
            except JobError as exc:
                self.send_json(404, {"ok": False, "reason": str(exc)})
            except OSError:
                self.send_json(500, {"ok": False, "reason": "job_log_unavailable"})
        else:
            self.send_json(404, {"ok": False, "reason": "not_found"})

    def do_POST(self):
        if not self.authorize():
            self.send_json(401, {"ok": False, "reason": "unauthorized"})
            return
        if self.path == "/v14/desktop/unpair":
            if (self.headers.get("Content-Length","0")!="0" or
                    self.headers.get("Transfer-Encoding")):
                self.send_json(400,{"ok":False,"reason":"invalid_request"})
            else:
                self.send_json(200,unpair_desktop())
            return
        if self.path == "/v14/desktop/pair":
            try:
                if (self.headers.get("Transfer-Encoding") or
                        not 0<int(self.headers.get("Content-Length","0"))<=128):
                    raise ValueError("invalid_length")
                item=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if type(item) is not dict or set(item)!={"code"}:
                    raise ValueError("invalid_body")
                result=pair_desktop(item["code"])
                self.send_json(200 if result["ok"] else 409,result)
            except (ValueError,TypeError,UnicodeError):
                self.send_json(400,{"ok":False,"reason":"invalid_request"})
            return
        if self.path == "/v4/update/request":
            if (self.headers.get("Content-Length", "0") != "0" or
                    self.headers.get("Transfer-Encoding")):
                self.send_json(400, {"ok": False, "reason": "invalid_request"})
                return
            try:
                result = request_signed_update_check()
                self.send_json(202 if result["ok"] else 409, result)
            except (OSError, ValueError, RuntimeError):
                self.send_json(409, {"ok": False, "reason": "update_request_unavailable"})
            return
        cancel_match = re.fullmatch(r"/v3/jobs/([a-f0-9]{32})/cancel", self.path)
        if cancel_match:
            # Cancellation is ID-bound and intentionally accepts NO body.
            if (self.headers.get("Content-Length", "0") != "0" or
                    self.headers.get("Transfer-Encoding")):
                self.send_json(400, {"ok": False, "reason": "invalid_request"})
                return
            try:
                self.send_json(202, JOB_MANAGER.cancel(cancel_match.group(1)))
            except JobError as exc:
                self.send_json(404, {"ok": False, "reason": str(exc)})
            return
        if self.path not in ("/v1/actions", "/v2/jobs"):
            self.send_json(404, {"ok": False, "reason": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            if not 0 <= length <= MAX_BODY:
                raise ValueError("invalid length")
            body = json.loads(self.rfile.read(length))
            if self.path == "/v2/jobs":
                try:
                    self.send_json(202, JOB_MANAGER.submit(body))
                except JobError as exc:
                    reason = str(exc)
                    self.send_json(409 if reason == "ue_worker_busy" else 400,
                                   {"ok": False, "reason": reason})
                return
            if type(body) is not dict or set(body) != {"action"}:
                raise ValueError("invalid fields")
            if body["action"] not in ("prepare_workspace", "prepare_hero_metahuman_project"):
                self.send_json(403, {"ok": False, "reason": "action_denied"})
                return
            if not ACTION_LOCK.acquire(blocking=False):
                self.send_json(409, {"ok": False, "reason": "busy"})
                return
            try:
                self.send_json(200, prepare_workspace() if body["action"] == "prepare_workspace"
                               else prepare_hero_metahuman_project())
            finally:
                ACTION_LOCK.release()
        except (ValueError, UnicodeError, json.JSONDecodeError):
            self.send_json(400, {"ok": False, "reason": "invalid_request"})
        except (OSError, FileExistsError):
            self.send_json(500, {"ok": False, "reason": "workspace_unavailable"})


def main():
    if platform.system() != "Windows":
        raise SystemExit("This UE worker must run on Windows")
    token = read_secret()
    global JOB_MANAGER
    JOB_MANAGER = JobManager(workspace_root)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.token = token
    print(f"{NODE_ID} listening on {HOST}:{PORT}", flush=True)
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
