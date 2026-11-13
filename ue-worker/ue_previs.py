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
PRIVATE_SHOTS_ROOT = "/Game/Director/V071/ShotBindings"
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
    # Every preview MUST have its own sequence bound to a camera actor
    # in the copied level, never to source V03 map possessables.
    expected_sequences = {}
    for shot in FRAME_SHOTS:
        name = "WaitingOffice_EP01_SH" + shot + "_V03"
        expected_sequences[shot] = (
            PRIVATE_SHOTS_ROOT + "/" + work.name + "/" + name + "." + name
        )
    # Independent worker contract: reject stale 16:9 filmbacks and any
    # mismatched four-camera composition before an expensive MRQ invocation.
    poses = {
        "01": ([-480.0, -335.0, 235.0], [140.0, -45.0, 115.0], 20.0),
        "13": ([-860.0, 345.0, 225.0], [-245.0, 380.0, 103.0], 27.0),
        "26": ([-250.0, 80.0, 230.0], [425.0, 225.0, 145.0], 32.0),
        "31": ([-735.0, 250.0, 235.0], [-245.0, 380.0, 103.0], 28.0),
    }
    portrait_cameras = {
        shot: {
            "location": location, "look_at": target, "focal_mm": focal,
            "sensor_mm": [13.5, 24.0], "crop_aspect_ratio": 0.0,
            "constrain_aspect_ratio": True,
        }
        for shot, (location, target, focal) in poses.items()
    }
    if (data.get("stage_map") != expected_map or
            data.get("source_map") != MAP_PATH or
            data.get("light_intensities") !=
            {"V03_Key_Light": 800.0, "V03_Fill_Light": 400.0} or
            data.get("camera13_reframe") != expected_camera13 or
            data.get("bound_preview_sequences") != expected_sequences or
            data.get("portrait_preview_cameras") != portrait_cameras):
        raise JobError("preview_stage_or_portrait_camera_unverified")
    if hashlib.sha256(source_map_file.read_bytes()).hexdigest() != source_sha256_before:
        raise JobError("source_v03_stage_was_modified")
    screenshots = []
    for shot in FRAME_SHOTS:
        sequence = expected_sequences[shot]
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
        "bound_preview_sequences": expected_sequences,
        "portrait_preview_cameras": portrait_cameras,
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



# Pinned, already-verified V1.3 UE 5.8 native MetaHuman Character candidate.
# Never audit a caller-selected asset; this is the sole EP01 hero identity.
GPT_HERO_SOURCE_JOB = "d5253c965631447684e49613533e85ad"
GPT_HERO_SOURCE_SHA256 = "ccbd6bc1c39cedec3fd803642f604452bad949333c94eb4c63e5504dd33fc318"



# Real UE5.8 left/right iris edit from the succeeded RTX4090 job.
GPT_HERO_AMBER_SOURCE_JOB = "da7a5a59132d4e279f0433f4af1b94ce"
GPT_HERO_AMBER_SOURCE_SHA256 = (
    "358562baac529a1714489aa6de078038a94c491ff86c012c12df3c82ebcfccf5"
)


