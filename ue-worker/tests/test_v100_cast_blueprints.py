"""V1.0 five separately editable original character Blueprints; no skeleton claims.

Offline faux Unreal tests execute actual cast Python functions (not UE itself).
"""
from __future__ import annotations
import ast
import copy
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import agent
import ue_jobs

IDS=("CHAR_GPT","CHAR_GEM","CHAR_DS","CHAR_CLA","CHAR_ZERO")


def plan():
    return {
        "task":"build_ep01_cast_blueprints",
        "project_id":"WaitingOffice","episode_id":"EP01",
        "fps":24,
        "shots":[{"shot_id":f"{i:02d}","ordinal":i,
                   "duration_ms":10000 if i==31 else 5000} for i in range(1,32)],
        "expected_total_ms":160000,
    }


class Component:
    def __init__(self):
        self.properties={}
        self.location=None
        self.scale=None
        self.material=None

    def set_editor_property(self, key, val):
        self.properties[key]=val

    def set_material(self, slot, mat):
        assert slot==0
        self.material=mat

    def set_relative_location(self,loc,*args):
        self.location=loc

    def set_relative_scale3d(self,scale):
        self.scale=scale

    def set_static_mesh(self, mesh):
        return mesh is not None


class Actor:
    def __init__(self):
        self.components={}

    def set_actor_label(self, label):
        self.label=label

    def get_component_by_class(self,*args):
        return Component()

    def set_actor_scale3d(self,*args):
        return True


class Scene:
    def __init__(self,lib):
        self.lib=lib
        self.levels=[]

    def new_level(self,path):
        if path in self.lib.assets:
            return False
        self.lib.assets.add(path)
        self.levels.append(path)
        return True

    def save_current_level(self):
        return True


class Library:
    def __init__(self):
        self.assets=set()
        self.dirs=set()

    def does_asset_exist(self,path):
        return path in self.assets

    def does_directory_exist(self,path):
        return path in self.dirs

    def make_directory(self,path):
        self.dirs.add(path)
        return True

    def load_asset(self,path):
        return object() if path.startswith("/Engine/BasicShapes/") else None

    def save_loaded_asset(self,asset):
        return True

    def load_blueprint_class(self,path):
        return object() if path in self.assets else None


class Factory:
    def __init__(self):
        self.props={}

    def set_editor_property(self,key,value):
        self.props[key]=value


class Tools:
    def __init__(self,lib):
        self.lib=lib

    def create_asset(self, asset_name, package_path, asset_class, factory):
        path=package_path+"/"+asset_name
        if path in self.lib.assets:
            return None
        self.lib.assets.add(path)
        return object()


class Subsystem:
    def __init__(self):
        self.nodes=[]
        self.names=[]
    def k2_gather_subobject_data_for_blueprint(self,bp):
        return ["root"]
    def add_new_subobject(self,params):
        obj=Component()
        self.nodes.append(obj)
        return len(self.nodes)-1,""
    def rename_subobject(self,handle,new_name):
        self.names.append(new_name)
        return True


def fake_unreal():
    lib=Library()
    scene=Scene(lib)
    subsystem=Subsystem()
    actors=[]
    class ActorSubsystem:
        def spawn_actor_from_class(self,actor_class,position,rotation):
            a=Actor()
            actors.append(a)
            return a
    factory=lambda :Factory()
    ue=types.SimpleNamespace(
        Actor=Actor,
        Blueprint=type("Blueprint",(),{}),
        BlueprintFactory=factory,
        StaticMeshActor=Actor,
        StaticMeshComponent=Component,
        PointLight=Actor,
        PointLightComponent=Component,
        CineCameraActor=Actor,
        CineCameraComponent=Component,
        LevelEditorSubsystem=type("LevelEditorSubsystem",(),{}),
        EditorActorSubsystem=type("EditorActorSubsystem",(),{}),
        SubobjectDataSubsystem=type("SubobjectDataSubsystem",(),{}),
        AddNewSubobjectParams=lambda **args:args,
        SubobjectDataBlueprintFunctionLibrary=types.SimpleNamespace(
            get_data=lambda handle:handle,
            get_object=lambda data:subsystem.nodes[data]),
        EditorAssetLibrary=lib,
        AssetToolsHelpers=types.SimpleNamespace(get_asset_tools=lambda:Tools(lib)),
        MaterialEditingLibrary=types.SimpleNamespace(
            create_material_expression=lambda *args:Component(),
            connect_material_property=lambda *args:True,
            recompile_material=lambda *args:True),
        Material=type("Material",(),{}),
        MaterialFactoryNew=factory,
        MaterialExpressionConstant3Vector=type("Constant3",(),{}),
        MaterialExpressionConstant=type("Constant",(),{}),
        MaterialProperty=types.SimpleNamespace(MP_BASE_COLOR=0,MP_ROUGHNESS=1),
        LinearColor=lambda *v:v,
        Vector=lambda *v:v,Rotator=lambda *v:v,Text=lambda x:x,
        MathLibrary=types.SimpleNamespace(
            find_look_at_rotation=lambda *args:None),
    )
    ue.get_editor_subsystem=lambda klass:(scene if klass==ue.LevelEditorSubsystem
                                           else ActorSubsystem())
    ue.get_engine_subsystem=lambda _:subsystem
    return ue,lib,scene,subsystem,actors


