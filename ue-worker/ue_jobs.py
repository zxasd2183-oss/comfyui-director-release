"""Bounded asynchronous Unreal Editor jobs from audited Studio shot plans.

The server never accepts script paths, command strings, remote URLs, arbitrary
file paths, additional command arguments, or rendering directives. Jobs execute
the reviewed bundled Unreal script in an unprivileged Windows process identity.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_SHOTS = 150
MAX_DURATION_MS = 30 * 60 * 1000
FPS_ALLOWED = frozenset({24, 25, 30})
PREVIEW_MAX_DAILY_ATTEMPTS = 2
ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,47}$")
SHOT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
PROJECT_NAME = "DirectorVirtualStudio"
KNOWN_PLUGINS = ("PythonScriptPlugin", "EditorScriptingUtilities")


class JobError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def sanitized_plan(body):
    if type(body) is not dict or set(body) != {
        "task", "project_id", "episode_id", "fps", "shots", "expected_total_ms"
    }:
        raise JobError("invalid_fields")
    if body["task"] not in (
        "build_episode_timeline", "build_stage_cameras", "render_previs_stills"
    ):
        raise JobError("task_not_allowlisted")
    project_id, episode_id = body["project_id"], body["episode_id"]
    if (type(project_id) is not str or not ID.fullmatch(project_id) or
            type(episode_id) is not str or not ID.fullmatch(episode_id)):
        raise JobError("invalid_identifiers")
    fps = body["fps"]
    if type(fps) is not int or fps not in FPS_ALLOWED:
        raise JobError("invalid_fps")
    shots = body["shots"]
    if type(shots) is not list or not 1 <= len(shots) <= MAX_SHOTS:
        raise JobError("invalid_shot_count")
    used = set()
    validated, total_ms, last_frame = [], 0, 0
    for index, shot in enumerate(shots, 1):
        if type(shot) is not dict or set(shot) != {
            "shot_id", "ordinal", "duration_ms"
        }:
            raise JobError("invalid_shot_fields")
        shot_id, ordinal, duration = (
            shot["shot_id"], shot["ordinal"], shot["duration_ms"]
        )
        if (type(shot_id) is not str or not SHOT_ID.fullmatch(shot_id) or
                shot_id in used or type(ordinal) is not int or ordinal != index or
                type(duration) is not int or not 1 <= duration <= 120_000):
            raise JobError("invalid_shot")
        used.add(shot_id)
        total_ms += duration
        if total_ms > MAX_DURATION_MS:
            raise JobError("episode_too_long")
        next_frame = (total_ms * fps + 500) // 1000
        frames = next_frame - last_frame
        if frames < 1:
            raise JobError("shot_shorter_than_one_frame")
        validated.append({"shot_id": shot_id, "frames": frames,
                          "start_frame": last_frame, "end_frame": next_frame})
        last_frame = next_frame
    if type(body["expected_total_ms"]) is not int or total_ms != body["expected_total_ms"]:
        raise JobError("timeline_total_mismatch")
    # The V0.3 stage recipe is FIXED to WaitingOffice EP01 and does not
    # modify V0.2 sequences or accept any user-authored scene/code paths.
    if body["task"] in ("build_stage_cameras", "render_previs_stills"):
        if (project_id, episode_id, fps, len(validated), total_ms) != (
            "WaitingOffice", "EP01", 24, 31, 160000
        ):
            raise JobError("previs_requires_locked_ep01")
        if [s["shot_id"] for s in validated] != [
            str(i).zfill(2) for i in range(1, 32)
        ]:
            raise JobError("previs_requires_frozen_shot_ids")
    fmt = (
        "director_ue_previs_v04" if body["task"] == "render_previs_stills"
        else "director_ue_stage_v03" if body["task"] == "build_stage_cameras"
        else "director_ue_timeline_v1"
    )
    # This is a source-of-truth manifest built from Studio's registered shots.
    return {
        "format": fmt,
        "project_id": project_id, "episode_id": episode_id, "fps": fps,
        "shots": validated, "total_frames": last_frame, "total_ms": total_ms,
    }


def ensure_project(root):
    """Creates a minimal original UE project; never overwrites an existing one."""
    root.mkdir(parents=True, exist_ok=True)
    project = root / (PROJECT_NAME + ".uproject")
    expected = {
        "FileVersion": 3,
        "EngineAssociation": "5.8",
        "Category": "Film & Television",
        "Description": "Director UE original automated production project",
        "Plugins": [{"Name": name, "Enabled": True} for name in KNOWN_PLUGINS],
    }
    render_expected = dict(expected)
    render_expected["Plugins"] = expected["Plugins"] + [
        {"Name": "MovieRenderPipeline", "Enabled": True}
    ]
    if project.exists():
        if project.is_symlink():
            raise JobError("project_is_symlink")
        try:
            actual = json.loads(project.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            raise JobError("project_exists_not_managed_by_director") from None
        if actual not in (expected, render_expected):
            raise JobError("project_exists_not_managed_by_director")
    else:
        project.write_text(
            json.dumps(expected, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    (root / "Content").mkdir(exist_ok=True)
    (root / "Config").mkdir(exist_ok=True)
    return project


def find_editor_cmd():
    explicit = os.getenv("DIRECTOR_UE_EDITOR_CMD")
    if explicit:
        candidate = Path(explicit)
    else:
        candidate = (Path(os.getenv("PROGRAMFILES", r"C:\Program Files")) /
                     "Epic Games" / "UE_5.8" / "Engine" / "Binaries" /
                     "Win64" / "UnrealEditor-Cmd.exe")
    if not candidate.is_file() or candidate.name.lower() != "unrealeditor-cmd.exe":
        raise JobError("unreal_editor_cmd_not_found")
    return candidate


def run_commandlet(spec, root, work, timeout=900):
    # UE must NOT run as LocalSystem/admin: local UE plugins and project assets
    # are executable code and require an unprivileged service account.
    if os.name == "nt":
        username = os.getenv("USERNAME", "").lower()
        if username in {"system", "administrator"} or not username:
            raise JobError("ue_executor_must_be_non_admin")
    editor = find_editor_cmd()
    script_name = ("unreal_build_stage.py"
                   if spec["format"] == "director_ue_stage_v03"
                   else "unreal_build_episode.py")
    script = Path(__file__).resolve().with_name(script_name)
    if not script.is_file() or script.is_symlink():
        raise JobError("trusted_unreal_script_missing")
    project = ensure_project(root)
    work.mkdir(parents=True, exist_ok=False)
    spec_file, result_file = work / "plan.json", work / "result.json"
    spec_file.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    env = os.environ.copy()
    env["DIRECTOR_UE_SPEC_FILE"] = str(spec_file)
    env["DIRECTOR_UE_RESULT_FILE"] = str(result_file)
    command = [
        str(editor), str(project), "-run=pythonscript",
        "-script=" + str(script), "-unattended", "-nop4", "-nosplash",
        "-NoSound", "-log",
    ]
    try:
        with (work / "unreal.log").open("wb") as logfile:
            result = subprocess.run(
                command, env=env, cwd=str(root),
                stdout=logfile, stderr=subprocess.STDOUT, timeout=timeout,
                check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    except subprocess.TimeoutExpired:
        raise JobError("unreal_commandlet_timeout") from None
    if not result_file.exists():
        raise JobError("unreal_missing_result")
    data = json.loads(result_file.read_text(encoding="utf-8"))
    if type(data) is not dict or type(data.get("ok")) is not bool:
        raise JobError("invalid_unreal_result")
    if result.returncode != 0:
        raise JobError("unreal_commandlet_failed")
    if not data["ok"]:
        raise JobError("unreal_script_failed")
    if (data.get("shot_count") != len(spec["shots"]) or
            data.get("total_frames") != spec["total_frames"]):
        raise JobError("unreal_timeline_mismatch")
    receipt = {
        "master": data["master"],
        "shot_count": data["shot_count"],
        "total_frames": data["total_frames"], "fps": spec["fps"],
        "render_ready": False,
    }
    if spec["format"] == "director_ue_stage_v03":
        if (data.get("stage_map") !=
                "/Game/Director/V03/Maps/WaitingOffice_EP01_Stage" or
                data.get("camera_count") != len(spec["shots"]) or
                data.get("proxy_actor_count") != 5 or
                data.get("metahuman_bound") is not False):
            raise JobError("unreal_stage_result_mismatch")
        receipt.update({
            "stage_map": data["stage_map"],
            "camera_count": data["camera_count"],
            "proxy_actor_count": data["proxy_actor_count"],
            "metahuman_bound": False,
            "audio_bound": False,
        })
    return receipt


class JobManager:
    def __init__(self, root_factory, runner=run_commandlet):
        self.root_factory = root_factory
        self.runner = runner
        self.lock = threading.Lock()
        self.jobs = {}
        self.active = None
        self._restore()

    def _state_dir(self):
        return self.root_factory() / "JobStatus"

    def _save(self, entry):
        folder = self._state_dir()
        folder.mkdir(parents=True, exist_ok=True)
        job_id = entry["job_id"]
        # Job IDs are generated random hex, never caller-selected file paths.
        tmp = folder / (job_id + ".pending")
        target = folder / (job_id + ".json")
        tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
        tmp.replace(target)

    def _restore(self):
        folder = self._state_dir()
        if not folder.is_dir():
            return
        for item in sorted(folder.glob("*.json"),
                           key=lambda path: path.stat().st_mtime,
                           reverse=True)[:64]:
            if not re.fullmatch(r"[a-f0-9]{32}\.json", item.name):
                continue
            try:
                entry = json.loads(item.read_text(encoding="utf-8"))
                if (type(entry) is not dict or
                        entry.get("job_id") != item.stem or
                        entry.get("state") not in {
                            "queued", "running", "succeeded", "failed"
                        }):
                    continue
                if entry["state"] in {"queued", "running"}:
                    entry["state"] = "failed"
                    entry["reason"] = "worker_restarted_job_result_unconfirmed"
                    entry["finished_at"] = now()
                    self._save(entry)
                self.jobs[item.stem] = entry
            except (OSError, ValueError, TypeError):
                continue

    def _reserve_previs_attempt(self, job_id):
        """Durable rate cap: at most 2 V04 previews in any rolling 24 hours.

        Reservation is written before a new GPU task can start, and a failed
        task still counts against the budget (no retry storms). Budget file
        survives process restart independently of the 64-job status cache.
        """
        root = self._state_dir()
        root.mkdir(parents=True, exist_ok=True)
        budget = root / "preview_budget_v04.json"
        if budget.is_symlink():
            raise JobError("preview_budget_store_invalid")
        stamp = datetime.now(timezone.utc)
        attempts = []
        if budget.exists():
            try:
                blob = json.loads(budget.read_text(encoding="utf-8"))
                if not isinstance(blob, dict) or type(blob.get("attempts")) is not list:
                    raise ValueError("malformed preview budget")
                for entry in blob["attempts"]:
                    if (type(entry) is not dict or
                            not re.fullmatch("[a-f0-9]{32}", entry["job_id"])):
                        raise ValueError("malformed preview budget record")
                    instant = datetime.fromisoformat(entry["at"])
                    if instant.tzinfo is None:
                        raise ValueError("naive preview timestamp")
                    if instant > stamp + timedelta(minutes=2):
                        raise ValueError("future preview timestamp")
                    if stamp - instant < timedelta(hours=24):
                        attempts.append(entry)
            except (KeyError, TypeError, ValueError, OSError):
                raise JobError("preview_budget_store_invalid") from None
        if len(attempts) >= PREVIEW_MAX_DAILY_ATTEMPTS:
            raise JobError("preview_daily_limit_reached")
        attempts.append({"job_id": job_id, "at": stamp.isoformat()})
        temp = root / ("preview_budget_" + job_id + ".pending")
        temp.write_text(json.dumps({"attempts": attempts}, ensure_ascii=False),
                        encoding="utf-8")
        temp.replace(budget)

    def submit(self, body):
        spec = sanitized_plan(body)
        with self.lock:
            if self.active is not None:
                raise JobError("ue_worker_busy")
            job_id = uuid.uuid4().hex
            if spec["format"] == "director_ue_previs_v04":
                self._reserve_previs_attempt(job_id)
            entry = {
                "ok": True, "job_id": job_id,
                "state": "queued", "task": body["task"],
                "project_id": spec["project_id"],
                "episode_id": spec["episode_id"],
                "shot_count": len(spec["shots"]),
                "total_frames": spec["total_frames"],
                "created_at": now(),
            }
            self._save(entry)
            self.jobs[job_id] = entry
            if len(self.jobs) > 64:
                oldest = next(iter(self.jobs))
                if oldest != job_id:
                    del self.jobs[oldest]
            self.active = job_id
            thread = threading.Thread(
                target=self._execute, args=(job_id, spec),
                name="DirectorUEJob-" + job_id[:8], daemon=True,
            )
            thread.start()
            return dict(entry)

    def _execute(self, job_id, spec):
        with self.lock:
            self.jobs[job_id]["state"] = "running"
            self.jobs[job_id]["started_at"] = now()
            self._save(self.jobs[job_id])
        try:
            root = self.root_factory()
            work = root / "Jobs" / job_id
            if spec["format"] == "director_ue_previs_v04":
                from ue_previs import run_previs
                # Preview uses a separate, fixed render pipeline and strict
                # output receipt, never the legacy commandlet path.
                result = run_previs(spec, root, work)
            else:
                result = self.runner(spec, root, work)
            outcome = {"state": "succeeded", "result": result}
        except JobError as exc:
            outcome = {"state": "failed", "reason": str(exc)}
        except (OSError, ValueError, RuntimeError):
            outcome = {"state": "failed", "reason": "worker_internal_error"}
        with self.lock:
            self.jobs[job_id].update(outcome)
            self.jobs[job_id]["finished_at"] = now()
            self._save(self.jobs[job_id])
            self.active = None

    def lookup(self, job_id):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id or ""):
            raise JobError("invalid_job_id")
        with self.lock:
            entry = self.jobs.get(job_id)
            if entry is None:
                raise JobError("job_not_found")
            return dict(entry)