def build_gpt_hero_face_contour(spec,root,work):
    """Unrigged MetaHuman contour on a NEW candidate; preserves amber source."""
    from ue_jobs import JobError,find_editor_cmd
    from agent import hero_project_manifest
    if spec.get("format")!="director_ue_hero_face_v170":
        raise JobError("hero_face_spec_invalid")
    if ((spec.get("project_id"),spec.get("episode_id"),spec.get("fps"),
         spec.get("total_ms"),spec.get("total_frames"),len(spec.get("shots",[])))
            != ("WaitingOffice","EP01",24,160000,3840,31)
        or [x["shot_id"] for x in spec["shots"]] != [
            "%02d"%i for i in range(1,32)]):
        raise JobError("hero_face_requires_locked_ep01")
    if not re.fullmatch(r"[a-f0-9]{32}",work.name):
        raise JobError("hero_face_job_id_invalid")
    if work.exists() or work.is_symlink():
        raise JobError("hero_face_job_collision")
    project=root/"HeroProjects"/"CHAR_GPT"/"DirectorHeroGPT.uproject"
    if project.is_symlink() or not project.is_file():
        raise JobError("hero_face_project_missing")
    try:
        if json.loads(project.read_text("utf-8"))!=hero_project_manifest():
            raise JobError("hero_face_project_untrusted")
    except (UnicodeError,TypeError,ValueError):
        raise JobError("hero_face_project_unreadable") from None
    original=(project.parent/"Content"/"Director"/"Candidates"/"EP01"/
              "HeroLooks"/("J"+GPT_HERO_AMBER_SOURCE_JOB)/
              "MHC_CHAR_GPT_AmberV1.uasset")
    seed=(project.parent/"Content"/"Director"/"Candidates"/"EP01"/
          "HeroBuilds"/("J"+GPT_HERO_SOURCE_JOB)/"MHC_CHAR_GPT.uasset")
    if (original.is_symlink() or not original.is_file() or
        seed.is_symlink() or not seed.is_file()):
        raise JobError("hero_face_sources_unavailable")
    base=hashlib.sha256(original.read_bytes()).hexdigest()
    seed_hash=hashlib.sha256(seed.read_bytes()).hexdigest()
    if base!=GPT_HERO_AMBER_SOURCE_SHA256 or seed_hash!=GPT_HERO_SOURCE_SHA256:
        raise JobError("hero_face_source_hash_drift")
    dest=(project.parent/"Content"/"Director"/"Candidates"/"EP01"/
          "HeroFaces"/("J"+work.name)/"MHC_CHAR_GPT_FaceContourV1.uasset")
    if dest.is_symlink() or dest.exists():
        raise JobError("hero_face_candidate_collision")
    work.mkdir(parents=True,exist_ok=False)
    output=work/"hero_face_result.json"
    env=os.environ.copy()
    env["DIRECTOR_UE_JOB_ID"]=work.name
    env["DIRECTOR_UE_REVIEW_MODE"]="hero_face_v170"
    env["DIRECTOR_UE_RESULT_FILE"]=str(output)
    script=Path(__file__).resolve().with_name("unreal_create_previs_preset.py")
    if script.is_symlink() or not script.is_file():
        raise JobError("hero_face_script_unavailable")
    _run_unreal([str(find_editor_cmd()),str(project),"-run=pythonscript",
                 "-script="+str(script),"-unattended","-nop4",
                 "-nosplash","-NoSound","-log"],
                root,work/"hero_face.log",720,env)
    if output.is_symlink() or not output.is_file() or output.stat().st_size>6000:
        raise JobError("hero_face_receipt_missing")
    data=json.loads(output.read_text("utf-8"))
    if type(data) is not dict:
        raise JobError("hero_face_receipt_invalid")
    if data.get("ok") is not True:
        reason=data.get("reason")
        if type(reason) is str and re.fullmatch(
                r"hero_face_(?:step_failed_(?:identity|source|duplicate|register|"
                r"get_landmarks|landmark_count|landmark_coordinates|"
                r"landmark_scale|landmark_jaw_selection|sculpt|save)|"
                r"unregister_failed)",reason):
            raise JobError(reason)
        raise JobError("hero_face_editor_failed")
    name=("/Game/Director/Candidates/EP01/HeroFaces/J"+work.name+
          "/MHC_CHAR_GPT_FaceContourV1")
    if (data.get("character_id")!="CHAR_GPT" or
        data.get("asset_path")!=name or
        data.get("asset_class")!="MetaHumanCharacter" or
        data.get("face_edit_api")!="translate_face_landmarks_commit_face_state" or
        type(data.get("landmark_count")) is not int or
        not 20<=data["landmark_count"]<=1000 or
        type(data.get("landmarks_selected")) is not int or
        not 6<=data["landmarks_selected"]<=24 or
        type(data.get("live_landmarks_changed")) is not int or
        not 2<=data["live_landmarks_changed"]<=data["landmarks_selected"] or
        data.get("max_lateral_delta_cm")!=0.10 or
        data.get("jaw_style")!="subtle_symmetric_lower_face_narrowing_v1" or
        data.get("real_ue_sculpt_committed") is not True or
        data.get("original_asset_untouched") is not True or
        any(data.get(k) is not False for k in (
            "cloud_requests_executed","rigging_done",
            "high_res_textures_downloaded","groom_applied","wardrobe_applied",
            "cinematic_character_ready","character_master_approved",
            "visual_approved"))):
        raise JobError("hero_face_receipt_invalid")
    if dest.is_symlink() or not dest.is_file() or not (
            1024<=dest.stat().st_size<=100*1024*1024):
        raise JobError("hero_face_native_uasset_missing")
    digest=hashlib.sha256(dest.read_bytes()).hexdigest()
    if (hashlib.sha256(original.read_bytes()).hexdigest()!=base or
        hashlib.sha256(seed.read_bytes()).hexdigest()!=seed_hash):
        raise JobError("hero_face_source_modified")
    if digest==base:
        raise JobError("hero_face_asset_not_changed")
    return {
        "kind":"native_metahuman_face_contour_candidate_v170",
        "character_id":"CHAR_GPT","candidate_asset_path":name,
        "candidate_uasset_sha256":digest,
        "candidate_uasset_bytes":dest.stat().st_size,
        "live_landmarks_changed":data["live_landmarks_changed"],
        "landmarks_selected":data["landmarks_selected"],
        "real_ue_face_edit_committed":True,
        "source_amber_asset_sha256":base,
        "source_amber_asset_preserved":True,
        "original_seed_preserved":True,
        "face_sculpt_style":"subtle_lower_face_narrowing",
        "creative_face_visual_approved":False,
        "texture_sources_ready":False,"full_face_rig_ready":False,
        "groom_ready":False,"wardrobe_ready":False,
        "cinematic_character_ready":False,"character_master_approved":False,
    }


