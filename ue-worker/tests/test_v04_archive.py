"""End-to-end *offline* V04 runner contract with simulated engine subprocesses.

Ensures per-shot output checks and package manifest, not an assertion that the
live Unreal Editor has rendered any pictures yet.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ue_jobs
import ue_previs


def png_chunk(kind,payload):
    return (
        struct.pack(">I",len(payload))+kind+payload+
        struct.pack(">I",zlib.crc32(kind+payload)&0xFFFFFFFF)
    )


def valid_test_png():
    w,h=720,1280
    # Full valid 8-bit RGB PNG, not just a forged IHDR.
    rows=[]
    for y in range(h):
        row=bytes((x+y)%256 for x in range(w*3))
        rows.append(b"\x00"+row)
    content=zlib.compress(b"".join(rows),level=1)
    return (
        b"\x89PNG\r\n\x1a\n" +
        png_chunk(b"IHDR",struct.pack(">IIBBBBB",w,h,8,2,0,0,0))+
        png_chunk(b"IDAT",content)+png_chunk(b"IEND",b"")
    )


class V04ArchiveTest(unittest.TestCase):
    def test_four_real_png_files_are_packaged_with_complete_receipts(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            ue_jobs.ensure_project(root)
            stage=(root/"Content"/"Director"/"V03")
            (stage/"Maps").mkdir(parents=True)
            (stage/"Shots").mkdir(parents=True)
            (stage/"Maps"/"WaitingOffice_EP01_Stage.umap").write_bytes(b"map")
            for shot in ue_previs.FRAME_SHOTS:
                (stage/"Shots"/("WaitingOffice_EP01_SH"+shot+"_V03.uasset")).write_bytes(b"sequence")
            jobid="a"*32
            work=root/"Jobs"/jobid
            raw_png=valid_test_png()
            self.assertGreater(len(raw_png),2048)

            def fake_ue(command,root_path,logfile,timeout,env):
                logfile.parent.mkdir(parents=True,exist_ok=True)
                logfile.write_text("simulated stdout only")
                if any("-run=pythonscript" in str(arg) for arg in command):
                    asset="WO_EP01_PrevisPNG_"+jobid
                    result={
                        "ok":True,
                        "preset":"/Game/Director/V04/Presets/"+asset+"."+asset,
                        "width":720,"height":1280,"frames_per_shot":1,
                        "stage_map":"/Game/Director/V051/Maps/WO_EP01_ExposurePreview_"+jobid,
                        "source_map":ue_previs.MAP_PATH,
                        "light_intensities":{"V03_Key_Light":800.0,"V03_Fill_Light":400.0},
                    }
                    Path(env["DIRECTOR_UE_RESULT_FILE"]).write_text(json.dumps(result))
                else:
                    sequence=next(str(arg) for arg in command if str(arg).startswith("-LevelSequence="))
                    match=re.search(r"_SH(\d{2})_V03",sequence)
                    if not match:
                        raise AssertionError("missing expected shot")
                    output=Path(env["DIRECTOR_UE_PREVIEW_OUTPUT"])
                    (output/("WO_SH"+match.group(1)+"_V04_0000.png")).write_bytes(raw_png)

            durations=[3,5,5,6,6,5,5,6,5,6,5,5,4,5,5,5,7,5,5,5,6,5,6,5,4,5,5,6,5,5,5]
            spec=ue_jobs.sanitized_plan({
                "task":"render_previs_stills",
                "project_id":"WaitingOffice","episode_id":"EP01","fps":24,
                "shots":[{"shot_id":f"{i:02}","ordinal":i,"duration_ms":dur*1000}
                         for i,dur in enumerate(durations,1)],
                "expected_total_ms":160000,
            })
            with patch.object(ue_jobs,"find_editor_cmd",return_value=Path("UnrealEditor-Cmd.exe")),patch.object(
                ue_previs,"_run_unreal",side_effect=fake_ue
            ):
                result=ue_previs.run_previs(spec,root,work)
            self.assertEqual(result["preview_count"],4)
            self.assertTrue(result["source_stage_unchanged"])
            self.assertEqual(result["light_intensities"]["V03_Key_Light"],800.0)
            self.assertTrue(result["preview_stage_map"].startswith("/Game/Director/V051/Maps/"))
            self.assertEqual((stage/"Maps"/"WaitingOffice_EP01_Stage.umap").read_bytes(),b"map")
            self.assertFalse(result["render_ready"])
            self.assertFalse(result["metahuman_bound"])
            self.assertEqual(result["resolution"],"720x1280")
            bundle=root/Path(result["package"]["relative_path"])
            self.assertTrue(bundle.is_file())
            self.assertEqual(hashlib.sha256(bundle.read_bytes()).hexdigest(),result["package"]["sha256"])
            with zipfile.ZipFile(bundle) as archive:
                members=set(archive.namelist())
                self.assertEqual(
                    members,{"manifest.json"} | {
                        "Previews/"+shot+".png" for shot in ue_previs.FRAME_SHOTS
                    }
                )
                manifest=json.loads(archive.read("manifest.json"))
                self.assertTrue(manifest["not_final_film"])
                self.assertEqual(len(manifest["images"]),4)
                for shot in ue_previs.FRAME_SHOTS:
                    content=archive.read("Previews/"+shot+".png")
                    self.assertEqual(content[:8],ue_previs.PNG_MAGIC)
                    self.assertEqual(struct.unpack(">II",content[16:24]),(720,1280))
            self.assertEqual(
                {row["shot_id"] for row in result["screenshots"]},
                set(ue_previs.FRAME_SHOTS)
            )


if __name__ == "__main__":
    unittest.main()
