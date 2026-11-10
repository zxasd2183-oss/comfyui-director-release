"""Create a fixed low-cost PNG preview MRQ preset in Unreal Editor 5.8.

Executed only as a known commandlet from Director UE Worker. Asset paths and
render output directory are derived from the random server-owned job ID.
The script never renders by itself and never edits V02/V03 story assets.
"""
from __future__ import annotations

import json
import os
import re
import traceback
from pathlib import Path

import unreal

ROOT = "/Game/Director/V04"
PRESET_DIR = ROOT + "/Presets"


def main():
    result_file = Path(os.environ["DIRECTOR_UE_RESULT_FILE"])
    try:
        job_id = os.environ["DIRECTOR_UE_JOB_ID"]
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise RuntimeError("invalid_job_id")
        output = Path(os.environ["DIRECTOR_UE_PREVIEW_OUTPUT"]).resolve()
        # Both values come from the trusted Python worker, not from HTTP callers.
        if not output.is_dir() or output.name != "Previews" or output.parent.name != job_id:
            raise RuntimeError("invalid_preview_output_directory")
        for folder in (ROOT, PRESET_DIR):
            unreal.EditorAssetLibrary.make_directory(folder)
        asset_name = "WO_EP01_PrevisPNG_" + job_id
        asset_path = PRESET_DIR + "/" + asset_name
        if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            raise RuntimeError("preview_preset_collision")
        factory = unreal.MoviePipelinePrimaryConfigFactory()
        config = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            asset_name=asset_name,
            package_path=PRESET_DIR,
            asset_class=unreal.MoviePipelinePrimaryConfig,
            factory=factory,
        )
        if not config:
            raise RuntimeError("movie_pipeline_config_creation_failed")
        config.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
        config.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)
        setting = config.find_or_add_setting_by_class(
            unreal.MoviePipelineOutputSetting
        )
        setting.set_editor_property(
            "output_directory", unreal.DirectoryPath(str(output))
        )
        setting.set_editor_property("output_resolution", unreal.IntPoint(720,1280))
        setting.set_editor_property(
            "file_name_format", "{sequence_name}_V04_{frame_number}"
        )
        setting.set_editor_property("use_custom_playback_range", True)
        setting.set_editor_property("custom_start_frame", 0)
        setting.set_editor_property("custom_end_frame", 1)
        setting.set_editor_property("override_existing_output", False)
        if not unreal.EditorAssetLibrary.save_loaded_asset(config):
            raise RuntimeError("preview_preset_save_failed")
        result = {"ok":True, "preset":asset_path + "." + asset_name,
                  "width":720,"height":1280,"frames_per_shot":1}
    except Exception as exc:
        result = {"ok":False, "reason":str(exc)[:400],
                  "traceback":traceback.format_exc(limit=5)[-2000:]}
    result_file.write_text(
        json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    if result["ok"]:
        unreal.log("Director V04 preview preset created")
    else:
        unreal.log_error("Director V04 preview preset failed: " + result["reason"])


main()