def build_gpt_hero_amber_eyes(spec,root,work):
    """One copy of the real MetaHuman with both amber-brown iris settings."""
    from ue_jobs import JobError,find_editor_cmd
    from agent import hero_project_manifest
    if spec.get("format")!="director_ue_hero_eyes_v150":
        raise JobError("hero_eyes_format_invalid")
    if ((spec.get("project_id"),spec.get("episode_id"),spec.get("fps"),
         spec.get("total_ms"),spec.get("total_frames"),len(spec.get("shots",[])))
        != ("WaitingOffice","EP01",24,160000,3840,31)):
        raise JobError("hero_eyes_requires_locked_ep01")
    if [x["shot_id"] for x in spec["shots"]] != [
            "%02d"%i for i in range(1,32)]:
        raise JobError("hero_eyes_requires_frozen_shots")
    if not re.fullmatch(r"[a-f0-9]{32}",work.name):
        raise JobError("hero_eyes_job_invalid")
    if work.is_symlink() or work.exists():
        raise JobError("hero_eyes_job_collision")
    project=root/"HeroProjects"/"CHAR_GPT"/"DirectorHeroGPT.uproject"
    if project.is_symlink() or not project.is_file():
        raise JobError("hero_eyes_project_missing")
    try:
        if json.loads(project.read_text("utf-8"))!=hero_project_manifest():
            raise JobError("hero_eyes_project_untrusted")
    except (UnicodeError,ValueError,TypeError):
        raise JobError("hero_eyes_project_invalid") from None
    original=(project.parent/"Content"/"Director"/"Candidates"/"EP01"/
              "HeroBuilds"/("J"+GPT_HERO_SOURCE_JOB)/"MHC_CHAR_GPT.uasset")
    if original.is_symlink() or not original.is_file():
        raise JobError("hero_eyes_original_missing")
    hash_before=hashlib.sha256(original.read_bytes()).hexdigest()
    if hash_before!=GPT_HERO_SOURCE_SHA256:
        raise JobError("hero_eyes_original_hash_changed")
    dest=(project.parent/"Content"/"Director"/"Candidates"/"EP01"/
          "HeroLooks"/("J"+work.name)/"MHC_CHAR_GPT_AmberV1.uasset")
    if dest.exists() or dest.is_symlink():
        raise JobError("hero_eyes_candidate_collision")
    work.mkdir(parents=True,exist_ok=False)
    receipt=work/"hero_eyes_result.json"
    env=os.environ.copy()
    env["DIRECTOR_UE_JOB_ID"]=work.name
    env["DIRECTOR_UE_REVIEW_MODE"]="hero_eyes_v150"
    env["DIRECTOR_UE_RESULT_FILE"]=str(receipt)
    script=Path(__file__).resolve().with_name("unreal_create_previs_preset.py")
    if script.is_symlink() or not script.is_file():
        raise JobError("hero_eyes_script_missing")
    _run_unreal([
        str(find_editor_cmd()),str(project),"-run=pythonscript",
        "-script="+str(script),"-unattended","-nop4","-nosplash",
        "-NoSound","-log"
    ],root,work/"hero_eyes.log",600,env)
    if receipt.is_symlink() or not receipt.is_file() or receipt.stat().st_size>6000:
        raise JobError("hero_eyes_result_missing")
    data=json.loads(receipt.read_text("utf-8"))
    expected=("/Game/Director/Candidates/EP01/HeroLooks/J"+work.name+
              "/MHC_CHAR_GPT_AmberV1")
    if (type(data) is not dict or data.get("ok") is not True
        or data.get("asset_path")!=expected
        or data.get("asset_class")!="MetaHumanCharacter"
        or data.get("eye_tint_linear")!=[0.85,0.55,0.25,1.0]
        or data.get("eye_saturation")!=1.25
        or data.get("both_eyes_readback_verified") is not True
        or data.get("original_asset_untouched") is not True
        or any(data.get(k) is not False for k in (
            "groom_applied","wardrobe_applied","face_rig_created",
            "cinematic_character_ready","character_master_approved"))):
        raise JobError("hero_eyes_result_invalid")
    if (not dest.is_file() or dest.is_symlink()
        or not 1024<=dest.stat().st_size<=100*1024*1024):
        raise JobError("hero_eyes_native_uasset_missing")
    digest=hashlib.sha256(dest.read_bytes()).hexdigest()
    if hashlib.sha256(original.read_bytes()).hexdigest()!=hash_before:
        raise JobError("hero_eyes_original_was_modified")
    return {"kind":"real_native_metahuman_amber_eye_candidate_v150",
            "character_id":"CHAR_GPT","candidate_asset_path":expected,
            "candidate_uasset_sha256":digest,
            "candidate_uasset_bytes":dest.stat().st_size,
            "both_eye_parameters_verified":True,
            "eye_tint_linear":[0.85,0.55,0.25,1.0],
            "source_asset_preserved":True,
            "creative_eye_color_visual_approved":False,
            "hair_ready":False,"wardrobe_ready":False,"face_rig_ready":False,
            "cinematic_character_ready":False,"character_master_approved":False}


