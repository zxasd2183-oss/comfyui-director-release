"""Fixed four-frame V03 preview render via UE 5.8 Movie Render Queue CLI.

Only the trusted worker decides executable, map, shot IDs, preset settings,
outputs, timing and cost ceiling. No HTTP caller can submit paths or scripts.
No files are uploaded from the Windows host or exposed through public URLs.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import subprocess
import zipfile
from pathlib import Path

FRAME_SHOTS = ("01", "13", "26", "31")
MAP_PATH = "/Game/Director/V03/Maps/WaitingOffice_EP01_Stage"
SHOTS_PATH = "/Game/Director/V03/Shots/WaitingOffice_EP01_SH"
ASSET_PRESET_PREFIX = "/Game/Director/V04/Presets/WO_EP01_PrevisPNG_"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_PNG_BYTES = 25 * 1024 * 1024
MAX_RENDER_SECONDS = 180
MAX_PREP_SECONDS = 180


def read_png_dimensions(path):
    with path.open("rb") as fp:
        header = fp.read(24)
    if (len(header) != 24 or header[:8] != PNG_MAGIC or
            header[12:16] != b"IHDR"):
        raise ValueError("invalid_png_header")
    return struct.unpack(">II",header[16:24])


def check_png(path):
    from ue_jobs import JobError
    if path.is_symlink() or not path.is_file():
        raise JobError("preview_png_is_not_regular_file")
    size = path.stat().st_size
    if not 2048 <= size <= MAX_PNG_BYTES:
        raise JobError("preview_png_size_out_of_bounds")
    if read_png_dimensions(path) != (720,1280):
        raise JobError("preview_png_wrong_resolution")
    return {
        "filename":path.name,
        "bytes":size,
        "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
        "width":720, "height":1280,
    }


def ensure_mrq_plugin(project, work):
    """Upgrade exactly the known managed project file; never edit user projects.

    Movie Render Pipeline may not be enabled in the V02 project. We preserve
    the original full .uproject file as a local backup before adding only
    the official MovieRenderPipeline plugin entry. No UE production assets
    are modified.
    """
    from ue_jobs import JobError, KNOWN_PLUGINS
    original = json.loads(project.read_text(encoding="utf-8"))
    expected = {
        "FileVersion":3,
        "EngineAssociation":"5.8",
        "Category":"Film & Television",
        "Description":"Director UE original automated production project",
        "Plugins":[{"Name":plugin,"Enabled":True}
                   for plugin in KNOWN_PLUGINS],
    }
    upgraded = dict(expected)
    upgraded["Plugins"] = expected["Plugins"] + [
        {"Name":"MovieRenderPipeline","Enabled":True}
    ]
    if original == upgraded:
        return
    if original != expected:
        raise JobError("project_not_owned_by_director_no_plugin_changes")
    work.mkdir(parents=True,exist_ok=False)
    backup = work / "uproject_before_mrq.json"
    backup.write_bytes(project.read_bytes())
    updated = work / "uproject_mrq.json"
    updated.write_text(
        json.dumps(upgraded,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )
    # On NTFS, replace is atomic on the same volume. Work and project are
    # under the same Director workspace root, not a user-supplied path.
    updated.replace(project)


def validate_existing_stage(root):
    from ue_jobs import JobError
    content = root / "Content" / "Director" / "V03"
    if not (content/"Maps"/"WaitingOffice_EP01_Stage.umap").is_file():
        raise JobError("v03_stage_map_missing")
    for shot in FRAME_SHOTS:
        if not (content/"Shots"/("WaitingOffice_EP01_SH"+shot+"_V03.uasset")).is_file():
            raise JobError("v03_camera_sequence_missing_"+shot)


def _run_unreal(command,root,logfile,timeout,env):
    from ue_process import run_fixed
    run_fixed(
        command, root, logfile, timeout, env,
        "previs_render_timeout", "previs_unreal_process_failed",
    )


def run_previs(spec,root,work):
    """Return a job receipt only after four 720x1280 PNG files are validated."""
    from ue_jobs import JobError, ensure_project, find_editor_cmd
    if spec.get("format") != "director_ue_previs_v04":
        raise JobError("invalid_previs_spec")
    if not re.fullmatch(r"[a-f0-9]{32}",work.name):
        raise JobError("invalid_server_generated_job_id")
    if (spec["project_id"],spec["episode_id"],
        spec["fps"],spec["total_frames"],len(spec["shots"])) != (
            "WaitingOffice","EP01",24,3840,31):
        raise JobError("previs_requires_frozen_ep01")
    editor = find_editor_cmd()
    project = ensure_project(root)
    validate_existing_stage(root)
    source_map_file = root / "Content" / "Director" / "V03" / "Maps" / "WaitingOffice_EP01_Stage.umap"
    source_sha256_before = hashlib.sha256(source_map_file.read_bytes()).hexdigest()
    if work.is_symlink() or work.exists():
        raise JobError("previs_job_folder_already_exists")
    ensure_mrq_plugin(project,work)
    work.mkdir(parents=True,exist_ok=True)
    output = root / "Outputs" / "V04" / work.name / "Previews"
    if output.is_symlink() or output.exists():
        raise JobError("previs_output_collision")
    output.mkdir(parents=True)
    preset_script = Path(__file__).resolve().with_name(
        "unreal_create_previs_preset.py"
    )
    if not preset_script.is_file() or preset_script.is_symlink():
        raise JobError("trusted_mrq_preset_script_missing")
    results_path = work/"preset_result.json"
    env = os.environ.copy()
    env["DIRECTOR_UE_JOB_ID"] = work.name
    env["DIRECTOR_UE_RESULT_FILE"] = str(results_path)
    env["DIRECTOR_UE_PREVIEW_OUTPUT"] = str(output)
    _run_unreal(
        [str(editor),str(project),"-run=pythonscript",
         "-script="+str(preset_script),"-unattended","-nop4","-nosplash",
         "-NoSound","-log"],
        root,work/"preset.log",MAX_PREP_SECONDS,env
    )
    if not results_path.is_file():
        raise JobError("previs_preset_result_missing")
    data = json.loads(results_path.read_text(encoding="utf-8"))
    asset_name = "WO_EP01_PrevisPNG_" + work.name
    expected_preset = ASSET_PRESET_PREFIX + work.name + "." + asset_name
    if (not data.get("ok") or data.get("preset") != expected_preset or
            data.get("width") != 720 or data.get("height") != 1280 or
            data.get("frames_per_shot") != 1):
        raise JobError("previs_preset_creation_failed")
    # The map path comes from a pinned per-job asset name, not HTTP input.
    expected_map = "/Game/Director/V051/Maps/WO_EP01_ExposurePreview_" + work.name
    expected_camera13 = {
        "label": "V03_CAM_SH13",
        "original": [-420.0, 345.0, 225.0],
        "preview": [-860.0, 345.0, 225.0],
        "look_at": [-245.0, 380.0, 103.0],
    }
    if (data.get("stage_map") != expected_map or
            data.get("source_map") != MAP_PATH or
            data.get("light_intensities") !=
            {"V03_Key_Light": 800.0, "V03_Fill_Light": 400.0} or
            data.get("camera13_reframe") != expected_camera13):
        raise JobError("preview_stage_unverified")
    if hashlib.sha256(source_map_file.read_bytes()).hexdigest() != source_sha256_before:
        raise JobError("source_v03_stage_was_modified")
    screenshots = []
    for shot in FRAME_SHOTS:
        sequence_name = "WaitingOffice_EP01_SH"+shot+"_V03"
        sequence = SHOTS_PATH + shot + "_V03." + sequence_name
        before = set(output.rglob("*.png"))
        command = [
            str(editor),str(project),expected_map,
            "-game",
            "-LevelSequence="+sequence,
            "-MoviePipelineConfig="+expected_preset,
            "-unattended","-nop4","-nosplash","-RenderOffscreen",
            "-resx=720","-resy=1280","-log",
        ]
        _run_unreal(
            command,root,work/("render_"+shot+".log"),MAX_RENDER_SECONDS,env
        )
        new = set(output.rglob("*.png")) - before
        if len(new) != 1:
            raise JobError("previs_expected_exactly_one_new_png_"+shot)
        path = next(iter(new))
        if not path.name.lower().endswith(".png"):
            raise JobError("previs_invalid_extension")
        receipt = check_png(path)
        receipt["shot_id"]=shot
        # Keep pathname confined to the job-owned output, no absolute
        # arbitrary file paths are returned to Hub clients.
        receipt["relative_path"]=str(path.relative_to(root)).replace("\\","/")
        screenshots.append(receipt)
    if hashlib.sha256(source_map_file.read_bytes()).hexdigest() != source_sha256_before:
        raise JobError("source_v03_stage_was_modified")
    # One portable, operator-retrievable package. No endpoint publishes this.
    # Atomic rename makes incomplete archives impossible to claim as success.
    manifest = {
        "format": "director_ue_previs_package_v1",
        "project_id": "WaitingOffice", "episode_id": "EP01",
        "job_id": work.name, "mode": "V03 geometry proxy camera proof",
        "not_final_film": True,
        "not_metahuman": True,
        "images": screenshots,
    }
    package_name = "WaitingOffice_EP01_V04_" + work.name + ".zip"
    pending_archive = output.parent / (package_name + ".pending")
    package = output.parent / package_name
    if package.exists() or pending_archive.exists():
        raise JobError("previs_package_collision")
    with zipfile.ZipFile(pending_archive, mode="x",
                         compression=zipfile.ZIP_DEFLATED, compresslevel=4) as archive:
        archive.writestr("manifest.json",
                         json.dumps(manifest, ensure_ascii=False, indent=2))
        for shot in screenshots:
            relative = shot["relative_path"]
            local = root / Path(relative)
            # ZIP member names are fixed by the trusted worker, not callers.
            archive.write(local, arcname="Previews/" + shot["shot_id"] + ".png")
    pending_archive.replace(package)
    with zipfile.ZipFile(package, "r") as archive:
        expected_members = {"manifest.json"} | {
            "Previews/" + shot + ".png" for shot in FRAME_SHOTS
        }
        if (set(archive.namelist()) != expected_members or
                archive.testzip() is not None):
            raise JobError("previs_package_integrity_failed")
    return {
        "preview_kind":"stage_proxy_only",
        "preview_stage_map": expected_map,
        "source_stage_sha256": source_sha256_before,
        "source_stage_unchanged": True,
        "light_intensities": data["light_intensities"],
        "camera13_reframe": data["camera13_reframe"],
        "render_ready":False,
        "metahuman_bound":False,
        "preview_count":len(screenshots),
        "resolution":"720x1280",
        "format":"png",
        "output_dir":str(output.relative_to(root)).replace("\\","/"),
        "screenshots":screenshots,
        "package": {
            "relative_path":str(package.relative_to(root)).replace("\\","/"),
            "bytes":package.stat().st_size,
            "sha256":hashlib.sha256(package.read_bytes()).hexdigest(),
            "member_count":len(screenshots)+1,
        },
        "note":"Only V03 blockout cubes + fixed cameras. Not a finished film.",
    }