def load_builder(ue):
    source=(ROOT/"unreal_build_stage.py").read_text("utf-8")
    tree=ast.parse(source)
    funcs={"vec","rot","_cast_parts","_create_cast_materials",
           "_build_cast_blueprint","build_ep01_cast_blueprints"}
    names={"SCENE_GEOMETRY","APPROVED_ROOT","CAST_IDS","CAST_PALETTE",
           "CAST_STYLES"}
    nodes=[node for node in tree.body
           if (isinstance(node,ast.FunctionDef) and node.name in funcs)
           or (isinstance(node,ast.Assign) and any(
               isinstance(x,ast.Name) and x.id in names for x in node.targets))]
    ns={"os":os,"unreal":ue}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),
                 "cast-functions","exec"),ns)
    return ns


class TestCastV100(unittest.TestCase):
    def test_manifest_and_worker_no_render_claim(self):
        x=ue_jobs.sanitized_plan(plan())
        self.assertEqual(x["format"],"director_ue_cast_blueprints_v100")
        self.assertEqual((x["total_frames"],x["total_ms"]),(3840,160000))
        self.assertIn("build_ep01_cast_blueprints",agent.capabilities()["jobs"])
        self.assertTrue(agent.capabilities()["supports_ep01_cast_blueprints"])
        self.assertFalse(agent.capabilities()["supports_rendering"])
        for key,value in (("project_id","Malicious"),("episode_id","EP02"),
                          ("fps",30),("expected_total_ms",170000)):
            invalid=plan()
            invalid[key]=value
            with self.assertRaises(ue_jobs.JobError):
                ue_jobs.sanitized_plan(invalid)
        invalid=plan()
        invalid["script"]="../a.py"
        with self.assertRaises(ue_jobs.JobError):
            ue_jobs.sanitized_plan(invalid)

    def test_five_character_identity_and_wrist_right(self):
        ue,_,_,_,_=fake_unreal()
        cast=load_builder(ue)
        self.assertEqual(tuple(cast["CAST_STYLES"]),IDS)
        self.assertEqual(cast["CAST_STYLES"]["CHAR_GPT"]["hair"],"Chestnut")
        self.assertEqual(cast["CAST_STYLES"]["CHAR_GPT"]["eyes"],"Amber")
        self.assertEqual(cast["CAST_STYLES"]["CHAR_GPT"]["hair_style"],
                         "side_part_bob")
        self.assertEqual(cast["CAST_STYLES"]["CHAR_ZERO"]["hair_style"],
                         "low_black_ponytail")
        for ident in IDS:
            parts=cast["_cast_parts"](ident)
            self.assertGreaterEqual(len(parts),32)
            labels=[x[0] for x in parts]
            self.assertEqual(len(labels),len(set(labels)))
            self.assertNotIn("Logo"," ".join(labels))
            self.assertFalse(any("Right_Wrist_Red_Thread"==x for x in labels)
                             if ident!="CHAR_ZERO" else False)
        zero={p[0]:p for p in cast["_cast_parts"]("CHAR_ZERO")}
        self.assertIn("Right_Wrist_Red_Thread",zero)
        self.assertLess(zero["Right_Wrist_Red_Thread"][2][1],0)
        self.assertEqual(zero["Right_Wrist_Red_Thread"][4],"RedRope")

    def test_actual_builder_mocks_five_saved_actor_blueprints_and_review_map(self):
        ue,lib,scene,system,actors=fake_unreal()
        builder=load_builder(ue)["build_ep01_cast_blueprints"]
        jobid="a"*32
        with patch.dict(os.environ,{"DIRECTOR_UE_JOB_ID":jobid}):
            out=builder(ue_jobs.sanitized_plan(plan()))
        self.assertTrue(out["ok"])
        self.assertEqual([c["id"] for c in out["characters"]],list(IDS))
        self.assertEqual(out["material_count"],18)
        self.assertEqual(len(scene.levels),1)
        self.assertEqual(len(system.nodes),
                         sum(i["editable_mesh_components"] for i in out["characters"]))
        self.assertGreaterEqual(len(system.nodes),165)
        self.assertEqual(len(actors),8)
        self.assertTrue(out["review_map"].endswith("/EP01_Five_Cast_Review"))
        self.assertFalse(out["skeletal_rig_bound"])
        self.assertFalse(out["metahuman_bound"])
        self.assertFalse(out["facial_performance_ready"])
        self.assertFalse(out["studio_character_approval_verified"])
        self.assertFalse(out["render_ready"])
        self.assertFalse(any("/Approved/" in p for p in lib.assets))
        self.assertIn("Right_Wrist_Red_Thread",system.names)
        # Same job cannot overwrite or regenerate assets in its namespace.
        with patch.dict(os.environ,{"DIRECTOR_UE_JOB_ID":jobid}):
            with self.assertRaisesRegex(RuntimeError,"cast_job_namespace_collision"):
                builder(ue_jobs.sanitized_plan(plan()))

    def test_existing_approved_character_blocks_all_writes(self):
        ue,lib,_,_,_=fake_unreal()
        lib.assets.add("/Game/Director/Approved/Characters/CHAR_GPT")
        builder=load_builder(ue)["build_ep01_cast_blueprints"]
        with patch.dict(os.environ,{"DIRECTOR_UE_JOB_ID":"a"*32}):
            with self.assertRaisesRegex(RuntimeError,"approved_character_exists"):
                builder(ue_jobs.sanitized_plan(plan()))
        self.assertFalse(any("/Candidates/" in p for p in lib.assets))

    def test_no_faked_receipt_approval_or_bogus_paths(self):
        spec=ue_jobs.sanitized_plan(plan())
        jobid="c"*32
        base="/Game/Director/Candidates/EP01/CastBuilds/J"+jobid
        good={
            "ok":True,"kind":"original_static_blueprint_character_candidates_v100",
            "characters":[{"id":i,"path":base+"/Blueprints/BP_"+i,
                           "editable_mesh_components":35} for i in IDS],
            "review_map":base+"/Maps/EP01_Five_Cast_Review",
            "material_count":18,
            "right_wrist_red_thread_character":"CHAR_ZERO",
            "locked_gpt_hair":"short_dark_chestnut_bob",
            "locked_gpt_eyes":"amber",
            "shot_count":31,"total_frames":3840,
            "studio_character_approval_verified":False,
            "skeletal_rig_bound":False,
            "metahuman_bound":False,
            "facial_performance_ready":False,
            "render_ready":False,"no_approved_asset_replaced":True,
        }
        def run(receipt):
            def fake_process(command,root,logfile,timeout,env,*args):
                Path(env["DIRECTOR_UE_RESULT_FILE"]).write_text(
                    json.dumps(receipt),"utf-8")
            with tempfile.TemporaryDirectory() as tmp,patch.object(
                ue_jobs,"find_editor_cmd",
                return_value=Path("C:/UnrealEditor-Cmd.exe")),patch.object(
                ue_jobs,"run_fixed",side_effect=fake_process):
                return ue_jobs.run_commandlet(
                    spec,Path(tmp)/"project",Path(tmp)/jobid)
        result=run(good)
        self.assertEqual(len(result["characters"]),5)
        self.assertFalse(result["render_ready"])
        self.assertFalse(result["gpu_render_submitted"])
        for tamper in (
            {"studio_character_approval_verified":True},
            {"skeletal_rig_bound":True},
            {"metahuman_bound":True},
            {"locked_gpt_hair":"silver_long_hair"},
            {"characters":[*good["characters"][:-1],
                           {**good["characters"][-1],"path":"/Game/Director/Approved"}]},
        ):
            with self.subTest(tamper=str(tamper)[:45]):
                with self.assertRaisesRegex(
                    ue_jobs.JobError,"ue_cast_blueprint_receipt_invalid"):
                    run({**good,**tamper})


if __name__=="__main__":unittest.main()
