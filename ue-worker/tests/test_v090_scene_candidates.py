"""V0.9 EP01 authored UE scene candidates: offline fixed-scope contract.

Never runs Unreal; fake editor checks material/World creation and no overwrites.
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import agent
import ue_jobs


def plan():
    shots = [
        {"shot_id": f"{n:02}", "ordinal": n,
         "duration_ms": 10000 if n == 31 else 5000}
        for n in range(1, 32)
    ]
    return {
        "task": "build_ep01_scene_candidates",
        "project_id": "WaitingOffice", "episode_id": "EP01",
        "fps": 24, "shots": shots, "expected_total_ms": 160000,
    }


class Component:
    def set_static_mesh(self, mesh):
        return bool(mesh)

    def set_material(self, index, material):
        assert index == 0 and material is not None

    def set_editor_property(self, key, val):
        assert key and val is not None


class Actor:
    def set_actor_label(self, label):
        self.label = label

    def get_component_by_class(self, which):
        return Component()

    def set_actor_scale3d(self, dim):
        self.dim = dim


class FakeTools:
    def __init__(self, lib):
        self.lib = lib

    def create_asset(self, asset_name, package_path, asset_class, factory):
        path = package_path + "/" + asset_name
        assert path not in self.lib.assets
        self.lib.assets.add(path)
        return object()


class FakeLevel:
    def __init__(self, lib):
        self.lib = lib
        self.levels = []

    def new_level(self, path):
        assert path not in self.lib.assets
        self.lib.assets.add(path)
        self.levels.append(path)
        return True

    def save_current_level(self):
        return True


class FakeLibrary:
    def __init__(self):
        self.assets = set()
        self.dirs = set()

    def does_asset_exist(self, path):
        return path in self.assets

    def does_directory_exist(self, path):
        return path in self.dirs

    def make_directory(self, path):
        self.dirs.add(path)
        return True

    def load_asset(self, path):
        return object() if path in self.assets or path.startswith("/Engine/BasicShapes/") else None

    def save_loaded_asset(self, material):
        return True


def fake_ue():
    lib = FakeLibrary()
    level = FakeLevel(lib)
    actors = []
    class ActorSubsystem:
        def spawn_actor_from_class(self, klass, position, rotation):
            actor = Actor()
            actors.append(actor)
            return actor
    subsystem = ActorSubsystem()
    kind = lambda: object()
    ue = types.SimpleNamespace(
        EditorAssetLibrary=lib,
        AssetToolsHelpers=types.SimpleNamespace(get_asset_tools=lambda:FakeTools(lib)),
        MaterialEditingLibrary=types.SimpleNamespace(
            create_material_expression=lambda mat,typ:Component(),
            connect_material_property=lambda *args:True,
            recompile_material=lambda mat:True),
        MaterialProperty=types.SimpleNamespace(MP_BASE_COLOR=1, MP_ROUGHNESS=2),
        Material=object(), MaterialFactoryNew=kind,
        MaterialExpressionConstant3Vector=object(),
        MaterialExpressionConstant=object(),
        LinearColor=lambda *p:p,
        Vector=lambda *p:p, Rotator=lambda *p:p,
        StaticMeshActor=object(), StaticMeshComponent=object(),
        PointLight=object(), PointLightComponent=object(),
        CineCameraActor=object(), CineCameraComponent=object(),
        LevelEditorSubsystem=type("LevelEditorSubsystem",(),{}),
        EditorActorSubsystem=type("EditorActorSubsystem",(),{}),
        MathLibrary=types.SimpleNamespace(find_look_at_rotation=lambda *a:None),
    )
    ue.get_editor_subsystem = lambda typ: level if typ == ue.LevelEditorSubsystem else subsystem
    return ue, lib, level, actors


def load_scene_builder(ue):
    source = (ROOT / "unreal_build_stage.py").read_text("utf-8")
    tree = ast.parse(source)
    functions = {
        "vec", "rot", "_create_scene_materials", "_populate_scene",
        "build_ep01_scene_candidates",
    }
    assignments = {"SCENE_IDS", "SCENE_COLORS", "SCENE_GEOMETRY"}
    body = [
        node for node in tree.body
        if (isinstance(node,ast.FunctionDef) and node.name in functions)
        or (isinstance(node,ast.Assign)
            and any(isinstance(target,ast.Name) and target.id in assignments
                    for target in node.targets))
    ]
    ns = {"unreal":ue,"os":os}
    exec(compile(ast.fix_missing_locations(ast.Module(body=body,type_ignores=[])),
                 "<trusted-ue-scene-builder>","exec"),ns)
    return ns["build_ep01_scene_candidates"]


class SceneCandidatesV090Tests(unittest.TestCase):
    def test_worker_is_locked_to_real_31_shot_episode(self):
        result = ue_jobs.sanitized_plan(plan())
        self.assertEqual(result["format"],"director_ue_scene_candidates_v09")
        self.assertEqual((result["total_frames"],result["total_ms"]),(3840,160000))
        caps = agent.capabilities()
        self.assertIn("build_ep01_scene_candidates",caps["jobs"])
        self.assertTrue(caps["supports_ep01_scene_candidates"])
        self.assertFalse(caps["supports_rendering"])
        for name,value in (("episode_id","EP02"),("project_id","Other"),
                           ("fps",30),("expected_total_ms",170000)):
            modified = plan()
            modified[name] = value
            with self.assertRaises(ue_jobs.JobError):
                ue_jobs.sanitized_plan(modified)
        modified = plan()
        modified["path"] = "C:/escape"
        with self.assertRaises(ue_jobs.JobError):
            ue_jobs.sanitized_plan(modified)

    def test_creates_three_editable_worlds_and_ten_matte_materials(self):
        unreal,lib,level,actors = fake_ue()
        builder = load_scene_builder(unreal)
        spec = ue_jobs.sanitized_plan(plan())
        jobid = "a" * 32
        with patch.dict(os.environ,{"DIRECTOR_UE_JOB_ID":jobid}):
            result = builder(spec)
        self.assertTrue(result["ok"])
        self.assertEqual(result["material_count"],10)
        self.assertEqual([r["id"] for r in result["scene_candidates"]],
                         ["SCN_HALL","SCN_HALL_ALERT","SCN_ENTRANCE"])
        self.assertEqual(len(level.levels),3)
        for item in result["scene_candidates"]:
            self.assertIn("/SceneBuilds/J"+jobid+"/Maps/",item["path"])
            self.assertIn(item["path"],lib.assets)
            self.assertGreater(item["props"],19)
            self.assertGreaterEqual(item["lights"],2)
            self.assertGreaterEqual(item["review_cameras"],2)
        self.assertFalse(any(path.startswith("/Game/Director/Approved")
                             for path in lib.assets))
        self.assertFalse(result["studio_scene_approval_verified"])
        self.assertFalse(result["character_models_bound"])
        self.assertFalse(result["render_ready"])
        self.assertGreater(len(actors),90)
        # Idempotence must FAIL CLOSED: NEVER overwrite a previous candidate.
        with patch.dict(os.environ,{"DIRECTOR_UE_JOB_ID":jobid}):
            with self.assertRaisesRegex(RuntimeError,"namespace_collision"):
                builder(spec)

    def test_existing_approved_master_blocks_candidate_generation(self):
        unreal,lib,_,_ = fake_ue()
        lib.assets.add("/Game/Director/Approved/Scenes/SCN_HALL")
        builder = load_scene_builder(unreal)
        with patch.dict(os.environ,{"DIRECTOR_UE_JOB_ID":"b"*32}):
            with self.assertRaisesRegex(RuntimeError,"approved_scene_exists"):
                builder(ue_jobs.sanitized_plan(plan()))
        self.assertFalse(any(p.startswith("/Game/Director/Candidates")
                             for p in lib.assets))

    def test_missing_server_generated_job_id_refuses_writes(self):
        unreal,lib,_,_ = fake_ue()
        builder = load_scene_builder(unreal)
        with patch.dict(os.environ,{"DIRECTOR_UE_JOB_ID":"../evil"}):
            with self.assertRaisesRegex(RuntimeError,"job_id_invalid"):
                builder(ue_jobs.sanitized_plan(plan()))
        self.assertFalse(lib.assets)

    def test_builder_has_no_approval_or_render_calls(self):
        source = (ROOT / "unreal_build_stage.py").read_text("utf-8")
        tree = ast.parse(source)
        fn = next(x for x in tree.body if isinstance(x,ast.FunctionDef)
                  and x.name=="build_ep01_scene_candidates")
        calls = [ast.unparse(x.func) for x in ast.walk(fn)
                 if isinstance(x,ast.Call)]
        self.assertNotIn("unreal.EditorAssetLibrary.delete_asset",calls)
        self.assertNotIn("unreal.EditorAssetLibrary.rename_asset",calls)
        self.assertFalse(any("render" in x.lower() or "subprocess" in x.lower()
                             for x in calls))
        self.assertIn("unreal.EditorAssetLibrary.does_asset_exist",calls)


if __name__=="__main__":
    unittest.main()
