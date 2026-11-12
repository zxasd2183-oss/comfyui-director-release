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
from ue_process import JobCancelled, ProcessController, job_scope, run_fixed
import uuid
from datetime import datetime, timezone
from pathlib import Path

MAX_SHOTS = 150
MAX_DURATION_MS = 30 * 60 * 1000
FPS_ALLOWED = frozenset({24, 25, 30})
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
        "build_episode_timeline", "build_stage_cameras", "render_previs_stills",
        "audit_ep01_assets", "build_ep01_scene_candidates",
        "build_ep01_cast_blueprints", "render_cast_review_stills"
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
    if body["task"] in ("build_stage_cameras", "render_previs_stills",
                        "audit_ep01_assets", "build_ep01_scene_candidates",
                        "build_ep01_cast_blueprints",
                        "render_cast_review_stills"):
        if (project_id, episode_id, fps, len(validated), total_ms) != (
            "WaitingOffice", "EP01", 24, 31, 160000
        ):
            raise JobError("previs_requires_locked_ep01")
        if [s["shot_id"] for s in validated] != [
            str(i).zfill(2) for i in range(1, 32)
        ]:
            raise JobError("previs_requires_frozen_shot_ids")
    fmt = (
        "director_ue_cast_review_v110"
        if body["task"] == "render_cast_review_stills"
        else "director_ue_cast_blueprints_v100"
        if body["task"] == "build_ep01_cast_blueprints"
        else "director_ue_scene_candidates_v09"
        if body["task"] == "build_ep01_scene_candidates"
        else "director_ue_assets_v08" if body["task"] == "audit_ep01_assets"
        else "director_ue_previs_v04" if body["task"] == "render_previs_stills"
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
                   if spec["format"] in ("director_ue_stage_v03",
                                         "director_ue_assets_v08",
                                         "director_ue_scene_candidates_v09",
                                         "director_ue_cast_blueprints_v100")
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
    if spec["format"] in ("director_ue_scene_candidates_v09",
                          "director_ue_cast_blueprints_v100"):
        if not re.fullmatch(r"[a-f0-9]{32}", work.name):
            raise JobError("invalid_candidate_job_id")
        env["DIRECTOR_UE_JOB_ID"] = work.name
    command = [
        str(editor), str(project), "-run=pythonscript",
        "-script=" + str(script), "-unattended", "-nop4", "-nosplash",
        "-NoSound", "-log",
    ]
    run_fixed(
        command, root, work / "unreal.log", timeout, env,
        "unreal_commandlet_timeout", "unreal_commandlet_failed",
    )
    if not result_file.exists():
        raise JobError("unreal_missing_result")
    data = json.loads(result_file.read_text(encoding="utf-8"))
    if type(data) is not dict or type(data.get("ok")) is not bool:
        raise JobError("invalid_unreal_result")
    if not data["ok"]:
        raise JobError("unreal_script_failed")
    if spec["format"] == "director_ue_cast_blueprints_v100":
        # Static-component Blueprint candidates, NEVER skeletal MetaHumans.
        ids = ("CHAR_GPT", "CHAR_GEM", "CHAR_DS", "CHAR_CLA", "CHAR_ZERO")
        base = ("/Game/Director/Candidates/EP01/CastBuilds/J"
                + work.name)
        characters = data.get("characters")
        if (data.get("kind") !=
                "original_static_blueprint_character_candidates_v100" or
                type(characters) is not list or len(characters) != 5 or
                [v.get("id") for v in characters
                 if type(v) is dict] != list(ids) or
                data.get("review_map") !=
                base + "/Maps/EP01_Five_Cast_Review" or
                data.get("right_wrist_red_thread_character") != "CHAR_ZERO" or
                data.get("locked_gpt_hair") != "short_dark_chestnut_bob" or
                data.get("locked_gpt_eyes") != "amber" or
                data.get("material_count") != 18 or
                data.get("shot_count") != 31 or
                data.get("total_frames") != 3840 or
                any(data.get(field) is not False for field in (
                    "studio_character_approval_verified",
                    "skeletal_rig_bound", "metahuman_bound",
                    "facial_performance_ready", "render_ready")) or
                data.get("no_approved_asset_replaced") is not True):
            raise JobError("ue_cast_blueprint_receipt_invalid")
        for ident,item in zip(ids,characters):
            if (type(item) is not dict or
                    set(item) != {"id", "path", "editable_mesh_components"} or
                    item["id"] != ident or
                    item["path"] != base + "/Blueprints/BP_" + ident or
                    type(item["editable_mesh_components"]) is not int or
                    not 32 <= item["editable_mesh_components"] <= 100):
                raise JobError("ue_cast_blueprint_receipt_invalid")
        return {
            "kind":"original_static_blueprint_character_candidates_v100",
            "characters":characters,"review_map":data["review_map"],
            "material_count":18,"shot_count":31,"total_frames":3840,
            "right_wrist_red_thread_character":"CHAR_ZERO",
            "locked_gpt_hair":"short_dark_chestnut_bob",
            "locked_gpt_eyes":"amber",
            "studio_character_approval_verified":False,
            "skeletal_rig_bound":False,"metahuman_bound":False,
            "facial_performance_ready":False,
            "render_ready":False,"gpu_render_submitted":False,
            "no_approved_asset_replaced":True,
        }
    if spec["format"] == "director_ue_scene_candidates_v09":
        # The receipt is evidence of *saved EDITABLE DRAFT SCENES* only.
        # Never convert it into a Studio scene approval or render-ready flag.
        path_prefix = ("/Game/Director/Candidates/EP01/SceneBuilds/J"
                       + work.name + "/Maps/")
        ids = ("SCN_HALL", "SCN_HALL_ALERT", "SCN_ENTRANCE")
        scenes = data.get("scene_candidates")
        if (type(scenes) is not list or len(scenes) != 3 or
                data.get("candidate_kind") != "original_editable_environment_v09" or
                type(data.get("material_count")) is not int or
                data["material_count"] != 10 or
                data.get("shot_count") != 31 or
                data.get("total_frames") != 3840 or
                data.get("studio_scene_approval_verified") is not False or
                data.get("character_models_bound") is not False or
                data.get("render_ready") is not False or
                data.get("no_existing_scene_replaced") is not True):
            raise JobError("ue_scene_candidate_receipt_invalid")
        for expected, scene in zip(ids, scenes):
            if (type(scene) is not dict or set(scene) !=
                    {"id", "path", "props", "lights", "review_cameras"} or
                    scene["id"] != expected or
                    scene["path"] != path_prefix + expected or
                    any(type(scene[k]) is not int for k in
                        ("props", "lights", "review_cameras")) or
                    scene["props"] < 20 or scene["lights"] < 2 or
                    scene["review_cameras"] < 2):
                raise JobError("ue_scene_candidate_receipt_invalid")
        return {
            "candidate_kind": "original_editable_environment_v09",
            "scene_candidates": scenes,
            "material_count": 10, "shot_count": 31,
            "total_frames": 3840,
            "studio_scene_approval_verified": False,
            "character_models_bound": False,
            "render_ready": False,
            "gpu_render_submitted": False,
            "no_existing_scene_replaced": True,
        }
    if spec["format"] == "director_ue_assets_v08":
        # Read-only inventory. Neither presence nor class establishes approval,
        # proper sequence binding, animation, or permission to render.
        expected = {
            "characters": ("CHAR_GPT", "CHAR_GEM", "CHAR_DS", "CHAR_CLA", "CHAR_ZERO"),
            "scenes": ("SCN_HALL", "SCN_ENTRANCE"),
            "shots": tuple("SH%02d" % i for i in range(1, 32)),
        }
        report = data.get("asset_audit")
        if (type(report) is not dict or set(report) != set(expected) or
                data.get("shot_count") != 31 or data.get("total_frames") != 3840):
            raise JobError("ue_asset_audit_invalid")
        for kind, labels in expected.items():
            items = report.get(kind)
            if (type(items) is not list or len(items) != len(labels) or
                    [a.get("id") for a in items if type(a) is dict] != list(labels) or
                    any(type(a) is not dict or set(a) != {"id", "exists", "type_valid"}
                        or type(a["exists"]) is not bool or
                        type(a["type_valid"]) is not bool or
                        (a["type_valid"] and not a["exists"]) for a in items)):
                raise JobError("ue_asset_audit_invalid")
        return {
            "audit_only": True, "project_id": "WaitingOffice", "episode_id": "EP01",
            "shot_count": 31, "total_frames": 3840,
            "asset_audit": report,
            "all_assets_present_and_class_valid": all(
                a["exists"] and a["type_valid"]
                for group in report.values() for a in group),
            "studio_approval_verified": False,
            "animation_binding_verified": False,
            "render_ready": False,
            "gpu_render_submitted": False,
        }
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
        self.controller = None
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
                            "queued", "running", "succeeded", "failed", "cancelled"
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

    def submit(self, body):
        spec = sanitized_plan(body)
        with self.lock:
            if self.active is not None:
                raise JobError("ue_worker_busy")
            job_id = uuid.uuid4().hex
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
            self.controller = ProcessController()
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
            with job_scope(self.controller):
                if self.controller.cancel_requested.is_set():
                    raise JobCancelled("job_cancelled")
                root = self.root_factory()
                work = root / "Jobs" / job_id
                if spec["format"] == "director_ue_previs_v04":
                    from ue_previs import run_previs
                    result = run_previs(spec, root, work)
                elif spec["format"] == "director_ue_cast_review_v110":
                    from ue_previs import render_cast_review
                    result = render_cast_review(spec, root, work)
                else:
                    result = self.runner(spec, root, work)
                if self.controller.cancel_requested.is_set():
                    raise JobCancelled("job_cancelled")
            outcome = {"state": "succeeded", "result": result}
        except JobCancelled:
            outcome = {"state": "cancelled", "reason": "job_cancelled"}
        except JobError as exc:
            outcome = {"state": "failed", "reason": str(exc)}
        except (OSError, ValueError, RuntimeError):
            outcome = {"state": "failed", "reason": "worker_internal_error"}
        with self.lock:
            self.jobs[job_id].update(outcome)
            self.jobs[job_id]["finished_at"] = now()
            self._save(self.jobs[job_id])
            self.active = None
            self.controller = None

    def cancel(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise JobError("invalid_job_id")
        with self.lock:
            entry = self.jobs.get(job_id)
            if entry is None:
                raise JobError("job_not_found")
            if entry["state"] in {"succeeded", "failed", "cancelled"}:
                return {"ok": True, "job_id": job_id, "state": entry["state"],
                        "cancel_requested": False, "already_terminal": True}
            if self.active != job_id or self.controller is None:
                raise JobError("job_not_active")
            controller = self.controller
        # Never block the job-status lock while terminating a child process.
        controller.cancel()
        return {"ok": True, "job_id": job_id, "cancel_requested": True}

    def lookup(self, job_id):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id or ""):
            raise JobError("invalid_job_id")
        with self.lock:
            entry = self.jobs.get(job_id)
            if entry is None:
                raise JobError("job_not_found")
            return dict(entry)


# EP01 final-assembly inventory is inside the signed-owned Worker module.
# This avoids adding an untracked import to the pinned nine-file release.
# It never probes media, starts ffmpeg, writes files or approves a visual.
def inspect_episode_inputs(workspace: Path) -> dict:
    import wave

    workspace = Path(workspace).absolute()
    if (not workspace.is_dir() or workspace.is_symlink() or
            getattr(workspace, "is_junction", lambda: False)()):
        return {"ok": False, "reason": "workspace_unavailable"}

    def owned(path: Path) -> bool:
        path = path.absolute()
        try:
            path.relative_to(workspace)
        except ValueError:
            return False
        # Do not follow links, including dangling links in a parent.
        current = path
        while True:
            if (current.is_symlink() or
                    getattr(current, "is_junction", lambda: False)()):
                return False
            if current == workspace:
                break
            parent = current.parent
            if parent == current:
                return False
            current = parent
        return True

    missing, invalid, candidates = [], [], 0
    for number in range(1, 32):
        shot = f"{number:02d}"
        clip = workspace / "Outputs" / "EP01" / "Clips" / ("SH" + shot + ".mp4")
        try:
            if not owned(clip):
                invalid.append(shot)
            elif not clip.exists():
                missing.append(shot)
            elif not clip.is_file() or not 1024 <= clip.stat().st_size <= 8 * 1024 ** 3:
                invalid.append(shot)
            else:
                candidates += 1
        except (OSError, ValueError):
            invalid.append(shot)

    audio = workspace / "Outputs" / "EP01" / "Audio" / "MixedAudio.wav"
    mixdown_status = "missing"
    try:
        if not owned(audio):
            mixdown_status = "invalid"
        elif audio.exists():
            if not audio.is_file() or not 0 < audio.stat().st_size <= (160 * 48000 * 2 * 4 + 100000):
                mixdown_status = "invalid"
            else:
                with wave.open(str(audio), "rb") as wav:
                    if (wav.getnchannels() == 2 and wav.getframerate() == 48000 and
                            wav.getsampwidth() in (2, 3, 4) and
                            wav.getcomptype() == "NONE" and
                            wav.getnframes() == 160 * 48000):
                        mixdown_status = "pcm_metadata_valid"
                    else:
                        mixdown_status = "invalid"
    except (OSError, ValueError, EOFError, wave.Error):
        mixdown_status = "invalid"

    output = workspace / "Outputs" / "EP01" / "Final" / "WaitingOffice_EP01_v001.mp4"
    output_status = "absent"
    try:
        if not owned(output):
            output_status = "invalid"
        elif output.exists():
            output_status = "existing_file" if output.is_file() else "invalid"
    except (OSError, ValueError):
        output_status = "invalid"

    complete = (candidates == 31 and not missing and not invalid and
                mixdown_status == "pcm_metadata_valid" and output_status == "absent")
    return {
        "ok": True, "project_id": "WaitingOffice", "episode_id": "EP01",
        "fixed_shots": 31, "fixed_duration_seconds": 160,
        "clip_candidate_count": candidates, "missing_shot_ids": missing,
        "invalid_shot_ids": invalid, "mixdown_status": mixdown_status,
        "output_status": output_status, "input_inventory_complete": complete,
        "clips_codec_and_timing_verified": False,
        "artistic_approval_verified": False, "render_submitted": False,
        "note": "Inventory only; encoded media and artistic approvals require independent validation.",
    }