def audit_gpt_hero_metahuman_runtime(spec, root, work):
    """Probe actual UE 5.8 editor API without mutating native hero asset.

    The subprocess is the already-reviewed signed Unreal script and fixed
    isolated project. No auth tokens, remote URLs or arbitrary commands.
    """
    from ue_jobs import JobError, find_editor_cmd
    from agent import hero_project_manifest
    if spec.get("format") != "director_ue_hero_audit_v140":
        raise JobError("hero_audit_spec_invalid")
    if ((spec.get("project_id"),spec.get("episode_id"),spec.get("fps"),
         spec.get("total_ms"),spec.get("total_frames"),len(spec.get("shots",[])))
            != ("WaitingOffice","EP01",24,160000,3840,31)):
        raise JobError("hero_audit_requires_locked_ep01")
    if [x["shot_id"] for x in spec["shots"]] != [
            "%02d"%i for i in range(1,32)]:
        raise JobError("hero_audit_requires_frozen_shots")
    if not re.fullmatch(r"[a-f0-9]{32}",work.name):
        raise JobError("hero_audit_job_id_invalid")
    if work.exists() or work.is_symlink():
        raise JobError("hero_audit_job_collision")
    project=(root/"HeroProjects"/"CHAR_GPT"/"DirectorHeroGPT.uproject")
    if project.is_symlink() or not project.is_file():
        raise JobError("hero_audit_project_missing")
    try:
        if json.loads(project.read_text("utf-8"))!=hero_project_manifest():
            raise JobError("hero_audit_project_not_trusted")
    except (ValueError,UnicodeError,TypeError):
        raise JobError("hero_audit_project_invalid") from None
    original=(project.parent/"Content"/"Director"/"Candidates"/"EP01"/
              "HeroBuilds"/("J"+GPT_HERO_SOURCE_JOB)/"MHC_CHAR_GPT.uasset")
    if original.is_symlink() or not original.is_file():
        raise JobError("hero_audit_source_missing")
    digest=hashlib.sha256(original.read_bytes()).hexdigest()
    if digest!=GPT_HERO_SOURCE_SHA256:
        raise JobError("hero_audit_source_hash_drift")
    work.mkdir(parents=True,exist_ok=False)
    output=work/"hero_runtime.json"
    env=os.environ.copy()
    env["DIRECTOR_UE_JOB_ID"]=work.name
    env["DIRECTOR_UE_RESULT_FILE"]=str(output)
    env["DIRECTOR_UE_REVIEW_MODE"]="hero_audit_v140"
    fixed_script=Path(__file__).resolve().with_name(
        "unreal_create_previs_preset.py")
    if not fixed_script.is_file() or fixed_script.is_symlink():
        raise JobError("hero_audit_script_missing")
    _run_unreal(
        [str(find_editor_cmd()),str(project),"-run=pythonscript",
         "-script="+str(fixed_script),"-unattended","-nop4","-nosplash",
         "-NoSound","-log"],root,work/"hero_audit.log",480,env)
    if output.is_symlink() or not output.is_file() or output.stat().st_size>10000:
        raise JobError("hero_audit_runtime_receipt_missing")
    data=json.loads(output.read_text("utf-8"))
    if (type(data) is not dict or data.get("ok") is not True
        or data.get("asset_path")!="/Game/Director/Candidates/EP01/"
              "HeroBuilds/J"+GPT_HERO_SOURCE_JOB+"/MHC_CHAR_GPT"
        or data.get("asset_class")!="MetaHumanCharacter"
        or data.get("source_unmodified") is not True
        or data.get("character_master_approved") is not False
        or data.get("rigged") is not False
        or data.get("costly_cloud_requests_executed") is not False):
        raise JobError("hero_audit_runtime_receipt_invalid")
    if hashlib.sha256(original.read_bytes()).hexdigest()!=digest:
        raise JobError("hero_audit_modified_original")
    caps=data.get("capabilities")
    required=("character_editor_subsystem","request_auto_rigging",
              "request_texture_sources","build_meta_human",
              "try_add_object_to_edit","commit_eyes_settings")
    if (type(caps) is not dict or set(caps)!=set(required)
            or not all(type(caps[k]) is bool for k in required)):
        raise JobError("hero_audit_capabilities_invalid")
    examples=data.get("reference_examples")
    required_examples=("create","texture","rig","assembly")
    if (type(examples) is not dict
        or set(examples)!=set(required_examples)
        or not all(type(examples[k]) is bool for k in required_examples)):
        raise JobError("hero_audit_examples_invalid")
    if type(data.get("texture_source_state")) is not str:
        raise JobError("hero_audit_textures_invalid")
    return {"kind":"real_unreal_5_8_metahuman_runtime_audit_v140",
            "project":"DirectorHeroGPT","character_id":"CHAR_GPT",
            "seed_asset_verified":True,"seed_asset_sha256":digest,
            "character_asset_class":"MetaHumanCharacter",
            "capabilities":caps,"reference_examples":examples,
            "texture_source_state":data["texture_source_state"],
            "cloud_auth":"not_tested_no_cloud_request",
            "core_data":"not_verified_until_open_for_edit",
            "character_master_approved":False,
            "rigging_done":False,"cinematic_character_ready":False,
            "source_unmodified":True}


def build_gpt_hero_metahuman_seed(spec, root, work):
    """Use real UE 5.8 MetaHuman factory in fixed isolated project.

    No cloud login, rigging, rendering, asset uploads, arbitrary file inputs,
    or promotion to director-approved character master occurs here.
    """
    from ue_jobs import JobError, find_editor_cmd
    from agent import hero_project_manifest
    if spec.get("format") != "director_ue_hero_seed_v130":
        raise JobError("hero_seed_spec_invalid")
    if ((spec.get("project_id"),spec.get("episode_id"),
         spec.get("fps"),spec.get("total_ms"),spec.get("total_frames"),
         len(spec.get("shots",[]))) !=
        ("WaitingOffice","EP01",24,160000,3840,31)):
        raise JobError("hero_seed_requires_frozen_ep01")
    if [item["shot_id"] for item in spec["shots"]] != [
        "%02d"%i for i in range(1,32)]:
        raise JobError("hero_seed_requires_31_shots")
    if not re.fullmatch(r"[a-f0-9]{32}",work.name):
        raise JobError("hero_seed_invalid_job_id")
    if work.exists() or work.is_symlink():
        raise JobError("hero_seed_job_collision")
    project=(root/"HeroProjects"/"CHAR_GPT"/"DirectorHeroGPT.uproject")
    if project.is_symlink() or not project.is_file():
        raise JobError("hero_isolated_project_missing")
    try:
        if json.loads(project.read_text(encoding="utf-8"))!=hero_project_manifest():
            raise JobError("hero_project_manifest_not_trusted")
    except (UnicodeError,ValueError,TypeError):
        raise JobError("hero_project_manifest_invalid") from None
    folder=project.parent/"Content"/"Director"/"Candidates"/"EP01"/"HeroBuilds"/("J"+work.name)
    if folder.is_symlink() or folder.exists():
        raise JobError("hero_seed_asset_collision")
    work.mkdir(parents=True,exist_ok=False)
    file=work/"hero_result.json"
    env=os.environ.copy()
    env["DIRECTOR_UE_JOB_ID"]=work.name
    env["DIRECTOR_UE_RESULT_FILE"]=str(file)
    env["DIRECTOR_UE_REVIEW_MODE"]="hero_seed_v130"
    script=Path(__file__).resolve().with_name("unreal_create_previs_preset.py")
    if not script.is_file() or script.is_symlink():
        raise JobError("hero_seed_fixed_script_missing")
    _run_unreal(
        [str(find_editor_cmd()),str(project),"-run=pythonscript",
         "-script="+str(script),"-unattended","-nop4","-nosplash",
         "-NoSound","-log"],root,work/"hero_seed.log",900,env)
    if file.is_symlink() or not file.is_file() or file.stat().st_size>8000:
        raise JobError("hero_seed_result_missing")
    data=json.loads(file.read_text(encoding="utf-8"))
    expected="/Game/Director/Candidates/EP01/HeroBuilds/J"+work.name+"/MHC_CHAR_GPT"
    if (type(data) is not dict or data.get("ok") is not True
        or data.get("kind")!="real_native_metahuman_character_seed_v130"
        or data.get("asset_path")!=expected
        or data.get("asset_class")!="MetaHumanCharacter"
        or data.get("project")!="DirectorHeroGPT"
        or data.get("independent_ep01_source_untouched") is not True
        or any(data.get(flag) is not False for flag in (
            "rigging_done","textures_downloaded","groom_applied",
            "wardrobe_applied","character_master_approved",
            "cinematic_character_ready"))):
        raise JobError("hero_seed_result_invalid")
    uasset=folder/"MHC_CHAR_GPT.uasset"
    if (uasset.is_symlink() or not uasset.is_file()
            or not 1024<=uasset.stat().st_size<=100*1024*1024):
        raise JobError("hero_seed_native_uasset_missing")
    digest=hashlib.sha256(uasset.read_bytes()).hexdigest()
    return {
        "kind":"real_native_unreal_5_8_metahuman_character_seed_v130",
        "character_id":"CHAR_GPT","candidate_asset":expected,
        "native_uasset_verified":True,"native_uasset_sha256":digest,
        "native_uasset_bytes":uasset.stat().st_size,
        "source_episode_project_untouched":True,
        "rigging_done":False,"textures_downloaded":False,
        "groom_applied":False,"wardrobe_applied":False,
        "cinematic_character_ready":False,"character_master_approved":False,
        "next_stage":"create_full_rig_groom_wardrobe_and_cine_evidence"
    }


# V1.1 real Unreal Engine PNG visualization of the V1.0 cast Blueprints.
# The sources are pinned to a previously SUCCEEDED actor build; no gray V03
# proxies, generated concept art, or user-provided paths are involved.
CAST_V100_JOB = "f32dea96d7a94990b3eb274d1cef3de3"
CAST_V11_VIEWS = ("LINEUP", "GPT", "GEM", "DS", "CLA", "ZERO")
CAST_V11_ROOT = "/Game/Director/Candidates/EP01/ReviewRenders/J"
CAST_V11_PREVIEW = "WO_EP01_CastReview"
CAST_V11_MAX_PNG = 2 * 1024 * 1024


def render_cast_review(spec, root, work):
    """MRQ one true UE frame from each of 6 fixed cameras and verify PNGs.

    This explicitly DOES NOT create character models, modify source review
    level, approve candidate masters, or claim a finalized film.
    """
    from ue_jobs import JobError, ensure_project, find_editor_cmd
    if spec.get("format") != "director_ue_cast_review_v110":
        raise JobError("cast_review_spec_invalid")
    if (spec.get("project_id"),spec.get("episode_id"),
            spec.get("fps"),spec.get("total_ms"),
            spec.get("total_frames"),len(spec.get("shots",[]))) != (
            "WaitingOffice","EP01",24,160000,3840,31):
        raise JobError("cast_review_requires_frozen_ep01")
    if [x["shot_id"] for x in spec["shots"]] != [
            "%02d"%i for i in range(1,32)]:
        raise JobError("cast_review_requires_31_shots")
    if not re.fullmatch(r"[a-f0-9]{32}",work.name):
        raise JobError("cast_review_job_id_invalid")
    if work.is_symlink() or work.exists():
        raise JobError("cast_review_job_collision")
    editor = find_editor_cmd()
    project = ensure_project(root)
    source_root = (
        root/"Content"/"Director"/"Candidates"/"EP01"/"CastBuilds"
        /("J"+CAST_V100_JOB)
    )
    source = source_root/"Maps"/"EP01_Five_Cast_Review.umap"
    if source.is_symlink() or not source.is_file():
        raise JobError("cast_review_original_v100_map_missing")
    for sid in ("GPT","GEM","DS","CLA","ZERO"):
        item=source_root/"Blueprints"/("BP_CHAR_"+sid+".uasset")
        if item.is_symlink() or not item.is_file():
            raise JobError("cast_review_blueprint_missing_"+sid.lower())
    source_hash_before=hashlib.sha256(source.read_bytes()).hexdigest()
    ensure_mrq_plugin(project,work)
    work.mkdir(parents=True,exist_ok=True)
    output=root/"Outputs"/"V11"/work.name/"Previews"
    if output.is_symlink() or output.exists():
        raise JobError("cast_review_output_collision")
    output.mkdir(parents=True)
    script=Path(__file__).resolve().with_name("unreal_create_previs_preset.py")
    if not script.is_file() or script.is_symlink():
        raise JobError("trusted_cast_mrq_script_missing")
    env=os.environ.copy()
    env["DIRECTOR_UE_JOB_ID"]=work.name
    env["DIRECTOR_UE_RESULT_FILE"]=str(work/"preset_result.json")
    env["DIRECTOR_UE_PREVIEW_OUTPUT"]=str(output)
    env["DIRECTOR_UE_REVIEW_MODE"]="cast_v11"
    _run_unreal(
        [str(editor),str(project),"-run=pythonscript",
         "-script="+str(script),"-unattended","-nop4","-nosplash",
         "-NoSound","-log"],root,work/"preset.log",MAX_PREP_SECONDS,env)
    file=work/"preset_result.json"
    if not file.is_file() or file.is_symlink() or file.stat().st_size>16000:
        raise JobError("cast_review_preset_receipt_missing")
    data=json.loads(file.read_text(encoding="utf-8"))
    prefix=CAST_V11_ROOT+work.name
    expected_world=prefix+"/Maps/"+CAST_V11_PREVIEW
    expected_sequences={
        view:prefix+"/Shots/WO_EP01_CAST_"+view+".WO_EP01_CAST_"+view
        for view in CAST_V11_VIEWS
    }
    expected_presets={
        name:prefix+"/Presets/WO_EP01_CastPNG_"+name+
             ".WO_EP01_CastPNG_"+name
        for name in ("wide","portrait")
    }
    expected_cast={
        s:"WO_CANDIDATE_CHAR_"+s for s in ("GPT","GEM","DS","CLA","ZERO")
    }
    if (type(data) is not dict or data.get("ok") is not True
            or data.get("source_world") !=
            "/Game/Director/Candidates/EP01/CastBuilds/J"+
            CAST_V100_JOB+"/Maps/EP01_Five_Cast_Review"
            or data.get("review_world") != expected_world
            or data.get("view_sequences") != expected_sequences
            or data.get("mrq_presets") != expected_presets
            or data.get("cast") != expected_cast
            or data.get("views") != list(CAST_V11_VIEWS)
            or data.get("frames_per_view") != 1
            or data.get("source_world_unchanged") is not True):
        raise JobError("cast_review_preset_receipt_invalid")
    look=data.get("review_look")
    if (type(look) is not dict or
            look.get("face_component_overrides") != 52 or
            look.get("exposure_method") != "manual" or
            look.get("exposure_bias") != -1.5 or
            look.get("bloom_intensity") != 0.0 or
            look.get("floor_material") != "Charcoal" or
            look.get("backdrop_material") != "Parchment" or
            look.get("v120_source_master_unchanged") is not True):
        raise JobError("cast_review_v120_look_receipt_invalid")
    if hashlib.sha256(source.read_bytes()).hexdigest()!=source_hash_before:
        raise JobError("original_character_review_world_modified")
    images=[]
    for view in CAST_V11_VIEWS:
        before=set(output.rglob("*.png"))
        preset=expected_presets["wide" if view=="LINEUP" else "portrait"]
        width,height=(1280,720) if view=="LINEUP" else (720,1280)
        _run_unreal([
            str(editor),str(project),expected_world,
            "-game",
            "-LevelSequence="+expected_sequences[view],
            "-MoviePipelineConfig="+preset,
            "-unattended","-nop4","-nosplash","-RenderOffscreen",
            "-resx="+str(width),"-resy="+str(height),"-log",
        ],root,work/("render_"+view.lower()+".log"),MAX_RENDER_SECONDS,env)
        added=set(output.rglob("*.png"))-before
        if len(added)!=1:
            raise JobError("cast_review_exactly_one_png_required_"+view.lower())
        png=next(iter(added))
        filename="WO_EP01_CAST_"+view+"_V11_0000.png"
        if (png.is_symlink() or not png.is_file()
                or png.name != filename
                or png.stat().st_size<2048
                or png.stat().st_size>CAST_V11_MAX_PNG
                or read_png_dimensions(png)!=(width,height)):
            raise JobError("cast_review_invalid_png_"+view.lower())
        raw=png.read_bytes()
        images.append({
            "view":view,"filename":filename,
            "relative_path":str(png.relative_to(root)).replace("\\","/"),
            "bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),
            "width":width,"height":height,
        })
    if hashlib.sha256(source.read_bytes()).hexdigest()!=source_hash_before:
        raise JobError("original_character_review_world_modified")
    return {
        "kind":"actual_unreal_5_8_cast_mrq_review_v110",
        "source_cast_world":data["source_world"],
        "source_cast_sha256":source_hash_before,
        "source_cast_unchanged":True,
        "review_look":look,
        "render_world":expected_world,
        "bound_review_sequences":expected_sequences,
        "preview_count":len(images),
        "screenshots":images,
        "material_preview_only":True,
        "character_masters_approved":False,
        "skeletal_animation_bound":False,
        "final_film_rendered":False,
        "portrait_resolution":"720x1280",
        "lineup_resolution":"1280x720",
    }
